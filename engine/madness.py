"""Madness (CR 702.35), the keyword the rules define as two abilities.

CR 702.35a: *"Madness is a keyword that represents two abilities. The first is
a static ability that functions while the card with madness is in a player's
hand. The second is a triggered ability that functions when the first ability
is applied. 'Madness [cost]' means 'If a player would discard this card, that
player discards it, but exiles it instead of putting it into their graveyard'
and 'When this card is exiled this way, its owner may cast it by paying [cost]
rather than paying its mana cost. If that player doesn't, they put this card
into their graveyard.'"*

**Not flashback's shape, and the difference is the trigger.** Flashback is two
*static* abilities, so its keyword line is rewritten into the one sentence a
registry claims and nothing is left to run. Madness's second ability is a
triggered one, and a triggered ability is an object on the stack (CR 603.3)
that someone may respond to — so it has to be a compiled
:class:`~engine.oracle_types.ParsedTriggeredAbility` with an instruction behind
it. That is **cumulative upkeep's and flanking's shape** (CR 702.24a,
CR 702.25a: a keyword line *defined* as a triggered ability), and the keyword
line goes through the same seam they do, ``keyword_lines.keyword_line_triggers``, read
by both compiler front ends and by the Aura gate through
``_is_supported_keyword_line``. The grammar is not asked: no card outside a
reminder prints "When this card is exiled this way", and its one fire site is
the static ability beside it.

**The static half is a CR 614 replacement**, registered in
``engine/replacements/zone_changes.py`` beside the two that already replace where a
discarded card goes (Dodecapod's battlefield, Library of Leng's library top),
and asked by the chosen-discard seam ``handlers/discards._resolve_one_discard``
for the reason that seam already asks Dodecapod's. :func:`exile_madness_card`
is the whole effect, so both seams run one body. **The discard still happens**
(it is a discard for every "whenever a player discards" watcher); only the
destination changes, and the trigger is announced from that destination.

**The trigger's effect is a cast during resolution** (CR 608.2g: the steps of
601.2a–i, no priority after it, the spell becomes the topmost object, and the
resolving ability continues). :data:`MADNESS_CAST_KIND`'s handler grants a
:class:`~engine.cast_permissions.CastPermission` out of the owner's exile that
*requires* the madness cost (CR 118.9b, CR 702.35b — the flashback shape of a
permission) and arms the ``madness_cast`` prompt. The prompt is answered by a
cast under that permission or by declining, which puts the card into its
owner's graveyard. A non-interactive seat answers it the moment it is armed,
with the AI's own cast chooser (``ai_policy.choose_madness_cast``) — rehearsed
like any other cast — so a seat nobody asks casts a good madness spell and
declines a bad one rather than always doing either.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import (OracleInstruction, ParsedTriggeredAbility,
                           TriggerCondition)

if TYPE_CHECKING:
    from .alternative_costs import AlternativeCost

#: The keyword, as :attr:`AlternativeCost.keyword` carries it — what
#: "Madness costs you pay cost {2} less" would be read against
#: (``cost_modifiers.keyword_cost_modifiers``), and what a cast's log names.
MADNESS = "madness"

#: What the permission the trigger grants calls its source.
MADNESS_SOURCE = "madness"

#: The trigger condition CR 702.35a's second ability triggers on: "When this
#: card is exiled this way". Fired by :func:`exile_madness_card` and by
#: nothing else, because "this way" is the static ability beside it.
MADNESS_TRIGGER = "exiled_with_madness"

#: The instruction the trigger resolves: "its owner may cast it by paying
#: [cost] rather than paying its mana cost. If that player doesn't, they put
#: this card into their graveyard."
MADNESS_CAST_KIND = "offer_madness_cast"

#: The bucket the support report puts the trigger in. Carried here rather than
#: in ``effect_labels.TRIGGERED_LABELS`` for ``rampage.RAMPAGE_LABEL``'s
#: reason: that table describes what the grammar reads, and this ability is
#: derived from a keyword line the grammar never sees.
MADNESS_LABEL = "triggered_cast"

#: The permission's duration: it lasts exactly as long as the offer does, and
#: the offer's answer retires it (:func:`retire_offer`). No turn step sweeps
#: it, because nothing in a turn ends it — the resolution that granted it does.
MADNESS_OFFER = "madness_offer"

#: The prompt kind the trigger arms.
MADNESS_PROMPT = "madness_cast"

#: "madness {1}{r}" as a keyword-line part reads after
#: ``normalize_creature_line`` (lowercased, reminder text gone).
_MADNESS_PART = re.compile(r"^madness\s+(?P<cost>(?:\{[^{}]+\})+)$")

#: Any line that *is* a madness keyword line, readable or not: the word, then
#: a mana symbol or the dash a non-mana cost is printed behind. "Madness costs
#: you pay cost {2} less" is a static *about* madness costs and does not match,
#: for the reason ``flashback._FLASHBACK_SHAPE`` gives about Catalyst Stone.
_MADNESS_SHAPE = re.compile(r"^madness\s*(?:[—–-]|\{)", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")


def madness_cost_text(part: str) -> str | None:
    """The madness cost one keyword-line *part* prints, as mana symbols in
    upper case ("{1}{R}"), or None when the part is not a madness this engine
    can charge.

    The gate's admission test too (``keyword_lines._qualified_keyword_part``), for
    ``cumulative_upkeep.cumulative_upkeep_cost``'s reason: the reader that
    charges the cost is the one that admits the line. **A hybrid, Phyrexian
    or {X} symbol refuses** (``mana_cost_from_symbols``): an X here would be
    a number nothing announces, and charging it as 0 casts the spell for
    less than it prints. A non-mana cost behind a dash refuses for the same
    reason — no Torment card prints one, and nothing here could charge it.
    """
    from .mana_payment import mana_cost_from_symbols

    match = _MADNESS_PART.match(" ".join((part or "").lower().split()))
    if match is None:
        return None
    cost = match.group("cost").upper()
    if mana_cost_from_symbols(cost) is None:
        return None
    return cost


def is_madness_line(line: str) -> bool:
    """Whether *line* is a printed madness keyword line, readable or not."""
    stripped = _stripped(line)
    return bool(stripped) and _MADNESS_SHAPE.match(stripped) is not None


def unread_madness_line(oracle_text: str) -> str | None:
    """A printed madness-shaped line :func:`madness_cost_text` cannot read,
    or None — the support gate's question.

    Without it an instant whose *other* line compiles reports supported with
    the keyword dropped, which is what all six of Torment's madness instants
    did on the day of the ingest: Odyssey's flashback trap exactly.
    """
    for line in (oracle_text or "").split("\n"):
        if is_madness_line(line) and madness_cost_text(_stripped(line)) is None:
            return _stripped(line)
    return None


def madness_triggers(keyword_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered ability CR 702.35a says the madness on this line *is*.

    One per instance. The cost rides the instruction's payload, which is what
    the handler charges; the static half is read off the printed line itself
    (:func:`printed_madness_cost`), since it is the card in a hand that a
    replacement asks about, and a card in a hand has no compiled program on
    the battlefield to ask.
    """
    found = []
    for part in (keyword_line or "").split(","):
        cost = madness_cost_text(part.strip())
        if cost is None:
            continue
        found.append(ParsedTriggeredAbility(
            source_line=f"madness {cost.lower()}",
            condition=TriggerCondition(
                kind=MADNESS_TRIGGER,
                trigger="when",
                raw_text="when this card is exiled this way",
            ),
            instruction=OracleInstruction(
                MADNESS_CAST_KIND, f"madness {cost.lower()}", {"cost": cost},
            ),
            supported=True,
            effect_kind=MADNESS_LABEL,
        ))
    return tuple(found)


def madness_alternative_cost(cost: str) -> "AlternativeCost":
    """The CR 118.9 alternative cost "paying [cost] rather than paying its
    mana cost" names: mana only, and keyed :data:`MADNESS`."""
    from .alternative_costs import AlternativeCost

    return AlternativeCost(
        f"cast it by paying {cost.lower()} rather than paying its mana cost",
        mana=cost.upper(), keyword=MADNESS,
    )


@lru_cache(maxsize=None)
def _printed_cost(oracle_text: str) -> str | None:
    if "adness" not in (oracle_text or ""):
        return None
    for line in (oracle_text or "").split("\n"):
        if not is_madness_line(line):
            continue
        cost = madness_cost_text(_stripped(line))
        if cost is not None:
            return cost
    return None


def printed_madness_cost(card) -> str | None:
    """The madness cost *card* prints ("{R}"), or None.

    The printed text, because the card being asked about is in a hand: CR
    702.35a's static ability "functions while the card with madness is in a
    player's hand", where no layer applies (CR 613 is about objects on the
    battlefield and the stack) and the card is what it prints. Cached on the
    text, because every discard asks.
    """
    return _printed_cost(getattr(card, "oracle_text", "") or "")


def has_madness(card) -> bool:
    """Whether *card* prints madness, readable or not."""
    return any(
        is_madness_line(line)
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    )


def _seat_of(game, player) -> int | None:
    return next(
        (i for i, seated in enumerate(game.players) if seated is player), None
    )


def exile_madness_card(game, player, card) -> bool:
    """CR 702.35a's static ability and the trigger it sets off: put the
    discarded *card* into *player*'s exile instead of their graveyard, then
    put its "When this card is exiled this way" ability on the stack.
    Returns whether it applied; False leaves the caller's default move.

    One body for both discard seams (the ``discard`` event and the chosen
    discard), for ``replacements.discarded_onto_battlefield``'s reason.

    The trigger's controller is the card's **owner** ("its owner may cast
    it"), which is the discarding player: a hand holds only its owner's cards
    (CR 400.3). The card itself is the source — the ability functions from
    exile, the zone the static put it in — and rides the trigger context so
    the handler asks about *this* card, not a look-alike.
    """
    from .oracle import compile_card_oracle

    if printed_madness_cost(card) is None:
        return False
    seat = _seat_of(game, player)
    if seat is None:
        return False
    player.exile.append(card)
    game.log.append(
        f"{player.name} discarded {card.name} into exile (madness)"
    )
    for trigger in compile_card_oracle(card).triggered_abilities:
        if trigger.condition.kind != MADNESS_TRIGGER:
            continue
        if not trigger.supported or trigger.instruction is None:
            continue
        game._enqueue_triggered_ability(
            controller_index=seat,
            card=card,
            instruction=trigger.instruction,
            effect_kind=trigger.effect_kind,
            ability_text="When this card is exiled this way, its owner may "
            f"cast it by paying {trigger.instruction.payload['cost']} rather "
            "than paying its mana cost.",
            trigger_context={"madness_card": card},
        )
    return True


def offer_permission(game, seat: int, card, cost: str):
    """The permission the trigger's resolution opens: *card* out of *seat*'s
    exile, for its madness cost and nothing else (CR 118.9b), for as long as
    the offer stands. Granted as a stored :class:`CastPermission` rather than
    derived, because the AI weighs the cast on a scratch copy that owes no
    prompt (``ai_valuation.rehearse``'s ``detach="abstract"``) and the
    permission has to travel with the copy."""
    from .cast_permissions import grant_permission

    return grant_permission(
        game, player_index=seat, zone="exile", mode="cast", cards=[card],
        duration=MADNESS_OFFER, source_name=MADNESS_SOURCE,
        cost=madness_alternative_cost(cost),
    )


def retire_offer(game, permission) -> None:
    """End the offer's permission, used or not. A cast under it has already
    spent it (``cast_permissions.consume``); a decline has not."""
    game.cast_permissions[:] = [
        held for held in game.cast_permissions if held is not permission
    ]


def put_unused_card_into_graveyard(game, seat: int, card) -> bool:
    """"If that player doesn't, they put this card into their graveyard."

    Only while it is still in its owner's exile, by identity: a card that
    left is a new object (CR 400.7) the ability no longer knows. CR 702.35c
    then lets effects referencing the discarded card find it there
    (CR 400.7k) — which is why the discard was announced with this card."""
    player = game.players[seat]
    if not game.take_card_from_exile(seat, card):
        return False
    arrived = game.put_card_into_graveyard(player, card, from_zone="exile")
    game.log.append(
        f"{player.name} did not cast {card.name} for its madness cost"
        + (" and put it into their graveyard" if arrived else "")
    )
    return True


def offered_card_in_exile(game, seat: int, card) -> bool:
    """Whether *card* is still in *seat*'s exile, by identity."""
    return any(held is card for held in game.players[seat].exile)


def _decline(game, choice) -> None:
    """The offer is not taken: retire its permission, put the card into its
    owner's graveyard, and take the prompt down."""
    retire_offer(game, choice.data.get("_permission"))
    card = choice.data.get("_card")
    if card is not None:
        put_unused_card_into_graveyard(game, choice.player_index, card)
    game.discard_pending_choice(choice)


def resolve_madness_offer(game, choice, response: dict) -> bool:
    """Answer the ``madness_cast`` prompt.

    ``accept`` false (or absent) declines. True casts the card, under the
    offer's permission (``from_zone="exile"``, ``alternative_cost=True``: the
    cast path then finds the permission that *requires* the madness cost,
    CR 118.9b). The cast is either *perform* — a callable making the engine
    call itself, which is how the web route forwards a whole announcement
    through its own plumbing — or *announcement*, the keywords
    ``Game.queue_from_hand`` takes. A cast the engine refuses leaves the prompt
    owed, the permission standing and the card in exile, and the refusal is
    appended to *outcome* (a list) when the caller passed one.

    Answered inside ``_answer_pending_choice``, so the ability is still the
    resolving object while the spell is cast (CR 608.2g: the spell becomes the
    topmost object and the ability then finishes).
    """
    card = choice.data.get("_card")
    seat = choice.player_index
    if not response.get("accept"):
        _decline(game, choice)
        return True
    if card is None or not offered_card_in_exile(game, seat, card):
        retire_offer(game, choice.data.get("_permission"))
        game.discard_pending_choice(choice)
        return True
    perform = response.get("perform")
    if perform is None:
        announcement = dict(response.get("announcement") or {})
        announcement["from_zone"] = "exile"
        announcement["alternative_cost"] = True
        name = response.get("card_name") or card.name

        def perform(table):
            return table.queue_from_hand(seat, name, **announcement)

    result = perform(game)
    outcome = response.get("outcome")
    if isinstance(outcome, list):
        outcome.append(result)
    if not getattr(result, "supported", False):
        return False
    retire_offer(game, choice.data.get("_permission"))
    game.discard_pending_choice(choice)
    return True


def default_madness_offer(game, choice) -> None:
    """What a seat nobody asks does with the offer: the AI's own cast
    chooser, rehearsed like every other cast it makes
    (``ai_policy.choose_madness_cast``). A cast it would propose is made — its
    lands tapped by the plan, its announcement the chooser's — and anything
    else, or a cast the engine then refuses, declines."""
    from .ai_policy import cast_announcement, choose_madness_cast, tap_planned_lands

    card = choice.data.get("_card")
    seat = choice.player_index
    permission = choice.data.get("_permission")
    if card is not None and offered_card_in_exile(game, seat, card):
        action = choose_madness_cast(game, seat, card, permission)
        if action is not None:
            action = tap_planned_lands(game, seat, action)
            result = game.queue_from_hand(
                seat, action.card_name, **cast_announcement(action)
            )
            if getattr(result, "supported", False):
                game.log.append(
                    f"{game.players[seat].name} cast {action.card_name} for "
                    f"its madness cost"
                )
                retire_offer(game, permission)
                game.discard_pending_choice(choice)
                return
    _decline(game, choice)


__all__ = [
    "MADNESS",
    "MADNESS_CAST_KIND",
    "MADNESS_LABEL",
    "MADNESS_OFFER",
    "MADNESS_PROMPT",
    "MADNESS_SOURCE",
    "MADNESS_TRIGGER",
    "exile_madness_card",
    "has_madness",
    "is_madness_line",
    "madness_alternative_cost",
    "madness_cost_text",
    "madness_triggers",
    "offer_permission",
    "offered_card_in_exile",
    "printed_madness_cost",
    "default_madness_offer",
    "put_unused_card_into_graveyard",
    "resolve_madness_offer",
    "retire_offer",
    "unread_madness_line",
]
