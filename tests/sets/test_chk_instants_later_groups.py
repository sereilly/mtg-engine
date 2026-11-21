"""Champions of Kamigawa instants — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), library=None, opponent_library=None,
                opponent_hand=(), mine=(), theirs=(), interactive=()):
    """Two seats on seat 0's first main phase, costs off; libraries top
    first. Names resolve in CHK first, then the older sets the tests use."""
    pools = [set_pool(code) for code in ("CHK", "LEA", "MRD", "TMP")]

    def named(name):
        for pool in pools:
            if name in pool:
                return pool[name]
        raise KeyError(name)

    game = _W1G7Game(players=[
        _W1G7PlayerState(
            "P0", hand=[named(n) for n in hand],
            library=[named(n) for n in (library or ["Forest"] * 10)],
        ),
        _W1G7PlayerState(
            "P1", hand=[named(n) for n in opponent_hand],
            library=[named(n) for n in (opponent_library or ["Island"] * 10)],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G7Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def test_w1g7_peer_through_depths_takes_an_instant_or_sorcery(set_pool):
    game = _w1g7_table(
        set_pool, hand=["Peer Through Depths"],
        library=["Forest", "Grizzly Bears", "Lightning Bolt", "Wrath of God",
                 "Craw Wurm", "Island"],
        interactive={0},
    )
    assert game.cast_from_hand(0, "Peer Through Depths").supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "look_top_pick"
    offered = game.live_look_top_candidates(asked)
    assert [game.players[0].library[i].name for i in offered] == [
        "Lightning Bolt", "Wrath of God",
    ]
    assert not game.confirm_look_top_pick(0, 1)          # a creature card
    assert game.confirm_look_top_pick(0, 3)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Wrath of God"]
    library = _w1g7_names(game.players[0].library)
    assert library[0] == "Island"
    assert sorted(library[1:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt", "Craw Wurm"]
    )


def _w1g7_hinder_a_bolt(set_pool, interactive):
    game = _w1g7_table(
        set_pool, hand=["Hinder"], opponent_hand=["Lightning Bolt"],
        opponent_library=["Island", "Swamp"], interactive=interactive,
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Hinder", target_stack_index=0).supported
    return game


def test_w1g7_hinder_puts_the_countered_card_on_the_end_its_caster_picks(set_pool):
    """Its ruling (2020-08-07): Hinder's controller chooses the end."""
    for to_bottom, expected in (
        (False, ["Lightning Bolt", "Island", "Swamp"]),
        (True, ["Island", "Swamp", "Lightning Bolt"]),
    ):
        game = _w1g7_hinder_a_bolt(set_pool, interactive={0, 1})
        asked = _w1g7_settle(game, defaults=False)
        assert asked.kind == "library_end_choice" and asked.player_index == 0
        assert asked.data["moved_name"] == "Lightning Bolt"
        _w1g7_settle(game, answers={
            "library_end_choice":
                lambda g, c: g.confirm_library_end_choice(c.player_index, to_bottom),
        })
        assert _w1g7_names(game.players[1].library) == expected
        assert game.players[1].graveyard == []
        assert game.players[0].life == 20          # the Bolt was countered
        assert _w1g7_names(game.players[0].graveyard) == ["Hinder"]


def test_w1g7_hinder_at_a_seat_nobody_asks_buries_the_card(set_pool):
    game = _w1g7_hinder_a_bolt(set_pool, interactive=())
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].library) == ["Island", "Swamp", "Lightning Bolt"]
    assert game.players[0].life == 20

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
