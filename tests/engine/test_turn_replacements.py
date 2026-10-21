"""The record a resolving spell's turn-long replacement leaves
(``engine/turn_replacements.py``): Blind Fury, Equal Treatment, Plagiarize.

Blind Fury's doubling was a dedicated ``Game`` list with a clearing line of its
own in the cleanup step; it is a record on its caster's seat now, beside the
two Torment cards, and one sweep ends all three. These pin that arrangement:
what each card arms, that each arming is its own effect (CR 614.5's key), and
that the cleanup sweep is the whole of "this turn".
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.turn_replacements import (DAMAGE, DRAW, armed_turn_replacements,
                                      turn_replacements_on)
from tests.helpers import resolve_stack


def _cast(set_pool, code: str, name: str, **announce) -> Game:
    game = Game(players=[
        PlayerState(name="P0", hand=[set_pool(code)[name]] * 2,
                    library=[set_pool("LEA")["Forest"]] * 4),
        PlayerState(name="P1", library=[set_pool("LEA")["Island"]] * 4),
    ])
    game.enforce_mana_costs = False
    for _ in range(2):
        assert game.cast_from_hand(0, name, **announce).supported
        resolve_stack(game)
    return game


def test_blind_fury_arms_a_record_with_its_every_narrowing(set_pool):
    game = _cast(set_pool, "MIR", "Blind Fury")
    records = armed_turn_replacements(game, DAMAGE)
    assert len(records) == 2
    for record in records:
        assert (record.seat, record.multiplier, record.becomes) == (0, 2, None)
        assert record.combat_only and record.source_creature and record.recipient_creature
    assert len({record.key for record in records}) == 2
    assert not hasattr(game, "combat_damage_doubled_between_creatures")


def test_equal_treatment_and_plagiarize_arm_records_the_cleanup_sweep_ends(set_pool):
    game = _cast(set_pool, "TOR", "Equal Treatment")
    (first, second) = armed_turn_replacements(game, DAMAGE)
    assert (first.becomes, first.combat_only, first.source_creature) == (2, False, False)
    assert first.key != second.key

    plagiarized = _cast(set_pool, "TOR", "Plagiarize", target_player_index=1)
    records = armed_turn_replacements(plagiarized, DRAW)
    assert [(r.seat, r.affected_seat) for r in records] == [(0, 1), (0, 1)]

    for done in (game, plagiarized):
        done.resolve_cleanup_step(0)
        assert armed_turn_replacements(done, DAMAGE) == []
        assert armed_turn_replacements(done, DRAW) == []
        assert turn_replacements_on(done.players[0]) == []
