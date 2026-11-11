"""A resolution's count spec is read by a resolution's reader.

Three readers, in layers (``engine/handlers/_amounts.py``):
``evaluate_count`` counts a zone for a named owner and is also the CR 604.3
recompute's reader, so it holds no resolution; ``count_from_payload`` answers
the keys only a resolution can (``back_reference``, ``trigger_record``, the
cost records, the owner scopes) and hands the rest down; and
``per_recipient_amount`` answers one seat's share of a per-seat spec
(``seat_record``, ``resolution_record``, ``seat_tally_of``) before it counts.

The sacrifice handler (both its shared count and its per-seat one) and the
each-player discard called the bottom layer directly, so a key only a
resolution answers was read as a scan of a whole board — W1G5's first Lich's
Tomb lowering sacrificed every permanent that way. No shipped card's payload
carries such a key on those channels today (a census of both manifest roles:
5 channels, 15 specs, none), so these drive hand-built instructions through
the real dispatch point (``Game._execute_oracle_instruction``) with the
record a step before them would have left.
"""

from engine import Game, PlayerState
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import OracleInstruction
from tests.helpers import settle


def _table(set_pool):
    island = set_pool("LEA")["Island"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[island] * 20, hand=[island] * 3)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    for seat in range(2):
        for _ in range(3):
            permanent = Permanent(card=bears)
            game._put_permanent_onto_battlefield(seat, permanent, None)
    settle(game)
    return game


def _run(game, set_pool, payload, kind, results):
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1],
        card=set_pool("LEA")["Pestilence"], results=dict(results),
    )
    game._execute_oracle_instruction(OracleInstruction(kind, "", payload), context)
    settle(game)


def _bears(game, seat):
    return sum(
        1 for permanent in game.controlled_by(seat)
        if permanent.card.name == "Grizzly Bears"
    )


def test_a_shared_sacrifice_count_reads_the_resolutions_record(set_pool):
    """Urborg Justice's payload shape with the number an earlier step
    recorded: the opponent sacrifices that many (one), not one for every
    permanent its caster controls (three)."""
    game = _table(set_pool)
    _run(game, set_pool, {
        "filter": {"type_filter": "creature"}, "count": "x",
        "x_from_count": {"back_reference": "w2g3_number"},
        "who": "target_opponent",
    }, "sacrifice_matching_permanent", {"w2g3_number": 1})
    assert (_bears(game, 0), _bears(game, 1)) == (3, 2)


def test_a_per_seat_sacrifice_count_reads_each_seats_record(set_pool):
    """Omen of Fire's per-seat channel with a record per seat: seat 1 owes
    two, seat 0 owes none — not three each off their boards."""
    game = _table(set_pool)
    _run(game, set_pool, {
        "filter": {"type_filter": "creature"},
        "x_from_count_per_recipient": {"seat_record": "w2g3_owed"},
        "who": "each_player",
    }, "sacrifice_matching_permanent", {"w2g3_owed": {1: 2}})
    assert (_bears(game, 0), _bears(game, 1)) == (3, 1)


def test_a_per_seat_discard_count_reads_each_seats_record(set_pool):
    """Pox's discard channel with a record per seat: seat 1 discards the one
    it owes and seat 0 none — not a hand each, counted off their boards."""
    game = _table(set_pool)
    _run(game, set_pool, {
        "x_from_count_per_recipient": {"seat_record": "w2g3_owed"},
    }, "each_player_discards_a_card", {"w2g3_owed": {1: 1}})
    assert [len(player.hand) for player in game.players] == [3, 2]
