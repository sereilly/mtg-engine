"""Champions of Kamigawa sorceries.

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


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


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
                opponent_hand=(), opponent_graveyard=(), mine=(), theirs=(),
                interactive=()):
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
            graveyard=[named(n) for n in opponent_graveyard],
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


_W1G7_LOOKED = [
    "Forest", "Grizzly Bears", "Lightning Bolt", "Dark Ritual", "Craw Wurm",
    "Island", "Swamp",
]


def test_w1g7_commune_with_nature_takes_a_creature_and_bottoms_the_rest(set_pool):
    game = _w1g7_table(
        set_pool, hand=["Commune with Nature"], library=_W1G7_LOOKED,
        interactive={0},
    )
    assert game.cast_from_hand(0, "Commune with Nature").supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "look_top_pick" and asked.data["top_count"] == 5
    # Only the creature cards among the five are offered.
    offered = game.live_look_top_candidates(asked)
    assert [game.players[0].library[i].name for i in offered] == [
        "Grizzly Bears", "Craw Wurm",
    ]
    # A noncreature card is refused.
    assert not game.confirm_look_top_pick(0, 2)
    assert game.confirm_look_top_pick(0, 4)
    # "in any order": the looker is asked to arrange the bottom.
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "reorder_library" and asked.data["position"] == "bottom"
    assert asked.data["top_count"] == 4
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Craw Wurm"]
    library = _w1g7_names(game.players[0].library)
    assert library[:2] == ["Island", "Swamp"]
    assert sorted(library[2:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt", "Dark Ritual"]
    )


def test_w1g7_commune_with_nature_may_take_nothing(set_pool):
    """Its ruling (2004-12-01): no creature revealed, all five go to the
    bottom."""
    game = _w1g7_table(
        set_pool, hand=["Commune with Nature"],
        library=["Forest", "Island", "Lightning Bolt", "Swamp", "Mountain",
                 "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Commune with Nature").supported
    _w1g7_settle(game)
    assert game.players[0].hand == []
    library = _w1g7_names(game.players[0].library)
    assert library[0] == "Grizzly Bears" and len(library) == 6


def _w1g7_petals(set_pool, accept):
    game = _w1g7_table(
        set_pool, hand=["Petals of Insight"],
        library=["Forest", "Grizzly Bears", "Lightning Bolt", "Island", "Swamp"],
        interactive={0},
    )
    assert game.cast_from_hand(0, "Petals of Insight").supported
    asked = _w1g7_settle(game, defaults=False)
    # The offer is made having seen the three cards (CR 701.20e).
    assert asked.kind == "optional_pay"
    assert asked.data["looked_at"] == ["Forest", "Grizzly Bears", "Lightning Bolt"]
    _w1g7_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=accept),
    })
    return game


def test_w1g7_petals_of_insight_bottoms_the_three_and_returns_to_hand(set_pool):
    game = _w1g7_petals(set_pool, accept=True)
    player = game.players[0]
    # Its ruling (2013-06-07): it returns to the hand straight from the stack.
    assert _w1g7_names(player.hand) == ["Petals of Insight"]
    assert player.graveyard == []
    assert _w1g7_names(player.library)[:2] == ["Island", "Swamp"]
    assert sorted(_w1g7_names(player.library)[2:]) == sorted(
        ["Forest", "Grizzly Bears", "Lightning Bolt"]
    )


def _w1g7_extraction(set_pool, interactive=()):
    game = _w1g7_table(
        set_pool, hand=["Cranial Extraction"], interactive=interactive,
        opponent_hand=["Lightning Bolt", "Grizzly Bears", "Lightning Bolt"],
        opponent_library=["Island", "Lightning Bolt", "Swamp", "Lightning Bolt", "Craw Wurm"],
        opponent_graveyard=["Lightning Bolt", "Forest"],
    )
    assert game.cast_from_hand(0, "Cranial Extraction", target_player_index=1).supported
    return game


def test_w1g7_cranial_extraction_exiles_every_copy_of_the_named_card(set_pool):
    game = _w1g7_extraction(set_pool, interactive={0})
    asked = _w1g7_settle(game, defaults=False)
    assert asked.kind == "choose_card_name"
    # "a nonland card name": a land's name is refused.
    assert not game.confirm_choose_card_name(0, "Island")
    _w1g7_settle(game, answers={
        "choose_card_name": lambda g, c: g.confirm_choose_card_name(0, "Lightning Bolt"),
    })
    victim = game.players[1]
    assert _w1g7_names(victim.exile) == ["Lightning Bolt"] * 5
    assert _w1g7_names(victim.hand) == ["Grizzly Bears"]
    assert _w1g7_names(victim.graveyard) == ["Forest"]
    assert sorted(_w1g7_names(victim.library)) == ["Craw Wurm", "Island", "Swamp"]
    assert game.players[0].exile == []


def test_w1g7_cranial_extraction_at_a_seat_nobody_asks_names_from_public_evidence(set_pool):
    """The default names what the target's graveyard shows (CR 400.2), and
    the strip finds the hidden copies too."""
    game = _w1g7_extraction(set_pool)
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].exile) == ["Lightning Bolt"] * 5


def test_w1g7_petals_of_insight_otherwise_draws_three(set_pool):
    game = _w1g7_petals(set_pool, accept=False)
    player = game.players[0]
    assert _w1g7_names(player.hand) == ["Forest", "Grizzly Bears", "Lightning Bolt"]
    assert _w1g7_names(player.graveyard) == ["Petals of Insight"]
    assert _w1g7_names(player.library) == ["Island", "Swamp"]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
