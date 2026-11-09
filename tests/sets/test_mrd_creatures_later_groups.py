"""Mirrodin creatures, the later groups' sections (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_peacekeeper(set_pool, lives, *, interactive=()):
    """Loxodon Peacekeeper on seat 0, the seats at *lives*."""
    keeper = _w1g9_Permanent(card=set_pool("MRD")["Loxodon Peacekeeper"])
    players = [
        _w1g9_PlayerState(name=f"P{seat}", battlefield=[keeper] if seat == 0 else [])
        for seat in range(len(lives))
    ]
    for player, life in zip(players, lives):
        player.life = life
    game = _w1g9_Game(players=players)
    game.interactive_seats = set(interactive)
    return game, keeper


def test_w1g9_loxodon_peacekeeper_goes_to_the_lowest_life_total(set_pool):
    """"At the beginning of your upkeep, the player with the lowest life total
    gains control of this creature." Read off the life totals as it resolves:
    at three seats the one lowest takes it, and on its new controller's upkeep
    it moves on when somebody else is lower."""
    game, keeper = _w1g9_peacekeeper(set_pool, [20, 12, 15])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 1
    assert "P1 gains control of Loxodon Peacekeeper" in game.log

    game.players[2].life = 3
    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 2


def test_w1g9_loxodon_peacekeeper_stays_with_a_controller_who_is_lowest(set_pool):
    game, keeper = _w1g9_peacekeeper(set_pool, [7, 20])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 0
    assert "Loxodon Peacekeeper is already controlled by P0" in game.log


def test_w1g9_loxodon_peacekeeper_tie_is_its_controllers_choice(set_pool):
    """"If two or more players are tied for lowest life total, you choose one
    of them, and that player gains control of this creature." An interactive
    controller is offered exactly the tied seats — not the player at 20 — and
    names one; nothing changes hands until the answer."""
    game, keeper = _w1g9_peacekeeper(set_pool, [10, 10, 20], interactive=(0,))
    game.resolve_upkeep(0)
    assert game.resolve_top_of_stack() is False
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("player_choice", 0)
    ]
    assert game.pending_choices[0].data["seats"] == [0, 1]
    assert game.controller_index_of(keeper) == 0
    assert game.confirm_player_choice(0, 2) is False   # not tied
    assert game.confirm_player_choice(0, 1) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 1


def test_w1g9_loxodon_peacekeeper_tie_default_keeps_it(set_pool):
    """A controller nobody asks names itself among the tied seats
    (``ai_prompt_picks.player_choice_pick``): the other answer gives the
    creature away."""
    game, keeper = _w1g9_peacekeeper(set_pool, [10, 10])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(keeper) == 0
    assert "Loxodon Peacekeeper: chose P0" in game.log

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _w1g10_Game, PlayerState as _w1g10_PlayerState
from engine.models import Permanent as _w1g10_Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_fatespinner_upkeep(set_pool, *, interactive=False):
    """P1 controls Fatespinner; P2's turn begins and its upkeep trigger is put
    on the stack (and, for a person, resolved to its question)."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20),
        _w1g10_PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {1}
    spinner = _w1g10_Permanent(card=set_pool("MRD")["Fatespinner"])
    game._put_permanent_onto_battlefield(0, spinner, None)
    game.active_player_index = 0
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.resolve_untap_step(1)
    game.resolve_upkeep(1)
    return game


def _w1g10_answer(game, mode_index):
    game.resolve_top_of_stack()          # held on the opponent's question
    prompt = game.pending_choice_of("mode_choice", 1)
    assert prompt is not None
    assert prompt.data["labels"] == ["draw step", "main phase", "combat phase"]
    assert game.resolve_pending_choice("mode_choice", 1, mode_index=mode_index)
    _w1g10_resolve_stack(game)


def test_w1g10_fatespinner_unasked_opponent_skips_the_draw_step(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool)
    _w1g10_resolve_stack(game)
    game.resolve_draw_step(1)
    assert game.players[1].hand == []
    assert "P2 skipped draw step" in game.log
    assert game.enter_next_turn_phase("beginning") == "precombat_main"


def test_w1g10_fatespinner_main_phase_skips_both_main_phases(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 1)
    game.resolve_draw_step(1)
    assert len(game.players[1].hand) == 1      # the draw step was not chosen
    # Straight from the beginning phase into combat, and from combat to the
    # ending phase: "each instance" is both main phases.
    assert game.enter_next_turn_phase("beginning") == "combat"
    assert game.current_turn_phase == "combat"
    assert game.next_unskipped_phase_after("combat") == "ending"


def test_w1g10_fatespinner_combat_phase_is_skipped_on_every_road(set_pool):
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 2)
    game.resolve_draw_step(1)
    assert game.enter_next_turn_phase("beginning") == "precombat_main"
    # The AI's combat walker names combat from the main phase rather than
    # asking the plan; the skip is honoured there too (CR 500.11).
    game.advance_combat_phase()
    assert game.current_turn_phase == "postcombat_main"
    assert "P2 skipped the combat phase" in game.log


def test_w1g10_fatespinner_skips_a_combat_phase_added_after_it_resolved(set_pool):
    """The ruling (2004-12-01): "This is true even if a new step or phase is
    added to the turn after the ability resolves." An additional combat phase
    after the postcombat main phase (Relentless Assault's shape, CR 500.8) is
    skipped too."""
    game = _w1g10_fatespinner_upkeep(set_pool, interactive=True)
    _w1g10_answer(game, 2)
    game.resolve_draw_step(1)
    assert game.enter_next_turn_phase("beginning") == "precombat_main"
    assert game.enter_next_turn_phase() == "postcombat_main"
    assert game.add_extra_phase(after_phase="postcombat_main", phase_name="combat")
    assert game.next_unskipped_phase_after("postcombat_main") == "ending"


def test_w1g10_fatespinner_skip_ends_with_its_turn(set_pool):
    """"This turn": the cleanup sweep ends the record, so the opponent's next
    turn has its draw step."""
    game = _w1g10_fatespinner_upkeep(set_pool)
    _w1g10_resolve_stack(game)
    assert game.skip_step_counts
    game.expire_stamped_phase_skips()
    assert not game.skip_step_counts and not game.skip_phase_counts


def test_w1g10_fatespinner_does_not_trigger_on_its_controllers_upkeep(set_pool):
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20),
        _w1g10_PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    spinner = _w1g10_Permanent(card=set_pool("MRD")["Fatespinner"])
    game._put_permanent_onto_battlefield(0, spinner, None)
    game.resolve_upkeep(0)
    assert not game.stack

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
