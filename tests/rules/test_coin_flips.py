"""CR 705 — flipping a coin.

One printed "Flip a coin." is one flip, and every sentence after it that says
"the flip" reads *that* flip's result (CR 705.2: only the player who flipped
wins or loses it). The engine models that as an instruction that records its
result in the resolution's scratchpad and ordinary ``if_then`` conditions that
read the record — which is what these check, because the alternative reading
(each conditional flipping its own coin) is invisible in every test that forces
the RNG to one constant.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CATALOG = {c.name: c for c in load_catalog()}


def _bottle_game():
    bottle = Permanent(card=_CATALOG["Bottle of Suleiman"])
    bottle.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="A")
    p1.battlefield.append(bottle)
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    return game, p1


@pytest.mark.cr("705.1")
def test_one_printed_flip_draws_from_the_rng_once():
    """"{1}, Sacrifice this artifact: Flip a coin. If you win the flip, … If you
    lose the flip, …" — one flip, two sentences reading it."""
    game, _p1 = _bottle_game()

    with patch("engine.handlers._common.random.random", return_value=0.0) as flip:
        game.queue_permanent_ability(0, "Bottle of Suleiman", permanent_index=0)
        game._settle()

    assert flip.call_count == 1


@pytest.mark.cr("705.2")
def test_both_branches_read_the_same_flip():
    """The test the constant-RNG ones cannot do. The RNG is rigged to *win then
    lose*: with one flip the Djinn arrives and nobody is damaged, and with two
    the card would both win and lose its own flip."""
    game, p1 = _bottle_game()

    with patch(
        "engine.handlers._common.random.random", side_effect=[0.0, 0.99, 0.99, 0.99]
    ):
        game.queue_permanent_ability(0, "Bottle of Suleiman", permanent_index=0)
        game._settle()

    assert [p.card.name for p in p1.battlefield if p.metadata.get("is_token")] == [
        "Djinn Token"
    ]
    assert p1.life == 20, "the losing branch belongs to a flip that was won"


@pytest.mark.cr("705.2")
def test_the_losing_branch_damages_the_flipper():
    """"this artifact deals 5 damage to **you**" — the player who flipped, which
    is the ability's controller and not an opponent."""
    game, p1 = _bottle_game()

    with patch("engine.handlers._common.random.random", return_value=0.99):
        game.queue_permanent_ability(0, "Bottle of Suleiman", permanent_index=0)
        game._settle()

    assert p1.life == 15
    assert game.players[1].life == 20
    assert not any(p.metadata.get("is_token") for p in p1.battlefield)
