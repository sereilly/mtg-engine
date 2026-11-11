"""Whether an AI seat entwines a spell (CR 702.42a), and the cast it makes if
it does.

Entwine is not a larger version of one mode, so it is not weighed where the
other optional costs are (``ai_casts._times_worth_taking`` declines
``OFFER_ENTWINES``): paying it **is** choosing every mode, and every mode has
its own targets (CR 601.2c) on the side its own effect wants. So it is weighed
one level out, after ``ai_casts._cast_candidate_in_each_mode`` has built each
mode as a whole candidate of its own — the targets it would name, a payable
cost, a rehearsal that says it is worth casting — exactly as
``ai_casts._every_mode_worth_casting`` combines the modes of a "choose one or
more" spell. The difference is the price: those modes share one cost, an
entwined spell pays its entwine on top, so the cast is planned again with that
mana (or that sacrifice) included and **rehearsed as the combined cast** —
what the board looks like after every mode has resolved in printed order is
the score, and the seat entwines only when that beats the best single mode.

A mode whose targets do not fit a mode's announcement (one seat and one
battlefield slot: several targets, a division or a cross-board list do not
travel in it) leaves the seat casting its best single mode, never an entwined
cast the engine would refuse.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import ai_cast_trace as cast_trace
from .entwine import entwine_cost
from .oracle import compile_card_oracle
from .targeting import derive_cast_spec

if TYPE_CHECKING:
    from .ai_actions import CastAction
    from .game import Game
    from .models import CardDefinition


#: A non-mana entwine ("Entwine—Sacrifice three lands.") is paid only by a
#: seat that still controls this many lands afterwards — the buyback rule
#: (``ai_casts.BUYBACK_PERMANENTS_KEPT``) for the same reason: enough lands to
#: cast everything a limited deck holds.
ENTWINE_LANDS_KEPT = 6


def _entwine_offer(card: "CardDefinition"):
    """The card's entwine as a ``CastOffer`` (``ai_valuation.cast_offers``),
    or None."""
    from .ai_valuation import cast_offers

    key = entwine_cost(card.oracle_text or "")
    if key is None:
        return None
    return next((offer for offer in cast_offers(card) if offer.key == key), None)


def _mode_entry(candidate: "CastAction") -> "dict | None":
    """One ``mode_choices`` entry for *candidate* (a single-mode cast), or None
    when its targets do not fit a mode's announcement."""
    if (
        len(candidate.target_permanent_ids or ()) > 1
        or len(candidate.target_graveyard_indices or ()) > 1
    ):
        return None
    if candidate.divided_targets or candidate.target_role_refs:
        return None
    return {
        "index": candidate.mode_index,
        "target_player_index": candidate.target_player_index,
        "target_permanent_ids": candidate.target_permanent_ids,
        "target_graveyard_indices": candidate.target_graveyard_indices,
        "target_stack_index": candidate.target_stack_index,
    }


def _price_is_spare(game: "Game", player_index: int, card, offer) -> bool:
    """Whether a non-mana entwine price leaves the seat its reserve."""
    price = offer.price
    if price is None:
        return True
    if (
        price.pay_life or price.pay_life_x or price.discard_cards
        or price.discard_filters or price.discard_whole_hand
        or price.return_filter is not None
        or price.sacrifice_all_filter is not None
        or price.exile_filter is not None
    ):
        # Every entwine printed in this pool is mana or a sacrifice of lands;
        # a price of any other resource is declined rather than guessed at.
        return False
    if price.sacrifice_filter is None:
        return True
    available = game._additional_cost_candidates(
        player_index, price, giving_up="sacrifice"
    )
    return len(available) - max(1, price.sacrifice_count) >= ENTWINE_LANDS_KEPT


def entwined_cast(
    game: "Game", player_index: int, card: "CardDefinition",
    built: "list[CastAction]", best: "CastAction",
    *, from_zone: str = "hand", extra_generic: int = 0,
) -> "CastAction | None":
    """The entwined cast of *card*, scored by its rehearsal — or None when the
    seat would not, or could not, make one.

    *built* is every single-mode candidate ``_cast_candidate_in_each_mode``
    found (each a mode with a legal announcement, a payable cost and a
    rehearsal worth proposing) and *best* the one it would cast. None unless
    every mode has a legal announcement (CR 700.2a) and every mode that
    *targets* is in *built*: CR 702.42a chooses all of them, and a targeting
    mode the seat would not cast on its own (nothing on the side its effect
    wants) is a mode the entwined cast would have to aim anyway. A mode that
    names no target is announced bare, and the rehearsal says what it adds.

    Asked inside the permission *built* was weighed under
    (``ai_weighed_cast.casting_under``, held by the caller): the price, the
    rehearsal's trip out of the pile and the zone's bonus read it, so the
    entwined cast and the single modes are one reading of one card wherever
    it is cast from — and it is scored where they are
    (``ai_cast_score.finished_cast_candidate``).
    """
    offer = _entwine_offer(card)
    if offer is None or best is None:
        return None
    program = compile_card_oracle(card)
    if not program.modes:
        return None
    with cast_trace.attempt(
        game, player_index, card, variant="entwined", offers={offer.key: 1},
        from_zone=from_zone, zone_index=best.hand_index,
    ):
        return _entwined(
            game, player_index, card, built, best, offer, program,
            from_zone=from_zone, extra_generic=extra_generic,
        )


def _entwined(
    game: "Game", player_index: int, card: "CardDefinition",
    built: "list[CastAction]", best: "CastAction", offer, program,
    *, from_zone: str, extra_generic: int,
) -> "CastAction | None":
    """`entwined_cast` for a card that prints an entwine and modes."""
    from .ai_actions import cast_announcement, weighed_at_instant_speed
    from .ai_cast_gates import _printed_costs_are_payable
    from .ai_cast_score import finished_cast_candidate, kept_above_the_floor
    from .ai_payment import _cost_for, _plan_land_taps
    from .ai_scoring import (_rehearse_announcement, _weighed_through_the_fight,
                             held_at_instant_speed, not_worth_proposing,
                             read_at_instant_speed)

    by_mode = {candidate.mode_index: candidate for candidate in built}
    announceable = set(game.announceable_modes(player_index, card))
    entries = []
    for index in range(len(program.modes)):
        if index not in announceable:
            # CR 700.2a: a mode with no legal announcement cannot be chosen,
            # and an entwined cast chooses every one.
            return cast_trace.dropped(
                f"mode {index} has no legal announcement now (CR 700.2a)"
            )
        candidate = by_mode.get(index)
        if candidate is None:
            # A mode the seat would not cast **alone** may still be worth
            # casting after its siblings: "Create an X/X black Demon …, where
            # X is the number of cards in your hand" is a 0/0 from an empty
            # hand and a 5/5 after "You draw five cards" (Promise of Power's
            # 2004-12-01 ruling). A mode that names no target needs no
            # candidate to be announced; one that does is left to the single
            # modes, whose targets this seat has weighed.
            if derive_cast_spec(
                card, program, from_zone=from_zone, mode_index=index,
            ) is not None:
                return cast_trace.dropped(
                    f"mode {index} targets, and was not worth casting alone"
                )
            entries.append({"index": index})
            continue
        if (
            candidate.optional_cost_payments
            or candidate.alternative_cost
            or candidate.x_value != best.x_value
        ):
            return cast_trace.dropped(
                f"mode {index} was built with an offer, an alternative cost or"
                " another X"
            )
        entry = _mode_entry(candidate)
        if entry is None:
            return cast_trace.dropped(
                f"mode {index}'s targets do not fit one mode's announcement"
            )
        entries.append(entry)
    taken = {offer.key: 1}
    hand_index = best.hand_index
    if not _printed_costs_are_payable(
        game, player_index, card, hand_index, from_zone, best.x_value, taken=taken,
    ):
        return cast_trace.dropped("the entwine's printed cost cannot be paid")
    if not _price_is_spare(game, player_index, card, offer):
        return cast_trace.dropped(
            "the entwine's price is not spare (ENTWINE_LANDS_KEPT, or not mana)"
        )
    player = game.players[player_index]
    tap_indices: tuple = ()
    tap_colors: tuple = ()
    if game.enforce_mana_costs:
        required = dict(_cost_for(game, player, card, best.x_value, extra_generic=extra_generic))
        if offer.mana is not None:
            for symbol, amount in offer.mana.cost_at(None).items():
                required[symbol] = required.get(symbol, 0) + amount
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return cast_trace.dropped("unaffordable with the entwine's mana on top")
        tap_indices, tap_colors = plan
    action = replace(
        best,
        mode_index=None,
        mode_choices=entries,
        optional_cost_payments=taken,
        target_permanent_ids=None,
        target_graveyard_indices=None,
        target_stack_index=None,
        land_tap_indices=tap_indices,
        land_tap_colors=tap_colors,
        score=0.0,
    )
    announcement = cast_announcement(action)
    rehearsal = _rehearse_announcement(
        game, player_index, card, announcement, planned=action,
    )
    rehearsal = _weighed_through_the_fight(
        game, player_index, card, announcement, rehearsal, planned=action,
    )
    # At instant speed, read as the single modes were (`read_at_instant_speed`,
    # `held_at_instant_speed`, the floor): the entwined cast is one more
    # candidate of the same builder.
    instant = weighed_at_instant_speed()
    if instant:
        rehearsal, held = read_at_instant_speed(
            game, player_index, card, action, rehearsal,
        )
        if held is not None:
            return cast_trace.dropped(held)
    if (refused := not_worth_proposing(rehearsal)) is not None:
        return cast_trace.dropped(refused)
    if instant and (held := held_at_instant_speed(rehearsal)) is not None:
        return cast_trace.dropped(held)
    # Comparable with *best*'s score, because it is finished where *best* was
    # (`ai_cast_score.finished_cast_candidate`): the zone's bonus — a cast under a
    # permission that ends, or from the command zone — is the same for every
    # mode and for all of them together.
    return kept_above_the_floor(
        finished_cast_candidate(game, player_index, card, action, rehearsal)
    )


__all__ = ["ENTWINE_LANDS_KEPT", "entwined_cast"]
