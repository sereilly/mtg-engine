"""Per-card tests for Homelands' artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W2G3: combat restrictions and shroud exceptions ---

from engine import Game, PlayerState
from engine.combat_restrictions import granted_blocker_whitelists
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g3_unsick(permanent: Permanent) -> Permanent:
    permanent.metadata["summoning_sickness_turn"] = -5
    return permanent


def test_jovens_tools_carries_the_printed_blocker_class(set_pool):
    """"{4}, {T}: Target creature can't be blocked this turn except by Walls."

    The class of blocker is payload, not a word in the instruction's name — a
    card printing another subtype is the same restriction. A **list**, because
    the static printing's union ("Walls and/or creatures with flying") is the
    same reader on the other side.
    """
    program = compile_card_oracle(set_pool("HML")["Joven's Tools"])

    assert program.supported, program.reason
    [ability] = program.activated_abilities
    assert ability.instruction.kind == "grant_cant_be_blocked_except_by_until_eot"
    assert ability.instruction.payload["allowed_blockers"] == [
        {"type_filter": "creature", "subtype_filter": "wall"}
    ]


def test_jovens_tools_lets_only_the_named_blockers_through(set_pool):
    """A *whitelist*, not Tower of Coireall's blacklist: everything the sentence
    does not name is illegal, where the blacklist lets the rest of the board
    block. Both are asserted, because a record read as the other one would give
    each card the opposite effect."""
    lea = set_pool("LEA")
    tools = Permanent(card=set_pool("HML")["Joven's Tools"])
    attacker = _w2g3_unsick(Permanent(card=lea["Grizzly Bears"]))
    wall = Permanent(card=lea["Wall of Wood"])
    bear = Permanent(card=lea["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[tools, attacker], library=[lea["Forest"]] * 5)
    p2 = PlayerState(name="P2", battlefield=[wall, bear], library=[lea["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Joven's Tools", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert result.supported, result.details
    assert granted_blocker_whitelists(attacker) == (
        [{"type_filter": "creature", "subtype_filter": "wall"}],
    )

    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()   # declare blockers

    assert game.declare_blockers(1, {0: 1})[0], "a Wall is what the card allows"
    assert not game.declare_blockers(1, {1: 1})[0], "everything else is illegal"


def test_the_jovens_tools_whitelist_ends_with_the_turn(set_pool):
    """"This turn" is the cleanup sweep and nothing else — the record is the
    whole of the effect, so an entry that outlived the turn would be an evasion
    ability nobody granted."""
    lea = set_pool("LEA")
    tools = Permanent(card=set_pool("HML")["Joven's Tools"])
    attacker = _w2g3_unsick(Permanent(card=lea["Grizzly Bears"]))
    p1 = PlayerState(name="P1", battlefield=[tools, attacker], library=[lea["Forest"]] * 5)
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.activate_permanent_ability(
        0, "Joven's Tools", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert granted_blocker_whitelists(attacker)

    game.resolve_cleanup_step(0)

    assert granted_blocker_whitelists(attacker) == ()
