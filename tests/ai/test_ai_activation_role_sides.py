"""An activated ability naming several targets aims each one at its own board.

`ai_abilities._choose_activation_role_targets` took **one** side for the whole
chain — and none at all unless a role was a seat, so the walk took the first
option at each level, which is the first board in seat order. "Until end of
turn, target creature with the chosen ability loses it and **another target
creature** gains it" (Phyrexian Splicer) therefore named two of the
activator's own creatures: {2} and a tap to move its own flying from one of
its creatures to another. The cast side learned a side per role at Planeshift
(`ai_target_sides.role_target_sides`); the activation side asks the same
derivation now (`ai_target_sides.ability_role_target_sides`).
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_simulator import SimulationReport, _play_activations
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import (derive_activation_spec, role_is_seat, spec_roles,
                              usable_activated_abilities)
from tests.helpers import resolve_stack

_POOL: dict = {}
for _card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _POOL.setdefault(_card.name, _card)

#: The same permanents on both boards, so a chooser with no side takes the
#: activator's own for every role: seat 0 is first in every walk.
_MIRROR = ("Grizzly Bears", "Hill Giant", "Serra Angel", "Wall of Wood", "Forest",
           "Mountain", "Island", "Sol Ring", "Mox Pearl", "Castle", "Crusade")
_GRAVE = ("Grizzly Bears", "Hill Giant", "Lightning Bolt", "Sol Ring", "Forest")


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _table(*, costs: bool = False) -> Game:
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=[]),
        PlayerState("Opp", library=[forest] * 30, hand=[forest] * 2),
    ])
    game.enforce_mana_costs = costs
    game.interactive_seats = set()
    game.turn = 5
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


#: The side each role of each roles ability wants, as printed. Written out by
#: hand rather than read off `ability_role_target_sides`, so the census does
#: not ask the derivation under test what the answer is. None is "either": a
#: seat, or a role a relation to another role already places.
_PRINTED_SIDES = {
    "Crooked Scales": ("opponent", "you"),
    "Gauntlets of Chaos": ("you", "opponent"),
    "Goblin Welder": (None, None),
    "Phyrexian Splicer": ("opponent", "you"),
    "Planeswalker's Favor": (None, "you"),
    "Planeswalker's Scorn": (None, "opponent"),
    "Soldevi Heretic": ("you", None),
    "Triangle of War": ("you", "opponent"),
}


def test_every_role_an_activation_names_is_on_the_board_its_step_wants():
    """Every supported permanent whose first usable ability announces roles,
    on a mirrored board. Before: one role slot of the sixteen on the wrong
    board — Phyrexian Splicer's first, the activator's own flyer."""
    examined, wrong, proposed = [], [], 0
    for name, card in sorted(_POOL.items()):
        if card.primary_type in ("instant", "sorcery", "land") or card.face_of is not None:
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        ability = next(iter(usable_activated_abilities(program)), None)
        if ability is None or ability.instruction is None:
            continue
        roles = spec_roles(derive_activation_spec(ability))
        if not roles:
            continue
        examined.append(name)
        game = _table()
        _put(game, 0, name)
        for seat in (0, 1):
            for other in _MIRROR:
                _put(game, seat, other)
            game.players[seat].graveyard.extend(_POOL[n] for n in _GRAVE)
        game.auto_resolve_pending_choices()

        action = choose_activation_action(game, 0)
        if action is None or action.permanent_name != name:
            continue
        proposed += 1
        refs = action.target_role_refs or []
        assert len(refs) == len(roles), (name, refs)
        for role, ref, side in zip(roles, refs, _PRINTED_SIDES[name]):
            if "permanent_id" not in ref or role_is_seat(role) or side is None:
                continue
            seat = game.controller_index_of(game.permanent_by_id(ref["permanent_id"]))
            if (seat == 0) != (side == "you"):
                wrong.append((name, role.get("role"), side))

    assert sorted(examined) == sorted(_PRINTED_SIDES), examined
    assert proposed >= 7, proposed
    assert wrong == [], wrong


def test_the_splicer_takes_an_opponents_flying_and_gives_it_to_its_own_creature():
    """Through the executor the simulator runs: the opposing Serra Angel is
    grounded and the keyword lands on the activator's side — not the
    activator's own Angel robbed for its own Giant, which is what a chain
    walked from seat 0 with no side named. (*Which* of its own creatures gets
    it is the first, flyer or not: a valuation this policy does not have.)"""
    game = _table(costs=True)
    splicer = _put(game, 0, "Phyrexian Splicer")
    own_flyer = _put(game, 0, "Serra Angel")
    _put(game, 0, "Hill Giant")
    for _ in range(2):
        _put(game, 0, "Forest")
    their_flyer = _put(game, 1, "Serra Angel")
    game.auto_resolve_pending_choices()

    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Phyrexian Splicer"
    named = [game.permanent_by_id(ref["permanent_id"]) for ref in action.target_role_refs]
    assert named[0] is their_flyer, [p.card.name for p in named]
    assert game.controller_index_of(named[1]) == 0

    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, 0, report, 1, 1)
    resolve_stack(game)

    assert not report.refused_activations, report.refused_activations
    assert splicer.tapped
    assert not game._has_keyword(their_flyer, "flying"), game.log[-6:]
    assert game._has_keyword(own_flyer, "flying")
    assert game._has_keyword(named[1], "flying")
