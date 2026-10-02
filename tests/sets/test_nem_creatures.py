"""Nemesis creatures.

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

Cards come from `set_pool("NEM")` / `set_cards("NEM")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: lands, mana and untapping ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_crt_upkeep(game, seat):
    """Start *seat*'s turn and settle every trigger its upkeep put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return seat


def _w1g6_bears(set_pool, count):
    return [Permanent(card=set_pool("LEA")["Grizzly Bears"]) for _ in range(count)]


def test_wild_mammoth_goes_to_the_player_with_the_most_creatures(set_pool):
    """"At the beginning of your upkeep, if a player controls more creatures
    than each other player, the player who controls the most creatures gains
    control of this creature."

    CR 603.4's intervening-if over a strict superlative: a tie names nobody, so
    the trigger does not even fire. When the other seat is ahead the Mammoth
    goes to them, and "your upkeep" is the new controller's from then on — so
    the *old* controller's upkeep does nothing, and the new one's moves it back
    once the count has turned round.
    """
    island = set_pool("LEA")["Island"]
    mammoth = Permanent(card=set_pool("NEM")["Wild Mammoth"])
    p0 = PlayerState(name="P0", battlefield=[mammoth, *_w1g6_bears(set_pool, 1)],
                     library=[island] * 8)
    p1 = PlayerState(name="P1", battlefield=_w1g6_bears(set_pool, 2),
                     library=[island] * 8)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()

    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 0, "two against two is a tie"
    assert not any("gains control of Wild Mammoth" in line for line in game.log)

    p1.battlefield.append(_w1g6_bears(set_pool, 1)[0])
    game._settle()
    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 1
    assert "P1 gains control of Wild Mammoth" in game.log

    p0.battlefield.extend(_w1g6_bears(set_pool, 4))
    game._settle()
    _w1g6_crt_upkeep(game, 0)
    assert game.controller_index_of(mammoth) == 1, (
        "P0's upkeep is no longer the Mammoth controller's upkeep"
    )
    _w1g6_crt_upkeep(game, 1)
    assert game.controller_index_of(mammoth) == 0, (
        "five creatures against four, the Mammoth itself counted on P1's side"
    )
