"""A resolving spell's "don't untap" over a targeted player's permanents is a
lock on that player's step (CR 611.2c, CR 502.3).

"Creatures target player controls don't untap during that player's next
untap step." (Misstep.) "Creatures and lands target opponent controls don't
untap during their next untap step." (Exhaustion.) "Lands target player
controls don't untap during their next untap step." (Mana Vapors.)

The effect modifies no characteristic and changes no controller, so by
CR 611.2c it "modifies the rules of the game, so it can affect objects that
weren't affected when that continuous effect began" — and each card's ruling
says so of that card (Misstep 2008-08-01, Mana Vapors 2008-08-01, Exhaustion
2009-10-01: "This includes creatures which entered the battlefield after
Misstep resolved."). The three were markers on the permanents present at
resolution, so one cast afterwards untapped on schedule; they are now the
record Blinding Beam's lock is (``engine/untap_step_locks.py``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import resolve_stack


def _table(set_pool, spell_set: str, spell: str, *, seats: int = 2):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[lea["Island"]] * 10)
        for seat in range(seats)
    ])
    game.players[0].hand.append(set_pool(spell_set)[spell])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _put(game, seat: int, card, *, tapped: bool = True) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = tapped
    return permanent


def _untap_step(game, seat: int) -> None:
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)


@pytest.mark.cr("611.2c", "502.3")
def test_misstep_holds_down_a_creature_that_arrived_after_it_resolved(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, "MMQ", "Misstep")
    present = _put(game, 1, lea["Grizzly Bears"])
    mine = _put(game, 0, lea["Hill Giant"])

    assert game.cast_from_hand(0, "Misstep", target_player_index=1).supported
    resolve_stack(game)
    arrived = _put(game, 1, lea["Craw Wurm"])
    land = _put(game, 1, lea["Forest"])

    _untap_step(game, 1)
    assert present.tapped and arrived.tapped, game.log
    # Only creatures: the target's land untaps.
    assert not land.tapped
    # The lock is the target's step's: the next one untaps them.
    _untap_step(game, 1)
    assert not present.tapped and not arrived.tapped
    # …and it never named the caster's step.
    _untap_step(game, 0)
    assert not mine.tapped


@pytest.mark.cr("611.2c", "502.3")
def test_exhaustion_holds_both_types_and_announces_only_an_opponent(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, "USG", "Exhaustion")
    exhaustion = game.players[0].hand[0]
    spec = derive_cast_spec(exhaustion, compile_card_oracle(exhaustion))
    assert spec == {"kind": "player", "opponents_only": True}, spec

    mine = _put(game, 0, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Exhaustion", target_player_index=1).supported
    resolve_stack(game)
    creature = _put(game, 1, lea["Grizzly Bears"])
    land = _put(game, 1, lea["Forest"])

    _untap_step(game, 1)
    assert creature.tapped and land.tapped, game.log
    _untap_step(game, 0)
    assert not mine.tapped
    _untap_step(game, 1)
    assert not creature.tapped and not land.tapped


@pytest.mark.cr("611.2c", "502.3")
def test_mana_vapors_holds_a_land_played_after_it_resolved(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, "PCY", "Mana Vapors")
    assert game.cast_from_hand(0, "Mana Vapors", target_player_index=1).supported
    resolve_stack(game)
    played = _put(game, 1, lea["Forest"])
    creature = _put(game, 1, lea["Grizzly Bears"])

    _untap_step(game, 1)
    assert played.tapped, game.log
    assert not creature.tapped, "only lands"


@pytest.mark.cr("611.2c", "502.3")
def test_misstep_does_not_hold_another_players_creature_untapping_in_that_step(set_pool):
    """"Creatures **target player controls**": a Seedborn Muse's controller
    untaps in the target's step (the Muse's own ruling), and the lock names
    the target's creatures, not that step's every untap — Blinding Beam's
    "Creatures don't untap during target player's next untap step" is the
    printing that does."""
    lea = set_pool("LEA")
    game = _table(set_pool, "MMQ", "Misstep")
    _put(game, 0, set_pool("LGN")["Seedborn Muse"], tapped=False)
    mine = _put(game, 0, lea["Hill Giant"])
    theirs = _put(game, 1, lea["Grizzly Bears"])

    assert game.cast_from_hand(0, "Misstep", target_player_index=1).supported
    resolve_stack(game)

    _untap_step(game, 1)
    assert theirs.tapped, game.log
    assert not mine.tapped, game.log
