"""Damage dealt outside the handlers is a whole damage event: "whenever this
creature is dealt damage" sees it.

``Game._mark_damage_on_permanent`` is half of a creature's damage event — the
marking; the other half is ``_fire_dealt_damage_triggers`` (CR 603.2), which
``handlers._common.apply_damage_to_creature`` and the combat step's own
``then`` add. Three callers outside the handlers called the bare half: Cyclone's
sweep, Earthbind's entry, and every CR 614.9 redirect handing damage to a
creature (Veteran Bodyguard, Martyrs of Korlis, Pariah, Shimian Night Stalker,
Daughter of Autumn …). A Fungusaur dealt damage by any of them grew nothing.
Round kg3 routed all three through whole events while making them ask CR
616.1e's question.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _game(active: int = 0) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(2)
    ])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(active)
    game.resolve_untap_step(active)
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _fungusaur_triggered(game: Game) -> bool:
    return any(
        item.card is not None and item.card.name == "Fungusaur" for item in game.stack
    )


def test_cyclones_sweep_wakes_a_fungusaur():
    game = _game(active=1)
    cyclone = _put(game, 1, "Cyclone")
    _put(game, 1, "Forest")
    fungusaur = _put(game, 0, "Fungusaur")
    game.resolve_upkeep(1, human_choices={cyclone.permanent_id: True}, defer_priority=True)
    assert fungusaur.damage_marked == 1
    assert _fungusaur_triggered(game)


def test_damage_pariah_moves_onto_a_fungusaur_wakes_it():
    game = _game()
    fungusaur = _put(game, 0, "Fungusaur")
    pariah = _put(game, 0, "Pariah")
    attach_aura(pariah, fungusaur)
    sorcerer = _put(game, 1, "Prodigal Sorcerer")
    ping = next(
        a.instruction for a in compile_card_oracle(_POOL["Prodigal Sorcerer"]).activated_abilities
        if a.instruction is not None and a.instruction.kind == "deal_damage"
    )
    game._execute_oracle_instruction(ping, OracleExecutionContext(
        card=_POOL["Prodigal Sorcerer"], caster=game.players[1],
        target=game.players[0], source_permanent=sorcerer,
    ))
    assert game.players[0].life == 20
    assert fungusaur.damage_marked == 1
    assert _fungusaur_triggered(game)
