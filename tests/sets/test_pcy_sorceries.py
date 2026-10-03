"""Prophecy sorceries.

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


# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blessed_wind_table(set_pool, *, mine, theirs):
    """Blessed Wind in seat 0's hand, the two life totals given. W1G5's own."""
    me = _W1G5PlayerState(name="W1G5-A", hand=[set_pool("PCY")["Blessed Wind"]])
    me.life = mine
    them = _W1G5PlayerState(name="W1G5-B")
    them.life = theirs
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    return game, me, them


def test_w1g5_blessed_wind_sets_the_target_players_life_to_twenty(set_pool):
    """"Target player's life total becomes 20."

    CR 119.5 in both directions: aimed at an opponent on 31 it is a loss of 11,
    aimed at its caster on 4 a gain of 16 — and the seat is the one announced,
    not a default: the other player's total does not move either time.
    """
    card = set_pool("PCY")["Blessed Wind"]
    game, me, them = _w1g5_blessed_wind_table(set_pool, mine=4, theirs=31)
    spec = game.cast_target_spec(0, card)
    assert spec["kind"] == "player"
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}

    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=1).supported
    _w1g5_resolve_stack(game)
    assert (me.life, them.life) == (4, 20)

    game, me, them = _w1g5_blessed_wind_table(set_pool, mine=4, theirs=31)
    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (me.life, them.life) == (20, 31)
    assert any("life total became 20 (was 4)" in line for line in game.log)


def test_w1g5_blessed_wind_gain_half_is_a_life_gain(set_pool):
    """The gain is an event, not an assignment (CR 119.5): a seat that can't
    gain life (CR 119.7) stays where it was, which an assignment would ignore.
    """
    from engine.models import Permanent

    game, me, _them = _w1g5_blessed_wind_table(set_pool, mine=7, theirs=20)
    game._put_permanent_onto_battlefield(
        1, Permanent(card=set_pool("MIR")["Forsaken Wastes"]), None,
    )
    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert me.life == 7, "Forsaken Wastes: players can't gain life"
# end of the W1G5 sorceries block
