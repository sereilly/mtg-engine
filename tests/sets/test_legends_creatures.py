"""Per-card tests for Legends' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _vanilla(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _blocked_by(attacker: Permanent, blockers: list[Permanent]) -> tuple[Game, PlayerState]:
    """Attack with *attacker* into *blockers*, all of which block it, and let
    every trigger the declaration put on the stack resolve."""
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=list(blockers))
    game = Game(players=[p1, p2])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg
    game.advance_combat_phase()   # declare_blockers
    ok, msg = game.declare_blockers(1, {i: 0 for i in range(len(blockers))})
    assert ok, msg
    game._settle()
    return game, p1


# ---------------------------------------------------------------------------
# Rampage (round 1) — CR 702.23, the keyword Legends brings to the pool
# ---------------------------------------------------------------------------

_RAMPAGERS = {
    "Aerathi Berserker": 3,
    "Chromium": 2,
    "Craw Giant": 2,
    "Frost Giant": 2,
    "Hunding Gjornersen": 1,
    "Marhault Elsdragon": 1,
    "Wolverine Pack": 2,
}


@pytest.mark.parametrize("name,amount", sorted(_RAMPAGERS.items()))
def test_every_rampage_card_compiles_to_the_ability_the_rule_defines(name, amount, set_pool):
    """CR 702.23a defines rampage as a triggered ability, so each of these
    compiles to one — not to a keyword line something else has to remember to
    act on. The seven of them are the whole of rampage in the pool."""
    program = compile_card_oracle(set_pool("LEG")[name])
    assert program.supported, program.reason
    rampage = [
        trig for trig in program.triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "rampage_pump"
    ]
    assert len(rampage) == 1, f"{name} should carry exactly one rampage ability"
    assert rampage[0].condition.kind == "creature_becomes_blocked"
    assert rampage[0].instruction.payload["amount"] == amount


def test_craw_giant_grows_by_two_for_each_blocker_past_the_first(set_pool):
    """Craw Giant is 6/4 with trample and rampage 2. Three blockers is two
    beyond the first, so +4/+4."""
    giant = Permanent(card=set_pool("LEG")["Craw Giant"])
    _, p1 = _blocked_by(giant, [Permanent(card=_vanilla(f"Blocker {i}", 1, 1)) for i in range(3)])

    assert p1.battlefield[0].effective_power == 10
    assert p1.battlefield[0].effective_toughness == 8


def test_craw_giant_keeps_the_rest_of_its_printed_line(set_pool):
    """The rampage half of a keyword line must not eat the other half. Craw
    Giant prints "Trample, rampage 2" as one line, and admitting rampage there
    is what would quietly drop the trample beside it."""
    giant = Permanent(card=set_pool("LEG")["Craw Giant"])
    assert giant.has_keyword("trample")


def test_hunding_gjornersen_gets_nothing_from_a_lone_blocker(set_pool):
    """Rampage 1, one blocker: the ability still triggers and resolves, and
    grants nothing (CR 702.23a's "beyond the first")."""
    hunding = Permanent(card=set_pool("LEG")["Hunding Gjornersen"])
    base = hunding.effective_power
    _, p1 = _blocked_by(hunding, [Permanent(card=_vanilla("Blocker", 1, 1))])

    assert p1.battlefield[0].effective_power == base
