"""Darksteel artifacts — the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Thunderstaff's static shave of each attacker's combat damage while it is
# untapped, and Talon of Pain's trigger on any source its controller controls
# other than itself — both hollow on arrival, both driven here.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState
from engine.named_counters import counters_on as _w1g6_counters_on

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 8),
        _W1G6PlayerState(
            name="Bob", hand=list(opponent_hand), library=[lea["Island"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card, *, tapped=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    game._sync_control()
    return permanent


def test_w1g6_thunderstaff_shaves_one_from_each_attacker_while_untapped(set_pool):
    """"As long as this artifact is untapped, if a creature would deal combat
    damage to you, prevent 1 of that damage." Ruling (2004-12-01): "it
    prevents 1 damage from each creature, each time it would deal combat
    damage to you." A Grizzly Bears and a Hill Giant unblocked: 2 + 3 less one
    each is 3. The same attack with the staff tapped is 5."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"])
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 17
    assert sum("prevented 1 of" in line and "Thunderstaff" in line for line in game.log) == 2

    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"], tapped=True)
    _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_put(game, 1, lea["Hill Giant"])
    _w1g6_declare_attack(game, 1)
    _w1g6_drive_combat(game)
    assert game.players[0].life == 15


def test_w1g6_thunderstaff_leaves_noncombat_damage_alone(set_pool):
    """Combat damage only: a Lightning Bolt aimed at the staff's controller
    deals its full 3."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    _w1g6_put(game, 0, dst["Thunderstaff"])
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_settle(game)
    assert game.players[0].life == 17


def test_w1g6_thunderstaff_pumps_attackers(set_pool):
    """"{2}, {T}: Attacking creatures get +1/+0 until end of turn." — and
    tapping it for that switches its shield off for the damage that follows."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Thunderstaff"])
    bear = _w1g6_put(game, 0, lea["Grizzly Bears"])
    _w1g6_declare_attack(game, 0)
    assert game.activate_permanent_ability(0, "Thunderstaff").supported
    _w1g6_settle(game)
    assert bear.effective_power == 3
    _w1g6_drive_combat(game)
    assert game.players[1].life == 17


def test_w1g6_talon_of_pain_counts_damage_from_its_controllers_other_sources(set_pool):
    """"Whenever a source you control other than this artifact deals damage
    to an opponent, put a charge counter on this artifact." A spell (Lightning
    Bolt) and a creature's combat damage each add one; the opponent's own
    Bolt at its own face adds none."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[lea["Lightning Bolt"]], opponent_hand=[lea["Lightning Bolt"]],
    )
    talon = _w1g6_put(game, 0, dst["Talon of Pain"])
    _w1g6_put(game, 0, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(talon, "charge") == 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=1).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(talon, "charge") == 1
    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 20 - 3 - 3 - 2
    assert _w1g6_counters_on(talon, "charge") == 2


def test_w1g6_talon_of_pain_spends_its_counters_and_does_not_count_itself(set_pool):
    """"{X}, {T}, Remove X charge counters from this artifact: It deals X
    damage to any target." Two counters off, two damage to the opponent —
    and that damage, being the Talon's own, puts no counter back."""
    dst = set_pool("DST")
    game = _w1g6_table(set_pool)
    talon = _w1g6_put(game, 0, dst["Talon of Pain"])
    talon.metadata["charge_counters"] = 2
    result = game.activate_permanent_ability(
        0, "Talon of Pain", target_player_index=1, x_value=2,
    )
    assert result.supported, result.details
    _w1g6_settle(game)
    assert game.players[1].life == 18
    assert _w1g6_counters_on(talon, "charge") == 0
    assert talon.tapped

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
