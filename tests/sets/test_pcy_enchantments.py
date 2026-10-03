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


# --- W1G3: activation costs ---
# Brutal Suppression: "Activated abilities of nontoken Rebels cost an additional
# "Sacrifice a land" to activate." Drought's imposed sacrifice
# (``cost_modifiers.sacrifice_taxes``) with its subject read off the ability's
# source — so it is charged, it refuses with nothing paid when no land can pay
# it, and a token Rebel or a non-Rebel is untouched.

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack


def _w1g3_suppressed(set_pool, mine, *, token_rebel=False):
    """Seat 1 controls Brutal Suppression; seat 0 holds *mine*, turn 0 begun.
    *token_rebel* marks seat 0's first permanent as a token."""
    me = [Permanent(card=card) for card in mine]
    if token_rebel:
        me[0].metadata["is_token"] = True
    suppression = Permanent(card=set_pool("PCY")["Brutal Suppression"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=list(me)),
        PlayerState(name="P1", battlefield=[suppression]),
    ])
    game.enforce_mana_costs = False
    for permanent in me:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, me


def test_w1g3_brutal_suppression_charges_a_rebel_a_land(set_pool):
    """Rappelling Scouts (a Human Rebel Scout) pays a land on top of its {2}{W},
    and its ability still resolves."""
    lea = set_pool("LEA")
    game, (scouts, forest) = _w1g3_suppressed(
        set_pool, [set_pool("MMQ")["Rappelling Scouts"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")
    assert result.supported, result.details
    resolve_stack(game)

    assert not game.is_on_battlefield(forest)
    assert [c.name for c in game.players[0].graveyard] == ["Forest"]
    assert ("color", "B") in game._protection_qualities(scouts)


def test_w1g3_brutal_suppression_with_no_land_refuses_before_paying(set_pool):
    """CR 601.2h via 602.2b: an additional cost that cannot be paid makes the
    ability unactivatable — refused with nothing on the stack and nothing paid."""
    game, (scouts,) = _w1g3_suppressed(set_pool, [set_pool("MMQ")["Rappelling Scouts"]])
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")

    assert not result.supported
    assert "Land" in result.details and "Brutal Suppression" in result.details
    assert game.stack == [] and game._protection_qualities(scouts) == set()


def test_w1g3_brutal_suppression_spares_tokens_and_non_rebels(set_pool):
    """"Nontoken Rebels": a token Rebel's ability and a Drudge Skeletons'
    regeneration are activated with every land left where it was."""
    lea = set_pool("LEA")
    game, (scouts, forest) = _w1g3_suppressed(
        set_pool, [set_pool("MMQ")["Rappelling Scouts"], lea["Forest"]],
        token_rebel=True,
    )
    result = game.queue_permanent_ability(0, "Rappelling Scouts", mana_color="B")
    assert result.supported, result.details
    resolve_stack(game)
    assert game.is_on_battlefield(forest)

    game, (_skeletons, forest) = _w1g3_suppressed(
        set_pool, [lea["Drudge Skeletons"], lea["Forest"]],
    )
    result = game.queue_permanent_ability(0, "Drudge Skeletons")
    assert result.supported, result.details
    assert game.is_on_battlefield(forest)
