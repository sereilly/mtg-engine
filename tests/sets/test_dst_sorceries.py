"""Darksteel sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle


def _w1g5_cloud_table(set_pool, *, hands, boards, interactive=()):
    """Alice holds Death Cloud on her first main phase; *hands* and *boards*
    are each seat's cards by name (LEA unless they are Darksteel's)."""
    lea, dst = set_pool("LEA"), set_pool("DST")

    def named(name):
        return dst[name] if name in dst else lea[name]

    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name="Alice", hand=[dst["Death Cloud"]] + [named(n) for n in hands[0]],
            library=[lea["Plains"]] * 10,
        ),
        _W1G5PlayerState(
            name="Bob", hand=[named(n) for n in hands[1]], library=[lea["Island"]] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat in (0, 1):
        for name in boards[seat]:
            permanent = _W1G5Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g5_settle(game)
    return game, placed[0], placed[1]


def test_w1g5_death_cloud_takes_x_of_each_of_four_things_from_each_player(set_pool):
    """"Each player loses X life, discards X cards, sacrifices X creatures of
    their choice, then sacrifices X lands of their choice." X = 2: both seats
    lose 2 life, discard 2 of their 3 cards, give up 2 creatures (Bob has only
    one — as much as possible, CR 609.3) and then 2 lands."""
    game, _mine, _theirs = _w1g5_cloud_table(
        set_pool,
        hands=(["Forest", "Forest", "Island"], ["Island", "Island", "Plains"]),
        boards=(
            ["Grizzly Bears", "Grizzly Bears", "Grizzly Bears", "Forest", "Forest", "Forest"],
            ["Grizzly Bears", "Island", "Island", "Island"],
        ),
    )
    game.cast_from_hand(0, "Death Cloud", x_value=2)
    _w1g5_settle(game)
    alice, bob = game.players

    def names(seat):
        return sorted(p.card.name for p in game.controlled_by(seat))

    assert (alice.life, bob.life) == (18, 18)
    assert (len(alice.hand), len(bob.hand)) == (1, 1)
    assert names(0) == ["Forest", "Grizzly Bears"]
    assert names(1) == ["Island"]
    assert sum(c.name == "Grizzly Bears" for c in alice.graveyard) == 2
    assert sum(c.name == "Island" for c in bob.graveyard) == 4  # two discarded, two sacrificed


def test_w1g5_death_cloud_asks_each_seat_in_turn_order_and_a_creature_land_goes_once(set_pool):
    """Both seats answer for themselves, the active player first (CR 101.4):
    Alice's discard, then Bob's, then each seat's creature, then each seat's
    land. Alice gives up the Forest Living Lands animated as her creature —
    and by the land sacrifice it is gone, so it is not offered again (the
    card's 2013-06-07 ruling: "it won't be on the battlefield when you
    sacrifice lands")."""
    game, mine, theirs = _w1g5_cloud_table(
        set_pool,
        hands=(["Island"], ["Plains"]),
        boards=(["Living Lands", "Forest", "Grizzly Bears", "Plains"],
                ["Grizzly Bears", "Island", "Island"]),
        interactive=(0, 1),
    )
    living_forest, bears, plains = mine[1], mine[2], mine[3]
    assert living_forest.is_creature
    game.cast_from_hand(0, "Death Cloud", x_value=1)
    asked = []
    for _ in range(8):
        owed = _w1g5_settle(game, defaults=False)
        if owed is None:
            break
        asked.append((owed.kind, owed.player_index, (owed.data.get("filter") or {}).get("type_filter")))
        seat = owed.player_index
        if owed.kind == "discard":
            assert game.confirm_discard(seat, [0])
        elif seat == 0 and asked[-1][2] == "creature":
            assert game.confirm_sacrifice(0, permanent_ids=[living_forest.permanent_id])
        elif seat == 0:
            # The animated Forest went as a creature: offering it now refuses.
            assert not game.confirm_sacrifice(0, permanent_ids=[living_forest.permanent_id])
            assert game.confirm_sacrifice(0, permanent_ids=[plains.permanent_id])
        else:
            wanted = asked[-1][2]
            chosen = next(p for p in game.controlled_by(1) if p.has_type(wanted))
            assert game.confirm_sacrifice(1, permanent_ids=[chosen.permanent_id])
    assert asked == [
        ("discard", 0, None), ("discard", 1, None),
        ("sacrifice", 0, "creature"), ("sacrifice", 1, "creature"),
        ("sacrifice", 0, "land"), ("sacrifice", 1, "land"),
    ]
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Living Lands"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Island"]
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert any(p is bears for p in game.controlled_by(0))

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
