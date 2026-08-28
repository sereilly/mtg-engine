"""Per-card tests for The Dark's artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, _nosick


# --- G4: combat, prevention, control (The Dark) ---


def _board(set_pool, artifact_name: str, *others: Permanent):
    artifact = Permanent(card=set_pool("DRK")[artifact_name])
    p1 = PlayerState(name="P1", battlefield=[artifact])
    p2 = PlayerState(name="P2", battlefield=list(others))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, artifact


def test_barls_cage_holds_a_creature_down_for_one_untap_step(set_pool):
    """"{3}: Target creature doesn't untap during its controller's next untap
    step." A one-shot marker, not the standing restriction
    ``engine/untap_restrictions.py`` holds — and one step only, so the creature
    untaps on the turn after."""
    victim = Permanent(card=_mk_creature_card("Victim", 2, 2))
    victim.tapped = True
    game, _cage = _board(set_pool, "Barl's Cage", victim)

    result = game.activate_permanent_ability(
        0, "Barl's Cage", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert victim.metadata.get("skip_next_untap") == 1

    game.start_turn(1)
    assert victim.tapped is True, "it was held down for its controller's untap step"

    game.start_turn(0)
    game.start_turn(1)
    assert victim.tapped is False, "and only for one of them"


def test_barls_cage_needs_a_creature(set_pool):
    """The printed noun is enforced at resolution: an explicitly chosen
    non-creature fizzles rather than sliding onto whatever else is legal."""
    rock = Permanent(card=_mk_creature_card("Rock", 0, 0))
    rock.card = rock.card.__class__(
        **{**rock.card.__dict__, "type_line": "Artifact", "power": None, "toughness": None}
    )
    rock.tapped = True
    game, _cage = _board(set_pool, "Barl's Cage", rock)

    game.activate_permanent_ability(
        0, "Barl's Cage", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert "skip_next_untap" not in rock.metadata


def test_tower_of_coireall_stops_only_the_named_blockers(set_pool):
    """"{T}: Target creature can't be blocked by Walls this turn."

    The blocker class is payload, tested by the declare-blockers step through
    the same ``subject_matches`` the printed static restrictions go through —
    so a Wall may not block and anything else still may.
    """
    attacker = _nosick(Permanent(card=_mk_creature_card("Attacker", 2, 2)))
    wall = Permanent(card=_mk_creature_card("Stone Wall", 0, 4))
    wall.card = wall.card.__class__(
        **{**wall.card.__dict__, "type_line": "Creature — Wall"}
    )
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))

    tower = Permanent(card=set_pool("DRK")["Tower of Coireall"])
    p1 = PlayerState(name="P1", battlefield=[tower, attacker])
    p2 = PlayerState(name="P2", battlefield=[wall, bear])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Tower of Coireall", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert result.supported

    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()  # declare blockers

    assert not game.declare_blockers(1, {0: 1})[0], "a Wall can't block it"
    assert game.declare_blockers(1, {1: 1})[0], "anything else still can"


def test_tower_of_coireall_carries_the_printed_noun(set_pool):
    """The restriction is the noun phrase, not the word "Wall" baked into a
    kind — a card printed with another subtype is the same instruction."""
    program = compile_card_oracle(set_pool("DRK")["Tower of Coireall"])
    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "grant_cant_be_blocked_by_until_eot"
    assert ability.instruction.payload["blocker_filter"] == {
        "type_filter": "creature",
        "subtype_filter": "wall",
    }
