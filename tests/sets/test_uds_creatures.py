"""Urza's Destiny creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _g5_creature_combat(blocker: Permanent, attackers: list[Permanent]) -> Game:
    """A combat with *attackers* declared and *blocker* facing them all.

    Stops at the declare-blockers step so the caller can make the declaration
    itself, which is the whole subject of this block's one creature.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers)),
        PlayerState(name="P2", battlefield=[blocker]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, list(range(len(attackers))), 1)
    assert declared, why
    game.advance_combat_phase()
    return game


def test_wall_of_glare_blocks_three_attackers_at_once(set_pool):
    """"This creature can block any number of creatures."

    CR 509.1a gives a blocker **one** attacker unless something says otherwise,
    and the ceiling that lifts it was a substring scan for the *other* printed
    spelling ("can block an additional creature"): read against "any number" it
    answers zero, so the card would have been admitted blocking exactly one.

    Three attackers rather than two, so the reading cannot be an off-by-one:
    a grant of "one additional" would take two and refuse the third.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Wall of Glare"])
    assert program.supported, program.reason

    bear = set_pool("LEA")["Grizzly Bears"]
    wall = Permanent(card=pool["Wall of Glare"])
    game = _g5_creature_combat(wall, [Permanent(card=bear) for _ in range(3)])
    assert game._max_blocks_for(wall) >= 3, game._max_blocks_for(wall)

    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why


def test_an_ordinary_wall_still_blocks_only_one(set_pool):
    """The ceiling stays where CR 509.1a puts it for a creature printing none.

    The direction a table like this fails in is upward — a claim keyed loosely
    enough to match Wall of Glare would match every Wall in the pool — so the
    refusal is asserted beside the permission rather than assumed.
    """
    lea = set_pool("LEA")
    wall = Permanent(card=lea["Wall of Wood"])
    game = _g5_creature_combat(wall, [Permanent(card=lea["Grizzly Bears"])] * 2)
    assert game._max_blocks_for(wall) == 1

    blocked, why = game.declare_blockers(1, {0: [0, 1]})
    assert not blocked, why
