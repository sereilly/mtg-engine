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


# --- W2G2: the flipper is the ability's controller, not the other chooser ---

from engine.models import CardDefinition as _W2G2CardDefinition


def _w2g2_assassin_duel(set_pool):
    """Mogg Assassin on seat 0, a creature each side, both seats asked.

    The pool's first card whose coin flip decides between **two different
    players'** choices, which is why it is here: every other flip in the pool
    has one seat making every decision, so "you win the flip" and "the seat that
    chose" are the same player and CR 705.2's last sentence is unobservable.
    """
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    assassin = Permanent(card=set_pool("EXO")["Mogg Assassin"])
    game._put_permanent_onto_battlefield(0, assassin, None)
    assassin.metadata["summoning_sickness_turn"] = -99

    def bear(name):
        return _W2G2CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={}, power="2", toughness="2",
        )

    mine = Permanent(card=bear("Mine"))
    game._put_permanent_onto_battlefield(0, mine, None)
    theirs = Permanent(card=bear("Theirs"))
    game._put_permanent_onto_battlefield(1, theirs, None)
    game.log.clear()
    return game, mine, theirs


@pytest.mark.cr("705.2")
def test_only_the_ability_controller_wins_or_loses_the_flip(set_pool):
    """"Only the player who flips the coin wins or loses the flip; no other
    players are involved."

    Mogg Assassin's flip sits between two seats' picks — "You choose target
    creature an opponent controls, and that opponent chooses target creature.
    Flip a coin. If you win the flip, destroy the creature you chose. If you
    lose the flip, destroy the creature your opponent chose." Both branches
    belong to the *ability's controller's* flip, so a win destroys what they
    announced and a loss destroys what the other seat picked.

    Read the other way round the card plays exactly backwards and nothing
    fails: a creature dies on every activation either way, and only which one
    says whose flip it was.
    """
    game, mine, theirs = _w2g2_assassin_duel(set_pool)

    with patch("engine.handlers._common.random.random", return_value=0.0):
        game.activate_permanent_ability(
            0, "Mogg Assassin", target_permanent_ids=[theirs.permanent_id]
        )
        game.resolve_pending_choice(
            "permanent_choice", 1, permanent_id=mine.permanent_id
        )
        game._settle()

    alive = {p.card.name for p in game.all_permanents()}
    assert "Theirs" not in alive, "seat 0 won its own flip"
    assert "Mine" in alive


@pytest.mark.cr("705.2")
def test_losing_the_flip_takes_the_other_seats_pick(set_pool):
    """The other half of the same rule, and the half a constant-RNG test of the
    winning branch alone cannot distinguish from "destroy both"."""
    game, mine, theirs = _w2g2_assassin_duel(set_pool)

    with patch("engine.handlers._common.random.random", return_value=0.99):
        game.activate_permanent_ability(
            0, "Mogg Assassin", target_permanent_ids=[theirs.permanent_id]
        )
        game.resolve_pending_choice(
            "permanent_choice", 1, permanent_id=mine.permanent_id
        )
        game._settle()

    alive = {p.card.name for p in game.all_permanents()}
    assert "Mine" not in alive, "seat 0 lost its own flip"
    assert "Theirs" in alive
