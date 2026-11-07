"""A permanent's own static prevention over **itself**, and over what it is
attached to (CR 604, CR 615).

The other shape from ``shields.py``: a static ability that applies while its
source is on the battlefield, with no charges and no lifetime, so there is no
``Shield`` to hold and nothing for the sweeps to clear. Each is read off the
**damaged permanent's own text** — or the text of an Aura or Equipment on it —
at the moment damage would be dealt: "prevent all damage … to this creature by
<source type>" (Argothian Treefolk) and its "enchanted / equipped" form
(Artifact Ward), "if a source would deal 3 or less damage to this creature"
(Callous Giant), the Phantoms' "prevent that damage. Remove a +1/+1 counter",
and the per-point counter shield (Rock Hydra).

The statics a permanent prints over **others** — its controller, a set of
permanents it describes, the whole table — are ``blankets.py``'s; which printed
lines the package implements is ``lines.py``'s question.

Split out of ``prevention.py`` at the 2,000-line cap's split round, where it
was that module's last section, and cut again at kg4 by recipient: the half
read off the damaged permanent stayed here, the half read off a battlefield
moved to ``blankets.py``.
"""

from __future__ import annotations

import re

from ..damage_source_colors import damage_source_colors
from ..models import PlayerState
from ..named_counters import counters_on, remove_counters
from ..pt import remove_plus1_counters
from .registry import (
    PER_POINT_COUNTER_SHIELD, SELF_WHOLE_EVENT_COUNTER, SMALL_EVENT_BLANKET,
    SOURCE_TYPE_BLANKET, PreventionOutcome, _condition_holds, _once,
    prevention_effect, source_has_type,
)


# ---------------------------------------------------------------------------
# A permanent's own static prevention over itself
# ---------------------------------------------------------------------------
#
# Everything in ``shields.py`` is a shield a recipient was *given*: something
# resolved, armed it, and it is spent. This is the other shape — a static
# ability that applies while its source is on the battlefield, with no charges
# and no lifetime, so there is no Shield to hold and nothing for the sweeps to
# clear. It is read off the source's text at damage time for the same reason
# engine/replacements/' interceptors are: the card says it, so the card is
# where the answer lives.

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

    A spell's damage source is the card itself (CR 120.7) -- the card as
    printed, which records neither who cast it nor what it was aimed at. So the
    targets come from ``Game.resolving_targets``, the seam
    ``_execute_oracle_instruction`` pushes around every instruction, exactly as
    the seat does. Reading the stack instead does not work and is not merely
    slower: the object is popped before its instructions run, so by the time the
    damage would be dealt there is nothing there to ask.

    "Spells", not abilities: an activated or triggered ability is not a spell
    (CR 113.9), and its damage source is the permanent it is on -- which is what
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


def _source_type_shields(game, event: dict):
    """``(holder, resolved)`` for each line shielding the damaged permanent
    against a source class, in the order they are read. Pure.

    It reads text and answers, spending nothing. Two places print the line,
    and both are read here: the recipient's own text ("dealt to **this**
    creature", so a second copy on the battlefield shields itself and not its
    twin) and the text of whatever is attached to it ("dealt to **enchanted**
    creature", which is a shield the recipient's own text says nothing about).
    """
    from ..aura_attachment import auras_attached_to

    recipient = event["recipient"]
    if isinstance(recipient, PlayerState) or recipient is None:
        return
    places = [(recipient, prevent_all_from_source_type)] + [
        (attached, attached_prevent_all_from_source_type)
        for attached in auras_attached_to(recipient)
    ]
    for holder, reader in places:
        card = getattr(holder, "effective_card", None) or holder.card
        for line in (card.oracle_text or "").splitlines():
            wanted = reader(line)
            if wanted is None or not _condition_holds(game, wanted, holder):
                continue
            # An Aura's colour is the **Aura's**, recorded as it entered — not
            # the enchanted creature's, which has none of its own.
            resolved = _resolved_chosen_color(wanted, holder)
            if resolved is not None:
                yield holder, resolved


def _source_type_shielded_by(game, event: dict) -> dict | None:
    """The source class the damaged permanent is shielded against: the first
    line :func:`_source_type_shields` reads, or None."""
    return next((resolved for _holder, resolved in _source_type_shields(game, event)), None)


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


def _source_type_blanket_sources(game, event: dict) -> list:
    """The permanent whose line shields the recipient against this source —
    the recipient itself ("…to **this** creature by artifact sources") or an
    Aura on it ("…to **enchanted** creature"). Pure."""
    return _once(
        holder for holder, resolved in _source_type_shields(game, event)
        if (event.get("combat") or not resolved.get("combat_only"))
        and _source_shield_matches(
            game, event.get("source"), event["recipient"], resolved,
            event.get("source_seat"),
        )
    )


@prevention_effect(
    SOURCE_TYPE_BLANKET, applies=_applies_source_type_blanket,
    sources=_source_type_blanket_sources,
    label="Prevent all damage to this permanent from the described sources",
)
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


#: "If damage would be dealt to this creature, prevent that damage. Remove a
#: +1/+1 counter from this creature." (Phantom Centaur, Phantom Flock, Phantom
#: Nantuko, Phantom Nishoba, Phantom Nomad, Phantom Tiger.) Nine Lives' shape
#: with the permanent as its own recipient and the counter going *off* rather
#: than on — CR 615.5's additional effect, after the prevention, once per event.
#:
#: The later templating ("If this creature would be dealt damage, prevent that
#: damage and remove a +1/+1 counter from it.") is the same effect in one
#: sentence and is read here too; the counter's word is payload, as Nine Lives'
#: and Rock Hydra's are.
_PREVENT_THEN_REMOVE_COUNTER_RE = re.compile(
    r"^(?:if damage would be dealt to this "
    r"(?:artifact|creature|enchantment|land|permanent)"
    r"|if this (?:artifact|creature|enchantment|land|permanent) would be dealt "
    r"damage), prevent that damage(?:\. | and )"
    r"remove an? (?P<counter>\S+) counter from "
    r"(?:this (?:artifact|creature|enchantment|land|permanent)|it)$"
)


def prevent_then_remove_counter_kind(
    line: str, card_name: str | None = None
) -> str | None:
    """The counter *line* removes from its own permanent each time it prevents,
    or None if it is not that line. One matcher for the interceptor and both
    claim readers, so what is implemented and what is claimed cannot drift.

    *card_name* collapses CR 201.5's self-reference the way
    :func:`prevent_small_event_threshold` does, for a printing that names the
    creature ("If Unbreathing Horde would be dealt damage, …").
    """
    normalized = " ".join((line or "").strip().lower().rstrip(".").split())
    if card_name:
        from ..self_reference import _collapse_self_references

        normalized = _collapse_self_references(
            normalized, card_name, "this creature"
        )
    match = _PREVENT_THEN_REMOVE_COUNTER_RE.match(normalized)
    return match.group("counter") if match else None


def _self_counter_shield(game, event: dict) -> str | None:
    """The counter the damaged permanent's own text removes when it prevents
    this event, or None. Pure.

    The recipient's own text only — "dealt to **this** creature" — read off the
    effective card, so a creature that lost its abilities (CR 613 layer 6) has
    no shield and a copy of a Phantom has one.
    """
    recipient = event["recipient"]
    if isinstance(recipient, PlayerState) or recipient is None:
        return None
    if event["amount"] <= 0:
        return None
    card = getattr(recipient, "effective_card", None) or recipient.card
    for line in (card.oracle_text or "").splitlines():
        counter = prevent_then_remove_counter_kind(line, card.name)
        if counter is not None:
            return counter
    return None


def _applies_self_counter_shield(game, event: dict) -> bool:
    return _self_counter_shield(game, event) is not None


#: "If this creature would be dealt damage from multiple sources at the same
#: time (say, because it's blocked by multiple creatures), all of the damage is
#: prevented and only one +1/+1 counter is removed." (Phantom Centaur et al.,
#: 2022-12-08.) The engine deals one event per source, and CR 510.2's combat
#: damage is the simultaneous dealing that splits into several of them — so the
#: permanent remembers, for the rest of the combat damage step, that its
#: counter has been paid for this damage. The step's tail ends the record
#: (:func:`end_simultaneous_damage`), as it ends the defending player's
#: announcement beside it; a first-strike step and the regular one are two
#: dealings and cost two counters.
#:
#: Combat damage only. Every non-combat event in this pool is one source's
#: damage at one moment, and is its own event.
SIMULTANEOUS_RIDER_SPENT = "prevention_rider_spent_this_combat_damage_step"


def end_simultaneous_damage(game) -> None:
    """The combat damage step's tail: its simultaneous dealing is over, so every
    rider it paid for is paid for (CR 510.2)."""
    for permanent in game.all_permanents():
        permanent.metadata.pop(SIMULTANEOUS_RIDER_SPENT, None)


def _remove_rider_counter(game, event: dict, counter: str) -> int | None:
    """CR 615.5's additional effect for the Phantoms: one *counter* counter
    off the damaged permanent, once per damage event — or None when this
    simultaneous dealing has already paid for it.

    Not conditional on a counter being there: "If this creature has no +1/+1
    counters on it …, damage that would be dealt to it is still prevented"
    (2022-12-08). The prevention is the effect; the counter is what follows it.
    """
    permanent = event["recipient"]
    if event.get("combat"):
        if permanent.metadata.get(SIMULTANEOUS_RIDER_SPENT):
            return None
        permanent.metadata[SIMULTANEOUS_RIDER_SPENT] = True
    if counter == "+1/+1":
        return remove_plus1_counters(permanent, 1)
    removed = min(1, counters_on(permanent, counter))
    if removed:
        remove_counters(permanent, counter, removed)
    return removed


def _counter_word(counter: str, removed: int | None) -> str:
    if removed is None:
        return "(its counter already paid for this damage)"
    if removed <= 0:
        return f"(no {counter} counter to remove)"
    return f"(removed a {counter} counter)"


def _remove_counter_unpreventable(game, event: dict) -> None:
    """CR 615.12 for the Phantoms: "If damage that would be dealt to this
    creature can't be prevented, the damage is dealt and a +1/+1 counter is
    removed from this creature." (2022-12-08.)"""
    counter = _self_counter_shield(game, event)
    if counter is None:
        return
    removed = _remove_rider_counter(game, event, counter)
    game.log.append(
        f"{event['amount']} damage to {event['recipient'].card.name} can't be "
        f"prevented {_counter_word(counter, removed)}"
    )


def _the_recipient(game, event: dict) -> list:
    """The damaged permanent, whose own text prints the shield (the Phantoms)."""
    recipient = event["recipient"]
    return [] if isinstance(recipient, PlayerState) or recipient is None else [recipient]


@prevention_effect(
    SELF_WHOLE_EVENT_COUNTER, applies=_applies_self_counter_shield,
    sources=_the_recipient,
    unpreventable=_remove_counter_unpreventable,
    label="Prevent the damage and remove a counter from the creature",
)
def _prevent_and_remove_own_counter(game, event: dict) -> PreventionOutcome | None:
    """Prevent the damage and remove a counter from the creature: "If damage
    would be dealt to this creature, prevent that damage. Remove a +1/+1
    counter from this creature." (The Phantoms.)

    The registration's ``label`` is the option CR 616.1e's prompt shows, so it
    says what the effect does rather than which card printed it (Urza's Armor's
    reason, in ``blankets.py``).

    The whole event, however large, from every source; then one counter off,
    once per event and once per simultaneous combat dealing. Nothing is
    recorded beyond that — the next event reads the text again (CR 611.2).
    """
    counter = _self_counter_shield(game, event)
    if counter is None:  # pragma: no cover - the predicate just said otherwise
        return None
    permanent = event["recipient"]
    amount = event["amount"]
    removed = _remove_rider_counter(game, event, counter)
    game.log.append(
        f"{permanent.card.name} prevented {amount} damage "
        f"{_counter_word(counter, removed)}"
    )
    return PreventionOutcome(prevented=amount)


#: "For each 1 damage that would be dealt to this creature, if it has a +1/+1
#: counter on it, remove a +1/+1 counter from it and prevent that 1 damage."
#: (Rock Hydra.) The counter's word is payload, exactly as Nine Lives' is
#: (``blankets.py``); the backreference holds the removal to the same counter the
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


def _remove_counters_per_damage(game, event: dict, counter: str) -> int:
    """Rock Hydra's counters for this event: one per point, as far as they go."""
    permanent = event["recipient"]
    if counter == "+1/+1":
        return remove_plus1_counters(permanent, event["amount"])
    removed = min(event["amount"], counters_on(permanent, counter))
    if removed > 0:
        remove_counters(permanent, counter, removed)
    return removed


def _remove_counters_per_damage_unpreventable(game, event: dict) -> None:
    """CR 615.12 for Rock Hydra: "If damage that would be dealt to Rock Hydra
    can't be prevented, you still remove a +1/+1 counter from it for each 1
    damage dealt." (Rock Hydra, 2008-08-01.)"""
    counter = _per_damage_counter_shield(game, event)
    if counter is None:
        return
    removed = _remove_counters_per_damage(game, event, counter)
    if removed > 0:
        game.log.append(
            f"{event['amount']} damage to {event['recipient'].card.name} can't "
            f"be prevented; it still removed {removed} {counter} counter(s)"
        )


@prevention_effect(
    PER_POINT_COUNTER_SHIELD, applies=_applies_per_damage_counter,
    sources=_the_recipient,
    unpreventable=_remove_counters_per_damage_unpreventable,
    label="Prevent each 1 damage by removing a counter from the creature",
)
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
    removed = _remove_counters_per_damage(game, event, counter)
    if removed <= 0:
        return None
    game.log.append(
        f"{permanent.card.name} removed {removed} {counter} counter(s) to "
        f"prevent {removed} damage"
    )
    return PreventionOutcome(prevented=removed)


#: "If a source would deal **3** or less damage to this creature, prevent that
#: damage." (Callous Giant.) A static shield narrowed by the **size of the
#: event** — every other reader in this package narrows by who is dealing the
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


@prevention_effect(
    SMALL_EVENT_BLANKET, applies=_applies_small_event_blanket,
    sources=_the_recipient,
    label="Prevent damage of the printed amount or less",
)
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
