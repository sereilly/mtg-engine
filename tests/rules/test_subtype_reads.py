"""CR 613 layer 4 — a creature *type* is computed, not printed.

``Permanent.has_type`` resolves through the layer system, so a creature that
became a Wall is one and a printed Wall that stopped being one is not. Four
places in the engine asked the same question of ``card.type_line`` instead —
the text as printed, which no effect can change — and the two answers disagree
for anything whose type is granted.

The disagreement was in *one function*: ``_can_block_attacker`` tested
Juggernaut's "can't be blocked by Walls" against the printed line and
Invisibility's "can't be blocked except by Walls" against ``has_type``, three
lines apart. Primal Clay's third body is the creature that tells them apart.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CATALOG = {c.name: c for c in load_catalog()}


def _wall_bodied_clay(game: Game, seat: int) -> Permanent:
    """A Primal Clay whose controller chose the 1/6 Wall body."""
    game.interactive_seats = {seat}
    game.players[seat].hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(seat, "Primal Clay")
    game.resolve_top_of_stack()
    clay = game.players[seat].battlefield[-1]
    assert game.confirm_enter_body_choice(seat, 2)
    assert clay.has_type("wall")
    clay.metadata["summoning_sickness_turn"] = -99
    return clay


def _duel() -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


@pytest.mark.cr("613.1d", "509.1b")
def test_a_creature_that_became_a_wall_cannot_block_a_juggernaut():
    """"This creature can't be blocked by Walls." The restriction is about what
    the blocker *is* (CR 613 layer 4), not about what its card says."""
    game, p1, _p2 = _duel()
    juggernaut = Permanent(card=_CATALOG["Juggernaut"])
    juggernaut.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(juggernaut)
    clay = _wall_bodied_clay(game, 1)

    assert not game._can_block_attacker(clay, juggernaut)


@pytest.mark.cr("613.1d", "509.1b")
def test_the_same_creature_on_another_body_can_block_it():
    """The control: the 3/3 body is no Wall, so the restriction does not reach
    it. Without this the test above would pass for a Clay that simply could not
    block anything."""
    game, p1, p2 = _duel()
    juggernaut = Permanent(card=_CATALOG["Juggernaut"])
    juggernaut.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(juggernaut)
    game.interactive_seats = {1}
    p2.hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(1, "Primal Clay")
    game.resolve_top_of_stack()
    clay = p2.battlefield[-1]
    assert game.confirm_enter_body_choice(1, 0)
    clay.metadata["summoning_sickness_turn"] = -99

    assert not clay.has_type("wall")
    assert game._can_block_attacker(clay, juggernaut)


@pytest.mark.cr("613.1d")
def test_a_granted_wall_is_a_legal_target_for_an_ability_that_wants_one():
    """Ali Baba: "{R}: Tap target Wall." The picker and the resolution both ask
    the layer system, so a granted Wall is offered and accepted."""
    game, p1, p2 = _duel()
    ali = Permanent(card=_CATALOG["Ali Baba"])
    ali.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(ali)
    clay = _wall_bodied_clay(game, 1)

    game.activate_permanent_ability(
        0, "Ali Baba", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert clay.tapped


@pytest.mark.cr("613.1d")
def test_a_granted_wall_is_not_a_legal_non_wall_target():
    """The mirror question, and the one the printed read got backwards in the
    other direction: Nettling Imp's "target **non-Wall** creature" must decline
    a creature that became a Wall.
    """
    game, p1, p2 = _duel()
    imp = Permanent(card=_CATALOG["Nettling Imp"])
    imp.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(imp)
    clay = _wall_bodied_clay(game, 1)

    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(imp.card)
    instruction = next(
        ability.instruction
        for ability in program.activated_abilities
        if ability.instruction is not None
        and ability.instruction.kind == "mark_non_wall_target_to_attack"
    )

    assert not game._ability_target_legal(instruction, clay)
