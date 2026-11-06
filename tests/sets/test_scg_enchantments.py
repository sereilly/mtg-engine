"""Scourge enchantments, Auras included.

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
#
# Fatal Mutation: "When enchanted creature is turned face up, destroy it. It
# can't be regenerated." CR 708.8 lets a face-down creature be enchanted, and
# the Aura stays on as its host turns; the trigger is the host's turn, watched
# from the Aura (``event_filters._turned_face_up_filter``'s ``turned_attached``).

from engine import Game as _W1G5EGame, PlayerState as _W1G5EPlayerState
from engine.card_loader import load_catalog as _w1g5e_load_catalog
from engine.face_down import (face_down_card as _w1g5e_face_down_card,
                              turn_face_up as _w1g5e_turn_face_up)
from engine.models import Permanent as _W1G5EPermanent
from engine.special_actions import take_permanent_special_action as _w1g5e_take
from tests.helpers import resolve_stack as _w1g5e_resolve_stack

_W1G5E_CATALOG = {card.name: card for card in _w1g5e_load_catalog()}


def _w1g5e_permanent(card, *, face_down=False):
    permanent = _W1G5EPermanent(
        card=_w1g5e_face_down_card(card) if face_down else card,
    )
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5e_mutated(set_pool, host_name="Woodcloaker", *, extra_mine=()):
    """A's face-down *host_name* with four Forests; B enchants it with Fatal
    Mutation, cast through the engine (B holds a Swamp's {B} in its pool)."""
    scg = set_pool("SCG")
    host = _w1g5e_permanent(scg[host_name], face_down=True)
    forests = [_w1g5e_permanent(_W1G5E_CATALOG["Forest"]) for _ in range(4)]
    p1 = _W1G5EPlayerState(name="A", battlefield=[host, *forests, *extra_mine],
                           library=[_W1G5E_CATALOG["Island"]] * 10)
    p2 = _W1G5EPlayerState(name="B", hand=[scg["Fatal Mutation"]],
                           library=[_W1G5E_CATALOG["Island"]] * 10)
    game = _W1G5EGame(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(1)
    p2.mana_pool["B"] = 1
    cast = game.queue_from_hand(1, "Fatal Mutation", target_player_index=0,
                                target_permanent_ids=[host.permanent_id])
    assert cast.supported, cast.details
    _w1g5e_resolve_stack(game)
    aura = next(p for p in game.controlled_by(1) if p.card.name == "Fatal Mutation")
    assert aura.metadata.get("attached_to") is host
    game.active_player_index = 0
    game.start_priority_window(0)
    return game, host, aura


def test_w1g5_fatal_mutation_destroys_its_host_as_it_turns_up_unregenerated(set_pool):
    game, host, aura = _w1g5e_mutated(set_pool)
    host.regeneration_shield = 1
    assert _w1g5e_take(game, 0, host, "turn_face_up") is None
    # APNAP (CR 603.3b): B's Mutation above A's own Woodcloaker trigger.
    assert [item.card.name for item in game.stack] == ["Woodcloaker", "Fatal Mutation"]
    _w1g5e_resolve_stack(game)
    game.check_state_based_actions()
    a, b = game.players
    assert [card.name for card in a.graveyard] == ["Woodcloaker"]
    assert [card.name for card in b.graveyard] == ["Fatal Mutation"]
    assert "Fatal Mutation destroyed Woodcloaker" in game.log


def test_w1g5_fatal_mutation_answers_an_effect_turning_its_host_up(set_pool):
    """Any road up is the event (CR 708.7): an effect's turn (Ixidor's
    reading) sets it off as the special action does."""
    game, host, _aura = _w1g5e_mutated(set_pool, "Titanic Bulvox")
    assert _w1g5e_turn_face_up(game, host, how="an effect")
    assert [item.card.name for item in game.stack] == ["Fatal Mutation"]
    _w1g5e_resolve_stack(game)
    assert "Titanic Bulvox" in [card.name for card in game.players[0].graveyard]


def test_w1g5_fatal_mutation_ignores_another_permanent_turning_up(set_pool):
    """The Aura watches its own host, by identity — another face-down creature
    turned up beside it sets nothing off."""
    other = _w1g5e_permanent(set_pool("SCG")["Scornful Egotist"], face_down=True)
    game, host, _aura = _w1g5e_mutated(set_pool, extra_mine=(other,))
    assert _w1g5e_turn_face_up(game, other, how="an effect")
    assert game.stack == []
    assert any(p is host for p in game.controlled_by(0))

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

# ==== end W1G9 ======================================================
