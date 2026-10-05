"""Planeshift sorceries.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour ---
# An arrival card: supported on the day of the ingest and never run until now.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine import targeting as _w1g6_targeting
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_strafe_table(set_pool, swapped):
    """A green Wurm and a red Giant across the table, with their colours
    swapped for the turn through layer 5 when *swapped*; seat 0 holds two
    Strafes. Returns the game, the creature that is nonred now and the one
    that is red now."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.active_player_index = 0
    wurm = _W1G6Permanent(card=set_pool("LEA")["Craw Wurm"])
    giant = _W1G6Permanent(card=set_pool("LEA")["Hill Giant"])
    for perm in (wurm, giant):
        w1g6_game._put_permanent_onto_battlefield(1, perm, None)
    if swapped:
        wurm.metadata["color_override_until_eot"] = "R"
        giant.metadata["color_override_until_eot"] = "G"
        w1g6_game._recompute_continuous_effects()
    w1g6_game.players[0].hand.extend([set_pool("PLS")["Strafe"]] * 2)
    nonred, red = (giant, wurm) if swapped else (wurm, giant)
    return w1g6_game, nonred, red  # _w1g6_strafe_table


def test_w1g6_strafe_may_only_be_aimed_at_a_creature_that_is_not_red_right_now(set_pool):
    """"Strafe deals 3 damage to target nonred creature." The exclusion is
    layer 5's: the red Giant is refused and the green Wurm takes 3; with the
    two colours swapped for the turn, the Giant (green now) is the legal
    target and the Wurm (red now) is not."""
    strafe = set_pool("PLS")["Strafe"]
    assert _w1g6_targeting.derive_cast_spec(strafe, _w1g6_compile(strafe)) == {
        "kind": "creature", "filter": {"exclude_colors": ["R"]},
    }
    for swapped in (False, True):
        game, nonred, red = _w1g6_strafe_table(set_pool, swapped)
        assert not game.queue_from_hand(0, "Strafe", target_permanent_ids=[red.permanent_id]).supported
        assert len(game.players[0].hand) == 2, "a refused cast spends nothing"
        assert game.queue_from_hand(0, "Strafe", target_permanent_ids=[nonred.permanent_id]).supported
        _w1g6_resolve_stack(game)
        game.check_state_based_actions()
        assert red.damage_marked == 0
        assert nonred.damage_marked == 3 or not game.is_on_battlefield(nonred)
