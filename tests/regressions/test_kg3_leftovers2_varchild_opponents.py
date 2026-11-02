"""Varchild's War-Riders: each Survivor goes to an opponent its controller
names.

"Cumulative upkeep—Have an opponent create a 1/1 red Survivor creature
token." CR 702.24a: "pay [cost] for each age counter on it" — one "have an
opponent create" per age counter, and its ruling (2004-10-04): "If you have
multiple opponents, you can put the Survivor tokens onto the battlefield under
the control of different players." ``upkeep_step._have_an_opponent_create``
gave every token to the first living opponent after the payer, asking nobody.

Each age counter's opponent is now asked of the payer through the choosers'
seam (``handlers/player_choices.ask_which_opponent``: one opponent is no
question, a seat nobody asks takes the first offered), in one resumable loop
whose last step creates the tokens — so nothing is created before the last
answer, and a seat nobody asks makes them in one creation per opponent, as
before.

Backwards on 90bef6d1: the interactive payer was never asked and P1 got both.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _table(seats: int, *, interactive=()) -> tuple[Game, Permanent]:
    riders = Permanent(card=_CARDS["Varchild's War-Riders"])
    riders.metadata["summoning_sickness_turn"] = -99
    add_counters(riders, "age", 1)  # the upkeep's counter makes two
    game = Game(players=[
        PlayerState(name=f"P{seat}", battlefield=[riders] if seat == 0 else [],
                    library=[_CARDS["Island"]] * 5)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._sync_control()
    return game, riders


def _survivors(game: Game, seat: int) -> int:
    return sum(1 for p in game.controlled_by(seat) if p.card.name == "Survivor Token")


def _upkeep(game: Game) -> None:
    game.resolve_upkeep(0, human_choices={"Varchild's War-Riders": True})
    game._settle()


def test_the_payer_names_an_opponent_for_each_age_counter():
    game, riders = _table(3, interactive=(0,))
    _upkeep(game)

    asked = [c for c in game.pending_choices if c.kind == "player_choice"]
    assert [c.player_index for c in asked] == [0], game.log[-6:]
    assert sorted(asked[0].data["seats"]) == [1, 2]
    assert (_survivors(game, 1), _survivors(game, 2)) == (0, 0), "nothing before the last answer"
    assert game.confirm_player_choice(0, 1)
    asked = [c for c in game.pending_choices if c.kind == "player_choice"]
    assert [c.player_index for c in asked] == [0], "asked again, for the second counter"
    assert game.confirm_player_choice(0, 2)
    resolve_stack(game)

    assert (_survivors(game, 1), _survivors(game, 2)) == (1, 1), game.log[-8:]
    assert game.is_on_battlefield(riders) and counters_on(riders, "age") == 2


def test_a_payer_nobody_asks_gives_them_to_the_first_opponent_offered():
    game, riders = _table(3)
    _upkeep(game)
    resolve_stack(game)

    assert not game.pending_choices
    assert (_survivors(game, 1), _survivors(game, 2)) == (2, 0), game.log[-6:]
    assert game.is_on_battlefield(riders)


def test_with_one_opponent_nobody_is_asked():
    game, riders = _table(2, interactive=(0,))
    _upkeep(game)
    resolve_stack(game)

    assert not [c for c in game.pending_choices if c.kind == "player_choice"]
    assert _survivors(game, 1) == 2, game.log[-6:]
