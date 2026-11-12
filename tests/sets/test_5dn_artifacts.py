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


def test_w1g1_clearwater_goblet_s_gain_is_a_person_s_to_decline(set_pool):
    """"You may": a person is asked (the optional offer) and may say no."""
    fdn = set_pool("5DN")
    game = _w1g1_table(set_pool, hand=[fdn["Clearwater Goblet"]])
    game.interactive_seats = {0}
    _w1g1_cast(game, "Clearwater Goblet", {"W": 1, "U": 1, "C": 3})
    game.start_turn(1)
    _w1g1_settle(game)
    game.start_turn(0)
    owed = _w1g1_settle(game, defaults=False)
    assert owed is not None and owed.kind == "optional_pay"
    assert game.resolve_pending_choice("optional_pay", 0, accept=False, option=None)
    _w1g1_settle(game)
    assert game.players[0].life == 20


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

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from tests.helpers import settle as _w1g3_settle


def _w1g3_station_table(set_pool, *, graveyard, interactive=()):
    """Salvaging Station on seat 0's board, a Grizzly Bears on each side to
    die, and *graveyard* seat 0's."""
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g3_settle(game)
    station = _W1G3Permanent(card=set_pool("5DN")["Salvaging Station"])
    game._put_permanent_onto_battlefield(0, station, None)
    bears = []
    for seat in (0, 1):
        bear = _W1G3Permanent(card=lea["Grizzly Bears"])
        game._put_permanent_onto_battlefield(seat, bear, None)
        bears.append(bear)
    _w1g3_settle(game)
    return game, station, bears


def _w1g3_bolt(game, set_pool, victim):
    game.players[0].hand.append(set_pool("LEA")["Lightning Bolt"])
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    )
    assert result.supported, (result, game.log[-4:])


def test_w1g3_salvaging_station_returns_a_small_noncreature_artifact(set_pool):
    """"{T}: Return target noncreature artifact card with mana value 1 or less
    from your graveyard to the battlefield." The spec carries both narrowings;
    the Ornithopter (an artifact *creature* at 0) and the Rod of Ruin (at 4)
    are refused at announcement (CR 602.2b); the Sol Ring enters, the Station
    taps."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, _bears = _w1g3_station_table(
        set_pool, graveyard=[atq["Ornithopter"], lea["Rod of Ruin"], lea["Sol Ring"]],
    )
    spec = _w1g3_activation_spec(_w1g3_compile(station.card).activated_abilities[0])
    assert spec["card_type"] == "artifact" and spec["own_graveyard_only"]
    assert spec["graveyard_mana_value"] == {"op": "le", "value": 1}
    assert spec["graveyard_excluded_types"] == ["creature"]

    for slot in (0, 1):
        refused = game.activate_permanent_ability(
            0, "Salvaging Station", target_player_index=0,
            target_graveyard_indices=[slot],
        )
        assert not refused.supported, slot
    assert not station.tapped
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[2],
    ).supported
    _w1g3_settle(game)

    alice = game.players[0]
    assert station.tapped
    assert any(p.card.name == "Sol Ring" for p in alice.battlefield)
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Rod of Ruin"]


def test_w1g3_salvaging_station_untaps_when_a_creature_dies_and_goes_again(set_pool):
    """"Whenever a creature dies, you may untap this artifact." Any creature,
    the opponent's too. Untapped by the death, a bare activation (no slot
    named, as an AI seat makes it) takes the legal Black Lotus — never the
    Ornithopter first in the pile."""
    lea, atq = set_pool("LEA"), set_pool("ATQ")
    game, station, bears = _w1g3_station_table(
        set_pool,
        graveyard=[atq["Ornithopter"], lea["Sol Ring"], lea["Black Lotus"]],
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[1],
    ).supported
    _w1g3_settle(game)
    assert station.tapped

    _w1g3_bolt(game, set_pool, bears[1])
    _w1g3_settle(game)
    assert not station.tapped, game.log[-6:]

    assert game.activate_permanent_ability(0, "Salvaging Station").supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert {p.card.name for p in alice.battlefield} >= {"Sol Ring", "Black Lotus"}
    assert [c.name for c in alice.graveyard] == ["Ornithopter", "Lightning Bolt"]


def test_w1g3_salvaging_station_untap_is_a_choice_an_asked_seat_may_decline(set_pool):
    """The "may" is asked of an interactive seat, and declined leaves the
    Station tapped."""
    lea = set_pool("LEA")
    game, station, bears = _w1g3_station_table(
        set_pool, graveyard=[lea["Sol Ring"]], interactive={0},
    )
    assert game.activate_permanent_ability(
        0, "Salvaging Station", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    assert station.tapped
    _w1g3_bolt(game, set_pool, bears[0])
    asked = _w1g3_settle(game, defaults=False)
    assert asked is not None and asked.kind == "optional_pay", game.log[-6:]
    assert asked.data["card_name"] == "Salvaging Station"
    assert game.confirm_optional_pay(0, "Salvaging Station", accept=False)
    _w1g3_settle(game)
    assert station.tapped


def _w1g3_bauble_table(set_pool, graveyard):
    lea = set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 5,
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g3_settle(game)
    game._put_permanent_onto_battlefield(
        0, _W1G3Permanent(card=set_pool("5DN")["Conjurer's Bauble"]), None
    )
    _w1g3_settle(game)
    return game


def test_w1g3_conjurers_bauble_draws_over_an_empty_graveyard(set_pool):
    """Drive list (supported on arrival, and wrong): "{T}, Sacrifice this
    artifact: Put **up to one** target card from your graveyard on the bottom
    of your library. Draw a card." CR 601.2c lets the announcement name no
    card, so the Bauble is activatable with nothing in the graveyard, for its
    draw. It was refused ("no valid target") — the lowering dropped "up to"."""
    game = _w1g3_bauble_table(set_pool, graveyard=[])
    result = game.activate_permanent_ability(0, "Conjurer's Bauble")
    assert result.supported, result
    _w1g3_settle(game)
    alice = game.players[0]
    assert [c.name for c in alice.hand] == ["Island"]
    assert [c.name for c in alice.graveyard] == ["Conjurer's Bauble"]


def test_w1g3_conjurers_bauble_naming_no_card_bottoms_none(set_pool):
    """Announced naming no card over a graveyard that holds one, the Bauble
    draws and bottoms nothing — it bottomed the Lightning Bolt anyway, the
    first card in the pile, for a player who had chosen zero. Named, the
    card goes to the bottom."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    game = _w1g3_bauble_table(set_pool, graveyard=[bolt])
    assert game.activate_permanent_ability(
        0, "Conjurer's Bauble", target_player_index=0, target_graveyard_indices=[],
    ).supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert [c.name for c in alice.graveyard] == ["Lightning Bolt", "Conjurer's Bauble"]
    assert [c.name for c in alice.hand] == ["Island"]
    assert alice.library[-1].name == "Island"

    game = _w1g3_bauble_table(set_pool, graveyard=[bolt])
    assert game.activate_permanent_ability(
        0, "Conjurer's Bauble", target_player_index=0, target_graveyard_indices=[0],
    ).supported
    _w1g3_settle(game)
    alice = game.players[0]
    assert alice.library[-1].name == "Lightning Bolt"
    assert [c.name for c in alice.graveyard] == ["Conjurer's Bauble"]

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================
