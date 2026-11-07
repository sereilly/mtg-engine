"""What one event takes off the battlefield looks back at itself (CR 603.10a,
704.3).

CR 704.3: the game "performs all applicable state-based actions
simultaneously as a single event". CR 603.10a: a leaves-the-battlefield
ability looks back in time — "the game 'looks back in time' to determine if
those abilities trigger, using the existence of those abilities and the
appearance of objects immediately prior to the event". So a permanent dying
in an event sees every other permanent that dies in it.

The engine performed one check as a series of sweeps, one per rule and per
seat (``game_ending._check_state_based_actions``), each taking its victims
off the battlefield before the next began — and "destroy all" one permanent
at a time (``destroy_sweeps.destroy_all_matching``). A Massacre Wurm ("Whenever
a creature an opponent controls dies, that player loses 2 life") swept first
never saw the opponent's creatures die beside it: two Hill Giants dying with it
to one combat's damage, or to one Wrath of God, cost their controller 0 life
instead of 4. With the Wurm on the seat swept last it was 4 — the asymmetry
is the defect.

Now one check is one event (``Game.leaving_together`` around each pass, the
pass extracted as ``_state_based_pass``) and so is each sweep: what the event
has already taken off the battlefield is an observer of each later death in
it (``DeathsMixin._death_observers``). Driven through a real combat, a state
check, a check whose deaths come from two different rules, and Wrath of God,
with the Wurm on the seat swept first and on the seat swept last.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import declare_attack

_CARDS = {card.name: card for card in load_catalog()}

WURM = "Massacre Wurm"


def _table() -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    """On the battlefield without entering (the Wurm's own entry trigger would
    shrink the board this test is about)."""
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _settle(game: Game) -> None:
    for _ in range(100):
        if game.stack:
            game.resolve_top_of_stack()
            continue
        if game.pending_choices:
            game.auto_resolve_pending_choices()
            continue
        return
    raise AssertionError(game.log[-8:])


def _board(wurm_seat: int):
    game = _table()
    wurm = _set_down(game, wurm_seat, WURM)
    giants = [_set_down(game, 1 - wurm_seat, "Hill Giant") for _ in range(2)]
    return game, wurm, giants


def _lethal_damage(game, wurm, giants) -> None:
    for permanent in (wurm, *giants):
        permanent.damage_marked = 10
    game.check_state_based_actions()


def _two_rules(game, wurm, giants) -> None:
    """The Wurm dies to toughness 0 (CR 704.5f, the earlier sweep), the
    Giants to lethal damage (CR 704.5g, the later one) — two sweeps of one
    check."""
    wurm.toughness_bonus -= 5
    for giant in giants:
        giant.damage_marked = 10
    game.check_state_based_actions()


def _wrath(game, wurm, giants) -> None:
    game.players[0].hand = [_CARDS["Wrath of God"]]
    assert game.cast_from_hand(0, "Wrath of God").supported


def _combat(game, wurm, giants) -> None:
    """A real combat damage step: the Wurm's controller attacks with the Wurm
    (already dealt 3) and a Hill Giant of its own; one of the opponent's
    Giants blocks each. Every creature in the fight dies to the one check
    after the damage."""
    attacker = game.controller_index_of(wurm)
    wurm.damage_marked = 3
    partner = _set_down(game, attacker, "Hill Giant")
    slots = {
        perm.permanent_id: slot
        for seat in (0, 1)
        for slot, perm in enumerate(game.players[seat].battlefield)
    }
    declare_attack(game, attacker, blocks={
        slots[giants[0].permanent_id]: slots[wurm.permanent_id],
        slots[giants[1].permanent_id]: slots[partner.permanent_id],
    })
    game.advance_combat_phase()   # combat damage, and the check after it


ROADS = {
    "combat": _combat,
    "lethal_damage": _lethal_damage,
    "two_rules": _two_rules,
    "wrath_of_god": _wrath,
}


@pytest.mark.parametrize("wurm_seat", [0, 1], ids=["wurm_swept_first", "wurm_swept_last"])
@pytest.mark.parametrize("road", sorted(ROADS))
def test_a_dying_wurm_sees_the_creatures_dying_beside_it(road, wurm_seat):
    game, wurm, giants = _board(wurm_seat)
    before = [player.life for player in game.players]
    ROADS[road](game, wurm, giants)
    _settle(game)
    assert not any(
        p.card.name in (WURM, "Hill Giant") for p in game.all_permanents()
    ), [p.card.name for p in game.all_permanents()]
    opponent = 1 - wurm_seat
    lost = before[opponent] - game.players[opponent].life
    assert lost == 4, (
        f"{road}: the Wurm on seat {wurm_seat} died with two of seat "
        f"{opponent}'s creatures and seat {opponent} lost {lost}; it sees "
        "both die (CR 603.10a), 2 each\n" + "\n".join(game.log[-15:])
    )
    assert game.departure_batch is None if hasattr(game, "departure_batch") else True
