"""An AI seat puts a shield up against something coming, never in an idle main
phase.

LGN Phase 5, smoke game 1: the AI's Deftblade Elite ("{1}{W}: Prevent all
combat damage that would be dealt to and dealt by this creature this turn")
was activated in main phase 1 **and** main phase 2 every turn, with nothing in
combat, and spent the seat's mana. The main-phase chooser
(``ai_abilities.choose_activation_action``) prices every non-damage ability
at a flat 2.5 and proposes the best; the rehearsed shapes beside it (a land's
ability, a type rewrite, an armed draw replacement, a source given up) are
carried out on a copy and proposed only where the seat is ahead once the turn
is over. A shield was not one of them, so nothing asked what it stopped.
``ai_valuation.shields_only`` makes it one: a prevention or regeneration
shield and nothing else (``SHIELD_KINDS``).

The rehearsal itself already read a shield as worth nothing on an idle board —
the instant-speed chooser, which rehearses every proposal, never took it — so
the same shield in front of a lethal blocker or a burn spell is still taken.
"""
from __future__ import annotations

from unittest import mock

from engine import ai_abilities
from engine.ai_abilities import choose_activation_action
from engine.ai_policy import choose_instant_speed_activation
from engine.ai_valuation import SHIELD_KINDS, shields_only
from engine.card_loader import load_catalog
from engine.game import Game
from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES
from engine.mixins._constants import phases_after
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

#: The prevention and regeneration kinds that are not a shield: each takes one
#: away or pins damage where it is.
_NOT_SHIELDS = frozenset({
    "deny_regeneration_to_block_pair",
    "deny_regeneration_to_self",
    "deny_regeneration_to_target",
    "forbid_damage_prevention",
    "lock_damage_to_target",
})


def _table(own, other=(), *, enforce=True) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=_CARDS[name])))
        game.players[seat].library = [_CARDS["Plains"]] * 10
    game._recompute_continuous_effects()
    return game


def _main_phase(game: Game, phase: str = "precombat_main") -> Game:
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    if phase == "postcombat_main":
        game.current_turn_phase = game.current_step = phase
        game.turn_phases_remaining = phases_after(phase)
    return game


def _blocking(attacker: str, blocker: str, lands=()) -> Game:
    """Seat 1 (the AI) blocks seat 0's *attacker* with *blocker*; the game
    stands in the declare-blockers step with the block declared."""
    game = _table([attacker], [blocker, *lands])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    resolve_stack(game)
    game.advance_combat_phase()  # declare blockers
    assert game.current_step == "declare_blockers"
    ok, why = game.declare_blockers(1, {0: 0}, acting_index=1)
    assert ok, why
    resolve_stack(game)
    return game


#: Shields that are card-line kinds (``card_hooks``) and so have no category.
_HOOK_SHIELDS = frozenset({"grant_forcefield_shield", "shield_target_land_from_destruction"})


def test_every_prevention_and_regeneration_kind_is_read_one_way_or_the_other():
    kinds = {
        kind for kind, family in INSTRUCTION_CATEGORIES.items()
        if family in ("prevention", "regeneration")
    }
    assert kinds | _HOOK_SHIELDS == SHIELD_KINDS | _NOT_SHIELDS, sorted(
        (kinds | _HOOK_SHIELDS) ^ (SHIELD_KINDS | _NOT_SHIELDS)
    )
    assert not _HOOK_SHIELDS & set(INSTRUCTION_CATEGORIES)


def test_the_shapes_the_phase_five_boards_held_are_shields():
    for name in ("Deftblade Elite", "Drudge Skeletons", "Circle of Protection: Red",
                 "Urborg Phantom", "Living Wall"):
        (first, *_rest) = usable_activated_abilities(compile_card_oracle(_CARDS[name]))
        assert shields_only(first.instruction), name
    # A shield beside another effect is not "only a shield" (Maze of Ith's untap).
    (maze, *_rest) = usable_activated_abilities(compile_card_oracle(_CARDS["Maze of Ith"]))
    assert not shields_only(maze.instruction)


def test_deftblade_elite_is_not_activated_in_either_main_phase():
    for phase in ("precombat_main", "postcombat_main"):
        for other in ((), ("Grizzly Bears",)):
            game = _main_phase(_table(["Deftblade Elite", "Plains", "Plains"], other), phase)
            assert choose_activation_action(game, 0) is None, (phase, other)


def test_a_regeneration_shield_is_not_activated_in_a_main_phase():
    game = _main_phase(_table(["Drudge Skeletons", "Swamp"], ["Grizzly Bears"]))
    assert choose_activation_action(game, 0) is None


def test_the_flat_score_proposed_it_every_main_phase():
    """Backwards: with the shield read as any other effect, the chooser
    proposes Deftblade's {1}{W} in both main phases on an empty board.

    Since kg4 every other effect is held to the cast rule too
    (``ai_abilities._moves_something``), which reads the idle shield as the
    nothing it is — a second layer over this one, so the backwards reading
    switches both off."""
    with mock.patch.object(ai_abilities, "shields_only", lambda instruction: False), \
            mock.patch.object(ai_abilities, "_moves_something", lambda *args: True):
        for phase in ("precombat_main", "postcombat_main"):
            game = _main_phase(_table(["Deftblade Elite", "Plains", "Plains"]), phase)
            action = choose_activation_action(game, 0)
            assert action is not None and action.permanent_name == "Deftblade Elite", phase


def test_deftblade_elite_shields_itself_from_a_blocker_that_would_kill_it():
    """The AI's Deftblade Elite blocks a Grizzly Bears: without the shield the
    1/1 dies, with it nothing does — the card working, in the declare-blockers
    step's priority."""
    game = _blocking("Grizzly Bears", "Deftblade Elite", lands=("Plains", "Plains"))
    action = choose_instant_speed_activation(game, 1)
    assert action is not None and action.permanent_name == "Deftblade Elite"


def test_drudge_skeletons_regenerate_in_front_of_a_lethal_attacker():
    game = _blocking("Grizzly Bears", "Drudge Skeletons", lands=("Swamp",))
    action = choose_instant_speed_activation(game, 1)
    assert action is not None and action.permanent_name == "Drudge Skeletons"


def test_drudge_skeletons_regenerate_in_response_to_a_lightning_bolt():
    game = _main_phase(_table(["Mountain"], ["Drudge Skeletons", "Swamp"], enforce=False))
    game.players[0].hand = [_CARDS["Lightning Bolt"]]
    (skeletons,) = [p for p in game.controlled_by(1) if p.card.name == "Drudge Skeletons"]
    result = game.queue_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_ids=[skeletons.permanent_id],
    )
    assert result.supported, result.details
    assert game.stack
    action = choose_instant_speed_activation(game, 1)
    assert action is not None and action.permanent_name == "Drudge Skeletons"
