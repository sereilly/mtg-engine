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

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=(), mana=True):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g9_mana_seism_adds_a_colourless_mana_for_each_land_sacrificed(set_pool):
    """"Sacrifice any number of lands, then add that much {C}." The seat
    chooses how many as the sorcery resolves (the prompt waits, CR 608.2);
    three lands sacrificed are {C}{C}{C}, and a seat nobody asks sacrifices
    none and adds none."""
    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Mana Seism"],
        mine=["Mountain", "Mountain", "Forest", "Forest"], interactive=(0,),
    )
    alice = game.players[0]
    for mountain in mine[:2]:
        assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert game.cast_from_hand(0, "Mana Seism").supported
    _w1g9_settle(game, defaults=False)
    [prompt] = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("sacrifice", 0)
    assert game.confirm_sacrifice(
        0, permanent_ids=[mine[0].permanent_id, mine[2].permanent_id, mine[3].permanent_id],
    )
    _w1g9_settle(game)
    assert _w1g9_names(game, 0) == ["Mountain"]
    assert alice.mana_pool["C"] == 3

    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Mana Seism"], mine=["Mountain", "Mountain"],
    )
    for mountain in mine:
        assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert game.cast_from_hand(0, "Mana Seism").supported
    _w1g9_settle(game)
    assert _w1g9_names(game, 0) == ["Mountain", "Mountain"]
    assert game.players[0].mana_pool["C"] == 0


def test_w1g9_feast_of_worms_takes_a_second_land_only_for_a_legendary_one(set_pool):
    """"Destroy target land. If that land was legendary, its controller
    sacrifices another land of their choice." Asked of the land as it last
    was (CR 608.2h), and the sacrifice is its controller's — chosen by Bob
    when Bob is asked. An ordinary land costs Bob only itself."""
    game, _mine, theirs = _w1g9_table(
        set_pool, hand=["Feast of Worms"],
        theirs=["Shizo, Death's Storehouse", "Island", "Swamp"],
        interactive=(1,), mana=False,
    )
    assert game.cast_from_hand(
        0, "Feast of Worms", target_permanent_ids=[theirs[0].permanent_id],
    ).supported
    _w1g9_settle(game, defaults=False)
    [prompt] = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("sacrifice", 1)
    assert game.confirm_sacrifice(1, permanent_ids=[theirs[2].permanent_id])
    _w1g9_settle(game)
    assert _w1g9_names(game, 1) == ["Island"]
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Shizo, Death's Storehouse", "Swamp",
    ]
    assert _w1g9_names(game, 0) == []

    game, _mine, theirs = _w1g9_table(
        set_pool, hand=["Feast of Worms"],
        theirs=["Shizo, Death's Storehouse", "Island", "Swamp"], mana=False,
    )
    assert game.cast_from_hand(
        0, "Feast of Worms", target_permanent_ids=[theirs[1].permanent_id],
    ).supported
    _w1g9_settle(game)
    assert _w1g9_names(game, 1) == ["Shizo, Death's Storehouse", "Swamp"]

# ==== end w1g9 ======================================================
