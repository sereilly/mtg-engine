"""Invasion artifacts.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_artifact_duel(set_pool, *, active: int = 0, library: int = 10):
    """Two non-interactive seats, costs off, on *active*'s turn."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * library)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(active)
    return game


def _w1g8_artifact_put(game, card, seat: int, *, tapped: bool = False):
    """*card* on *seat*'s battlefield, optionally already tapped."""
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = tapped
    return permanent


def test_tsabos_web_draws_a_card_when_it_enters(set_pool):
    """"When this artifact enters, draw a card." Cast from hand, the Web is
    replaced by the top card of the library."""
    game = _w1g8_artifact_duel(set_pool)
    game.players[0].hand = [set_pool("INV")["Tsabo's Web"]]

    assert game.cast_from_hand(0, "Tsabo's Web").supported
    _w1g8_resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Island"]


def test_tsabos_web_holds_down_lands_with_a_nonmana_activated_ability(set_pool):
    """"Each land with an activated ability that isn't a mana ability doesn't
    untap during its controller's untap step." Strip Mine (a sacrifice
    ability), Maze of Ith (no mana ability at all) and Drifting Meadow
    (cycling is an activated ability, CR 702.29a) stay tapped. Forest and
    Adarkar Wastes — whose second ability is a mana ability with a drawback,
    CR 605.1a — untap, and so does a nonland with an activated ability."""
    game = _w1g8_artifact_duel(set_pool, active=1)
    _w1g8_artifact_put(game, set_pool("INV")["Tsabo's Web"], 0)
    held = [
        _w1g8_artifact_put(game, set_pool(code)[name], 1, tapped=True)
        for code, name in (
            ("ATQ", "Strip Mine"), ("DRK", "Maze of Ith"), ("USG", "Drifting Meadow"),
        )
    ]
    free = [
        _w1g8_artifact_put(game, set_pool(code)[name], 1, tapped=True)
        for code, name in (
            ("LEA", "Forest"), ("ICE", "Adarkar Wastes"), ("LEA", "Icy Manipulator"),
        )
    ]

    game.resolve_untap_step(1)

    assert [permanent.card.name for permanent in held if permanent.tapped] == [
        "Strip Mine", "Maze of Ith", "Drifting Meadow",
    ]
    assert not any(permanent.tapped for permanent in free)


def test_tsabos_web_binds_its_own_controllers_lands_too(set_pool):
    """"…during **its controller's** untap step" — each land's own controller,
    not the Web's opponent only: the Web's controller's Strip Mine stays
    tapped on their own untap step."""
    game = _w1g8_artifact_duel(set_pool, active=0)
    _w1g8_artifact_put(game, set_pool("INV")["Tsabo's Web"], 0)
    mine = _w1g8_artifact_put(game, set_pool("ATQ")["Strip Mine"], 0, tapped=True)
    forest = _w1g8_artifact_put(game, set_pool("LEA")["Forest"], 0, tapped=True)

    game.resolve_untap_step(0)

    assert mine.tapped
    assert not forest.tapped
