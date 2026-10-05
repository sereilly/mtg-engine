"""Invasion instants.

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


# --- W1G3: domain ---
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_cast_spec as _w1g3_cast_spec
from tests.helpers import resolve_stack as _w1g3_resolve

_W1G3_LIBRARY = [
    "Grizzly Bears", "Craw Wurm", "Lightning Bolt", "Giant Growth",
    "Counterspell", "Dark Ritual",
]


def _w1g3_counsel(set_pool, lands, *, interactive=True):
    """Worldly Counsel cast by seat 0 over a six-card library of known order,
    with *lands* on its side. Stops with the look's prompt owed."""
    w1g3_lea = set_pool("LEA")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(
            name="W1G3-A",
            hand=[set_pool("INV")["Worldly Counsel"]],
            library=[w1g3_lea[name] for name in _W1G3_LIBRARY],
        ),
        _W1G3PlayerState(name="W1G3-B"),
    ])
    w1g3_game.enforce_mana_costs = False
    w1g3_game.active_player_index = 0
    if interactive:
        w1g3_game.interactive_seats = {0}
    for w1g3_name in lands:
        w1g3_game._put_permanent_onto_battlefield(
            0, _W1G3Permanent(card=w1g3_lea[w1g3_name]), None
        )
    assert w1g3_game.cast_from_hand(0, "Worldly Counsel").supported
    w1g3_game.resolve_top_of_stack()
    return w1g3_game  # _w1g3_counsel


def test_w1g3_worldly_counsel_chooses_nothing_as_it_is_cast(set_pool):
    """It has no target; the look is a decision made as it resolves."""
    card = set_pool("INV")["Worldly Counsel"]
    spec = _w1g3_cast_spec(card, _w1g3_compile(card))
    assert spec is None or spec.get("kind") == "none"


def test_w1g3_worldly_counsel_looks_at_one_card_per_basic_land_type(set_pool):
    """"Look at the top X cards of your library, where X is the number of basic
    land types among lands you control. Put one of those cards into your hand
    and the rest on the bottom of your library in any order." Three types (a
    Plains and a Tropical Island) offer the top three, not the top two."""
    game = _w1g3_counsel(set_pool, ["Plains", "Tropical Island"])
    [owed] = [c for c in game.pending_choices if c.kind == "look_top_pick"]
    assert owed.player_index == 0 and owed.data["top_count"] == 3

    assert game.confirm_look_top_pick(0, 1)
    _w1g3_resolve(game)
    me = game.players[0]
    assert [card.name for card in me.hand] == ["Craw Wurm"]
    assert [card.name for card in me.library] == [
        "Giant Growth", "Counterspell", "Dark Ritual",
        "Grizzly Bears", "Lightning Bolt",
    ], "the two not taken go to the bottom"
    assert [card.name for card in me.graveyard] == ["Worldly Counsel"]


def test_w1g3_worldly_counsel_cannot_reach_past_its_domain(set_pool):
    """Two Forests are one type: only the top card is offered, and an answer
    naming the second card is refused with the prompt still owed."""
    game = _w1g3_counsel(set_pool, ["Forest", "Forest"])
    [owed] = [c for c in game.pending_choices if c.kind == "look_top_pick"]
    assert owed.data["top_count"] == 1
    assert not game.confirm_look_top_pick(0, 1)
    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 0)
    assert [card.name for card in game.players[0].hand] == ["Grizzly Bears"]


def test_w1g3_worldly_counsel_with_no_basic_land_types_looks_at_nothing(set_pool):
    """X is 0: no prompt, no card, and the library is untouched."""
    game = _w1g3_counsel(set_pool, [])
    _w1g3_resolve(game)
    me = game.players[0]
    assert not game.pending_choices
    assert not me.hand
    assert [card.name for card in me.library] == _W1G3_LIBRARY
    assert "W1G3-A has no cards to look at" in game.log


def test_w1g3_worldly_counsel_a_headless_seat_takes_the_default(set_pool):
    """A non-interactive seat is never left owing the look."""
    game = _w1g3_counsel(
        set_pool, ["Plains", "Island", "Swamp", "Mountain", "Forest"],
        interactive=False,
    )
    _w1g3_resolve(game)
    game.auto_resolve_pending_choices()
    me = game.players[0]
    assert not game.pending_choices and not game.stack
    assert len(me.hand) == 1 and len(me.library) == 5
