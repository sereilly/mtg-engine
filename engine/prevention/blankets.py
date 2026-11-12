"""A permanent's static prevention over **others** — its controller, a set of
permanents it describes, the whole table — and the one-shot over a chosen
source (CR 604, CR 615).

``static.py``'s shape, a static ability with no charges and no lifetime read off
its source's text at damage time, with the recipient somewhere else: the line is
found by scanning the battlefields the sentence reaches rather than on the
damaged permanent. "If a source would deal damage to you, prevent that damage
and put a counter on this" (Nine Lives) and "… prevent N of that damage"
(Urza's Armor, the Spheres, Daunting Defender's "to a Cleric creature you
control"), the blankets over the controller (Glacial Chasm, Energy Field), a
spell class (Energy Storm), a noun phrase (Bubble Matrix, Inner Sanctum,
Statecraft) and a shared colour (Well-Laid Plans).

The one-shot "the next time it would deal damage this turn, prevent that
damage" (Desperate Gambit) is here too: a charge rather than a static, but like
the spell-class blanket beside it the sentence names no recipient, only a
source — its record lives on the source (``engine/next_damage.py``).

Cut out of ``static.py`` at kg4, by recipient: that module kept the statics read
off the damaged permanent itself.
"""

from __future__ import annotations

import re

from ..damage_redirects import event_dealing_moment
from ..damage_source_colors import damage_source_colors
from ..effect_ordering import source_names
from ..models import Permanent, PlayerState
from ..named_counters import add_counters
from ..next_damage import (DAMAGE_PREVENTED_NEXT, armed_for_event,
                           names_for_event, spend_for_event)
from .registry import (
    CHOSEN_SOURCE_ONE_SHOT, CONTROLLER_BLANKET, MATCHING_BLANKET,
    SHARED_COLOR_BLANKET, SPELL_CLASS_BLANKET, STATIC_POINTS,
    STATIC_WHOLE_EVENT, PreventionOutcome, _condition_holds, _once,
    prevention_effect, source_has_type,
)
from .shields import _source_label, recipient_label
from ..late_modules import LateModules
from ..object_colors import share_a_color

_late = LateModules(__package__.rpartition(".")[0])


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
#:
#: **And so is the recipient** (Daunting Defender: "If a source would deal
#: damage to **a Cleric creature you control**, prevent 1 of that damage.").
#: "You" is the printing permanent's controller; anything else is a printed
#: noun phrase, read by the grammar's noun parser (``subject_filter_payload``)
#: and answered at each event by ``subject_matches`` — the reader every other
#: shield over a described set of permanents asks (the matching blanket below),
#: so "Cleric creature you control" is one set wherever it is printed and is
#: read through the layers (a creature that *became* a Cleric is one). A phrase
#: the parser cannot read in full refuses the line rather than shielding a set
#: larger than the card names.
#:
#: **And the source's card type** (Sphere of Purity: "If **an artifact** would
#: deal damage to you, prevent 1 of that damage."). The source named by what it
#: is rather than called "a source" — CR 609.7c's static shield over "sources
#: … with certain properties", which "applies to sources that are permanents
#: with that property and to any sources that aren't on the battlefield that
#: have that property": a sacrificed Spellbomb's damage is an artifact's. One
#: closed word list rather than any noun, for ``blankets._SPELL_CLASSES``'
#: reason: ``source_has_type`` substring-matches a type line, and a word it
#: cannot answer would shield against nothing while the card reported
#: supported. A type and a colour together is a card nobody prints, and the
#: alternation cannot read one.
#:
#: **And two more narrowings, each read where it is asked** (Thunderstaff: "As
#: long as this artifact is untapped, if a creature would deal **combat**
#: damage to you, prevent 1 of that damage."). The untapped clause is part of
#: the printed line, as Veteran Bodyguard's is (``replacements.redirects``), so
#: it is matched here and asked of the printing permanent at each event — a
#: tapped Thunderstaff shields nothing, and untapping it again is the shield
#: again (CR 611.3a: a static ability's effect applies while its condition
#: holds). "Combat" is the event's own flag (CR 510.2). The per-event shave is
#: the ruling's count (2004-12-01): "it prevents 1 damage from each creature,
#: each time it would deal combat damage to you" — three double strikers are
#: six events, six points.
_PREVENT_N_OF_DAMAGE_RE = re.compile(
    r"^(?P<untapped>as long as this (?:artifact|creature|enchantment|land|permanent)"
    r" is untapped, )?"
    r"if (?:a (?:(?P<color>white|blue|black|red|green) )?source"
    r"|an? (?P<card_type>artifact|creature|enchantment|land)) would deal "
    r"(?P<combat>combat )?"
    r"damage to (?P<to>.+?), prevent (?P<points>\d+) of that damage$"
)


def static_points_shield(line: str) -> dict | None:
    """What *line* shaves off each event — ``{"points": n, "color": symbol or
    None, "card_type": word or None, "protects": filter or None}`` — or None
    if it is not that line.

    One matcher, asked by the interceptor below and by the claim reader, so
    what is prevented and what is claimed cannot drift. ``color`` is the mana
    symbol of the printed colour word and None for the unnarrowed sentence;
    ``card_type`` is the source's printed card type ("an artifact", Sphere of
    Purity) and None when the sentence says "a source". ``protects`` is None
    for "to you" (the controller, a player) and otherwise the filter payload
    of the permanents the line shields.
    """
    match = _PREVENT_N_OF_DAMAGE_RE.match(
        " ".join(line.strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    protects = None
    if match.group("to") != "you":
        from ..grammar import subject_filter_payload

        protects = subject_filter_payload(match.group("to"))
        if not protects:
            return None
    word = match.group("color")
    card_type = match.group("card_type")
    # ``untapped`` and ``combat`` (Thunderstaff) — see the pattern's comment.
    gates = {"untapped": match.group("untapped") is not None,
             "combat": match.group("combat") is not None}
    if word is None:
        return {"points": int(match.group("points")), "color": None,
                "card_type": card_type, "protects": protects, **gates}
    from ..oracle_types import _COLOR_WORD_TO_SYMBOL

    return {"points": int(match.group("points")),
            "color": _COLOR_WORD_TO_SYMBOL[word], "card_type": card_type,
            "protects": protects, **gates}


def prevent_n_of_damage(line: str) -> int | None:
    """How many points *line* shaves off each event it answers to, or None if
    it is not that line. The claim readers' question; the interceptor asks
    :func:`static_points_shield`, which also carries the source narrowing."""
    described = static_points_shield(line)
    return described["points"] if described else None


def _static_point_lines(game, event: dict):
    """``(permanent, points)`` for every line on the recipient's board that
    shaves points off this event. Pure — nothing is spent, because nothing
    here is a charge.

    "To **you**" is the Armor's controller (CR 109.5), which is why the scan is
    over the recipient's own battlefield: an opponent's Armor does nothing for
    the player being burned.

    A **permanent** recipient is asked of every battlefield's lines that name a
    set of permanents ("a Cleric creature you control", Daunting Defender),
    each with its own printing permanent as the observer and source, because
    the noun phrase — not who controls the Defender — says whose creatures it
    shields. A "to you" line never covers a permanent, and a permanent's line
    never covers a player.
    """
    recipient = event["recipient"]
    if event["amount"] <= 0 or recipient is None:
        return
    if isinstance(recipient, PlayerState):
        seat = game.players.index(recipient) if recipient in game.players else None
        if seat is None:
            return
        printers = [(seat, permanent) for permanent in game.controlled_by(seat)]
    else:
        printers = list(game.permanents_with_controller())
    from ..subject_filters import subject_matches

    source_colors: tuple[str, ...] | None = None
    for seat, permanent in printers:
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            described = static_points_shield(line)
            if described is None:
                continue
            if described["untapped"] and permanent.tapped:
                # "As long as this artifact is untapped, …" (Thunderstaff):
                # asked of the printing permanent now, at this event.
                continue
            if described["combat"] and not event.get("combat"):
                # "…would deal **combat** damage to you" (CR 510.2).
                continue
            protects = described["protects"]
            if isinstance(recipient, PlayerState):
                if protects is not None:
                    continue
            elif protects is None or not subject_matches(
                game, recipient, dict(protects), observer=seat, source=permanent,
            ):
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
            if described["card_type"] is not None and not source_has_type(
                # "If **an artifact** would deal damage to you" (Sphere of
                # Purity). Asked of the source as it is when the damage would
                # be dealt (CR 609.7c): a permanent through layer 4, so an
                # animated artifact land is an artifact source, and a source no
                # longer on the battlefield — a sacrificed Spellbomb — by what
                # it last was.
                game, event.get("source"), described["card_type"]
            ):
                continue
            yield permanent, described["points"]


def _static_points_prevented(game, event: dict) -> int:
    """How many points every such line on the recipient's board shaves off this
    event (:func:`_static_point_lines`).

    **Summed** across the battlefield, for ``replacements.damage._spell_damage_delta``'s
    reason exactly: CR 616.1 would apply two Armors as two effects in an order
    the affected player picks, subtraction commutes, and one candidate per
    registration is the model ``apply_in_order`` has. Clamped to the event, so
    two Armors against 1 damage prevent 1 and not 2.
    """
    if event["amount"] <= 0 or event["recipient"] is None:
        return 0
    total = sum(points for _permanent, points in _static_point_lines(game, event))
    return min(total, event["amount"])


def _applies_static_points(game, event: dict) -> bool:
    return _static_points_prevented(game, event) > 0


def _static_points_sources(game, event: dict) -> list:
    """The permanents whose lines :func:`_static_points_prevented` sums for
    this event (Urza's Armor, the Spheres, Daunting Defender). Pure."""
    return _once(perm for perm, _points in _static_point_lines(game, event))


@prevention_effect(
    STATIC_POINTS, applies=_applies_static_points, sources=_static_points_sources,
    label="Prevent some of that damage",
)
def _prevent_static_points(game, event: dict) -> PreventionOutcome | None:
    """A static prevention: "If a source would deal damage to you, prevent 1 of
    that damage." (Urza's Armor; the five Spheres print it over one colour.)

    Its registration's ``label`` is the option a player is shown when CR 616.1
    asks which effect applies first, so it names what the effect *is* rather
    than the first card that printed it — with a Sphere of Law on the table the
    prompt offered "Urza's Armor", a card that was not there.

    Every event, from every source, for as long as the permanent printing it is
    on the battlefield — and never used up, which is what makes it a static
    prevention rather than CR 615.7's pool. Nothing is spent and nothing is
    recorded: the next event asks the board again, so the shield ends with the
    permanent (CR 611.2) rather than needing a sweep.
    """
    prevented = _static_points_prevented(game, event)
    by = ", ".join(source_names(_static_points_sources(game, event)))
    game.log.append(
        f"{recipient_label(event['recipient'])} prevented {prevented} of "
        f"{event['amount']} damage ({by or 'a static prevention'})"
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


def _place_counter_unpreventable(game, event: dict) -> None:
    """CR 615.12 for Nine Lives: "If damage that a source would deal to you
    can't be prevented, you still put an incarnation counter on Nine Lives."
    (Nine Lives, 2020-06-23.) The prevention prevents nothing; the counter goes
    on all the same."""
    found = _static_prevention_source(game, event)
    if found is None:
        return
    permanent, counter = found
    total = add_counters(permanent, counter, 1)
    game.log.append(
        f"{event['amount']} damage to {event['recipient'].name} can't be "
        f"prevented; {permanent.card.name} still gets a {counter} counter "
        f"({total} {counter} counter(s))"
    )


def _static_whole_event_sources(game, event: dict) -> list:
    """The permanent :func:`_static_prevention_source` finds (Nine Lives)."""
    found = _static_prevention_source(game, event)
    return [] if found is None else [found[0]]


@prevention_effect(
    STATIC_WHOLE_EVENT, applies=_applies_static_whole_event,
    sources=_static_whole_event_sources,
    unpreventable=_place_counter_unpreventable,
    label="Prevent the damage and put a counter on this permanent",
)
def _prevent_and_place_counter(game, event: dict) -> PreventionOutcome | None:
    """Nine Lives: "If a source would deal damage to you, prevent that damage
    and put an incarnation counter on this enchantment."

    The whole instance is prevented however large it is, and the counter is
    placed once per prevented event rather than once per point — CR 615.5's
    "additional effect", which happens *after* the prevention and refers to the
    event, not to the damage's size. Nine damage and one damage each cost the
    same counter, which is what makes the card a nine-*event* shield.

    Once per **source**, too: "If more than one source deals damage to you at
    once, prevent the damage from each of them and put that many incarnation
    counters on Nine Lives" (2020-06-23) — the sentence opens "If a source
    would deal damage", and the engine's one event per source is that reading.
    The Phantoms (``static.py``) print "If damage would be dealt" and are
    ruled the other way.
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


#: "Prevent all damage that would be dealt to you." (Glacial Chasm.) A static
#: prevention on the permanent's **controller** rather than on the permanent
#: itself, and the unnarrowed member of ``static.py``'s source-type family: no
#: source class, no
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
#: ``_PREVENT_ALL_FROM_SOURCE_TYPE_RE`` carries its own in ``static.py`` — and the
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


def _controller_blankets(game, event: dict):
    """``(permanent, described)`` for each blanket shielding this player
    *against this event*, read off their own battlefield. Pure.

    A player has no text of their own, so the line is found on the permanents
    they control — the same read ``static._source_type_shielded_by`` makes of
    a damaged permanent, one relation out. Through the control seam rather than a
    battlefield list, so a Glacial Chasm somebody else has taken control of
    shields *them*.

    The source narrowing is tested here rather than in the applicability
    predicate below, so a board holding a narrow blanket that does not cover
    this event goes on looking for a wide one instead of answering with the
    first line it found.
    """
    recipient = event["recipient"]
    if not isinstance(recipient, PlayerState):
        return
    seat = game.players.index(recipient) if recipient in game.players else None
    if seat is None:
        return
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
            yield permanent, described


def _controller_blanket_for(game, event: dict) -> dict | None:
    """The first blanket :func:`_controller_blankets` finds, or None."""
    return next((described for _perm, described in _controller_blankets(game, event)), None)


def _applies_controller_blanket(game, event: dict) -> bool:
    described = _controller_blanket_for(game, event)
    if described is None:
        return False
    if event["amount"] <= 0:
        return False
    return bool(event.get("combat")) or not described["combat_only"]


def _controller_blanket_sources(game, event: dict) -> list:
    """The permanents whose blanket covers this event (Glacial Chasm, Energy
    Field), by :func:`_controller_blankets`' reading. Pure."""
    if event["amount"] <= 0:
        return []
    return [
        permanent for permanent, described in _controller_blankets(game, event)
        if event.get("combat") or not described["combat_only"]
    ]


@prevention_effect(
    CONTROLLER_BLANKET, applies=_applies_controller_blanket,
    sources=_controller_blanket_sources,
    label="Prevent all damage that would be dealt to you",
)
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


def _spell_class_blankets(game, event: dict):
    """``(permanent, described)`` for each spell-class blanket covering this
    event. Pure.

    Scanned over every battlefield rather than the recipient's: the sentence
    names no recipient at all, so an opponent's Energy Storm covers this damage
    exactly as your own would.
    """
    if event["amount"] <= 0:
        return
    source = event.get("source")
    if source is None or hasattr(source, "metadata"):
        # A permanent is not a spell however it is dealing the damage
        # (CR 110.1). A spell's source is the card as printed (CR 120.7), which
        # is the shape with no ``metadata``.
        return
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
                yield permanent, described


def _spell_class_blanket(game, event: dict) -> dict | None:
    """The first blanket :func:`_spell_class_blankets` finds, or None."""
    return next((described for _perm, described in _spell_class_blankets(game, event)), None)


def _applies_spell_class_blanket(game, event: dict) -> bool:
    return _spell_class_blanket(game, event) is not None


def _spell_class_blanket_sources(game, event: dict) -> list:
    """Every permanent whose spell-class blanket covers this event (Energy
    Storm). Pure."""
    return _once(perm for perm, _d in _spell_class_blankets(game, event))


@prevention_effect(
    SPELL_CLASS_BLANKET, applies=_applies_spell_class_blanket,
    sources=_spell_class_blanket_sources,
    label="Prevent all damage dealt by the described spells",
)
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
#: keeps this pattern's ``.+`` off the source-narrowed sentences ``static.py``
#: reads
#: ("…dealt to this creature **by artifact sources**"): that tail is not a noun
#: phrase, so the parser leaves it unconsumed and the line falls through to the
#: reader that owns it.
#:
#: ``plural=True`` is the other half of that gate and it is load-bearing: the
#: parser refuses a *singular* self-reference under it, so "…dealt to **this
#: creature**" and "…dealt to **enchanted creature**" — the two subjects the
#: source-narrowed readers in ``static.py`` own — cannot reach this shield. Without it
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
#: and it has its own reader above — admitted here it would read the source
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
    subject_filter_payload = _late.grammar.subject_filter_payload

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


def _matching_blankets(game, event: dict):
    """Each permanent whose blanket covers this event, once per covering line.
    Pure.

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
        return
    subject_matches = _late.subject_filters.subject_matches

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
            if any(
                end is not None and subject_matches(
                    game, end, dict(described["filter"]),
                    observer=seat, source=permanent,
                )
                for end in ends
            ):
                yield permanent


def _matching_blanket_for(game, event: dict) -> str | None:
    """The name of the first permanent :func:`_matching_blankets` finds, or
    None."""
    found = next(_matching_blankets(game, event), None)
    return None if found is None else found.card.name


def _applies_matching_blanket(game, event: dict) -> bool:
    return _matching_blanket_for(game, event) is not None


def _matching_blanket_sources(game, event: dict) -> list:
    """Every permanent whose "…to <phrase>" blanket covers this event (Bubble
    Matrix, Inner Sanctum, Statecraft). Pure."""
    return _once(_matching_blankets(game, event))


@prevention_effect(
    MATCHING_BLANKET, applies=_applies_matching_blanket,
    sources=_matching_blanket_sources,
    label="Prevent all damage to the described permanents",
)
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
        moment=event_dealing_moment(game, event),
    ) > 0


def _chosen_source_one_shot_sources(game, event: dict) -> list:
    """The cards that armed the riders answering this event (Desperate
    Gambit's losing flip, Impulsive Maneuvers'), by the name record beside the
    count (``next_damage.names_key``) — not the source the rider sits on,
    which is what it watches. Pure."""
    return names_for_event(
        event.get("source"), DAMAGE_PREVENTED_NEXT,
        combat=bool(event.get("combat")),
        moment=event_dealing_moment(game, event),
    )


@prevention_effect(
    CHOSEN_SOURCE_ONE_SHOT, applies=_applies_chosen_source_one_shot,
    sources=_chosen_source_one_shot_sources,
    label="Prevent the next damage the chosen source would deal",
)
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
        source, DAMAGE_PREVENTED_NEXT, combat=bool(event.get("combat")),
        moment=event_dealing_moment(game, event),
    )
    card = getattr(source, "card", source)
    game.log.append(
        f"{amount} damage from {getattr(card, 'name', 'a chosen source')} is "
        "prevented (the next time it would deal damage this turn)"
    )
    return PreventionOutcome(prevented=amount)


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


def _shared_color_blankets(game, event: dict):
    """Each permanent whose shared-colour blanket covers this event, once per
    covering line. Pure.

    Three things have to be true of the event before any board is scanned, and
    each is a printed word:

    - "**to a creature**" — the recipient is a permanent that is a creature
      now (CR 613 layer 4: an animated land is one, a player never is);
    - "**by another creature**" — the source is a *permanent* that is a
      creature, and a different object from the recipient. A spell's source is
      the card as printed (CR 120.7), which is not a creature however red it
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
        return

    recipient = event["recipient"]
    source = event.get("source")
    if not isinstance(recipient, Permanent) or not isinstance(source, Permanent):
        return
    if source is recipient or not recipient.is_creature or not source.is_creature:
        return
    if not share_a_color(
        game._effective_colors(recipient), game._effective_colors(source)
    ):
        return
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            described = prevent_between_shared_colors(line)
            if described is None:
                continue
            if described["combat_only"] and not event.get("combat"):
                continue
            yield permanent


def _applies_shared_color_blanket(game, event: dict) -> bool:
    return _shared_color_blanket_for(game, event) is not None


def _shared_color_blanket_for(game, event: dict) -> str | None:
    """The name of the first permanent :func:`_shared_color_blankets` finds,
    or None."""
    found = next(_shared_color_blankets(game, event), None)
    return None if found is None else found.card.name


def _shared_color_blanket_sources(game, event: dict) -> list:
    """Every permanent whose shared-colour blanket covers this event
    (Well-Laid Plans). Pure."""
    return _once(_shared_color_blankets(game, event))


@prevention_effect(
    SHARED_COLOR_BLANKET, applies=_applies_shared_color_blanket,
    sources=_shared_color_blanket_sources,
    label="Prevent damage between creatures that share a color",
)
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
