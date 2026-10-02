"""Nemesis artifacts.

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
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w1g6_art_take_turn(game, seat):
    """Start *seat*'s turn and settle what its beginning phase put on the stack."""
    game.start_turn(seat)
    for _ in range(4):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    return game.turn


def _w1g6_kill_switch_board(set_pool, *, own_before_switch):
    """Kill Switch beside its controller's own artifact, in either board
    order, and one artifact on the other seat."""
    lea = set_pool("LEA")
    switch = Permanent(card=set_pool("NEM")["Kill Switch"])
    mine = Permanent(card=lea["Jayemdae Tome"])
    theirs = Permanent(card=lea["Howling Mine"])
    ours = [mine, switch] if own_before_switch else [switch, mine]
    players = [
        PlayerState(name="P0", battlefield=ours, library=[lea["Island"]] * 8),
        PlayerState(name="P1", battlefield=[theirs], library=[lea["Island"]] * 8),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game, switch, mine, theirs


@pytest.mark.parametrize("own_before_switch", [True, False])
def test_kill_switch_holds_the_artifacts_it_tapped_while_it_stays_tapped(
    set_pool, own_before_switch
):
    """"{2}, {T}: Tap all other artifacts. They don't untap during their
    controllers' untap steps for as long as this artifact remains tapped."

    "They" is the set the sweep named, by identity: not the Switch ("other"),
    and not an artifact that arrives afterwards. The opponent's artifact stays
    down through their untap step; the Switch's controller's own stays down
    through the very step the Switch untaps in, because CR 502.3 determines
    what untaps *before* untapping anything — in either board order, which is
    what the parametrize is for (the step used to read the lock live, so a
    Switch earlier in the list released what came after it).
    """
    game, switch, mine, theirs = _w1g6_kill_switch_board(
        set_pool, own_before_switch=own_before_switch
    )
    _w1g6_art_take_turn(game, 0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(0, "Kill Switch", ability_index=0)
    resolve_stack(game)

    assert result.supported, result.details
    assert switch.tapped and mine.tapped and theirs.tapped
    late = Permanent(card=set_pool("LEA")["Sol Ring"])
    game.players[1].battlefield.append(late)
    game._settle()
    late.tapped = True

    _w1g6_art_take_turn(game, 1)
    assert theirs.tapped, "held through its controller's untap step"
    assert not late.tapped, "an artifact the sweep never named is not held"

    _w1g6_art_take_turn(game, 0)
    assert not switch.tapped, "the Switch prints no choice to stay tapped"
    assert mine.tapped, "held through the step the Switch untapped in"

    _w1g6_art_take_turn(game, 1)
    assert not theirs.tapped, "released once the Switch untapped"
    _w1g6_art_take_turn(game, 0)
    assert not mine.tapped
