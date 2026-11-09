"""An untap-step lock is a lasting change to the rehearsal only where it binds
something (``ai_rehearsal._untap_lock_entries``).

Misstep, Exhaustion and Mana Vapors became locks on the targeted player's
step in MRD W2G4 (CR 611.2c). The per-permanent marker they replaced changed
nothing on a board with no creature, so the rehearsal read such a cast as
doing nothing and the AI kept the card; the lock is a record on the game, and
read whole by ``position_digest`` it made every cast a lasting change — the
seeded MMQ game in ``sim_fingerprint`` cast Misstep at a creatureless board.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_rehearsal import position_digest
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, theirs=()):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="P0", library=[lea["Island"]] * 5,
                    hand=[set_pool("MMQ")["Misstep"]]),
        PlayerState(name="P1", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for name in theirs:
        game._put_permanent_onto_battlefield(1, Permanent(card=lea[name]), None)
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _game_fields_after_misstep(game):
    before = position_digest(game)["game"]["untap_step_locks"]
    assert game.cast_from_hand(0, "Misstep", target_player_index=1).supported
    resolve_stack(game)
    assert [lock.seat for lock in game.untap_step_locks] == [1]
    return before, position_digest(game)["game"]["untap_step_locks"]


def test_a_lock_over_no_creature_digests_as_no_lock(set_pool):
    before, after = _game_fields_after_misstep(_table(set_pool, theirs=["Forest"]))
    assert before == after == "[]"


def test_a_lock_over_a_creature_is_a_change(set_pool):
    before, after = _game_fields_after_misstep(_table(set_pool, theirs=["Grizzly Bears"]))
    assert before == "[]" and after != before
