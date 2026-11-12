"""Fifth Dawn artifacts.

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
#
# Sunburst on a noncreature (CR 702.44a: charge counters), each card cast
# through the real cast path with costs enforced. Six of these arrived
# "supported" entering with no counters at all.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.named_counters import counters_on as _w1g1_counters_on
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool, *, hand=()):
    """Two seats on seat 0's first main phase, costs enforced."""
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_cast(game, name, pool, **announce):
    game.players[0].mana_pool.update(pool)
    result = game.cast_from_hand(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    _w1g1_settle(game)
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g1_put(game, card, seat):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g1_activate(game, name, pool=None, **announce):
    if pool:
        game.players[0].mana_pool.update(pool)
    result = game.activate_permanent_ability(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    _w1g1_settle(game)
    return result


def test_w1g1_opaline_bracers_grows_by_its_charge_counters(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Opaline Bracers"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    bracers = _w1g1_cast(game, "Opaline Bracers", {"R": 1, "G": 1, "W": 1, "C": 1})
    assert _w1g1_counters_on(bracers, "charge") == 3
    assert _w1g1_counters_on(bracers, "+1/+1") == 0
    _w1g1_activate(game, "Opaline Bracers", {"C": 2}, target_permanent_ids=[bears.permanent_id])
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g1_baton_of_courage_is_cast_on_the_opponent_s_turn(set_pool):
    """Flash: cast in the opponent's turn with three colours, then a charge
    counter is a +1/+1 for the turn."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Baton of Courage"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    game.start_turn(1)
    _w1g1_settle(game)
    baton = _w1g1_cast(game, "Baton of Courage", {"R": 1, "G": 1, "W": 1})
    assert _w1g1_counters_on(baton, "charge") == 3
    _w1g1_activate(game, "Baton of Courage", target_permanent_ids=[bears.permanent_id])
    assert _w1g1_counters_on(baton, "charge") == 2
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g1_clearwater_goblet_gains_its_charge_counters_each_upkeep(set_pool):
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Clearwater Goblet"]])
    goblet = _w1g1_cast(game, "Clearwater Goblet", {"W": 1, "U": 1, "B": 1, "C": 2})
    assert _w1g1_counters_on(goblet, "charge") == 3
    game.start_turn(1)
    _w1g1_settle(game)
    assert game.players[0].life == 20
    game.start_turn(0)
    _w1g1_settle(game)
    assert game.players[0].life == 23


def test_w1g1_engineered_explosives_x_buys_colors_not_counters(set_pool):
    """The rulings (2020-08-07): X lets more colours be spent, and the counters
    are the colours — X=3 paid with two colours and a colourless is two. The
    sacrifice reads the counters the Explosives left with (CR 608.2h)."""
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Engineered Explosives"]])
    bears = _w1g1_put(game, lea["Grizzly Bears"], 0)
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    explosives = _w1g1_cast(
        game, "Engineered Explosives", {"U": 1, "B": 1, "C": 1}, x_value=3,
    )
    assert _w1g1_counters_on(explosives, "charge") == 2
    _w1g1_activate(game, "Engineered Explosives", {"C": 2})
    assert not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(giant)


def test_w1g1_engineered_explosives_at_zero_destroys_mana_value_zero(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Engineered Explosives"]])
    lotus = _w1g1_put(game, lea["Black Lotus"], 1)
    bears = _w1g1_put(game, lea["Grizzly Bears"], 1)
    explosives = _w1g1_cast(game, "Engineered Explosives", {}, x_value=0)
    assert _w1g1_counters_on(explosives, "charge") == 0
    _w1g1_activate(game, "Engineered Explosives", {"C": 2})
    assert not game.is_on_battlefield(lotus)
    assert game.is_on_battlefield(bears)


def test_w1g1_heliophial_deals_the_counters_it_was_sacrificed_with(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Heliophial"]])
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    heliophial = _w1g1_cast(game, "Heliophial", {"W": 1, "U": 1, "B": 1, "C": 2})
    assert _w1g1_counters_on(heliophial, "charge") == 3
    _w1g1_activate(game, "Heliophial", {"C": 2}, target_permanent_ids=[giant.permanent_id])
    assert any("Heliophial dealt 3 damage to Hill Giant" in line for line in game.log)
    assert not game.is_on_battlefield(giant)


def test_w1g1_infused_arrows_shrinks_by_the_counters_it_removes(set_pool):
    fdn, lea = set_pool("5DN"), set_pool("LEA")
    game = _w1g1_table(set_pool, hand=[fdn["Infused Arrows"]])
    giant = _w1g1_put(game, lea["Hill Giant"], 1)
    arrows = _w1g1_cast(game, "Infused Arrows", {"W": 1, "U": 1, "B": 1, "C": 1})
    assert _w1g1_counters_on(arrows, "charge") == 3
    _w1g1_activate(game, "Infused Arrows", target_permanent_ids=[giant.permanent_id], x_value=2)
    assert _w1g1_counters_on(arrows, "charge") == 1
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)


def test_w1g1_pentad_prism_makes_a_mana_per_charge_counter_and_stays(set_pool):
    """Once it has run out of charge counters it remains on the battlefield
    (2020-08-07)."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Pentad Prism"]])
    prism = _w1g1_cast(game, "Pentad Prism", {"R": 1, "G": 1})
    assert _w1g1_counters_on(prism, "charge") == 2
    _w1g1_activate(game, "Pentad Prism", mana_color="U")
    _w1g1_activate(game, "Pentad Prism", mana_color="B")
    assert game.players[0].mana_pool.get("U") == 1
    assert game.players[0].mana_pool.get("B") == 1
    refused = game.activate_permanent_ability(0, "Pentad Prism", mana_color="W")
    assert not refused.supported
    assert game.is_on_battlefield(prism)

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
