"""Prophecy lands.

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


# --- W2G1: tolls, part two ---
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.mana_payment import plan_payment as _w2g1_plan_payment
from engine.mana_payment import untapped_mana_lands as _w2g1_payment_lands
from engine.models import Permanent as _W2G1Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile


def _w2g1_cave_on_the_opponents_turn(set_pool):
    """Rhystic Cave and an Island under seat 0, on seat 1's turn — the timing
    "Activate only as an instant" exists for."""
    game = _W2G1Game(players=[_W2G1PlayerState(name="P0"), _W2G1PlayerState(name="P1")])
    game.start_turn(1)
    game._close_current_priority_step()
    cave = _W2G1Permanent(card=set_pool("PCY")["Rhystic Cave"])
    island = _W2G1Permanent(card=set_pool("LEA")["Island"])
    for land in (cave, island):
        game._put_permanent_onto_battlefield(0, land, None)
        land.metadata["summoning_sickness_turn"] = -99
    return game, cave, island  # _w2g1_cave_on_the_opponents_turn


def test_w2g1_declined_rhystic_cave_makes_no_free_mana(set_pool):
    """Rhystic Cave is declined this wave (its mana can be denied by any
    player paying {1}, and nothing yet runs that offer inside a mana ability).
    What the decline must not leave behind is the land it would otherwise be:
    Scryfall's ``produced_mana`` summary says WUBRG, and both mana seams used to
    fall back to it for a land with no compiled mana ability — a free
    five-colour land that no player could deny, tappable on any turn.

    Neither seam reads the summary for a land the engine runs none of the text
    of: the payment planner does not count it, and tapping it adds nothing and
    taps nothing. The Island beside it is untouched by the rule.

    When the Cave lands, this test is the one to rewrite: the toll replaces it.
    """
    assert not _w2g1_compile(set_pool("PCY")["Rhystic Cave"]).supported
    game, cave, island = _w2g1_cave_on_the_opponents_turn(set_pool)

    assert _w2g1_payment_lands(game.controlled_by(0)) == [island]
    assert _w2g1_plan_payment({}, _w2g1_payment_lands(game.controlled_by(0)), {"R": 1}) is None

    assert game.tap_land_for_mana(0, "Rhystic Cave", "R", permanent_id=cave.permanent_id) is False
    assert not cave.tapped
    assert sum(game.players[0].mana_pool.values()) == 0

    assert game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)
    assert game.players[0].mana_pool["U"] == 1
# end of the W2G1 lands block
