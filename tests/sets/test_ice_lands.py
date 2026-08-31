"""Ice Age (ICE) land cards.

ICE **ships** (SET_PLAYBOOK.md Phase 4 moved it from ``measured`` to ``sets``).
It was measured while these tests were written, and the pool resolves through
``set_pool("ICE")`` either way — that fixture is about which cards a test may
name, not about which a player may deck. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.cumulative_upkeep import cumulative_upkeep_cost
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.turn_state import record_attack
from tests.helpers import _nosick


# --- Round 1: cumulative upkeep (CR 702.24) ---
def test_halls_of_mist_carries_its_static_line_as_an_instruction(set_pool):
    """A land whose cumulative upkeep compiles *and* whose static line does.

    The land support gate used to skip the static check for any land carrying
    an ability, so implementing the keyword would have turned this card
    supported with "Creatures that attacked … can't attack" doing nothing. The
    gate reads every land now — and passing the gate is not doing the thing, so
    the line is carried as the instruction ``can_attack`` scans for (W2G3).
    """
    program = compile_card_oracle(set_pool("ICE")["Halls of Mist"])

    assert program.supported
    assert [i.kind for i in program.instructions] == [
        "creatures_that_attacked_last_turn_cant_attack"
    ]
# --- Round 6: snow as a supertype the rules already knew how to read ---
def _combat(game: Game, attacker_indices: list[int]) -> None:
    """Advance seat 0's turn to the declare-blockers step with those attackers."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
def test_rime_dryad_is_unblockable_against_a_snow_covered_forest(set_pool):
    pool = set_pool("ICE")
    dryad = Permanent(card=pool["Rime Dryad"])
    blocker = Permanent(card=pool["Balduvian Bears"])
    snow = Permanent(card=pool["Snow-Covered Forest"])
    p1 = PlayerState(name="P1", battlefield=[dryad], life=20)
    p2 = PlayerState(name="P2", battlefield=[blocker, snow], life=20)
    game = Game(players=[p1, p2])

    _combat(game, [0])
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok
# --- Round 27: a supertype is a computed characteristic (CR 205.4, layer 4) ---
def _board(set_pool, *names, opponent=()):
    """A board of ICE cards, mine and the opponent's, ready to activate."""
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[n]) for n in names]
    theirs = [Permanent(card=pool[n]) for n in opponent]
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=mine, life=20),
            PlayerState(name="P2", battlefield=theirs, life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in mine:
        _nosick(perm)
    return game, mine, theirs
def test_a_thawed_forest_stops_satisfying_snow_forestwalk(set_pool):
    """The finding, stated as behaviour. Nine call sites asked what supertypes
    a permanent had by reading its printed type line, which was right while
    nothing in the pool could change one — and Arcum's Weathervane is the card
    that makes it wrong. Snow forestwalk (CR 702.14c) is one of the nine.
    """
    from engine.landwalk import land_satisfies, landwalk_requirement

    game, (vane,), (forest,) = _board(
        set_pool, "Arcum's Weathervane", opponent=["Snow-Covered Forest"]
    )
    requirement = landwalk_requirement("snow forestwalk")
    assert land_satisfies(forest, requirement)

    result = game.activate_permanent_ability(
        0, "Arcum's Weathervane", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert not land_satisfies(forest, requirement), (
        "a thawed forest is not the snow Forest CR 702.14c asks for"
    )
# --- Round 31: a cumulative upkeep cost is a cost, not a mana cost ---
def test_glacial_chasm_charges_its_upkeep_in_life(set_pool):
    """"Cumulative upkeep—Pay 2 life" is a cost this engine charges, and the
    keyword line is read for a land the same way it is for a creature."""
    chasm = set_pool("ICE")["Glacial Chasm"]
    program = compile_card_oracle(chasm)

    assert "cumulative upkeep" not in (program.reason or "").lower()
    assert cumulative_upkeep_cost(
        "cumulative upkeep—pay 2 life"
    ).life == 2
    upkeep = [
        trig for trig in program.triggered_abilities
        if trig.instruction is not None
        and trig.instruction.kind == "cumulative_upkeep"
    ]
    assert len(upkeep) == 1
    assert upkeep[0].instruction.payload["life"] == 2


# --- W1G1: prevention and damage shields ---
def test_glacial_chasm_is_supported_with_every_line_accounted_for(set_pool):
    """Four printed lines, four readers: the cumulative upkeep keyword, the
    enters trigger, the combat restriction and the static prevention. The land
    gate names the first line nothing claims, so this passing is the claim that
    nothing is left."""
    program = compile_card_oracle(set_pool("ICE")["Glacial Chasm"])

    assert program.supported, program.reason
    assert any(
        instr.kind == "creatures_cant_attack" for instr in program.instructions
    ), "the restriction has to be an instruction, or can_attack's board scan never sees it"


def test_glacial_chasm_grounds_its_controllers_creatures(set_pool):
    """"Creatures you control can't attack." (CR 506.3.) Scoped to the seat that
    controls the land — an opponent's creatures are untouched."""
    pool = set_pool("ICE")
    chasm = Permanent(card=pool["Glacial Chasm"])
    mine = _nosick(Permanent(card=pool["Balduvian Bears"]))
    theirs = _nosick(Permanent(card=pool["Balduvian Bears"]))
    p1 = PlayerState(name="P1", battlefield=[chasm, mine], life=20)
    p2 = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[p1, p2])

    assert not game.can_attack(mine, 1)
    assert game.can_attack(theirs, 0)


def test_glacial_chasm_prevents_every_point_dealt_to_its_controller(set_pool):
    """"Prevent all damage that would be dealt to you." (CR 615.) A static
    ability with no charges: a second event this turn is prevented exactly like
    the first, and the shield ends when the land does rather than by a sweep."""
    pool = set_pool("ICE")
    chasm = Permanent(card=pool["Glacial Chasm"])
    p1 = PlayerState(name="P1", battlefield=[chasm], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game._deal_damage_to_player(p1, 5)
    game._deal_damage_to_player(p1, 4)
    assert p1.life == 20

    # Nothing is recorded, so the answer follows the board.
    game.remove_from_battlefield(chasm)
    game._deal_damage_to_player(p1, 3)
    assert p1.life == 17


def test_glacial_chasm_shields_only_its_own_controller(set_pool):
    """"To you" is the land's controller (CR 109.5) — an opponent's face is not
    covered by a Chasm on the other side of the table."""
    pool = set_pool("ICE")
    chasm = Permanent(card=pool["Glacial Chasm"])
    p1 = PlayerState(name="P1", battlefield=[chasm], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game._deal_damage_to_player(p2, 6)
    assert p2.life == 14
# --- end W1G1 ---


# --- W2G3: combat restrictions and requirements ---
def _w2g3_attack_last_turn(game: Game, permanent: Permanent, seat: int) -> None:
    """Stamp *permanent* as having attacked on *seat*'s previous turn.

    Written through ``record_attack`` rather than poked into metadata: the
    stamp's shape is the declare-attackers step's, and a test that spelled it
    out by hand would keep passing after the step changed it.
    """
    record_attack(permanent, seat, game.seat_turn_counts.get(seat, 0) - 1)


def test_halls_of_mist_stops_a_creature_that_attacked_last_turn(set_pool):
    """"Creatures that attacked during their controller's last turn can't
    attack." (CR 506.3, 508.1c.)

    Giant Turtle's restriction printed about the board, so it reaches a
    creature whose own text says nothing — and it reaches it from the *other*
    side of the table, since the sentence names no controller.
    """
    pool = set_pool("ICE")
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    halls = Permanent(card=pool["Halls of Mist"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears], life=20),
        PlayerState(name="P2", battlefield=[halls], life=20),
    ])
    game._sync_control()
    game.active_player_index = 0
    game.seat_turn_counts[0] = 2

    # Nothing recorded: the Bears attacked no turn at all and are free.
    assert game.can_attack(bears, 1)

    _w2g3_attack_last_turn(game, bears, 0)
    assert not game.can_attack(bears, 1)


def test_halls_of_mist_leaves_a_creature_that_attacked_two_turns_ago_alone(set_pool):
    """"Their controller's **last** turn" is one ordinal, not "ever". A stamp
    two of the seat's turns old says nothing about this combat."""
    pool = set_pool("ICE")
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    halls = Permanent(card=pool["Halls of Mist"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears], life=20),
        PlayerState(name="P2", battlefield=[halls], life=20),
    ])
    game._sync_control()
    game.active_player_index = 0
    game.seat_turn_counts[0] = 3
    record_attack(bears, 0, 1)

    assert game.can_attack(bears, 1)


def test_halls_of_mist_restriction_ends_with_the_land(set_pool):
    """The restriction is read off the board every declaration, never stamped
    on the creature — so removing the Halls frees the attack at once."""
    pool = set_pool("ICE")
    bears = _nosick(Permanent(card=pool["Balduvian Bears"]))
    halls = Permanent(card=pool["Halls of Mist"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bears], life=20),
        PlayerState(name="P2", battlefield=[halls], life=20),
    ])
    game._sync_control()
    game.active_player_index = 0
    game.seat_turn_counts[0] = 2
    _w2g3_attack_last_turn(game, bears, 0)
    assert not game.can_attack(bears, 1)

    game.remove_from_battlefield(halls)

    assert game.can_attack(bears, 1)
# --- end W2G3 ---
