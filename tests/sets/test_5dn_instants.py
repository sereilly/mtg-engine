"""Fifth Dawn instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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
#
# Plunge into Darkness: "Pay any amount of life, then look at that many
# cards", a resolution-time number that sizes the look; entwined, both modes
# in printed order.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), mine=(), library=(), interactive=()):
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}",
            library=list(library) if seat == 0 else [set_pool("LEA")["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    placed = []
    for card in mine:
        permanent = _W1G7Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    _w1g7_settle(game)
    return game, placed


def _w1g7_library(set_pool):
    lea = set_pool("LEA")
    return [lea[name] for name in (
        "Forest", "Island", "Swamp", "Mountain", "Plains", "Grizzly Bears",
        "Hill Giant", "Llanowar Elves",
    )]


def test_w1g7_plunge_into_darkness_pays_the_life_it_names_and_looks_that_deep(set_pool):
    """The second mode, its ruling (2004-12-01): "choose X, pay X life, look
    at the top X cards of your library, put one into your hand, and exile the
    rest" — all on resolution. Driven as an interactive seat: the number
    prompt offers 0 up to the life total (CR 119.4), 3 is paid, and the look
    is three cards deep; the pick of the Swamp sends the other two to exile."""
    plunge = set_pool("5DN")["Plunge into Darkness"]
    game, _ = _w1g7_table(
        set_pool, hand=[plunge], library=_w1g7_library(set_pool), interactive=(0,),
    )
    player = game.players[0]

    result = game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    assert result.supported, result
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "number_choice"
    assert (owed.data["minimum"], owed.data["maximum"]) == (0, 20)
    assert game.confirm_number_choice(0, 3)
    assert player.life == 17
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "look_top_pick"
    assert owed.data["top_count"] == 3
    swamp = next(card for card in player.library[:3] if card.name == "Swamp")
    assert game.confirm_look_top_pick(0, player.library.index(swamp))
    _w1g7_settle(game)

    assert [card.name for card in player.hand] == ["Swamp"]
    assert sorted(card.name for card in player.exile) == ["Forest", "Island"]
    assert [card.name for card in player.library[:1]] == ["Mountain"]
    assert "Plunge into Darkness: P0 paid 3 life (20 -> 17)" in game.log


def test_w1g7_plunge_into_darkness_unasked_pays_a_measured_amount(set_pool):
    """A seat nobody asks names a real amount and keeps clear of the life
    the AI holds back from every optional price (``life_paid_for_a_look``):
    four at 20 life, nothing at 10 — and a payment of nothing looks at
    nothing."""
    plunge = set_pool("5DN")["Plunge into Darkness"]
    game, _ = _w1g7_table(set_pool, hand=[plunge], library=_w1g7_library(set_pool))
    player = game.players[0]

    game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    _w1g7_settle(game)

    assert player.life == 16
    assert len(player.hand) == 1 and len(player.exile) == 3
    assert len(player.library) == 4

    game, _ = _w1g7_table(set_pool, hand=[plunge], library=_w1g7_library(set_pool))
    player = game.players[0]
    player.life = 10
    game.cast_from_hand(0, "Plunge into Darkness", mode_index=1)
    _w1g7_settle(game)

    assert player.life == 10
    assert player.hand == [] and player.exile == []
    assert len(player.library) == 8


def test_w1g7_plunge_into_darkness_entwined_sacrifices_then_pays(set_pool):
    """Entwine {B}: both modes in printed order (CR 702.42b; the ruling's
    (1)–(5)) — the creatures go, 3 life comes back for each, and only then is
    the life chosen and paid, so the gain can fund a deeper look."""
    pool = set_pool("5DN")
    lea = set_pool("LEA")
    plunge = pool["Plunge into Darkness"]
    game, (bear, elves) = _w1g7_table(
        set_pool, hand=[plunge], library=_w1g7_library(set_pool),
        mine=[lea["Grizzly Bears"], lea["Llanowar Elves"]], interactive=(0,),
    )
    player = game.players[0]
    player.life = 11

    result = game.cast_from_hand(
        0, "Plunge into Darkness", optional_cost_payments={"{B}": 1},
    )
    assert result.supported, result
    assert game.pending_sacrifice is not None
    assert game.confirm_sacrifice(0, [0, 1]) is True
    owed = _w1g7_settle(game, defaults=False)
    assert owed is not None and owed.kind == "number_choice"
    assert player.life == 17 and owed.data["maximum"] == 17
    game.confirm_number_choice(0, 2)
    _w1g7_settle(game)

    assert player.battlefield == []
    assert player.life == 15
    assert len(player.hand) == 1 and len(player.exile) == 1

# ==== end w1g7 ======================================================
