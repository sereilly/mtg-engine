"""A permanent's own static prevention, and the printed lines it implements
(CR 604, CR 615).

The other shape from ``shields.py``: a static ability that applies while its
source is on the battlefield, with no charges and no lifetime, so there is no
``Shield`` to hold and nothing for the sweeps to clear. Each is read off its
source's text at the moment damage would be dealt — "prevent that damage and
put a counter on this" (Nine Lives), "prevent all damage … by <source type>"
printed on the permanent or on what is attached to it, "prevent N of that
damage", the per-point counter shield (Rock Hydra), and the blankets a
permanent prints over its controller, a spell class, a noun phrase, a small
event or a shared colour — together with the one-shot "the next time a source
of your choice would deal damage, prevent it".

``prevention_claims_line`` is here too: it is how the grammar's parse claim
and the support gate ask which printed lines this package implements, so it
reads the matchers below — and the static form of the directional shield in
``shields.py`` — rather than a second copy of any pattern.

Split out of ``prevention.py`` at the 2,000-line cap's split round, where it
was that module's last section.
"""

from __future__ import annotations

import re

from ..damage_source_colors import damage_source_colors
from ..models import PlayerState
from ..named_counters import add_counters, counters_on, remove_counters
from ..next_damage import DAMAGE_PREVENTED_NEXT, armed_for_event, spend_for_event
from ..pt import remove_plus1_counters
from .registry import (
    CHOSEN_SOURCE_ONE_SHOT, CONTROLLER_BLANKET, MATCHING_BLANKET,
    PER_POINT_COUNTER_SHIELD, SHARED_COLOR_BLANKET, SMALL_EVENT_BLANKET,
    SOURCE_TYPE_BLANKET, SPELL_CLASS_BLANKET, STATIC_POINTS, STATIC_WHOLE_EVENT,
    PreventionOutcome, prevention_effect, source_has_type,
)
from .shields import (_source_label, attached_damage_shield, recipient_label,
                      self_damage_shield)


# ---------------------------------------------------------------------------
# A permanent's own static prevention, and the printed lines it implements
# ---------------------------------------------------------------------------
#
# Everything in ``shields.py`` is a shield a recipient was *given*: something
# resolved, armed it, and it is spent. This is the other shape — a static
# ability that applies while its source is on the battlefield, with no charges
# and no lifetime, so there is no Shield to hold and nothing for the sweeps to
# clear. It is read off the source's text at damage time for the same reason
# engine/replacements/' interceptors are: the card says it, so the card is
# where the answer lives.

#: "If a source would deal damage to you, prevent that damage and put an
#: incarnation counter on this enchantment." (Nine Lives.) The counter's word
#: and the noun the card calls itself are **payload**, not part of the pattern's
#: meaning — a second card printing this with a different counter needs no code
#: here, which is the same reason engine/combat_restrictions.py holds its land
#: type as data.
_PREVENT_AND_COUNT_RE = re.compile(
    r"^if a source would deal damage to you, prevent that damage and put "
    r"an? (?P<counter>[a-z]+) counter on this "
    r"(?:artifact|creature|enchantment|land|permanent)$"
)


def prevent_and_count_kind(line: str) -> str | None:
    """The counter *line* places when it prevents, or None if it is not that
    line. One matcher, asked by the interceptor below and by both claim
    readers, so what is implemented and what is claimed cannot drift."""
    match = _PREVENT_AND_COUNT_RE.match(" ".join(line.strip().lower().rstrip(".").split()))
    return match.group("counter") if match else None


#: "Prevent all damage that would be dealt to this creature by artifact
#: sources." (Argothian Treefolk.) / "…by artifact creatures." (Argothian
#: Pixies.) The source class is payload, the way every other text-keyed table
#: here holds its parameter — a card printed "by red sources" needs no code.
#:
#: Anchored at both ends. A line saying more than this is a prevention this
#: file does not implement, and a prefix match would claim it and then enforce
#: the narrower rule, which is damage prevented that the card does not prevent.
#:
#: The subject is captured rather than fixed, because Artifact Ward prints the
#: same sentence about the creature it **enchants**. Two readers rather than one
#: permissive matcher: the shield is derived by reading a permanent's text, and
#: an Aura is itself a permanent — a single matcher would have Artifact Ward
#: shielding *itself* from artifact sources, which is a card nobody printed.
#: The optional leading condition (Bronze Horse: "**As long as you control
#: another creature,** prevent all damage ..."). CR 611.2's "as long as" clause
#: on a static ability -- the shield exists only while it holds, and it is
#: rechecked on every event rather than latched, because the creature it counts
#: may leave. The noun phrase is read by the same reader every other printed
#: noun phrase goes through, so "another creature" means here what it means
#: everywhere.
_PREVENT_ALL_FROM_SOURCE_TYPE_RE = re.compile(
    r"^(?:as long as you control (?P<condition>[^,]+), )?"
    r"prevent all (?P<combat>combat )?damage that would be dealt to "
    r"(?P<subject>this|enchanted|equipped) "
    r"(?:artifact|creature|enchantment|land|permanent) by "
    r"(?P<source>"
    r"(?:artifact|creature|enchantment|land) (?:sources|creatures|artifacts|permanents)"
    r"|enchanted creatures"
    r"|walls"
    r"|creatures it's blocking"
    r"|spells that target it"
    # "…by **creatures**" (Uncle Istvan). The bare plural, which is the same
    # class the two-word "creature sources" names — the printed noun says what
    # the source must be and "sources" says nothing further. Last in the
    # alternation because two phrases above open with the same word; the
    # pattern is anchored, so neither can be shadowed, and the order says
    # which reading is the narrow one.
    r"|creatures"
    # "…by **sources of the chosen color**." (Prismatic Ward.) / "…of the
    # **last** chosen color." (Chromatic Armor, which lets its controller
    # re-choose.) The property is one the *holder* recorded as it entered
    # (CR 614.1c), not one the phrase names outright — so it is resolved
    # against the permanent carrying the line before the source is tested, and
    # a holder that recorded nothing shields against nothing rather than
    # against everything. Both printings are one alternative: "last" says which
    # of several choices counts, and only the latest is kept either way.
    r"|sources of the (?:last )?chosen color"
    r")$"
)

#: What each printed source phrase means, as the fields
#: :func:`_source_shield_matches` tests. Data rather than a branch per phrase,
#: for the reason the land type in ``combat_restrictions.py`` is data: a card
#: printed with another noun in the same sentence is the same effect.
#:
#: The three Legends phrases are each a *different kind* of narrowing, which is
#: why the value is a dict rather than the type string this used to return.
#: "Walls" is a subtype (CR 205.3), "enchanted creatures" is a state of the
#: source object, and "creatures it's blocking" is a relationship between the
#: source and the recipient that neither object carries on its own.
_SOURCE_CLASSES: dict[str, dict[str, object]] = {
    "artifact sources": {"card_type": "artifact"},
    "artifact creatures": {"card_type": "artifact"},
    "artifact permanents": {"card_type": "artifact"},
    "creature sources": {"card_type": "creature"},
    # Uncle Istvan's bare plural. The same class, because the printed noun is
    # what narrows the source and "sources" adds nothing to it.
    "creatures": {"card_type": "creature"},
    "creature creatures": {"card_type": "creature"},
    "creature permanents": {"card_type": "creature"},
    "enchantment sources": {"card_type": "enchantment"},
    "enchantment creatures": {"card_type": "enchantment"},
    "enchantment permanents": {"card_type": "enchantment"},
    "land sources": {"card_type": "land"},
    "land creatures": {"card_type": "land"},
    "land permanents": {"card_type": "land"},
    "walls": {"subtype": "wall"},
    "enchanted creatures": {"card_type": "creature", "enchanted": True},
    "creatures it's blocking": {"card_type": "creature", "blocked_by_recipient": True},
    # "...by **spells that target it**" (Bronze Horse). Not a property of the
    # source object at all: it is a fact about the spell on the stack that is
    # dealing the damage, and the same spell aimed at something else is not
    # shielded against. A fourth kind of narrowing beside the three above, which
    # is why the value is a dict rather than a type word.
    "spells that target it": {"spell_targets_recipient": True},
    # Resolved against the holder before the source is tested — see
    # :func:`_resolved_chosen_color`. The key is deliberately not `color`: a
    # class that reached the matcher unresolved must answer *nothing* rather
    # than every source, and a key no branch of `_source_shield_matches` reads
    # would do the opposite.
    "sources of the chosen color": {"chosen_color": True},
    "sources of the last chosen color": {"chosen_color": True},
}


def _resolved_chosen_color(wanted: dict, holder) -> dict | None:
    """*wanted* with a chosen-colour class turned into the colour the holder
    recorded, or None when it recorded none.

    CR 614.1c puts the choice at entry and ``engine/mixins/permanent_state.py``
    stamps it, so the answer lives on the permanent whose text carried the line
    — which is why it is resolved here, where that permanent is in hand, rather
    than in the pure matcher below. The same shape
    ``handlers/_chosen._resolve_chosen_color`` gives the noun-phrase side.

    None rather than an unnarrowed shield: a holder with no colour recorded has
    named no property for CR 615.9 to recheck, and a shield answering to every
    source is the widest possible reading of a sentence that names one colour.
    """
    if not wanted.get("chosen_color"):
        return wanted
    color = (getattr(holder, "metadata", {}) or {}).get("chosen_color")
    if not color:
        return None
    resolved = {k: v for k, v in wanted.items() if k != "chosen_color"}
    resolved["color"] = color
    return resolved


def _source_shield_matches(
    game, source, recipient, wanted: dict, seat: int | None = None
) -> bool:
    """Whether *source* is in the class *wanted* names.

    Every key is checked, never a subset: a shield whose phrase this file
    admits and whose narrowing it then ignores is damage prevented that the
    card does not prevent, which is the direction every gate in this codebase
    is written against.
    """
    card_type = wanted.get("card_type")
    if card_type and not source_has_type(game, source, str(card_type)):
        return False
    subtype = wanted.get("subtype")
    if subtype:
        if not hasattr(source, "has_type") or not source.has_type(str(subtype)):
            return False
    if wanted.get("enchanted"):
        from ..aura_attachment import auras_attached_to

        if not hasattr(source, "metadata") or not auras_attached_to(source):
            return False
    color = wanted.get("color")
    if color and color not in damage_source_colors(game, source, seat=seat):
        # CR 615.9 rechecks the recorded property when the damage would be
        # dealt, so a source that has changed colour since the Aura entered is
        # tested by what it is now.
        return False
    if wanted.get("chosen_color"):
        # Unresolved: nothing was recorded, so the class names no source at all.
        # Answering True here would shield against every source in the game.
        return False
    if wanted.get("spell_targets_recipient") and not _spell_targets_recipient(
        game, source, recipient
    ):
        return False
    if wanted.get("blocked_by_recipient"):
        # "…by creatures **it's blocking**" (Wall of Shadows, Wall of Vapor).
        # The Wall is the blocker and the source is an attacker it was declared
        # against, so the relationship is read off combat rather than off
        # either object — and it is directional: a creature blocking the Wall
        # is not a creature the Wall is blocking.
        if not _recipient_is_blocking(game, recipient, source):
            return False
    return True


def _spell_targets_recipient(game, source, recipient) -> bool:
    """Whether *source* is a spell on the stack that targets *recipient*.

    A spell's damage source is the card itself (CR 109.5) -- the card as
    printed, which records neither who cast it nor what it was aimed at. So the
    targets come from ``Game.resolving_targets``, the seam
    ``_execute_oracle_instruction`` pushes around every instruction, exactly as
    the seat does. Reading the stack instead does not work and is not merely
    slower: the object is popped before its instructions run, so by the time the
    damage would be dealt there is nothing there to ask.

    "Spells", not abilities: an activated or triggered ability is not a spell
    (CR 113.7a), and its damage source is the permanent it is on -- which is what
    the first refusal below tests, because a permanent is not a spell however it
    is dealing the damage.

    By the stable target *id* rather than a recorded index: an index is a slot
    in a battlefield list, and anything leaving renumbers every later one.
    """
    if source is None or hasattr(source, "metadata"):
        return False
    permanent_id = getattr(recipient, "permanent_id", None)
    if permanent_id is None:
        return False
    chosen = getattr(game, "resolving_targets", None) or ()
    return bool(chosen) and permanent_id in chosen[-1]


def _recipient_is_blocking(game, recipient, source) -> bool:
    """Whether *recipient* was declared as a blocker of *source* (CR 509.1a)."""
    if not hasattr(recipient, "metadata") or not hasattr(source, "metadata"):
        return False
    attacker_index = game.battlefield_index_of(source)
    blocker_index = game.battlefield_index_of(recipient)
    blocker_seat = game.controller_index_of(recipient)
    if attacker_index is None or blocker_index is None or blocker_seat is None:
        return False
    assignments = game.combat_blockers.get(blocker_seat, {})
    return attacker_index in (assignments.get(blocker_index) or ())


def _source_type_shield_match(line: str):
    return _PREVENT_ALL_FROM_SOURCE_TYPE_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )


def _shield_from_match(match) -> dict | None:
    """The source class, event narrowing and condition one matched line
    describes."""
    wanted = _SOURCE_CLASSES.get(match.group("source"))
    if wanted is None:
        # A phrase the pattern admits with no class behind it would be a shield
        # against everything. Answering None keeps the card unsupported.
        return None
    described = {**wanted, "combat_only": bool(match.group("combat"))}
    phrase = match.group("condition")
    if phrase is not None:
        # The grammar's own noun-phrase reader, lazily imported because the
        # grammar's parse claim imports this module. A phrase it cannot read
        # answers None, which keeps the card unsupported rather than shielding
        # it unconditionally -- a condition dropped is a shield strictly wider
        # than the card prints.
        from ..grammar import subject_filter_payload

        filt = subject_filter_payload(phrase)
        if filt is None:
            return None
        described["condition"] = {"kind": "controls", "who": "you", "filter": filt}
    return described


def prevent_all_from_source_type(line: str) -> dict | None:
    """The class of source *line* shields the permanent printing it against, or
    None if it is not that line. One matcher, asked by the interceptor below and
    by the claim reader, so what is implemented and what is claimed cannot
    drift."""
    match = _source_type_shield_match(line)
    if match is None or match.group("subject") != "this":
        return None
    return _shield_from_match(match)


def attached_prevent_all_from_source_type(line: str) -> dict | None:
    """The same answer for the "enchanted / equipped" form (Artifact Ward),
    where the shield covers what the Aura or Equipment is attached to rather
    than the permanent printing the line.

    Exported for ``engine/auras.py``'s support gate, which claims the line by
    asking the code that carries it out.
    """
    match = _source_type_shield_match(line)
    if match is None or match.group("subject") == "this":
        return None
    return _shield_from_match(match)


def _source_type_shielded_by(game, event: dict) -> dict | None:
    """The source class the damaged permanent is shielded against.

    Pure: it reads text and answers, spending nothing. Two places print the
    line, and both are read here: the recipient's own text ("dealt to **this**
    creature", so a second copy on the battlefield shields itself and not its
    twin) and the text of whatever is attached to it ("dealt to **enchanted**
    creature", which is a shield the recipient's own text says nothing about).
    """
    from ..aura_attachment import auras_attached_to

    recipient = event["recipient"]
    if isinstance(recipient, PlayerState) or recipient is None:
        return None
    for line in getattr(recipient, "effective_card", recipient.card).oracle_text.splitlines():
        wanted = prevent_all_from_source_type(line)
        if wanted is None or not _condition_holds(game, wanted, recipient):
            continue
        resolved = _resolved_chosen_color(wanted, recipient)
        if resolved is not None:
            return resolved
    for attached in auras_attached_to(recipient):
        for line in attached.effective_card.oracle_text.splitlines():
            wanted = attached_prevent_all_from_source_type(line)
            if wanted is None or not _condition_holds(game, wanted, attached):
                continue
            # The colour is the **Aura's**, recorded as it entered — not the
            # enchanted creature's, which has none of its own.
            resolved = _resolved_chosen_color(wanted, attached)
            if resolved is not None:
                return resolved
    return None


def _condition_holds(game, wanted: dict, holder) -> bool:
    """Whether a shield's "as long as" clause holds right now (CR 611.2).

    Asked here, where the permanent whose text carried the line is in hand, and
    asked on every event rather than latched: the creature the clause counts may
    leave, and a shield that outlived its condition is one the card does not
    print. Pure, like every other predicate in this file.

    The clause is evaluated by ``engine/static_bonuses.conditional_static_holds``
    -- the same payload shape and the same evaluator the conditional P/T bonuses
    use, so "you control another creature" has one meaning in the engine.
    """
    condition = wanted.get("condition")
    if condition is None:
        return True
    from ..static_bonuses import conditional_static_holds

    seat = game.controller_index_of(holder)
    if seat is None:
        return False
    return conditional_static_holds(game, seat, holder, condition)


def _applies_source_type_blanket(game, event: dict) -> bool:
    wanted = _source_type_shielded_by(game, event)
    if wanted is None:
        return False
    if wanted.get("combat_only") and not event.get("combat"):
        # "Prevent all **combat** damage … by Walls" (Marble Priest). A shield
        # that ignored the word would stop a Wall's ping as well, which is a
        # strictly larger effect than the card prints.
        return False
    return _source_shield_matches(
        game, event.get("source"), event["recipient"], wanted,
        event.get("source_seat"),
    )


def _source_class_label(wanted: dict) -> str:
    """The printed class a shield answers to, in words rather than as its dict.

    The log line used to interpolate the payload itself, which put
    ``{'card_type': 'artifact', 'combat_only': False}`` in front of a player.
    Built from the same keys the matcher reads, so a narrowing added there and
    forgotten here shows as the generic word instead of as a silently different
    claim.
    """
    color = wanted.get("color")
    if color:
        # The symbol back to the printed word, through the grammar's own colour
        # table rather than a second copy of it.
        from ..grammar.vocabulary import COLOR_WORDS

        return next(
            (word for word, symbol in COLOR_WORDS.items() if symbol == color),
            str(color),
        )
    for key in ("subtype", "card_type"):
        value = wanted.get(key)
        if value:
            return str(value).lower()
    if wanted.get("enchanted"):
        return "enchanted creature"
    if wanted.get("blocked_by_recipient"):
        return "blocked creature"
    if wanted.get("spell_targets_recipient"):
        return "targeting spell"
    return "matching"


@prevention_effect(SOURCE_TYPE_BLANKET, applies=_applies_source_type_blanket)
def _prevent_all_from_source_type(game, event: dict) -> PreventionOutcome | None:
    wanted = _source_type_shielded_by(game, event)
    if wanted is None:
        return None
    recipient = event["recipient"]
    game.log.append(
        f"{recipient.card.name} prevented {event['amount']} damage "
        f"from a {_source_class_label(wanted)} source"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "If a source would deal damage to you, prevent **1** of that damage."
#: (Urza's Armor.) The sibling of ``_PREVENT_AND_COUNT_RE`` above, one clause
#: apart: Nine Lives prevents the whole instance and charges a counter for it,
#: this one shaves a fixed number of points and charges nothing. The number is
#: payload, the way every parameter in this file is — a card printing "prevent 2
#: of that damage" needs no code here.
#:
#: A **prevention** (CR 615) and not a replacement, which the printed verb
#: settles: CR 615.1 says a prevention effect is one that uses the word
#: "prevent". Written as a CR 614 replacement it would still arrive at the right
#: life total and would report the wrong thing to everything that asks how much
#: damage was prevented.
#:
#: **The source's colour is payload too** (the five Odyssey Spheres: "If a
#: *red* source would deal damage to you, prevent 2 of that damage."). One
#: optional word in front of "source", read through ``damage_source_colors`` at
#: the moment the damage would be dealt (CR 615.1 — a static prevention is not
#: locked in), so a spell answers with its stack colours, a permanent through
#: layer 5, and a source Ghostly Flame makes colourless *as a source of damage*
#: is no colour's source at all.
_PREVENT_N_OF_DAMAGE_RE = re.compile(
    r"^if a (?:(?P<color>white|blue|black|red|green) )?source would deal "
    r"damage to you, prevent (?P<points>\d+) of that damage$"
)


def static_points_shield(line: str) -> dict | None:
    """What *line* shaves off each event — ``{"points": n, "color": symbol or
    None}`` — or None if it is not that line.

    One matcher, asked by the interceptor below and by the claim reader, so
    what is prevented and what is claimed cannot drift. ``color`` is the mana
    symbol of the printed colour word and None for the unnarrowed sentence.
    """
    match = _PREVENT_N_OF_DAMAGE_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    word = match.group("color")
    if word is None:
        return {"points": int(match.group("points")), "color": None}
    from ..oracle_types import _COLOR_WORD_TO_SYMBOL

    return {"points": int(match.group("points")),
            "color": _COLOR_WORD_TO_SYMBOL[word]}


def prevent_n_of_damage(line: str) -> int | None:
    """How many points *line* shaves off each event it answers to, or None if
    it is not that line. The claim readers' question; the interceptor asks
    :func:`static_points_shield`, which also carries the source narrowing."""
    described = static_points_shield(line)
    return described["points"] if described else None


def _static_points_prevented(game, event: dict) -> int:
    """How many points every such line on the recipient's board shaves off this
    event. Pure — nothing is spent, because nothing here is a charge.

    **Summed** across the battlefield, for ``replacements._spell_damage_delta``'s
    reason exactly: CR 616.1 would apply two Armors as two effects in an order
    the affected player picks, subtraction commutes, and one candidate per
    registration is the model ``apply_in_order`` has. Clamped to the event, so
    two Armors against 1 damage prevent 1 and not 2.

    "To **you**" is the Armor's controller (CR 109.5), which is why the scan is
    over the recipient's own battlefield: an opponent's Armor does nothing for
    the player being burned.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or not isinstance(recipient, PlayerState):
        return 0
    seat = game.players.index(recipient) if recipient in game.players else None
    if seat is None:
        return 0
    total = 0
    source_colors: tuple[str, ...] | None = None
    for permanent in game.controlled_by(seat):
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            described = static_points_shield(line)
            if described is None:
                continue
            if described["color"] is not None:
                # "a **red** source": the source's colour as a source of
                # damage, asked once per event and only when some line narrows.
                if source_colors is None:
                    source_colors = damage_source_colors(
                        game, event.get("source"), seat=event.get("source_seat")
                    )
                if described["color"] not in source_colors:
                    continue
            total += described["points"]
    return min(total, amount)


def _applies_static_points(game, event: dict) -> bool:
    return _static_points_prevented(game, event) > 0


@prevention_effect(STATIC_POINTS, applies=_applies_static_points)
def _prevent_static_points(game, event: dict) -> PreventionOutcome | None:
    """A static prevention: "If a source would deal damage to you, prevent 1 of
    that damage." (Urza's Armor; the five Spheres print it over one colour.)

    The words before the colon are the option a player is shown when CR 616.1
    asks which effect applies first, so they name what the effect *is* rather
    than the first card that printed it — with a Sphere of Law on the table the
    prompt offered "Urza's Armor", a card that was not there.

    Every event, from every source, for as long as the permanent printing it is
    on the battlefield — and never used up, which is what makes it a static
    prevention rather than CR 615.7's pool. Nothing is spent and nothing is
    recorded: the next event asks the board again, so the shield ends with the
    permanent (CR 611.2) rather than needing a sweep.
    """
    prevented = _static_points_prevented(game, event)
    game.log.append(
        f"{event['recipient'].name} prevented {prevented} of "
        f"{event['amount']} damage (a static prevention)"
    )
    return PreventionOutcome(prevented=prevented)


def _static_prevention_source(game, event: dict):
    """The recipient's own permanent whose static prevention covers this event,
    with the counter it charges — or None.

    Pure, like every other applicability predicate here: it looks the permanent
    up and reads its text, and the counter is only placed by the ``apply`` half.
    """
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        return None
    for permanent in game.controlled_by(recipient):
        for line in permanent.effective_card.oracle_text.splitlines():
            counter = prevent_and_count_kind(line)
            if counter is not None:
                return permanent, counter
    return None


def _applies_static_whole_event(game, event: dict) -> bool:
    return _static_prevention_source(game, event) is not None


@prevention_effect(STATIC_WHOLE_EVENT, applies=_applies_static_whole_event)
def _prevent_and_place_counter(game, event: dict) -> PreventionOutcome | None:
    """Nine Lives: "If a source would deal damage to you, prevent that damage
    and put an incarnation counter on this enchantment."

    The whole instance is prevented however large it is, and the counter is
    placed once per prevented event rather than once per point — CR 615.5's
    "additional effect", which happens *after* the prevention and refers to the
    event, not to the damage's size. Nine damage and one damage each cost the
    same counter, which is what makes the card a nine-*event* shield.
    """
    found = _static_prevention_source(game, event)
    if found is None:
        return None
    permanent, counter = found
    total = add_counters(permanent, counter, 1)
    game.log.append(
        f"{permanent.card.name} prevented {event['amount']} damage to "
        f"{event['recipient'].name} ({total} {counter} counter(s))"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "For each 1 damage that would be dealt to this creature, if it has a +1/+1
#: counter on it, remove a +1/+1 counter from it and prevent that 1 damage."
#: (Rock Hydra.) The counter's word is payload, exactly as Nine Lives' is
#: above; the backreference holds the removal to the same counter the
#: condition asked about, so a line naming two different counters is not this
#: shape and refuses.
_PER_DAMAGE_COUNTER_RE = re.compile(
    r"^for each 1 damage that would be dealt to this "
    r"(?:artifact|creature|enchantment|land|permanent), "
    r"if it has an? (?P<counter>\S+) counter on it, "
    r"remove an? (?P=counter) counter from it and prevent that 1 damage$"
)


def per_damage_counter_kind(line: str) -> str | None:
    """The counter *line* spends per point of damage, or None if it is not
    that line. One matcher for the interceptor and both claim readers, so what
    is implemented and what is claimed cannot drift."""
    match = _PER_DAMAGE_COUNTER_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    return match.group("counter") if match else None


def _counters_available(permanent, counter: str) -> int:
    """How many *counter* counters *permanent* holds. "+1/+1" lives on the
    P/T channel (engine/pt.py — it has layer-7d meaning); every other word is
    an inert named counter."""
    if counter == "+1/+1":
        return int(permanent.metadata.get("plus_counters", 0))
    return counters_on(permanent, counter)


def _per_damage_counter_shield(game, event: dict) -> str | None:
    """The counter kind the recipient's own per-point shield spends, or None."""
    recipient = event["recipient"]
    if isinstance(recipient, PlayerState):
        return None
    for line in recipient.effective_card.oracle_text.splitlines():
        counter = per_damage_counter_kind(line)
        if counter is not None:
            return counter
    return None


def _applies_per_damage_counter(game, event: dict) -> bool:
    counter = _per_damage_counter_shield(game, event)
    return counter is not None and _counters_available(event["recipient"], counter) > 0


@prevention_effect(PER_POINT_COUNTER_SHIELD, applies=_applies_per_damage_counter)
def _remove_counter_per_damage(game, event: dict) -> PreventionOutcome | None:
    """Rock Hydra's automatic half: one counter per point, only as far as the
    counters go (CR 615.7's partial prevention) — three counters against five
    damage remove all three and let two through.

    This was the acknowledged line the roadmap called "the Nine Lives class
    hiding behind a verified-sounding acknowledgement": prevention.py was
    credited with it while implementing only the activated {R} shield, so the
    damage went through in full with the counters untouched.
    """
    counter = _per_damage_counter_shield(game, event)
    if counter is None:
        return None
    permanent = event["recipient"]
    if counter == "+1/+1":
        removed = remove_plus1_counters(permanent, event["amount"])
    else:
        have = counters_on(permanent, counter)
        removed = min(event["amount"], have)
        if removed > 0:
            remove_counters(permanent, counter, removed)
    if removed <= 0:
        return None
    game.log.append(
        f"{permanent.card.name} removed {removed} {counter} counter(s) to "
        f"prevent {removed} damage"
    )
    return PreventionOutcome(prevented=removed)


#: "Prevent all damage that would be dealt to you." (Glacial Chasm.) A static
#: prevention on the permanent's **controller** rather than on the permanent
#: itself, and the unnarrowed member of the family above: no source class, no
#: charges and no duration, because a static ability applies while its source is
#: on the battlefield and stops the moment it is not.
#:
#: The printed "combat" is captured for the reason
#: ``_PREVENT_ALL_FROM_SOURCE_TYPE_RE`` captures its own: a shield that ignored
#: the word would stop a burn spell as well, which is a strictly larger effect
#: than such a card prints.
#:
#: Anchored at both ends, and **without** a duration: "…this turn" is a one-shot
#: effect a spell resolves, which the grammar's ``PreventDamage`` production
#: reads and this must not claim. Claiming the line here takes it away from
#: those productions entirely (``engine/grammar/registries.py``), so the anchor
#: is what keeps the two sentences apart.
#: The trailing source narrowing (Energy Field: "…**by sources you don't
#: control**"). Payload, because it is the one clause that separates two cards
#: printing the same blanket — and a *relation* rather than a description of the
#: source object, so it cannot ride ``_SOURCE_CLASSES`` beside the card types:
#: CR 109.5 gives a source a controller, and the clause compares that seat with
#: the protected one. A blanket that dropped it would shield its controller from
#: their own Flesh Reaver, which is a strictly larger card.
#:
#: The optional leading condition (Spirit of Resistance: "**As long as you
#: control a permanent of each color,** prevent all damage that would be dealt
#: to you."). CR 611.2's "as long as" on a static ability, exactly as
#: ``_PREVENT_ALL_FROM_SOURCE_TYPE_RE`` carries its own one screen up — and the
#: clause is read by the grammar's condition reader rather than as a noun
#: phrase behind a fixed "you control", because "of each color" is a relation
#: over the set and not a narrowing of one permanent.
_PREVENT_ALL_TO_CONTROLLER_RE = re.compile(
    r"^(?:as long as (?P<condition>[^,]+), )?"
    r"prevent all (?P<combat>combat )?damage that would be dealt to you"
    r"(?P<foreign> by sources you don't control)?$"
)


def prevent_all_to_controller(line: str) -> dict | None:
    """The blanket *line* gives the permanent's controller, or None.

    One matcher, asked by the interceptor below and by the claim reader, so
    what is implemented and what is claimed cannot drift.
    """
    match = _PREVENT_ALL_TO_CONTROLLER_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    described: dict = {
        "combat_only": bool(match.group("combat")),
        "foreign_sources_only": bool(match.group("foreign")),
    }
    phrase = match.group("condition")
    if phrase is not None:
        # The grammar's own condition reader, lazily imported because the
        # grammar's parse claim imports this module. Held to the one shape
        # ``_condition_holds`` answers for a standing ability — "you control
        # …", evaluated by ``static_bonuses.conditional_static_holds`` — so a
        # clause that reader would answer False for by not knowing it leaves the
        # card unsupported instead of admitted with a shield that never arms.
        # A clause nothing reads answers None for the same reason in the other
        # direction: a condition dropped is a Glacial Chasm.
        from ..grammar import condition_payload_for

        condition = condition_payload_for(phrase)
        if (
            not condition
            or condition.get("kind") != "controls"
            or condition.get("who") != "you"
        ):
            return None
        described["condition"] = condition
    return described


def _controller_blanket_for(game, event: dict) -> dict | None:
    """The blanket shielding this player *against this event*, read off their
    own battlefield. Pure.

    A player has no text of their own, so the line is found on the permanents
    they control — the same read ``_source_type_shielded_by`` makes of a
    damaged permanent, one relation out. Through the control seam rather than a
    battlefield list, so a Glacial Chasm somebody else has taken control of
    shields *them*.

    The source narrowing is tested here rather than in the applicability
    predicate below, so a board holding a narrow blanket that does not cover
    this event goes on looking for a wide one instead of answering with the
    first line it found.
    """
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        return None
    seat = game.players.index(recipient) if recipient in game.players else None
    if seat is None:
        return None
    for permanent in game.controlled_by(seat):
        for line in permanent.effective_card.oracle_text.splitlines():
            described = prevent_all_to_controller(line)
            if described is None:
                continue
            if not _condition_holds(game, described, permanent):
                # "**As long as you control a permanent of each color,** …"
                # (Spirit of Resistance.) Rechecked at every event rather than
                # latched (CR 611.2): the fifth colour may have left since.
                continue
            if described["foreign_sources_only"] and (
                # "…by sources **you don't control**" (Energy Field). CR 109.5's
                # seat, derived once inside ``deal_damage`` and read here rather
                # than re-derived — a source with no controller at all (a
                # turn-based action) is one nobody controls, so it is covered.
                event.get("source_seat") == seat
            ):
                continue
            return described
    return None


def _applies_controller_blanket(game, event: dict) -> bool:
    described = _controller_blanket_for(game, event)
    if described is None:
        return False
    if event["amount"] <= 0:
        return False
    return bool(event.get("combat")) or not described["combat_only"]


@prevention_effect(CONTROLLER_BLANKET, applies=_applies_controller_blanket)
def _prevent_all_to_controller(game, event: dict) -> PreventionOutcome | None:
    """Glacial Chasm: "Prevent all damage that would be dealt to you."

    Every point, from every source, for as long as the permanent printing it is
    on the battlefield. Nothing is spent and nothing is recorded — the next
    event asks the board again, which is what makes the shield end with the
    permanent (CR 611.2) rather than needing a sweep.
    """
    described = _controller_blanket_for(game, event) or {}
    game.log.append(
        f"{event['recipient'].name} prevented {event['amount']} damage "
        + (
            "(all damage from sources they don't control)"
            if described.get("foreign_sources_only")
            else "(all damage that would be dealt to them)"
        )
    )
    return PreventionOutcome(prevented=event["amount"])


#: "Prevent all damage that would be dealt by instant and sorcery spells."
#: (Energy Storm.) A static prevention with **no recipient** — every point every
#: spell of the named classes would deal, to anything. The narrowing is on the
#: source's card type, which is what makes it a different reader from the
#: recipient-scoped blanket above: there is no object to hang the shield off, so
#: the permanent printing the line is scanned for on every event instead.
#:
#: The classes are captured and split on "and", so a card printing one type or
#: three needs no code — the same choice ``_SOURCE_DAMAGE_CAP`` makes about its
#: own printed class one file over.
_PREVENT_ALL_FROM_SPELL_CLASS_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt by "
    r"(?P<classes>[a-z ]+?) spells$"
)


def prevent_all_from_spell_class(line: str) -> dict | None:
    """The spell classes *line* shields the whole table from, or None.

    One matcher, asked by the interceptor below and by the claim reader, so what
    is prevented and what is claimed cannot drift.

    A class naming no readable type refuses the whole line rather than
    shielding against everything: ``source_has_type`` answers False for a word
    it does not know, and a shield that matched every spell would be a card
    nobody printed.
    """
    match = _PREVENT_ALL_FROM_SPELL_CLASS_RE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    classes = tuple(
        word.strip()
        for word in match.group("classes").replace(" and ", ",").split(",")
        if word.strip()
    )
    if not classes or any(word not in _SPELL_CLASSES for word in classes):
        return None
    return {"classes": classes, "combat_only": bool(match.group("combat"))}


#: The card types a spell class may name. A closed set rather than any word,
#: because ``source_has_type`` substring-matches a type line: an unlisted word
#: would answer False for every spell and the shield would silently do nothing,
#: which is the failure this file's claim readers exist to keep out of the
#: supported pool.
_SPELL_CLASSES = frozenset({
    "artifact", "creature", "enchantment", "instant", "sorcery",
})


def _spell_class_blanket(game, event: dict) -> dict | None:
    """The spell-class blanket covering this event, or None. Pure.

    Scanned over every battlefield rather than the recipient's: the sentence
    names no recipient at all, so an opponent's Energy Storm covers this damage
    exactly as your own would.
    """
    if event["amount"] <= 0:
        return None
    source = event.get("source")
    if source is None or hasattr(source, "metadata"):
        # A permanent is not a spell however it is dealing the damage
        # (CR 110.1). A spell's source is the card as printed (CR 109.5), which
        # is the shape with no ``metadata``.
        return None
    for permanent in game.all_permanents():
        for line in permanent.effective_card.oracle_text.splitlines():
            described = prevent_all_from_spell_class(line)
            if described is None:
                continue
            if described["combat_only"] and not event.get("combat"):
                continue
            if any(
                source_has_type(game, source, word)
                for word in described["classes"]
            ):
                return described
    return None


def _applies_spell_class_blanket(game, event: dict) -> bool:
    return _spell_class_blanket(game, event) is not None


@prevention_effect(SPELL_CLASS_BLANKET, applies=_applies_spell_class_blanket)
def _prevent_all_from_spell_class(game, event: dict) -> PreventionOutcome | None:
    """Energy Storm: "Prevent all damage that would be dealt by instant and
    sorcery spells."

    Every point, for as long as the permanent printing it is on the
    battlefield. Nothing is spent and nothing recorded — the next event asks the
    board again, which is what ends the shield with the permanent (CR 611.2)
    rather than with a sweep.
    """
    described = _spell_class_blanket(game, event)
    if described is None:  # pragma: no cover - the predicate just said otherwise
        return None
    game.log.append(
        f"{event['amount']} damage from a "
        f"{'/'.join(described['classes'])} spell is prevented"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "Prevent all damage that would be dealt to **creatures**." (Bubble Matrix) /
#: "…to **creatures you control**." (Inner Sanctum.) The recipient is a printed
#: noun phrase describing permanents, which is what makes this a different
#: reader from :func:`prevent_all_to_controller` above — that one's recipient is
#: a *player*, and a player has no characteristics to match.
#:
#: One row for both cards, because the only difference between them is the noun
#: phrase: "you control" narrows the set relative to the permanent printing the
#: line (CR 109.5), and it rides the payload as an ordinary filter the one
#: matcher already tests. Spelling either card's phrase into a kind would make
#: every printed narrowing a new kind and a new interceptor.
#:
#: Anchored at both ends and **without** a duration, exactly as the controller
#: blanket above is and for its reason: "…this turn" is a one-shot effect the
#: grammar's ``PreventDamage`` production reads, and claiming the line here
#: takes it away from that production entirely
#: (``engine/grammar/registries.py``).
#:
#: The phrase is read by the **grammar's** noun parser
#: (``grammar.subject_filter_payload``) rather than by a regex here, for
#: ``combat_restrictions._printed_noun``'s reason one file over:
#: ``subject_matches`` is what will answer this at every damage event, and a
#: second reader of "creatures you control" would be free to disagree with it.
#: A phrase it cannot read *in full* refuses the whole line — which is also what
#: keeps this pattern's ``.+`` off the source-narrowed sentences above it
#: ("…dealt to this creature **by artifact sources**"): that tail is not a noun
#: phrase, so the parser leaves it unconsumed and the line falls through to the
#: reader that owns it.
#:
#: ``plural=True`` is the other half of that gate and it is load-bearing: the
#: parser refuses a *singular* self-reference under it, so "…dealt to **this
#: creature**" and "…dealt to **enchanted creature**" — the two subjects the
#: source-narrowed readers above own — cannot reach this shield. Without it
#: both would reduce to a bare ``{"type_filter": "creature"}`` and one Aura
#: would make every creature in the game unkillable.
#:
#: **The direction is captured, and only two of the three are here.** Statecraft
#: prints "…dealt **to and dealt by** creatures you control", which is this
#: blanket read at both ends of the event — the same widening
#: ``_STATIC_DAMAGE_SHIELD_RE`` carries for the singular subjects, in
#: ``shields.py``. A bare "by" is deliberately *not* an alternative:
#: "Prevent all damage that would be dealt **by instant and sorcery spells**"
#: (Energy Storm) is a narrowing of the *source class* with no recipient at all,
#: and it has its own reader below — admitted here it would read the source
#: description as a set of protected permanents and shield whatever happened to
#: match it.
_PREVENT_ALL_TO_MATCHING_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt "
    r"(?P<direction>to and dealt by|to) "
    r"(?P<subject>.+)$"
)


def prevent_all_to_matching(line: str) -> dict | None:
    """The set of permanents *line* shields, or None.

    One matcher, asked by the interceptor below and by the claim reader, so what
    is prevented and what is claimed cannot drift.
    """
    from ..grammar import subject_filter_payload

    match = _PREVENT_ALL_TO_MATCHING_RE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    described = subject_filter_payload(match.group("subject"), plural=True)
    # None covers both refusals that matter here: a phrase the noun parser
    # cannot read end to end, and one carrying a narrowing `subject_matches`
    # cannot test. Either admitted, the shield would cover a strictly larger set
    # than the card prints — which for a prevention is a permanent nothing can
    # ever kill.
    if not described:
        return None
    return {
        "filter": described,
        "combat_only": bool(match.group("combat")),
        "two_way": match.group("direction") == "to and dealt by",
    }


def _matching_blanket_for(game, event: dict) -> str | None:
    """The name of a permanent whose blanket covers this event, or None. Pure.

    Every battlefield, because the sentence names no controller of its own:
    Bubble Matrix shields both seats' creatures and Inner Sanctum shields its
    own controller's, and which of the two a card is depends on the noun phrase
    rather than on who owns the enchantment. ``observer`` is therefore the seat
    controlling the *printing* permanent (CR 109.5) and ``source`` is that
    permanent, which is what makes "you control" mean the Sanctum's controller.

    **Both ends are asked when the line prints both.** Statecraft's "…to and
    dealt by creatures you control" covers the damage one of those creatures
    *deals* as well, and that half of the event is the only one a player can be
    on — so a ``PlayerState`` recipient is no longer an early return, it simply
    fails the recipient half and is carried by the source half or by nothing.
    The set is matched at the damage event rather than when the enchantment
    entered (CR 611.2c), so a creature that changed hands since is read the way
    the board reads now.
    """
    if event["amount"] <= 0:
        return None
    from ..models import Permanent
    from ..subject_filters import subject_matches

    recipient = event["recipient"]
    # A player is the controller blanket's business, one reader up: the noun
    # phrase here describes permanents, and asking `subject_matches` about a
    # `PlayerState` is a question it has no answer for.
    protected = None if isinstance(recipient, PlayerState) else recipient
    source = event.get("source")
    dealer = source if isinstance(source, Permanent) else None
    for seat, permanent in game.permanents_with_controller():
        for line in permanent.effective_card.oracle_text.splitlines():
            described = prevent_all_to_matching(line)
            if described is None:
                continue
            if described["combat_only"] and not event.get("combat"):
                continue
            ends = [protected]
            if described["two_way"]:
                ends.append(dealer)
            for end in ends:
                if end is not None and subject_matches(
                    game, end, dict(described["filter"]),
                    observer=seat, source=permanent,
                ):
                    return permanent.card.name
    return None


def _applies_matching_blanket(game, event: dict) -> bool:
    return _matching_blanket_for(game, event) is not None


@prevention_effect(MATCHING_BLANKET, applies=_applies_matching_blanket)
def _prevent_all_to_matching(game, event: dict) -> PreventionOutcome | None:
    """Bubble Matrix: "Prevent all damage that would be dealt to creatures."
    Statecraft: "…combat damage that would be dealt to and dealt by creatures
    you control."

    Every point, from every source, for as long as the permanent printing it is
    on the battlefield. Nothing is spent and nothing recorded — the next event
    asks the board again, which is what ends the shield with the permanent
    (CR 611.2) rather than with a sweep.
    """
    name = _matching_blanket_for(game, event)
    if name is None:  # pragma: no cover - the predicate just said otherwise
        return None
    # ``recipient_label`` rather than ``.card.name``: the two-way reading above
    # covers an event whose recipient is a *player* (a creature you control
    # attacking one), and a player has no card.
    game.log.append(
        f"{event['amount']} damage to {recipient_label(event['recipient'])} is "
        f"prevented ({name})"
    )
    return PreventionOutcome(prevented=event["amount"])


def _applies_chosen_source_one_shot(game, event: dict) -> bool:
    """Whether the event's source is carrying Desperate Gambit's losing half.

    Pure — it reads the count and never spends it, which is what CR 616.1's
    counting round requires of every predicate in this file.
    """
    if event["amount"] <= 0:
        return False
    # "…would deal **combat** damage…" (Impulsive Maneuvers) answers only to a
    # combat event; the unnarrowed rider (Desperate Gambit) to every one.
    return armed_for_event(
        event.get("source"), DAMAGE_PREVENTED_NEXT,
        combat=bool(event.get("combat")),
    ) > 0


@prevention_effect(CHOSEN_SOURCE_ONE_SHOT, applies=_applies_chosen_source_one_shot)
def _prevent_next_damage_from_chosen_source(game, event: dict) -> PreventionOutcome | None:
    """Desperate Gambit's losing flip: "the next time it would deal damage this
    turn, prevent that damage."

    The whole instance, whoever it was headed for — no recipient is recorded
    anywhere, because the sentence names none. Spent by instance, so a source
    that deals damage twice this turn has only its first event prevented; the
    rider's other end of life is the turn, swept with every other marker a
    damager carries (``mixins/_constants._EOT_METADATA_KEYS``).
    """
    source = event.get("source")
    amount = event["amount"]
    spend_for_event(
        source, DAMAGE_PREVENTED_NEXT, combat=bool(event.get("combat"))
    )
    card = getattr(source, "card", source)
    game.log.append(
        f"{amount} damage from {getattr(card, 'name', 'a chosen source')} is "
        "prevented (the next time it would deal damage this turn)"
    )
    return PreventionOutcome(prevented=amount)


#: "If a source would deal **3** or less damage to this creature, prevent that
#: damage." (Callous Giant.) A static shield narrowed by the **size of the
#: event** — every other reader in this file narrows by who is dealing the
#: damage or who is taking it. The threshold is payload, the way every
#: parameter here is: a card printing "2 or less" needs no code.
#:
#: The comparison is against the event *as it stands when this shield is
#: asked* (CR 615.1: a prevention effect applies to damage that "would be
#: dealt", and CR 616.1f re-asks after each applied effect). So five damage a
#: prevention pool has already cut to three is three or less, and one damage a
#: Furnace of Rath has not yet doubled is one — both are orders the Giant's
#: controller could choose, and the second is the one they would.
#:
#: All of it or none of it: "prevent **that damage**" names the whole event,
#: and four damage is not partly prevented.
_PREVENT_SMALL_EVENT_RE = re.compile(
    r"^if a source would deal (?P<threshold>\d+) or less damage to this "
    r"(?:artifact|creature|enchantment|land|permanent), prevent that damage$"
)


def prevent_small_event_threshold(line: str, card_name: str | None = None) -> int | None:
    """The largest event *line* prevents outright, or None if it is not that
    line. One matcher, asked by the interceptor below and by the claim reader,
    so what is prevented and what is claimed cannot drift.

    *card_name* collapses CR 201.5's self-reference the way
    ``_static_shield_match`` does, for the legendary templating that would
    print the creature's own name.
    """
    normalized = " ".join((line or "").strip().lower().rstrip(".").split())
    if card_name:
        from ..self_reference import _collapse_self_references

        normalized = _collapse_self_references(
            normalized, card_name, "this creature"
        )
    match = _PREVENT_SMALL_EVENT_RE.match(normalized)
    return int(match.group("threshold")) if match else None


def _small_event_threshold_for(game, event: dict) -> int | None:
    """The threshold under which the damaged permanent's own text prevents this
    event, or None. Pure.

    The recipient's own text only — "dealt to **this** creature" — so a second
    Giant shields itself and not its twin, and read off the effective card so
    a copy carries the shield and a creature whose text was removed does not.
    """
    recipient = event["recipient"]
    amount = event["amount"]
    if amount <= 0 or isinstance(recipient, PlayerState) or recipient is None:
        return None
    card = getattr(recipient, "effective_card", None) or recipient.card
    best: int | None = None
    for line in (card.oracle_text or "").splitlines():
        threshold = prevent_small_event_threshold(line, card.name)
        if threshold is not None and amount <= threshold:
            best = threshold if best is None else max(best, threshold)
    return best


def _applies_small_event_blanket(game, event: dict) -> bool:
    return _small_event_threshold_for(game, event) is not None


@prevention_effect(SMALL_EVENT_BLANKET, applies=_applies_small_event_blanket)
def _prevent_small_event(game, event: dict) -> PreventionOutcome | None:
    """Callous Giant: "If a source would deal 3 or less damage to this
    creature, prevent that damage."

    Every such event, for as long as the creature is on the battlefield.
    Nothing is spent and nothing recorded — the next event asks the text again
    (CR 611.2), and each is judged on its own size: three one-point pings are
    three prevented events, never a four-point total.
    """
    threshold = _small_event_threshold_for(game, event)
    if threshold is None:  # pragma: no cover - the predicate just said otherwise
        return None
    game.log.append(
        f"{event['recipient'].card.name} prevented {event['amount']} damage "
        f"({threshold} or less from one source)"
    )
    return PreventionOutcome(prevented=event["amount"])


#: "Prevent all damage that would be dealt to a creature by another creature
#: if they share a color." (Well-Laid Plans.) A static blanket over the whole
#: table with **no described set at either end**: what it names is a relation
#: between the event's two ends, which is why it is not a row of
#: ``prevent_all_to_matching`` — that reader tests one permanent against a noun
#: phrase, and "shares a colour with whatever is hitting it" is not a property
#: one permanent has.
#:
#: The printed "combat" is captured for the reason every blanket here captures
#: its own. Anchored and without a duration, for the controller blanket's
#: reason: "…this turn" would be a one-shot effect the grammar reads.
_PREVENT_SHARED_COLOR_RE = re.compile(
    r"^prevent all (?P<combat>combat )?damage that would be dealt to a "
    r"creature by another creature if they share a color$"
)


def prevent_between_shared_colors(line: str) -> dict | None:
    """The width of the shared-colour blanket *line* prints, or None.

    One matcher, asked by the interceptor below and by the claim reader, so
    what is prevented and what is claimed cannot drift.
    """
    match = _PREVENT_SHARED_COLOR_RE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    return {"combat_only": bool(match.group("combat"))}


def _shared_color_blanket_for(game, event: dict) -> str | None:
    """The name of a permanent whose shared-colour blanket covers this event,
    or None. Pure.

    Three things have to be true of the event before any board is scanned, and
    each is a printed word:

    - "**to a creature**" — the recipient is a permanent that is a creature
      now (CR 613 layer 4: an animated land is one, a player never is);
    - "**by another creature**" — the source is a *permanent* that is a
      creature, and a different object from the recipient. A spell's source is
      the card as printed (CR 109.5), which is not a creature however red it
      is, so a Lightning Bolt is never covered;
    - "**if they share a color**" — ``object_colors.share_a_color`` over the
      two objects' own layer-5 colours. The objects', deliberately, and not
      ``damage_source_colors``: Ghostly Flame rewrites what colour a source is
      *as a source of damage*, and this sentence asks about "they" — two
      creatures — rather than about the damage. Colourless shares with nothing
      (CR 105.2c), so two artifact creatures fight normally.

    Every battlefield, because the sentence names no controller: an opponent's
    Well-Laid Plans covers your creatures exactly as your own would.
    """
    if event["amount"] <= 0:
        return None
    from ..models import Permanent
    from ..object_colors import share_a_color

    recipient = event["recipient"]
    source = event.get("source")
    if not isinstance(recipient, Permanent) or not isinstance(source, Permanent):
        return None
    if source is recipient or not recipient.is_creature or not source.is_creature:
        return None
    if not share_a_color(
        game._effective_colors(recipient), game._effective_colors(source)
    ):
        return None
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            described = prevent_between_shared_colors(line)
            if described is None:
                continue
            if described["combat_only"] and not event.get("combat"):
                continue
            return permanent.card.name
    return None


def _applies_shared_color_blanket(game, event: dict) -> bool:
    return _shared_color_blanket_for(game, event) is not None


@prevention_effect(SHARED_COLOR_BLANKET, applies=_applies_shared_color_blanket)
def _prevent_between_shared_colors(game, event: dict) -> PreventionOutcome | None:
    """Well-Laid Plans: "Prevent all damage that would be dealt to a creature
    by another creature if they share a color."

    Every point, combat or not, for as long as the enchantment is on the
    battlefield. Nothing is spent and nothing recorded — the colours are read
    when the damage would be dealt (CR 615.1: prevention effects "aren't
    locked in ahead of time"), so a creature a Lace recoloured mid-combat is judged by what
    it is now.
    """
    name = _shared_color_blanket_for(game, event)
    if name is None:  # pragma: no cover - the predicate just said otherwise
        return None
    game.log.append(
        f"{event['amount']} damage to {recipient_label(event['recipient'])} "
        f"from {_source_label(event.get('source'))} is prevented — they share "
        f"a color ({name})"
    )
    return PreventionOutcome(prevented=event["amount"])


def prevention_claims_line(line: str, card_name: str | None = None) -> bool:
    """Whether one printed line is, in full, a static prevention effect
    implemented in this package.

    The twin of ``replacements.replacement_claims_line`` and read by the same
    two callers — the grammar's parse claim (engine/grammar/registries.py) and
    the support gate (engine/oracle.py) — because a permanent whose ability is a
    prevention produces no instruction either. Nine Lives happened to print
    three other lines, so it reported supported with this one silently doing
    nothing; a card printing only this one would have reported unsupported while
    working perfectly, which is the other half of the same hole.

    *card_name* is optional for the reason ``counter_cap_line``'s is, one gate
    over: the self-referencing form only exists on a card, so a reader asking
    about a bare line still gets the answer it always got, and the two callers
    that hold a card pass it. The runtime read is
    ``_attached_damage_shields``'s, which takes the name off the permanent it is
    already looking at.
    """
    return (
        prevent_and_count_kind(line) is not None
        or prevent_n_of_damage(line) is not None
        or per_damage_counter_kind(line) is not None
        or prevent_all_from_source_type(line) is not None
        or attached_prevent_all_from_source_type(line) is not None
        or attached_damage_shield(line, card_name) is not None
        or self_damage_shield(line, card_name) is not None
        or prevent_all_to_controller(line) is not None
        or prevent_all_to_matching(line) is not None
        or prevent_all_from_spell_class(line) is not None
        or prevent_small_event_threshold(line, card_name) is not None
        or prevent_between_shared_colors(line) is not None
    )
