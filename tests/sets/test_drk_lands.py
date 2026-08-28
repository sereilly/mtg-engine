"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


# --- G4: combat, prevention, control (The Dark) ---


def test_maze_of_ith_shields_the_creature_it_untaps(set_pool):
    """"{T}: Untap target attacking creature. Prevent all combat damage that
    would be dealt to and dealt by that creature this turn."

    Ebony Horse prints the same second sentence, which is exactly what the
    card-hook registry's entry bar forbids — so the sentence is a grammar
    production and the Maze is two ordinary instructions.
    """
    maze = Permanent(card=set_pool("DRK")["Maze of Ith"])
    attacker = _nosick(Permanent(card=_mk_creature_card("Attacker", 3, 3)))
    blocker = Permanent(card=_mk_creature_card("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[maze, blocker], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()  # declare blockers
    assert game.declare_blockers(1, {1: 0})[0]  # blocker is index 1; the Maze is 0

    result = game.activate_permanent_ability(
        1, "Maze of Ith", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert attacker.tapped is False, "the attacker was untapped"

    game.advance_combat_phase()  # combat damage
    assert attacker.damage_marked == 0, "no combat damage was dealt to it"
    assert blocker.damage_marked == 0, "and none by it"


def test_maze_of_ith_is_supported(set_pool):
    program = compile_card_oracle(set_pool("DRK")["Maze of Ith"])
    assert program.supported
    kinds = [
        instruction.kind
        for ability in program.activated_abilities
        for instruction in (ability.instruction,)
        if instruction is not None
    ]
    # One ability, lowered as a sequence of the two printed sentences.
    assert kinds == ["sequence"]
