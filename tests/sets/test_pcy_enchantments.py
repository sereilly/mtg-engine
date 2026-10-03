"""Prophecy enchantments.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: spell costs ---
from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_entangler_combat(set_pool, *, enchant: bool):
    """Three attacking Bears against P2's lone Wall of Wood, with Entangler
    cast by P2 onto the Wall first when *enchant* — through the real cast, so
    the picker's target and the attachment are the engine's own."""
    lea = set_pool("LEA")
    wall = _W1G2Permanent(card=lea["Wall of Wood"])
    bears = [_W1G2Permanent(card=lea["Grizzly Bears"]) for _ in range(3)]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name="P1", battlefield=list(bears)),
        _W1G2PlayerState(
            name="P2", battlefield=[wall], hand=[set_pool("PCY")["Entangler"]]
        ),
    ])
    game._sync_control()
    game.enforce_mana_costs = False
    if enchant:
        game.start_turn(1)
        result = game.cast_from_hand(
            1, "Entangler", target_player_index=1, target_permanent_index=0,
            target_permanent_ids=[wall.permanent_id],
        )
        assert result.supported, result.details
        _w1g2_resolve_stack(game)
    for bear in bears:
        bear.summoning_sick = False
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    declared, why = game.declare_attackers(0, [0, 1, 2], 1)
    assert declared, why
    game.advance_combat_phase()
    return game, wall


def test_w1g2_entangler_lets_the_enchanted_creature_block_every_attacker(set_pool):
    """"Enchanted creature can block any number of creatures." (CR 509.1b.)

    Wall of Glare's permission one sentence-subject over, asked of the Auras
    attached when blockers are declared — the same table, with "enchanted"
    rewritten to "this", so the two printings cannot come to mean different
    ceilings. Unenchanted, the same Wall blocks one.
    """
    program = _w1g2_compile(set_pool("PCY")["Entangler"])
    assert program.supported, program.reason

    game, wall = _w1g2_entangler_combat(set_pool, enchant=True)
    assert game._max_blocks_for(wall) >= 3
    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert blocked, why

    game, wall = _w1g2_entangler_combat(set_pool, enchant=False)
    assert game._max_blocks_for(wall) == 1
    blocked, why = game.declare_blockers(1, {0: [0, 1, 2]})
    assert not blocked, why


def test_w1g2_entanglers_permission_ends_with_the_aura(set_pool):
    """Nothing is stamped on the creature: the ceiling is read off the Aura
    while it is attached, so destroying the Aura takes the permission with it
    and nothing has to remember to clear a flag."""
    game, wall = _w1g2_entangler_combat(set_pool, enchant=True)
    entangler = next(
        p for p in game.all_permanents() if p.card.name == "Entangler"
    )
    assert game._max_blocks_for(wall) > 1
    game.remove_from_battlefield(entangler)
    assert game._max_blocks_for(wall) == 1
