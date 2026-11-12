"""Fifth Dawn sorceries.

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

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_cast_spec as _w1g3_derive_cast_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_table(set_pool, *, hand=(), graveyard=(), opponent_graveyard=(), interactive=()):
    """Two seats on seat 0's first main phase with ten-card libraries."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 10,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard if seat == 0 else opponent_graveyard),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    return game


def _w1g3_put(game, seat, card):
    permanent = _W1G3Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_settle(game)
    return permanent


def _w1g3_where(game, name):
    return [
        f"{seat}.{zone}"
        for seat, player in enumerate(game.players)
        for zone in ("hand", "library", "graveyard", "exile")
        for card in getattr(player, zone)
        if card.name == name
    ]


def _w1g3_cast_spec(card):
    return _w1g3_derive_cast_spec(card, _w1g3_compile(card))


def _w1g3_board(game, seat):
    return [p.card.name for p in game.controlled_by(seat)]


def test_w1g3_beacon_of_creation_counts_your_forests_and_shuffles_away(set_pool):
    """"Create a 1/1 green Insect creature token for each Forest you control.
    Shuffle Beacon of Creation into its owner's library." Three Forests of
    the caster's (not the opponent's one), three Insects, and the Beacon in
    the library."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(set_pool, hand=[fdn["Beacon of Creation"]])
    for _ in range(3):
        _w1g3_put(game, 0, lea["Forest"])
    _w1g3_put(game, 1, lea["Forest"])
    assert game.cast_from_hand(0, "Beacon of Creation").supported
    _w1g3_settle(game)

    insects = [p for p in game.controlled_by(0) if p.card.name == "Insect Token"]
    assert len(insects) == 3
    assert all((p.effective_power, p.effective_toughness) == (1, 1) for p in insects)
    assert _w1g3_where(game, "Beacon of Creation") == ["0.library"]
    assert len(game.players[0].library) == 11


def test_w1g3_beacon_of_creation_flashed_back_is_exiled_and_still_shuffles(set_pool):
    """CR 702.34a exiles a flashed-back spell "instead of putting it anywhere
    else", the library included — and CR 701.24c shuffles the library all the
    same (its own example: Black Sun's Zenith cast with flashback). Recoup
    grants the flashback; Psychogenic Probe hears the shuffle."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[set_pool("ODY")["Recoup"]], graveyard=[fdn["Beacon of Creation"]],
    )
    _w1g3_put(game, 0, lea["Forest"])
    _w1g3_put(game, 1, set_pool("MRD")["Psychogenic Probe"])
    assert game.cast_from_hand(
        0, "Recoup", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert game.cast_from_hand(0, "Beacon of Creation", from_zone="graveyard").supported
    _w1g3_settle(game)

    assert _w1g3_board(game, 0).count("Insect Token") == 1
    assert _w1g3_where(game, "Beacon of Creation") == ["0.exile"]
    assert len(game.players[0].library) == 10
    assert game.players[0].life == 18, "the library was shuffled"


def test_w1g3_beacon_of_tomorrows_gives_the_target_player_the_extra_turn(set_pool):
    """"Target player takes an extra turn after this one." Any player — the
    picker offers both seats — and the seat named is the one owed the turn
    (Time Warp's handler, CR 500.7), the caster's own when it names itself."""
    fdn = set_pool("5DN")
    beacon = fdn["Beacon of Tomorrows"]
    spec = _w1g3_cast_spec(beacon)
    assert spec is not None and spec.get("kind") == "player", spec
    assert not spec.get("opponent_only")

    for seat in (1, 0):
        game = _w1g3_table(set_pool, hand=[beacon])
        assert game.cast_from_hand(
            0, "Beacon of Tomorrows", target_player_index=seat,
        ).supported
        _w1g3_settle(game)
        assert _w1g3_where(game, "Beacon of Tomorrows") == ["0.library"]
        assert game.extra_turns.get(seat, 0) == 1
        assert game.extra_turns.get(1 - seat, 0) == 0
        assert f"P{seat} gained an extra turn" in game.log


def test_w1g3_beacon_of_unrest_takes_an_artifact_from_an_opponents_graveyard(set_pool):
    """"Put target artifact or creature card from a graveyard onto the
    battlefield under your control." Any graveyard, either type: the
    opponent's Rod of Ruin comes over under the caster's control and stays
    the opponent's card (CR 108.3) — destroyed, it goes to their graveyard.
    The instant beside it is no legal target."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"], lea["Shatter"]],
        opponent_graveyard=[lea["Lightning Bolt"], lea["Rod of Ruin"]],
    )
    spec = _w1g3_cast_spec(fdn["Beacon of Unrest"])
    assert spec.get("card_types") == ["artifact", "creature"]
    assert not spec.get("own_graveyard_only")
    refused = game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[0],
    )
    assert not refused.supported, "an instant card is not an artifact or creature card"

    assert game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[1],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == ["Rod of Ruin"]
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.library"]

    (rod,) = list(game.controlled_by(0))
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[rod.permanent_id]).supported
    _w1g3_settle(game)
    assert _w1g3_where(game, "Rod of Ruin") == ["1.graveyard"]


def test_w1g3_beacon_of_unrest_returns_a_creature_from_your_own_graveyard(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"]],
        graveyard=[lea["Shivan Dragon"]],
    )
    assert game.cast_from_hand(
        0, "Beacon of Unrest", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == ["Shivan Dragon"]
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.library"]


def test_w1g3_beacon_of_unrest_whose_card_left_is_not_shuffled(set_pool):
    """Ruling (2020-08-07): "If the target card is an illegal target by the
    time Beacon of Unrest tries to resolve, the spell won't resolve. You won't
    shuffle it into your library." The Rod of Ruin leaves the graveyard in
    response; the Beacon goes to its owner's graveyard and the library is
    untouched."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g3_table(
        set_pool, hand=[fdn["Beacon of Unrest"]], opponent_graveyard=[lea["Rod of Ruin"]],
    )
    assert game.queue_from_hand(
        0, "Beacon of Unrest", target_player_index=1, target_graveyard_indices=[0],
    ).supported
    rod = game.players[1].graveyard.pop(0)
    game.put_card_into_exile(game.players[1], rod)
    _w1g3_settle(game)
    assert _w1g3_board(game, 0) == []
    assert _w1g3_where(game, "Beacon of Unrest") == ["0.graveyard"]
    assert len(game.players[0].library) == 10

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

# ==== end w1g7 ======================================================
