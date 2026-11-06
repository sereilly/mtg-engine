"""Scourge artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.
#
# Proteus Machine: cast face down for {3}, turned face up for its {0} morph
# cost through the CR 116.2b special action, and its trigger's creature type
# chosen by a person and by a seat nobody asks — an indefinite change
# (CR 611.2a) that outlives the turn.

import pytest as _w1g9_pytest

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.card_loader import load_catalog as _w1g9_load_catalog
from engine.face_down import is_face_down as _w1g9_is_face_down
from engine.models import Permanent as _W1G9Permanent
from engine.special_actions import (
    take_permanent_special_action as _w1g9_take_special_action)
from tests.helpers import resolve_stack as _w1g9_resolve_stack

_W1G9_CATALOG = {card.name: card for card in _w1g9_load_catalog()}


def _w1g9_proteus_up(set_pool, *, interactive, board=()):
    """A game with *board* on seat 0, Proteus Machine cast face down and then
    turned face up; returns the game and the Machine with its trigger on the
    stack."""
    machine_card = set_pool("SCG")["Proteus Machine"]
    battlefield = []
    for card in board:
        permanent = _W1G9Permanent(card=card)
        permanent.metadata["summoning_sickness_turn"] = -99
        battlefield.append(permanent)
    p1 = _W1G9PlayerState(name="A", hand=[machine_card], battlefield=battlefield,
                          library=[_W1G9_CATALOG["Island"]] * 10)
    p2 = _W1G9PlayerState(name="B", library=[_W1G9_CATALOG["Island"]] * 10)
    game = _W1G9Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    p1.mana_pool.update({"C": 3})
    result = game.queue_from_hand(0, "Proteus Machine", alternative_cost=True)
    assert result.supported, result.details
    _w1g9_resolve_stack(game)
    (machine,) = [p for p in game.controlled_by(0) if _w1g9_is_face_down(p)]
    machine.metadata["summoning_sickness_turn"] = -99
    assert not machine.has_type("shapeshifter"), "a face-down 2/2 has no type (CR 708.2)"
    game.priority_player_index = 0
    assert _w1g9_take_special_action(game, 0, machine, "turn_face_up") is None
    assert machine.card is machine_card and machine.has_type("shapeshifter")
    assert [item.card.name for item in game.stack] == ["Proteus Machine"]
    return game, machine


def test_w1g9_proteus_machine_becomes_the_type_a_person_names_for_good(set_pool):
    """"When this creature is turned face up, it becomes the creature type of
    your choice. (This effect lasts indefinitely.)" Named Goblin, it is a
    Goblin and no longer a Shapeshifter (CR 205.1a) — still an artifact — and
    stays one through the cleanup step and the next turn (CR 611.2a)."""
    game, machine = _w1g9_proteus_up(set_pool, interactive=True)
    game.resolve_top_of_stack(pause_for_choices=True)
    (choice,) = game.pending_choices_of("creature_type_choice", 0)
    assert game.resolve_pending_choice("creature_type_choice", 0, creature_type="goblin")
    _w1g9_resolve_stack(game)
    assert machine.has_type("goblin") and not machine.has_type("shapeshifter")
    assert machine.has_type("artifact") and machine.is_creature
    game.resolve_cleanup_step(0)
    game.turn += 1
    game.start_turn(1)
    assert machine.has_type("goblin") and not machine.has_type("shapeshifter")
    assert any("Proteus Machine became a Goblin (Proteus Machine)" in line for line in game.log)


def test_w1g9_proteus_machine_left_to_itself_joins_its_controllers_tribe(set_pool):
    """A seat nobody asks names the commonest creature type among its other
    creatures (``ai_prompt_readers``' "join"): beside two Bears, Bear."""
    bears = _W1G9_CATALOG["Grizzly Bears"]
    game, machine = _w1g9_proteus_up(set_pool, interactive=False, board=(bears, bears))
    _w1g9_resolve_stack(game)
    assert machine.has_type("bear") and not machine.has_type("shapeshifter")

# ==== end W1G9 ======================================================
