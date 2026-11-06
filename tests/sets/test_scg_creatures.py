"""Scourge creatures (legendary ones too).

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

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.damage_redirects import redirects_on as _w1g7_redirects_on
from engine.face_down import (is_face_down as _w1g7_is_face_down,
                              morph_cost as _w1g7_morph_cost)
from engine.mana_payment import mana_cost_from_symbols as _w1g7_symbols
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.special_actions import (
    take_permanent_special_action as _w1g7_take_special_action)
from engine.targeting import derive_instruction_spec as _w1g7_instruction_spec
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_perm(card):
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_game(mine=(), theirs=(), *, hand=(), their_hand=()):
    me = _W1G7PlayerState(
        name="P0", battlefield=[_w1g7_perm(c) for c in mine], hand=list(hand), life=20,
    )
    them = _W1G7PlayerState(
        name="P1", battlefield=[_w1g7_perm(c) for c in theirs],
        hand=list(their_hand), life=20,
    )
    game = _W1G7Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game._recompute_continuous_effects()
    return game


def _w1g7_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Goblin Psychopath -------------------------------------------------------
#
# "Whenever this creature attacks or blocks, flip a coin. If you lose the flip,
# the next time it would deal combat damage this turn, it deals that damage to
# you instead." A CR 614.9 redirect of its own next combat damage to anyone,
# armed on resolution (ruling 2004-10-04: "resolves before combat damage is
# assigned"). The flip is the engine's (``handlers/_common.flip_coin``),
# fixed here through the module ``control_flow`` reads it from.


def _w1g7_flip(monkeypatch, won):
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda *a, **k: won
    )


def _w1g7_psychopath_attacks(set_pool, monkeypatch, *, won, blockers=(), blocks=None):
    _w1g7_flip(monkeypatch, won)
    game = _w1g7_game(mine=[set_pool("SCG")["Goblin Psychopath"]], theirs=list(blockers))
    _w1g7_declare_attack(game, 0, blocks=blocks or {})
    _w1g7_resolve_stack(game)
    return game


def test_w1g7_goblin_psychopath_losing_the_flip_hits_its_controller(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    assert any("lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 15 and game.players[1].life == 20
    assert any(
        "5 damage to P1 is dealt to P0 instead (Goblin Psychopath)" in line
        for line in game.log
    )


def test_w1g7_goblin_psychopath_winning_the_flip_deals_its_damage(set_pool, monkeypatch):
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=True)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 15


def test_w1g7_goblin_psychopath_one_time_covers_every_blocker(set_pool, monkeypatch):
    """"The next time" is one time (CR 510.2: combat damage is dealt at once):
    blocked by two, both blockers' shares go to its controller."""
    pool = set_pool("2ED")
    game = _w1g7_psychopath_attacks(
        set_pool, monkeypatch, won=False,
        blockers=(pool["Grizzly Bears"], pool["Hill Giant"]), blocks={0: 0, 1: 0},
    )
    game.advance_combat_phase()
    assert game.current_step == "combat_damage"
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: {0: 2, 1: 3}})
    assert ok, why
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == 15
    assert [c.name for c in game.players[1].graveyard] == []
    assert [c.name for c in game.players[0].graveyard] == ["Goblin Psychopath"]
    # The time is over once the step's dealing is (``end_simultaneous_redirects``).
    assert _w1g7_redirects_on(game.players[0]) == []


def test_w1g7_goblin_psychopath_blocking_and_losing_sends_its_damage_home(
    set_pool, monkeypatch
):
    _w1g7_flip(monkeypatch, False)
    giant = set_pool("2ED")["Hill Giant"]
    game = _w1g7_game(mine=[giant], theirs=[set_pool("SCG")["Goblin Psychopath"]])
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_resolve_stack(game)
    assert any("Goblin Psychopath: lost the coin flip" in line for line in game.log)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()
    # Its 5 went to its own controller; the Giant's 3 still landed on it.
    assert game.players[1].life == 15
    assert _w1g7_named(game, 0, "Hill Giant").damage_marked == 0
    assert _w1g7_named(game, 1, "Goblin Psychopath").damage_marked == 3


def test_w1g7_goblin_psychopath_gone_before_damage_hurts_nobody(set_pool, monkeypatch):
    """The ruling's point: the trigger resolves first, "This gives you a chance
    to possibly get rid of it before it hurts you." Removed from the battlefield
    after the flip, it deals no damage and the record moves none."""
    game = _w1g7_psychopath_attacks(set_pool, monkeypatch, won=False)
    psychopath = _w1g7_named(game, 0, "Goblin Psychopath")
    game.players[0].hand.append(set_pool("2ED")["Unsummon"])
    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[psychopath.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.advance_combat_phase()
    _w1g7_resolve_stack(game)
    assert game.players[0].life == 20 and game.players[1].life == 20


def test_w1g7_goblin_psychopath_compiles_its_whole_line(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Goblin Psychopath"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported
    steps = trigger.instruction.payload["steps"]
    assert [s.kind for s in steps] == ["flip_coin", "if_then"]
    (redirect,) = steps[1].payload["then"]
    assert redirect.payload == {"protects": "any", "combat_only": True, "uses": 1}
    # It targets nothing, so nothing is asked of the picker.
    assert _w1g7_instruction_spec([trigger.instruction]) is None


# --- Karona's Zealot ---------------------------------------------------------
#
# "When this creature is turned face up, all damage that would be dealt to it
# this turn is dealt to target creature instead." Rulings (2018-03-16): a target
# that has left or stopped being a creature takes nothing — later damage stays
# on the Zealot — and the damaged permanent's controller orders replacements.


def _w1g7_turn_up_zealot(set_pool, game, seat=0):
    zealot = set_pool("SCG")["Karona's Zealot"]
    player = game.players[seat]
    player.hand.append(zealot)
    game.enforce_mana_costs = True
    player.mana_pool.update({"C": 3})
    assert game.queue_from_hand(seat, "Karona's Zealot", alternative_cost=True).supported
    _w1g7_resolve_stack(game)
    (permanent,) = [p for p in game.controlled_by(seat) if _w1g7_is_face_down(p)]
    permanent.metadata["summoning_sickness_turn"] = -99
    for symbol, count in _w1g7_symbols(_w1g7_morph_cost(zealot)).items():
        key = "C" if symbol == "generic" else symbol
        player.mana_pool[key] = player.mana_pool.get(key, 0) + count
    game.priority_player_index = seat
    assert _w1g7_take_special_action(game, seat, permanent, "turn_face_up") is None
    assert sum(player.mana_pool.values()) == 0
    game.enforce_mana_costs = False
    return permanent


def _w1g7_bolt(set_pool, game, target, seat=1):
    game.players[seat].hand.append(set_pool("2ED")["Lightning Bolt"])
    assert game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[target.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)
    game.check_state_based_actions()


def test_w1g7_karonas_zealot_moves_all_its_damage_this_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"], pool["Wall of Stone"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    (trigger,) = [item for item in game.stack if item.card.name == "Karona's Zealot"]
    wall = _w1g7_named(game, 1, "Wall of Stone")
    # The trigger's target, named by id as an announcement names it.
    trigger.target_permanent_id = [wall.permanent_id]
    _w1g7_resolve_stack(game)
    assert any(
        "all damage that would be dealt to Karona's Zealot this turn is dealt to "
        "Wall of Stone instead" in line for line in game.log
    )
    # Every instance this turn, not the next one: two Bolts, both moved.
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 3
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0 and wall.damage_marked == 6


def test_w1g7_karonas_zealot_target_gone_leaves_the_damage_on_it(set_pool):
    """The ruling's example: the 1/1 took the first 3 and died; the next 3 has
    nowhere to go and is dealt to the Zealot (CR 614.9)."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Grizzly Bears"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 0
    assert "Grizzly Bears" in [c.name for c in game.players[1].graveyard]
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_redirect_ends_with_the_turn(set_pool):
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    assert _w1g7_redirects_on(zealot)
    game.resolve_cleanup_step(0)
    assert _w1g7_redirects_on(zealot) == []
    _w1g7_bolt(set_pool, game, zealot)
    assert zealot.damage_marked == 3


def test_w1g7_karonas_zealot_targets_a_creature(set_pool):
    program = _w1g7_compile(set_pool("SCG")["Karona's Zealot"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    assert trigger.supported and trigger.condition.kind == "turned_face_up"
    spec = _w1g7_instruction_spec([trigger.instruction])
    assert spec is not None and spec.get("kind") == "creature", spec


@_w1g7_pytest.mark.parametrize("asked", [False, True], ids=["default", "asked"])
def test_w1g7_karonas_zealot_beside_a_shield_its_controller_orders(set_pool, asked):
    """CR 616.1: a prevention shield on the Zealot and its redirect contend over
    one Bolt, and the Zealot's controller chooses (ruling 2018-03-16). A seat
    nobody asks moves the damage first (redirects sit ahead of the shields,
    ``replacements/registry.py``); one that is asked may spend the shield."""
    pool = set_pool("2ED")
    game = _w1g7_game(theirs=[pool["Hill Giant"]], hand=[pool["Healing Salve"]])
    zealot = _w1g7_turn_up_zealot(set_pool, game)
    _w1g7_resolve_stack(game)
    giant = _w1g7_named(game, 1, "Hill Giant")
    assert game.queue_from_hand(
        0, "Healing Salve", mode_index=1, target_permanent_ids=[zealot.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    if asked:
        game.interactive_seats = {0}
    game.players[1].hand.append(pool["Lightning Bolt"])
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[zealot.permanent_id]
    ).supported
    if not asked:
        _w1g7_resolve_stack(game)
        assert zealot.damage_marked == 0 and giant.damage_marked == 3
        return
    game.resolve_top_of_stack()
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert order.player_index == 0 and len(order.data["options"]) == 2
    keys = list(order.data["_keys"])
    shield_first = next(
        i for i, key in enumerate(keys) if key != "_apply_recorded_redirect"
    )
    assert "_apply_recorded_redirect" in keys
    assert game.resolve_pending_choice("effect_order", 0, option_index=shield_first)
    _w1g7_resolve_stack(game)
    assert zealot.damage_marked == 0 and giant.damage_marked == 0

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
