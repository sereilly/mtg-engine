"""The discard, cut along the seat that does it: the branches of
``hand._lower_discard`` that are a whole reading each.

A **floor**, not a family: ``hand.py`` reads it and it reads nothing back —
inside ``lowering/`` a module a family imports has to sit below the families,
which is ``_counted_pumps``' reason one family over and ``_recipients``' before
it. ``hand`` is its one importer.

Split out of ``hand.py`` at the thousand-line guard, and along the line that
module's own docstring drew for the day it came: "cut *inside*
``_lower_discard``, along its per-seat branches, rather than moving the family
out of the zone CR 701.9a names". So the discard family did not move —
``_lower_discard`` is still where a ``Discard`` node is lowered, still decides
which reading a sentence is, and still holds every seat the sentence has to be
*told* (a target, a seat an event froze, the defending player). What is here
are the four readings that need no such telling, each of which was one
``if`` in that function and is one function now:

- **every matching card** (``discard_all_matching``) — "discards all nonland
  cards": not a count at all, so nobody chooses;
- **the whole hand** (``discard_whole_hand``) — one instruction with a ``who``;
- **each player** (``each_player_discard``) — one decision per seat;
- **the effect's own controller** (``controller_discard``) — the chosen
  prompt, its "any number" ceiling, and the two random spellings.

Moved verbatim: no payload any of these emits changed in the move.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import (CHOSEN_COLOR_THIS_WAY, CHOSEN_CREATURE_TYPE_THIS_WAY,
                             CHOSEN_NUMBER_THIS_WAY,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec, halved_count_spec
from ._common import _amount_payload, _describe_targets, chargeable_card_filter
from ._events import _DAMAGED_PLAYER_EVENTS, _DEFENDING_PLAYER_EVENTS
from ._cost_records import SACRIFICED_FOR_COST
from ._filters import hand_name_relation



def discard_all_matching(
    node: ast.Discard, event: str | None, produced: frozenset[str],
) -> tuple[OracleInstruction, ...]:
    # "Discard your hand" (Chandra, Heart of Fire) — the effect's controller
    # discards every card. Checked before the targeted forms: the subject is
    # the implied "you", which they refuse.
    # "Target player reveals their hand and discards **all nonland cards**."
    # (Amnesia.) Not a count at all: every card answering the phrase goes, so
    # nobody chooses and there is no prompt — which is why it is read before the
    # counted forms rather than as an amount one of them could carry. The filter
    # is gated by the same reader every other card phrase is, so a narrowing the
    # matcher cannot test refuses instead of being dropped into a discard that
    # empties the whole hand.
    # "…that player reveals their hand and discards all cards of that
    # color." (Crosis, the Purger.) The seat a damage trigger froze rather
    # than one the announcement chose — the same instruction with a ``who``,
    # as ``discard_hand`` below reads the same seat, and admitted only under
    # an event that recorded one.
    damaged = node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS
    # "Target player reveals their hand. **That player** discards all …"
    # (Hint of Insanity): no event, so the player this effect targeted —
    # Flay's reading below, and the handler's default seat.
    named = node.player.kind == "that_player" and event is None
    if not (damaged or named) and node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            "no handler discards every matching card from a seat nobody "
            "targeted", node=node,
        )
    if node.at_random:
        raise LoweringError(
            "'all' names every matching card, so nothing is chosen at "
            "random", node=node,
        )
    payload: dict[str, object] = {}
    if node.filter is not None:
        # "…discards all cards **of that color**." (Persecute.) The colour
        # an earlier sentence of this same resolution chose (CR 608.2d),
        # taken off the filter **before** the testability gate and put back
        # as its own key after it: no card matcher holds a resolution, so a
        # gate asking "can every key be answered?" must not be shown one
        # that only the handler can. The same shape `subject_matches`'
        # ``subtype_filter_from`` takes for the identical question one
        # characteristic over.
        described_filter = node.filter
        carried: dict[str, object] = {}
        if described_filter.color_chosen_this_way:
            described_filter = dataclasses.replace(
                described_filter, color_chosen_this_way=False
            )
            carried["color_filter_from"] = CHOSEN_COLOR_THIS_WAY
        # "…discards all creature cards **of that type**." (Tsabo's Decree.)
        # The colour's sibling one characteristic over, split off for its
        # reason and carried under the key the destroy sweep in the same
        # card reads. Only behind the step that chose a creature type: with
        # no producer the words name nothing, and "all creature cards" is a
        # wider discard than the card prints.
        if described_filter.of_bound_type:
            if CHOSEN_CREATURE_TYPE_THIS_WAY not in produced:
                raise LoweringError(
                    "'of that type' names a creature type no step of this "
                    "effect chose", node=node,
                )
            described_filter = dataclasses.replace(
                described_filter, of_bound_type=False
            )
            carried["subtype_filter_from"] = CHOSEN_CREATURE_TYPE_THIS_WAY
        # "…discards all nonland cards with mana value **equal to the
        # number**." (Void.) The third record this sweep reads, split off
        # the same way and for the same reason.
        if described_filter.mana_value_equals_chosen_number:
            if CHOSEN_NUMBER_THIS_WAY not in produced:
                raise LoweringError(
                    "'equal to the number' names a number no step of this "
                    "effect chose", node=node,
                )
            described_filter = dataclasses.replace(
                described_filter, mana_value_equals_chosen_number=False
            )
            carried["mana_value_from"] = CHOSEN_NUMBER_THIS_WAY
        # "…discards all cards **of each of the sacrificed creature's
        # colors**." (Mind Extraction.) A fourth record, and the one that
        # is not a step's: what the spell's own *cost* ate (CR 601.2h),
        # which a different printed line charges and this clause cannot
        # see — so there is no producer to demand, for the reason
        # ``_record_conditions`` gives for ``CostObjectWas``. An unpaid
        # channel has no colours, and the handler discards nothing.
        if described_filter.colors_of_sacrificed_for_cost:
            described_filter = dataclasses.replace(
                described_filter, colors_of_sacrificed_for_cost=False
            )
            carried["any_colors_from_cost"] = SACRIFICED_FOR_COST
        described_filter, shared = hand_name_relation(described_filter, node)
        carried.update(shared)
        described = chargeable_card_filter(described_filter)
        if described is None:
            raise LoweringError(
                "no discard can test this narrowing", node=node
            )
        # An empty payload is a phrase that reduced to "all cards", which is
        # the whole hand — right for "discards all cards of that color",
        # where the *colour* is the whole narrowing and rides its own key.
        if described:
            payload["filter"] = described
        elif not carried:
            raise LoweringError(
                "no discard can test this narrowing", node=node
            )
        payload.update(carried)
    if damaged:
        payload["who"] = "damaged_player"
    elif not named:
        _describe_targets(payload, node.player)
    return (OracleInstruction("discard_all_matching_cards", "", payload),)


def discard_whole_hand(
    node: ast.Discard, event: str | None,
) -> tuple[OracleInstruction, ...]:
    """"Discard your hand" (Chandra, Heart of Fire), and every other seat the
    same emptying is printed for. One instruction with a ``who`` rather than a
    kind per seat: a second kind would be a second copy of emptying a hand."""
    if node.player.kind == "you":
        return (OracleInstruction("discard_hand", "", {}),)
    # "…, that player discards their hand" (Nicol Bolas). The same effect
    # aimed at the seat the firing event recorded, so it is the same
    # instruction with a `who` — a second kind would be a second copy of
    # emptying a hand. Admitted only under a trigger whose fire site
    # actually froze a damaged player: under any other event the words name
    # a seat nobody recorded, and the discard would silently empty the
    # ability's own controller's hand.
    if node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
        return (
            OracleInstruction("discard_hand", "", {"who": "damaged_player"}),
        )
    # "**Each player** discards their hand, then draws cards equal to the
    # greatest number of cards a player discarded this way." (Windfall.)
    # The same emptying offered to every living seat, so it is the same
    # instruction with a ``who`` rather than a second kind — the reading the
    # branch above already takes for the seat a trigger froze. Nobody
    # chooses which cards, so there is no prompt and no ordering to settle
    # (CR 101.4 orders decisions, and this effect asks for none).
    if node.player.kind == "each_player":
        return (
            OracleInstruction("discard_hand", "", {"who": "each_player"}),
        )
    # "…**target opponent** discards their hand." (Brink of Madness.) The
    # same emptying aimed at a seat the *announcement* chose (CR 601.2c /
    # 603.3d) rather than at one an event froze, so it is the same
    # instruction with a third ``who`` — a second kind would be a second
    # copy of emptying a hand, which is what the two branches above already
    # refuse to be.
    #
    # ``who`` says which seat the handler reads rather than leaving it to
    # the key's absence: an unkeyed payload is the controller's own hand
    # one branch up, and that is the one player this effect must not hit.
    # The ``targets`` description beside it is what raises the picker —
    # ``targeting._from_instruction`` reads it generically, so the trigger
    # announces an opponent (``_choose_trigger_targets``) instead of
    # falling through to the first living one.
    if node.player.kind in ("target_player", "target_opponent"):
        payload: dict[str, object] = {"who": "target"}
        _describe_targets(payload, node.player)
        return (OracleInstruction("discard_hand", "", payload),)
    # "Whenever this creature becomes blocked, **defending player** discards
    # all the cards in their hand, then draws that many cards." (Robber
    # Fly.) CR 506.2's seat, frozen by the combat fire site — the same
    # ``who`` channel the three branches above use, gated on an event that
    # really stamped one, exactly as the counted discard one screen down
    # gates the identical phrase.
    if node.player.kind == "defending_player":
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        return (
            OracleInstruction(
                "discard_hand", "", {"who": "defending_player"}
            ),
        )
    raise LoweringError(
        f"no whole-hand discard handler for {node.player.kind!r}", node=node
    )


def each_player_discard(node: ast.Discard) -> tuple[OracleInstruction, ...]:
    # "Each player discards a card." (Liliana, Waker of the Dead.) The handler
    # records which players could not, because the printed rider "Each opponent
    # who can't loses 3 life." reads that answer out of the same resolution.
    if node.at_random or node.filter is not None or node.up_to:
        raise LoweringError(
            "the each-player discard is chosen, unnarrowed and exact",
            node=node,
        )
    # "…discards **a third of the cards in their hand**" (Pox). One number
    # per seat, so it cannot be an amount: it is a count taken over *that*
    # player's hand, and the handler asks the evaluator once per seat
    # through the channel the per-recipient damage already uses.
    per_seat = (
        halved_count_spec(node.count, node)
        if isinstance(node.count, ast.Half) else None
    )
    if per_seat is not None:
        return (
            OracleInstruction(
                "each_player_discards_a_card", "",
                {X_FROM_COUNT_PER_RECIPIENT: per_seat},
            ),
        )
    if isinstance(node.count, ast.AnyNumber):
        # "**Each player discards any number of cards**, then draws that
        # many cards." (Flux.) A ceiling with no printed number: the bound
        # is the seat's own hand, which only the resolution knows, so it
        # travels as a flag and the handler sizes each prompt. The same
        # prompt Mind Bomb's "up to three" arms — "any number" and "up to
        # N" are one decision with two ceilings, and the "may" is already
        # inside both (a player may answer with none).
        return (
            OracleInstruction(
                "each_player_discards_up_to_cards", "",
                {"actor": node.player.kind, "any_number": True},
            ),
        )
    if not isinstance(node.count, ast.Fixed):
        raise LoweringError("each-player discards have a one-card handler", node=node)
    # A printed 1 keeps the empty payload every card written before the
    # count existed produced, so nothing that worked changes shape.
    payload = {} if node.count.value == 1 else {"amount": node.count.value}
    return (OracleInstruction("each_player_discards_a_card", "", payload),)


def controller_discard(node: ast.Discard) -> tuple[OracleInstruction, ...]:
    # "You may draw a card. If you do, discard a card." (Jeskai Elder) — the
    # effect's own controller discards, choosing the cards through the same
    # pending choice the targeted form uses. Fixed counts only: the variable
    # form stays with the random handler below, whose contract it is.
    if isinstance(node.count, ast.AnyNumber) and not node.at_random:
        # "…**discard any number of creature cards**." (Mind Maggots.) A
        # ceiling with no printed number, which is the same sentence the
        # each-player branch above already reads (Flux) pointed at one seat:
        # the bound is what the printed phrase names in the caster's own
        # hand, and only the resolution knows it. So it travels as a flag
        # and ``discard_controller_cards`` sizes the prompt, exactly as that
        # branch leaves the sizing to its handler.
        #
        # "Any number" carries its own "may" — a player may answer with
        # none — so the prompt is armed as a ceiling (``up_to``) rather than
        # as an amount. Read as an amount it would force the whole hand out,
        # which is a strictly larger cost than the card asks for.
        #
        # ``at_random`` is excluded rather than folded in: who picks is what
        # separates this handler from ``discard_x_target_cards``, and
        # nobody chooses a random discard's size either.
        payload: dict[str, object] = {"amount": 0, "any_number": True}
        if node.filter is not None:
            # The same reader the counted branch below uses, and for its
            # reason: a phrase ``_card_matches_filter`` cannot test would be
            # dropped where the prompt applies it, and a dropped narrowing
            # here offers the whole hand to a sentence naming one card type.
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no discard prompt can test this narrowing", node=node
                )
            payload["filter"] = described
        return (
            OracleInstruction("discard_controller_cards", "", payload),
        )
    # "…discard a card **for each Island you control**" — the number Last
    # Stand's "then discard that many cards" names. Counted at resolution on
    # the channel the draw beside it travels (``lowering/cards``), so the
    # two halves of that sentence are sized by one spec. Chosen, never "at
    # random": the sampling handler below reads no count spec.
    if isinstance(node.count, ast.AnyNumber):
        # "Discard **any number of cards at random**." (Rites of
        # Initiation.) Two decisions the card splits between two parties:
        # the player chooses *how many* and chance chooses *which*. So it
        # is two steps — a number with the hand as its ceiling, then the
        # sampling handler sized by that answer — and neither handler
        # learns the other's job. The chosen form one branch up asks one
        # question because there the cards are the answer to both.
        #
        # Unnarrowed, as printed: a narrowing would have to bound the
        # number *and* the sample by one reading of the phrase, and no
        # card asks for it.
        if node.filter is not None:
            raise LoweringError(
                "the any-number random discard is unnarrowed", node=node
            )
        return (
            OracleInstruction("choose_number", "", {
                "minimum": 0,
                "maximum_from_count": {
                    "zone": "hand", "owner": "you", "filter": {},
                },
            }),
            OracleInstruction("discard_x_target_cards", "", {
                "who": "caster", "amount_from": CHOSEN_NUMBER_THIS_WAY,
            }),
        )
    counted: dict[str, object] = {}
    if isinstance(node.count, ast.CountOf) and not node.at_random:
        counted = {X_FROM_COUNT: count_spec(node.count.filter, node)}
    amount = "x" if counted else _amount_payload(node.count)
    # "Discard **X** cards, then …" (Recall). The count may be the cast's X:
    # `discard_controller_cards` sizes its prompt through `resolve_amount`,
    # which reads `"x"` off the context, so the variable form is the same
    # handler with the same payload key rather than a second kind. What
    # stays refused is "at random" — who picks is what separates this
    # handler from `discard_x_target_cards`, and lowering a chosen discard
    # onto the random one takes the choice the card leaves its controller.
    if node.at_random:
        # "{5}, {T}: **Discard a card at random**, then draw two cards."
        # (Ring of Renewal.) Nobody chooses, so it is not this handler at
        # all: `discard_x_target_cards` is the one that samples, and what
        # separates the two is the chooser rather than the seat. Routed to
        # it with the seat named, because that handler reads
        # ``context.target`` by default — which for an activated ability
        # nobody targeted with is the **opponent**, so the ring would have
        # emptied the wrong hand while reporting itself resolved.
        if not isinstance(amount, (int, str)):
            raise LoweringError(
                "the random controller discard is counted or X", node=node
            )
        if node.up_to:
            # A ceiling is a choice of how many, and a sample has no chooser:
            # "any number … at random" above is the one spelling that says
            # who picks the number. Read as a count, "up to two at random"
            # would discard exactly two.
            raise LoweringError(
                "a random discard has nobody to choose under a ceiling",
                node=node,
            )
        random_payload: dict[str, object] = {
            "amount": amount, "who": "caster",
        }
        if node.filter is not None:
            # The same reader the targeted random discard uses one branch
            # down (Rag Man): a phrase the card matcher cannot test would
            # widen the sample to the whole hand, which is the one direction
            # a narrowing must never be dropped in.
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no random discard can test this narrowing", node=node
                )
            random_payload["filter"] = described
        return (
            OracleInstruction("discard_x_target_cards", "", random_payload),
        )
    if not isinstance(amount, (int, str)):
        raise LoweringError(
            "the controller discard is chosen, and counted or X", node=node
        )
    payload: dict[str, object] = {"amount": amount, **counted}
    if node.up_to:
        # "Discard **up to** two cards." A ceiling: fewer, none
        # included, is a legal answer, and the prompt has to be told so or it
        # demands exactly the printed number. The fused "…, then draw that
        # many" (Kinetic Augur) carried it; the bare sentence dropped it.
        payload["up_to"] = True
    # "Discard a **creature** card" (Crypt Lurker). Gated by the same reader
    # the discard *cost* is (round 87): the prompt and its re-check ask
    # ``_card_matches_filter``, so a phrase reaching past what that can
    # answer would be dropped where it is applied — and a dropped narrowing
    # here is a discard that takes any card at all while the card still
    # reports supported.
    if node.filter is not None:
        described = chargeable_card_filter(node.filter)
        if not described:
            raise LoweringError(
                "no discard prompt can test this narrowing", node=node
            )
        payload["filter"] = described
    return (OracleInstruction("discard_controller_cards", "", payload),)
