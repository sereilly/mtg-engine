"""A split damage sentence's CR 616.1 choices are made in APNAP order.

CR 616.1: "If two or more players have to make these choices at the same time,
choices are made in APNAP order (see rule 101.4)." kg3/dealings made one
printed damage sentence the lowering splits into steps ("Orcish Artillery
deals 2 damage to any target and 3 damage to you") one simultaneous dealing
(``oracle_types.ONE_DEALING``) — and left its steps dealt, and so asked, in
printed order: the target's controller before the active player.

``handlers/control_flow.sequence`` now deals a marked sequence's steps in
APNAP order of the player each one affects, where every step names exactly one
recipient it can say before it runs (the chosen target, "you", "itself",
"target player"); a step dealing to several (a sweep, "each player") keeps
the printed order for the whole sentence. Within one seat the printed order
stands (CR 101.4c).

Measured backwards on 90bef6d1: P1 was asked first.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.shields import add_shield, make_counting_pool, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(*, interactive=()) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _artillery(game: Game) -> Permanent:
    artillery = Permanent(card=_POOL["Orcish Artillery"])
    game._put_permanent_onto_battlefield(0, artillery, None)
    artillery.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    for seat in (0, 1):
        # Two prevention effects on each player: each damage event asks its
        # affected player which applies first (CR 616.1e).
        add_shield(game.players[seat], make_numeric_pool(1, source_name="Test Pool A"))
        add_shield(game.players[seat], make_counting_pool(1, "+1/+1", source_name="Test Pool B"))
    return artillery


def _asked(game: Game) -> list[int]:
    return [choice.player_index for choice in game.pending_choices if choice.kind == "effect_order"]


@pytest.mark.cr("616.1", "101.4", "608.2f")
def test_the_active_player_chooses_first():
    game = _table(interactive=(0, 1))
    _artillery(game)

    result = game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1)
    assert result.supported, result.details
    for _ in range(4):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack(pause_for_choices=True)

    assert _asked(game) == [0], game.log[-6:]
    assert game.resolve_pending_choice("effect_order", 0, option_index=0)
    assert _asked(game) == [1], game.log[-6:]
    assert game.resolve_pending_choice("effect_order", 1, option_index=0)
    resolve_stack(game)

    # 3 to P0 and 2 to P1, each less the 2 its two pools prevent between them
    # (the second applies once the first has, CR 616.1f).
    assert (game.players[0].life, game.players[1].life) == (19, 20), game.log[-8:]
    assert game.simultaneous_damage is None


@pytest.mark.cr("616.1", "101.4")
def test_on_the_other_seat_s_turn_the_target_chooses_first():
    """Activated on P1's turn: P1 is the active player, and the printed order
    is already APNAP."""
    game = _table(interactive=(0, 1))
    _artillery(game)
    game.active_player_index = 1

    result = game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1)
    assert result.supported, result.details
    for _ in range(4):
        if game.pending_choices or not game.stack:
            break
        game.resolve_top_of_stack(pause_for_choices=True)

    assert _asked(game) == [1], game.log[-6:]


@pytest.mark.cr("608.2f")
def test_nobody_asked_the_totals_are_the_printed_ones():
    game = _table()
    artillery = Permanent(card=_POOL["Orcish Artillery"])
    game._put_permanent_onto_battlefield(0, artillery, None)
    artillery.metadata["summoning_sickness_turn"] = -99
    game._sync_control()

    assert game.activate_permanent_ability(0, "Orcish Artillery", target_player_index=1).supported
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (17, 18)
