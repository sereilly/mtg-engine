"""Per-card tests for The Dark's instants.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


# --- G1: damage family (The Dark) ---


def _brimstone(set_pool, seats: int = 2):
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [set_pool("DRK")["Fire and Brimstone"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def _offered_seats(game, card):
    spec = derive_cast_spec(card, compile_card_oracle(card))
    return sorted(
        entry["seat"] for entry in game._enumerate_targets(0, card, spec, for_cast=True)
    )


def test_fire_and_brimstone_offers_nobody_when_nobody_attacked(set_pool):
    """"target player **who attacked this turn**". A restriction nothing
    enforces is not a narrower card, it is a card that hits any seat at all —
    and the picker is what enforces it."""
    game, players = _brimstone(set_pool)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == []


def test_fire_and_brimstone_offers_the_seat_that_declared_an_attacker(set_pool):
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [1]


def test_fire_and_brimstone_may_be_aimed_at_its_own_caster(set_pool):
    """"target **player**", not "target opponent": the caster is a legal answer
    when they are the one who attacked."""
    game, players = _brimstone(set_pool)
    players[0].attacked_this_turn = True

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [0]


def test_fire_and_brimstone_burns_its_caster_too(set_pool):
    """"4 damage to target player who attacked this turn **and 4 damage to
    you**" — one sentence, two clauses, and the second is not optional."""
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    result = game.cast_from_hand(0, "Fire and Brimstone", target_player_index=1)

    assert result.supported, result.details
    assert players[1].life == 16, game.log
    assert players[0].life == 16, game.log


def test_the_attacked_record_is_on_the_seat_not_on_its_creatures(set_pool):
    """A player who attacked and then lost the attacker still attacked this
    turn. Read off the board — the record every creature carries — the seat
    would stop being a legal target the moment its attacker died."""
    game, players = _brimstone(set_pool)
    attacker = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    attacker.summoning_sick = False
    players[1].battlefield = [attacker]
    game._sync_control()
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(1, [0])
    assert ok, msg
    game.remove_from_battlefield(attacker)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == [1]


def test_the_attacked_record_is_cleared_when_the_next_turn_begins(set_pool):
    """"this turn" is the turn, and the record resets with every other per-turn
    history — otherwise the card reads "who has ever attacked"."""
    game, players = _brimstone(set_pool)
    players[1].attacked_this_turn = True

    game.begin_turn_bookkeeping(1)

    assert _offered_seats(game, set_pool("DRK")["Fire and Brimstone"]) == []
