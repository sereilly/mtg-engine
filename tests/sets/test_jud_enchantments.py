"""Judgment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
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

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
#
# Drive-list cards (supported on arrival), each given a game: what they count
# is counted on the right board and at the right moment.

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_table(set_pool, catalog_by_name):
    jud = set_pool("JUD")
    island = catalog_by_name["Island"]
    game = _W1G7Game(players=[
        _W1G7PlayerState(name="P0", library=[island] * 10),
        _W1G7PlayerState(name="P1", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g7_card = lambda name: jud[name] if name in jud else catalog_by_name[name]
    return game


def _w1g7_put(game, seat, name):
    permanent = _W1G7Permanent(card=game._w1g7_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g7_resolve(game)
    _w1g7_nosick(permanent)
    return permanent


def _w1g7_bolt(game, seat, victim):
    game.players[seat].hand.append(game._w1g7_card("Lightning Bolt"))
    assert game.cast_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    ).supported
    _w1g7_resolve(game)


def test_w1g7_soulcatchers_aerie_counts_only_its_controllers_birds(
    set_pool, catalog_by_name,
):
    """"Whenever a Bird is put into **your** graveyard from the battlefield":
    the controller's Suntail Hawk dying adds a feather counter, and every Bird
    on the table — the opponent's too, "Bird creatures get" names no
    controller — grows by one. The opponent's Hawk dying adds nothing."""
    game = _w1g7_table(set_pool, catalog_by_name)
    aerie = _w1g7_put(game, 0, "Soulcatchers' Aerie")
    doomed, mine = _w1g7_put(game, 0, "Suntail Hawk"), _w1g7_put(game, 0, "Suntail Hawk")
    theirs = _w1g7_put(game, 1, "Suntail Hawk")
    _w1g7_bolt(game, 1, doomed)

    assert aerie.metadata.get("feather_counters") == 1
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    _w1g7_bolt(game, 0, theirs)
    assert aerie.metadata.get("feather_counters") == 1
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


def test_w1g7_epic_struggle_wins_at_its_controllers_upkeep_with_twenty_creatures(
    set_pool, catalog_by_name,
):
    """Nineteen creatures at the upkeep win nothing; the twentieth does, at the
    next upkeep of the enchantment's controller."""
    game = _w1g7_table(set_pool, catalog_by_name)
    _w1g7_put(game, 0, "Epic Struggle")
    for _ in range(19):
        _w1g7_put(game, 0, "Grizzly Bears")
    game.start_turn(0)
    _w1g7_resolve(game)
    assert not any(player.lost for player in game.players)
    _w1g7_put(game, 0, "Grizzly Bears")
    game.start_turn(0)
    _w1g7_resolve(game)
    assert game.players[1].lost and not game.players[0].lost


def test_w1g7_test_of_endurance_wins_at_fifty_life(set_pool, catalog_by_name):
    game = _w1g7_table(set_pool, catalog_by_name)
    _w1g7_put(game, 0, "Test of Endurance")
    game.players[0].life = 49
    game.start_turn(0)
    _w1g7_resolve(game)
    assert not game.players[1].lost
    game.players[0].life = 50
    game.start_turn(0)
    _w1g7_resolve(game)
    assert game.players[1].lost

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
