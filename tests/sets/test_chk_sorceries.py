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

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel, libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


# --- Yamabushi's Storm --------------------------------------------------------
# "Yamabushi's Storm deals 1 damage to each creature. If a creature dealt
# damage this way would die this turn, exile it instead." The sweep stamps
# the replacement on each creature it actually dealt to (CR 615.1a).


def test_w1g8_yamabushis_storm_exiles_every_creature_it_kills(set_pool):
    storm = set_pool("CHK")["Yamabushi's Storm"]
    elves = set_pool("LEA")["Llanowar Elves"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (_, hill) = _w1g8_table([elves], [elves, giant], hand=[storm])
    cast = game.cast_from_hand(0, "Yamabushi's Storm")
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 0, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Yamabushi's Storm"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []
    assert game.is_on_battlefield(hill) and hill.damage_marked == 1


def test_w1g8_yamabushis_storm_spares_what_it_dealt_no_damage_to(set_pool):
    """Protection from red prevents the Storm's damage to the Blacksmith
    (CR 702.16e), so it was not dealt damage this way: destroyed later that
    turn it dies as usual, while the Hill Giant the Storm did damage is
    exiled by the same Terror's twin."""
    storm = set_pool("CHK")["Yamabushi's Storm"]
    blacksmith = set_pool("ARN")["Repentant Blacksmith"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    game, _, (smith, hill) = _w1g8_table(
        [], [blacksmith, giant], hand=[storm, terror, terror]
    )
    assert game.cast_from_hand(0, "Yamabushi's Storm").supported
    _w1g8_settle(game)
    assert smith.damage_marked == 0 and hill.damage_marked == 1
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[smith.permanent_id]).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Repentant Blacksmith"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]



# --- Reverse the Sands --------------------------------------------------------
# "Redistribute any number of players' life totals." CR 119.7's
# redistribution; the rulings (2004-12-01): a life total is never split, and
# the caster chooses which player gets which as the spell resolves.


def test_w1g8_reverse_the_sands_hands_its_caster_the_higher_total(set_pool):
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.players[0].life, game.players[1].life = 5, 15
    cast = game.cast_from_hand(0, "Reverse the Sands")
    assert cast.supported, cast.details
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [15, 5]


def test_w1g8_reverse_the_sands_asks_its_caster_who_gets_each_total(set_pool):
    """An asked caster may leave the totals where they are — "any number of
    players" includes none — answering the ``player_choice`` prompt."""
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.interactive_seats = {0}
    game.players[0].life, game.players[1].life = 5, 15
    assert game.queue_from_hand(0, "Reverse the Sands").supported
    owed = _w1g8_settle(game, defaults=False)
    assert owed is not None and owed.kind == "player_choice"
    assert "5 life" in owed.data["prompt"]
    assert sorted(owed.data["seats"]) == [0, 1]
    assert game.confirm_player_choice(0, 0)
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [5, 15]


def test_w1g8_reverse_the_sands_at_a_table_of_three(set_pool):
    """Each total goes to one player; the caster's default takes the highest
    and hands the lowest to the opponent most ahead."""
    sands = set_pool("CHK")["Reverse the Sands"]
    game, _, _ = _w1g8_table([], [], hand=[sands])
    game.players.append(_w1g8_PlayerState(name="P3", life=20))
    _w1g8_stock_libraries(game)
    game.players[0].life, game.players[1].life, game.players[2].life = 3, 12, 30
    assert game.cast_from_hand(0, "Reverse the Sands").supported
    _w1g8_settle(game)
    lives = [p.life for p in game.players]
    assert sorted(lives) == [3, 12, 30]
    assert lives[0] == 30 and lives[2] == 3


def test_w1g8_reverse_the_sands_hands_no_higher_total_to_a_player_who_cant_gain(set_pool):
    """CR 119.7: under "Players can't gain life" no player may receive a
    higher total, so the only redistribution left is none."""
    sands = set_pool("CHK")["Reverse the Sands"]
    wastes = set_pool("MIR")["Forsaken Wastes"]
    game, _, _ = _w1g8_table([wastes], [], hand=[sands])
    game.players[0].life, game.players[1].life = 5, 15
    assert game.cast_from_hand(0, "Reverse the Sands").supported
    _w1g8_settle(game)
    assert [p.life for p in game.players] == [5, 15]

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
