"""Rules tests earned by Invasion wave 2, group 7 — CR 616.1e's default.

When a damage *cap* ("if a source would deal 4 or more damage, it deals 3
instead" — Divine Presence, Forethought Amulet) and a damage *multiplier*
(Furnace of Rath, Fiery Emancipation) both modify one event, CR 616.1 gives the
order to the affected player. An interactive seat is asked. Every other seat
takes the engine's default, and the default was two static numbers — the cap
ahead of the prevention shields, the multiplier behind them — which are each
right against the shields and wrong against each other: 5 became 3 and then 6,
where the player whose choice it is would double first and take 3.

``effect_ordering.choose_effect`` now chooses on that one contended round. The
tests assert the *numbers* and the *sequence* (the trace), because the sequence
is what a 616.1 implementation is and it is invisible in the totals.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.damage_events import damage_candidates
from engine.effect_ordering import (CAP, MULTIPLIER, Candidate, apply_in_order,
                                    choose_effect)
from engine.models import Permanent
from tests.helpers import _damage_dealt, _mk_card, _nosick


def _w2g7_board(mine=(), theirs=(), **p0) -> Game:
    game = Game(players=[
        PlayerState("A", battlefield=[_nosick(Permanent(card=c)) for c in mine], **p0),
        PlayerState("B", battlefield=[_nosick(Permanent(card=c)) for c in theirs]),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


_GIANT = _mk_card(name="W2G7 Giant", type_line="Creature - Giant", power=7, toughness=7)


@pytest.mark.cr("616.1e", "616.1f", "120.4b")
def test_w2g7_616_1e_the_default_doubles_before_it_caps(set_pool):
    """Divine Presence beside Furnace of Rath, damage to the Presence's own
    controller. Capped then doubled is 6; doubled then capped is 3, and the
    choice is the damaged player's."""
    presence = set_pool("INV")["Divine Presence"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = _w2g7_board(mine=[presence], theirs=[furnace, _GIANT])
    giant = game.players[1].battlefield[1]

    assert _damage_dealt(game, game.players[0], 5, source=giant) == 3
    # …and from the first point the cap applies at, where the old order's
    # answer was the same 6.
    assert _damage_dealt(game, game.players[0], 4, source=giant) == 3


@pytest.mark.cr("616.1e", "616.1f")
def test_w2g7_616_1f_a_cap_the_doubling_reaches_is_asked_again(set_pool):
    """Two damage is under Divine Presence's threshold, so on the first round
    only the Furnace applies. Doubled to 4 it is over, and CR 616.1f re-asks
    every remaining effect — the cap applies to the amount as it now stands."""
    presence = set_pool("INV")["Divine Presence"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = _w2g7_board(mine=[presence], theirs=[furnace, _GIANT])
    giant = game.players[1].battlefield[1]

    assert _damage_dealt(game, game.players[0], 2, source=giant) == 3
    assert _damage_dealt(game, game.players[0], 1, source=giant) == 2


@pytest.mark.cr("616.1e")
def test_w2g7_616_1e_a_tripling_source_is_capped_last_too(set_pool, catalog_by_name):
    """Fiery Emancipation: "If a source you control would deal damage … it
    deals triple that damage instead." Five was 3 and then **9**."""
    presence = set_pool("INV")["Divine Presence"]
    emancipation = catalog_by_name["Fiery Emancipation"]
    game = _w2g7_board(mine=[presence], theirs=[emancipation, _GIANT])
    giant = game.players[1].battlefield[1]

    assert _damage_dealt(game, game.players[0], 5, source=giant) == 3


@pytest.mark.cr("616.1e", "120.4b")
def test_w2g7_616_1e_forethought_amulet_caps_a_doubled_bolt(set_pool, catalog_by_name):
    """The card the cap was built for, through a real spell: Lightning Bolt
    under a Furnace of Rath at an Amulet's controller. 3 → capped 2 → doubled
    4 was the default; the Amulet's controller takes 2."""
    amulet = set_pool("LEG")["Forethought Amulet"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = Game(players=[
        PlayerState("A", hand=[catalog_by_name["Lightning Bolt"]],
                    battlefield=[_nosick(Permanent(card=furnace))]),
        PlayerState("B", battlefield=[_nosick(Permanent(card=amulet))]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._sync_control()

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game._settle()

    assert game.players[1].life == 18, game.log[-6:]


@pytest.mark.cr("616.1e")
def test_w2g7_616_1e_a_shield_still_absorbs_from_the_capped_number(set_pool):
    """All three shapes on one event: 4 damage, doubled, capped at 3, against
    "prevent the next 1". The shield comes last, so it takes its point off 3 —
    the old order (cap, shield, double) dealt 4."""
    presence = set_pool("INV")["Divine Presence"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = _w2g7_board(
        mine=[presence], theirs=[furnace, _GIANT], damage_prevention_pool=1
    )
    giant = game.players[1].battlefield[1]

    assert _damage_dealt(game, game.players[0], 4, source=giant) == 2
    assert game.players[0].damage_prevention_pool == 0


@pytest.mark.cr("616.1e")
def test_w2g7_616_1e_each_shape_alone_keeps_the_order_it_had(set_pool):
    """The rule is about the two contending. A cap with no multiplier still
    goes ahead of the shield (which keeps its points), and a multiplier with no
    cap still goes behind it (which absorbs from the printed number)."""
    presence = set_pool("INV")["Divine Presence"]
    furnace = set_pool("TMP")["Furnace of Rath"]

    capped = _w2g7_board(mine=[presence], theirs=[_GIANT], damage_prevention_pool=3)
    giant = capped.players[1].battlefield[0]
    assert _damage_dealt(capped, capped.players[0], 9, source=giant) == 0
    assert capped.players[0].damage_prevention_pool == 0

    doubled = _w2g7_board(theirs=[furnace, _GIANT], damage_prevention_pool=3)
    giant = doubled.players[1].battlefield[1]
    assert _damage_dealt(doubled, doubled.players[0], 3, source=giant) == 0


@pytest.mark.cr("616.1e")
def test_w2g7_616_1e_the_registrations_say_which_shape_they_are(set_pool):
    """The default reads a declared role, not an order range: the cap and all
    three multipliers carry one, and nothing else in a damage event does."""
    game = _w2g7_board()
    roles = {
        candidate.key: candidate.amount_role
        for candidate in damage_candidates(game.players[0])
        if candidate.amount_role
    }
    assert roles == {
        "_cap_damage_from_source_class": CAP,
        "_multiply_damage_dealt": MULTIPLIER,
        "_double_next_damage_from_chosen_source": MULTIPLIER,
    }
    creature_roles = {
        candidate.amount_role
        for candidate in damage_candidates(
            _nosick(Permanent(card=_GIANT))
        )
    }
    assert creature_roles == {"", CAP, MULTIPLIER}


@pytest.mark.cr("616.1e", "616.1f")
def test_w2g7_616_1e_the_default_is_a_sequence_and_the_trace_shows_it():
    """The choice in isolation, on three bare candidates: with a cap in
    contention the multiplier is taken first, then the cap, then the rest in
    order; without one, plain order."""

    def effect(key, order, fn, role=""):
        return Candidate(
            key=key, order=order, applies=lambda g, e: True,
            apply=lambda g, e: e.__setitem__("amount", fn(e["amount"])),
            amount_role=role,
        )

    cap = effect("cap", 5, lambda n: 3 if n >= 4 else n, CAP)
    shield = effect("shield", 100, lambda n: max(0, n - 1))
    double = effect("double", 700, lambda n: n * 2, MULTIPLIER)

    event = {"amount": 4}
    trace = apply_in_order(None, event, [cap, shield, double])
    assert trace.applied == ["double", "cap", "shield"]
    assert event["amount"] == 2

    event = {"amount": 4}
    trace = apply_in_order(None, event, [shield, double])
    assert trace.applied == ["shield", "double"]

    assert choose_effect(None, None, [cap, shield]) is cap


@pytest.mark.cr("616.1e")
def test_w2g7_616_1e_an_interactive_seat_is_still_asked(set_pool):
    """The default is what a seat takes when it is *not* asked. A seat that can
    answer still gets CR 616.1e's choice put to it, with both effects named."""
    presence = set_pool("INV")["Divine Presence"]
    furnace = set_pool("TMP")["Furnace of Rath"]
    game = _w2g7_board(mine=[presence], theirs=[furnace, _GIANT])
    game.interactive_seats = {0}
    giant = game.players[1].battlefield[1]

    game._deal_damage_to_player(game.players[0], 5, source=giant, asks=True)

    pending = [choice for choice in game.pending_choices if choice.kind == "effect_order"]
    assert len(pending) == 1, game.log[-4:]
    assert game.players[0].life == 20, "nothing is applied until the seat answers"
