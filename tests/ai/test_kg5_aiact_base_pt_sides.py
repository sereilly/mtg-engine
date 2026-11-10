"""A base P/T rewrite to a small printed number is aimed at an opponent (kg5 aiact).

"{T}: Until end of turn, target creature has base power 1 or base toughness
1." (Vhati il-Dal.) The rewrite (``set_base_pt_target_until_eot``, CR 613.4b)
carries no ``targets`` payload and its category is ``pump``, so the side
readers (``ai_target_sides.instruction_target_side`` / ``ability_target_side``)
read every one as "you": Sorceress Queen ("…has base power and toughness
0/2"), Singing Tree and Island of Wak-Wak ("…has base power 0") were aimed at
the AI's own creature, and Vhati's two modes — a ``choose_one`` whose steps
named no target — had no side at all, so the chooser took the biggest
creature on either board: usually its controller's.

A rewrite is now read by its printed numbers against a 2/2
(``ai_target_sides._base_pt_set_sign``, ``BASE_PT_REFERENCE``), a
``choose_one`` of rewrites by its modes, and the rewrite's own printed seat
("target creature you control", Chariot of the Sun; "…you cast this turn",
Cycle of Life) still wins.

Validated backwards: on the base, Vhati il-Dal shrinks its controller's Craw
Wurm, and the census finds Sorceress Queen, Singing Tree, Island of Wak-Wak
and Vhati il-Dal read as "you" or as no side.
"""

from __future__ import annotations

from unittest import mock

from engine import ai_abilities
from engine.ai_abilities import choose_activation_action
from engine.ai_activation_targets import _activation_target_side
from engine.ai_simulator import SimulationReport, _play_activations
from engine.ai_target_sides import _BASE_PT_SET_KINDS, _side_steps
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import stock_libraries


def _board(mine=(), theirs=()):
    """The AI's precombat main phase, costs enforced, nothing summoning sick."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    stock_libraries(game)
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    for seat, group in ((0, mine), (1, theirs)):
        for card in group:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _named(game, seat, name):
    return next(p for p in game.players[seat].battlefield if p.card.name == name)


def test_vhati_shrinks_the_opponents_creature_not_its_controllers(set_pool):
    """Vhati il-Dal beside the AI's Craw Wurm (6/4), the opponent's Serra
    Angel (4/4) across: the rewrite lands on the Angel and the Wurm keeps
    its size. Driven through the simulator's own executor."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("TMP")["Vhati il-Dal"], lea["Craw Wurm"], lea["Forest"], lea["Swamp"]],
        theirs=[lea["Serra Angel"]],
    )
    angel, wurm = _named(game, 1, "Serra Angel"), _named(game, 0, "Craw Wurm")
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Vhati il-Dal"
    assert game.permanent_at(action.target_player_index, action.target_permanent_index) is angel
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert 1 in (angel.effective_power, angel.effective_toughness)


def test_sorceress_queen_makes_the_opponents_creature_the_0_2(set_pool):
    """"{T}: Target creature other than this creature has base power and
    toughness 0/2 until end of turn." With the rehearsed "moves something"
    gate off (on this board, with no fight to spend it in, it may well be
    worth nothing), the target is the opponent's Serra Angel, not the AI's
    own Craw Wurm, the biggest creature on either board."""
    lea = set_pool("LEA")
    game = _board(
        mine=[set_pool("ARN")["Sorceress Queen"], lea["Craw Wurm"]],
        theirs=[lea["Serra Angel"]],
    )
    with mock.patch.object(ai_abilities, "_moves_something", lambda *a, **k: True):
        action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Sorceress Queen"
    assert action.target_player_index == 1
    assert game.permanent_at(1, action.target_permanent_index).card.name == "Serra Angel"


def _rewrites(cards):
    """``(card, ability_index, ability)`` for every supported activated
    ability with a base P/T rewrite among its steps, modes opened."""
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            if any(step.kind in _BASE_PT_SET_KINDS for step in _side_steps(ability.instruction)):
                yield card, index, ability


def test_every_base_pt_rewrite_is_aimed_by_its_numbers_or_its_printed_seat():
    """Census over both manifest roles: every activated ability that
    rewrites a target's base P/T reads "opponent" — every number printed in
    the pool is below a 2/2 — unless the rewrite prints the activator's own
    seat ("you control", "you cast this turn"), which reads "you". Asserts a
    floor on what it read."""
    from engine.card_loader import load_cards, manifest_set_paths
    from engine.faces import compilation_units

    read = []
    wrong = []
    for card, _index, ability in _rewrites(
        compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    ):
        steps = [
            step for step in _side_steps(ability.instruction) if step.kind in _BASE_PT_SET_KINDS
        ]
        own = any(
            (step.payload or {}).get("controller") == "you"
            or (step.payload or {}).get("cast_by_you_this_turn")
            for step in steps
        )
        side = _activation_target_side(Permanent(card=card), ability.instruction)
        read.append(card.name)
        if side != ("you" if own else "opponent"):
            wrong.append((card.name, side))
    assert not wrong, wrong
    assert {"Vhati il-Dal", "Sorceress Queen", "Island of Wak-Wak"} <= set(read), read
    assert len(read) >= 6, read
