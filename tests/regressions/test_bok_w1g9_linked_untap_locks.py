"""A linked untap lock adds to what its source holds; it never replaces it.

"Whenever Somnophore deals damage to a player, tap target creature that player
controls. That creature doesn't untap during its controller's untap step for
as long as Somnophore remains on the battlefield." Every resolution creates
its own continuous effect (CR 611.2a), and each lasts as long as the same
fact about the same source. The record on the source was *overwritten* by
each resolution (``handlers/tapping._restrict_untap_while_source``), so
Somnophore's second hit released its first victim at the next untap step —
the lock doing less than the card, in its controller's opponent's favour.
Found by Betrayers of Kamigawa's Neko-Te, whose wearer locks a creature every
time it damages one ("for as long as this Equipment remains on the
battlefield"); the per-set test is in ``tests/sets/test_bok_artifacts.py``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, settle


def _somnophore_hits(game, somno, victim) -> None:
    """Seat 0's Somnophore attacks seat 1 unblocked; its trigger, as it goes
    on the stack, is pointed at *victim* (by id, as the picker announces)."""
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    slot = [p.permanent_id for p in game.players[0].battlefield].index(somno.permanent_id)
    assert game.declare_attackers(0, [slot], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    game.advance_combat_phase(allow_damage_skip=False)
    assert [item.ability_kind for item in game.stack] == ["triggered"]
    item = game.stack[0]
    item.target = game.players[1]
    item.target_permanent_index = [
        [p.permanent_id for p in game.players[1].battlefield].index(victim.permanent_id)
    ]
    item.target_permanent_id = [victim.permanent_id]
    settle(game)


def test_somnophore_keeps_its_first_victim_after_a_second_hit(catalog_by_name):
    game = Game(players=[
        PlayerState("A", library=[catalog_by_name["Forest"]] * 12),
        PlayerState("B", library=[catalog_by_name["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    somno = Permanent(card=catalog_by_name["Somnophore"])
    game._put_permanent_onto_battlefield(0, somno, None)
    first = Permanent(card=catalog_by_name["Grizzly Bears"])
    second = Permanent(card=catalog_by_name["Hill Giant"])
    game._put_permanent_onto_battlefield(1, first, None)
    game._put_permanent_onto_battlefield(1, second, None)
    for permanent in (somno, first, second):
        _nosick(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)

    _somnophore_hits(game, somno, first)
    assert first.tapped and not second.tapped
    game.start_next_turn()
    settle(game)
    assert game.active_player_index == 1 and first.tapped

    game.start_next_turn()
    settle(game)
    _somnophore_hits(game, somno, second)
    assert second.tapped
    game.start_next_turn()
    settle(game)
    assert game.active_player_index == 1
    assert first.tapped, "the first lock outlives the second resolution"
    assert second.tapped

    game.remove_from_battlefield(somno)
    game.resolve_untap_step(1)
    assert not first.tapped and not second.tapped, "both end with their holder"
