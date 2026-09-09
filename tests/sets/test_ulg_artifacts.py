"""Urza's Legacy artifacts.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: zones — hands, graveyards, libraries ---
from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack


def _g5_jar_board(pool, lea, first_hand, second_hand) -> Game:
    """Memory Jar on seat 0's battlefield, both seats holding what is named.

    The libraries are deep enough for two sevens; the artifact is unsick because
    its ability taps. Its own tail (the `_sync_control` and the return of the
    permanent) so a mechanical union cannot splice another group's helper body
    onto this signature.
    """
    p1 = PlayerState(name="P1", library=[lea["Mountain"]] * 20, hand=list(first_hand))
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 20, hand=list(second_hand))
    board = Game(players=[p1, p2])
    board.enforce_mana_costs = False
    board.interactive_seats = set()
    jar = Permanent(card=pool["Memory Jar"])
    jar.metadata["summoning_sickness_turn"] = -99
    board.players[0].battlefield.append(jar)
    board._sync_control()
    return board


def test_w1g5_memory_jar_exiles_every_hand_and_deals_seven(set_pool):
    """"Each player exiles all cards from their hand face down and draws seven
    cards." One act per seat, not the caster's hand alone — the printed subject
    is the whole difference and a dropped one would empty one hand where the
    card empties the table's."""
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(
        pool, lea, [lea["Black Lotus"], lea["Mox Jet"]], [lea["Healing Salve"]],
    )

    result = game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    assert result.supported is True
    assert len(game.players[0].hand) == 7
    assert len(game.players[1].hand) == 7
    assert [c.name for c in game.players[0].exile] == ["Black Lotus", "Mox Jet"]
    assert [c.name for c in game.players[1].exile] == ["Healing Salve"]
    # The sacrifice was a cost, so the artifact is gone before anything resolved.
    assert game.players[0].battlefield == []
    assert [t.event for t in game.delayed_triggers] == ["next_end_step"]


def test_w1g5_memory_jar_gives_each_seat_back_its_own_pile_at_the_next_end_step(
    set_pool,
):
    """CR 603.7's delayed ability, and the half that could only go wrong one
    way: "each card **they** exiled this way" is asked once per player, so a
    flat record read once per seat would hand each of them the whole table's
    hands.

    The record survives the delay because the creating resolution's scratchpad
    is frozen onto the entry (CR 603.7d) — which is what makes this reachable at
    all, since the artifact was sacrificed as a cost and no permanent is left to
    hang a linked pile on.
    """
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(
        pool, lea, [lea["Black Lotus"], lea["Mox Jet"]], [lea["Healing Salve"]],
    )
    game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    game.resolve_end_step(0)
    resolve_stack(game)

    assert [c.name for c in game.players[0].hand] == ["Black Lotus", "Mox Jet"]
    assert [c.name for c in game.players[1].hand] == ["Healing Salve"]
    assert game.players[0].exile == []
    assert game.players[1].exile == []
    # The seven drawn cards were discarded, and Memory Jar itself is in the
    # graveyard it was sacrificed into.
    assert len(game.players[0].graveyard) == 8
    assert len(game.players[1].graveyard) == 7


def test_w1g5_memory_jar_still_deals_seven_to_a_seat_that_held_nothing(set_pool):
    """An empty hand exiles nothing and draws seven anyway — CR 608.2 does as
    much as it can, and the two halves of the sentence are not conditional on
    each other."""
    pool, lea = set_pool("ULG"), set_pool("LEA")
    game = _g5_jar_board(pool, lea, [lea["Black Lotus"]], [])

    game.activate_permanent_ability(0, "Memory Jar", ability_index=0)
    resolve_stack(game)

    assert len(game.players[1].hand) == 7
    assert game.players[1].exile == []

    game.resolve_end_step(0)
    resolve_stack(game)

    # Nothing came back for the seat that exiled nothing; its hand is empty.
    assert game.players[1].hand == []
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]
