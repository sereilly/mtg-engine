"""Odyssey lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.ai_policy import (
    _plan_land_taps as _w1g2_plan_land_taps,
    planned_tap_ability as _w1g2_planned_tap_ability,
)
from engine.board_payment import board_can_pay as _w1g2_board_can_pay
from engine.mana_payment import (
    is_mana_ability as _w1g2_is_mana_ability,
    taps_for_payment as _w1g2_taps_for_payment,
)
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

#: The five lands printing "{T}: Add <colour>. This land deals 1 damage to
#: you." and a threshold ability that sacrifices them: name, colour.
_W1G2_THRESHOLD_LANDS = [
    ("Barbarian Ring", "R"),
    ("Cabal Pit", "B"),
    ("Centaur Garden", "G"),
    ("Cephalid Coliseum", "U"),
    ("Nomad Stadium", "W"),
]

#: "This land enters tapped. {T}: Add <colour>. {T}, Sacrifice this land: Add
#: one mana of any color."
_W1G2_SACRIFICE_LANDS = [
    ("Abandoned Outpost", "W"),
    ("Bog Wreckage", "B"),
    ("Ravaged Highlands", "R"),
    ("Seafloor Debris", "U"),
    ("Timberland Ruins", "G"),
]

#: "{1}, {T}: Add <two colours>."
_W1G2_FILTER_LANDS = [
    ("Darkwater Catacombs", {"U": 1, "B": 1}),
    ("Mossfire Valley", {"R": 1, "G": 1}),
    ("Shadowblood Ridge", {"B": 1, "R": 1}),
    ("Skycloud Expanse", {"W": 1, "U": 1}),
    ("Sungrass Prairie", {"G": 1, "W": 1}),
]

_W1G2_ONE_OF_EACH = [
    ("{1}", {"generic": 1}), ("{W}", {"W": 1}), ("{U}", {"U": 1}),
    ("{B}", {"B": 1}), ("{R}", {"R": 1}), ("{G}", {"G": 1}),
]


def _w1g2_duel(set_pool, *, graveyard=0, pool=None):
    """A two-seat game that **charges mana**, seat 0's main phase, *pool*
    floating and *graveyard* cards in seat 0's graveyard."""
    lea = set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState("Caster", library=[lea["Forest"]] * 10),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool or {})
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card, *, untap=True):
    """*card* onto *seat*'s battlefield without being played. *untap* undoes
    an "enters tapped" so the test can reach the abilities behind it."""
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if untap:
        permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_floating(game, seat=0) -> dict:
    return {k: v for k, v in game.players[seat].mana_pool.items() if v}  # _w1g2_floating


def _w1g2_payable(game, seat=0) -> list:
    """Which one-symbol costs the castable highlight believes *seat* can pay."""
    return [
        label for label, cost in _W1G2_ONE_OF_EACH
        if _w1g2_board_can_pay(game, seat, cost)
    ]  # _w1g2_payable


# ---------------------------------------------------------------------------
# The threshold lands
# ---------------------------------------------------------------------------

@_w1g2_pytest.mark.parametrize("name, colour", _W1G2_THRESHOLD_LANDS)
def test_a_threshold_land_taps_for_its_colour_and_a_point_of_damage(
    set_pool, name, colour,
):
    """"{T}: Add {R}. This land deals 1 damage to you." A mana ability with a
    rider (CR 605.1a asks only that it could add mana): the tap seam runs
    both halves, the castable highlight counts the land, and the AI's planner
    counts it as one mana of its colour."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool)
    land = _w1g2_put(game, 0, ody[name])

    assert _w1g2_payable(game) == ["{1}", "{" + colour + "}"]
    assert _w1g2_taps_for_payment(land)
    # …one mana of its colour, and not two.
    assert _w1g2_plan_land_taps(game, game.players[0], {colour: 1}) is not None
    assert _w1g2_plan_land_taps(game, game.players[0], {colour: 2}) is None

    assert game.tap_land_for_mana(0, name, colour)

    assert _w1g2_floating(game) == {colour: 1}
    assert game.players[0].life == 19 and land.tapped


@_w1g2_pytest.mark.parametrize("name, colour", _W1G2_THRESHOLD_LANDS)
def test_a_threshold_land_cannot_count_itself_toward_its_seven(set_pool, name, colour):
    """"Threshold — {R}, {T}, Sacrifice this land: … Activate only if there
    are seven or more cards in your graveyard." With six cards the land that
    is about to be sacrificed would be the seventh — and is not in the
    graveyard when the clause is asked (CR 602.5: a player can't *begin* to
    activate). Refused: no mana spent, the land untapped and still there."""
    ody = set_pool("ODY")
    assert not any(
        ability.instruction is None
        for ability in _w1g2_compile(ody[name]).activated_abilities
    ), "the threshold ability compiles to an instruction, not a hollow line"

    game = _w1g2_duel(set_pool, graveyard=6, pool={colour: 1})
    land = _w1g2_put(game, 0, ody[name])
    bears = _w1g2_put(game, 1, set_pool("LEA")["Grizzly Bears"])

    refused = game.queue_permanent_ability(
        0, name, ability_index=1,
        **_w1g2_land_aim(name, bears),
    )

    assert not refused.supported
    assert "seven or more cards in your graveyard" in refused.details
    assert _w1g2_floating(game) == {colour: 1}
    assert game.is_on_battlefield(land) and not land.tapped
    assert len(game.players[0].graveyard) == 6 and game.stack == []


def _w1g2_land_aim(name, bears):
    """The announcement each threshold land's ability needs."""
    if name in ("Cabal Pit", "Centaur Garden"):
        return {"target_permanent_ids": [bears.permanent_id]}
    if name in ("Barbarian Ring", "Cephalid Coliseum"):
        return {"target_player_index": 1}
    return {}  # _w1g2_land_aim


def test_barbarian_ring_deals_its_two_from_the_graveyard(set_pool):
    """"{R}, {T}, Sacrifice this land: **It** deals 2 damage to any target."
    The Ring is in the graveyard by the time the ability resolves, so "it" is
    the land as it last existed on the battlefield (CR 608.2h) — the damage is
    still dealt, and still by a source named Barbarian Ring."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7, pool={"R": 1})
    ring = _w1g2_put(game, 0, ody["Barbarian Ring"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])

    assert game.queue_permanent_ability(
        0, "Barbarian Ring", ability_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert not game.is_on_battlefield(ring), "sacrificed as a cost"
    assert len(game.players[0].graveyard) == 8 and _w1g2_floating(game) == {}

    _w1g2_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(bears)
    assert "Barbarian Ring dealt 2 damage to Grizzly Bears" in game.log

    game = _w1g2_duel(set_pool, graveyard=7, pool={"R": 1})
    _w1g2_put(game, 0, ody["Barbarian Ring"])
    assert game.activate_permanent_ability(
        0, "Barbarian Ring", ability_index=1, target_player_index=1,
    ).supported
    assert game.players[1].life == 18


def test_cabal_pit_and_centaur_garden_size_a_creature_until_end_of_turn(set_pool):
    """"Target creature gets -2/-2 until end of turn." / "…+3/+3 until end of
    turn." A land is not a legal target for either, and the pump is gone at
    cleanup."""
    ody, lea = set_pool("ODY"), set_pool("LEA")

    game = _w1g2_duel(set_pool, graveyard=7, pool={"B": 1})
    pit = _w1g2_put(game, 0, ody["Cabal Pit"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    island = _w1g2_put(game, 1, lea["Island"])
    at_a_land = game.queue_permanent_ability(
        0, "Cabal Pit", ability_index=1, target_permanent_ids=[island.permanent_id],
    )
    assert not at_a_land.supported and game.is_on_battlefield(pit)
    assert game.activate_permanent_ability(
        0, "Cabal Pit", ability_index=1, target_permanent_ids=[bears.permanent_id],
    ).supported
    assert not game.is_on_battlefield(bears), "a 2/2 at -2/-2 has toughness 0"

    game = _w1g2_duel(set_pool, graveyard=7, pool={"G": 1})
    _w1g2_put(game, 0, ody["Centaur Garden"])
    bears = _w1g2_put(game, 0, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Centaur Garden", ability_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_cephalid_coliseum_draws_three_then_discards_three(set_pool):
    """"Target player draws three cards, then discards three cards." Aimed at
    its own controller: three more cards seen, hand size back where it was,
    and the three discards land on top of the Coliseum in the graveyard."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7, pool={"U": 1})
    _w1g2_put(game, 0, ody["Cephalid Coliseum"])
    game.players[0].hand.extend([lea["Island"]] * 2)

    assert game.queue_permanent_ability(
        0, "Cephalid Coliseum", ability_index=1, target_player_index=0,
    ).supported
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 2
    assert len(game.players[0].library) == 7
    assert len(game.players[0].graveyard) == 7 + 1 + 3


def test_nomad_stadium_gains_four(set_pool):
    """"Threshold — {W}, {T}, Sacrifice this land: You gain 4 life." No
    target, so nothing to announce."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7, pool={"W": 1})
    stadium = _w1g2_put(game, 0, ody["Nomad Stadium"])

    assert game.activate_permanent_ability(0, "Nomad Stadium", ability_index=1).supported

    assert game.players[0].life == 24
    assert not game.is_on_battlefield(stadium)


def test_a_threshold_lands_two_abilities_cannot_share_one_tap(set_pool):
    """Both abilities print {T}. Tapped for mana to pay the {R}, the Ring has
    nothing left to tap for its own threshold ability: the mana has to come
    from somewhere else."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7)
    ring = _w1g2_put(game, 0, ody["Barbarian Ring"])
    assert game.tap_land_for_mana(0, "Barbarian Ring", "R")

    refused = game.queue_permanent_ability(
        0, "Barbarian Ring", ability_index=1, target_player_index=1,
    )

    assert not refused.supported and "tapped" in refused.details
    assert game.is_on_battlefield(ring) and _w1g2_floating(game) == {"R": 1}


# ---------------------------------------------------------------------------
# The sacrifice lands
# ---------------------------------------------------------------------------

@_w1g2_pytest.mark.parametrize("name, colour", _W1G2_SACRIFICE_LANDS)
def test_a_sacrifice_land_enters_tapped_and_makes_any_colour_once(set_pool, name, colour):
    """"This land enters tapped. {T}: Add {W}. {T}, Sacrifice this land: Add
    one mana of any color." The second is a mana ability too (CR 605.1a), so
    it never uses the stack; it is not a tap-alone one, so the highlight and
    the payment planner count the land as its own colour and nothing else."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool)
    entered = _w1g2_put(game, 0, ody[name], untap=False)
    assert entered.tapped
    assert not game.tap_land_for_mana(0, name, colour), "it entered tapped"
    entered.tapped = False

    first, second = _w1g2_compile(ody[name]).activated_abilities
    assert _w1g2_is_mana_ability(first) and _w1g2_is_mana_ability(second)
    assert _w1g2_payable(game) == ["{1}", "{" + colour + "}"]
    assert _w1g2_planned_tap_ability(game, entered, "U" if colour != "U" else "R") is None

    other = "U" if colour != "U" else "R"
    result = game.queue_permanent_ability(0, name, ability_index=1, mana_color=other)

    assert result.supported and result.details == "resolved"
    assert game.stack == []
    assert _w1g2_floating(game) == {other: 1}
    assert not game.is_on_battlefield(entered)
    assert [card.name for card in game.players[0].graveyard] == [name]


def test_a_tapped_sacrifice_land_cannot_be_sacrificed_for_mana(set_pool):
    """The sacrifice ability costs {T} as well: once tapped for its own
    colour the land is not a second mana."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool)
    land = _w1g2_put(game, 0, ody["Bog Wreckage"])
    assert game.tap_land_for_mana(0, "Bog Wreckage", "B")

    refused = game.queue_permanent_ability(0, "Bog Wreckage", ability_index=1, mana_color="U")

    assert not refused.supported and game.is_on_battlefield(land)
    assert _w1g2_floating(game) == {"B": 1}


# ---------------------------------------------------------------------------
# The filter lands and Crystal Quarry
# ---------------------------------------------------------------------------

@_w1g2_pytest.mark.parametrize("name, made", _W1G2_FILTER_LANDS)
def test_a_filter_land_turns_one_mana_into_two_colours(set_pool, name, made):
    """"{1}, {T}: Add {U}{B}." A mana ability with a mana cost: it resolves
    inline (CR 605.3b), it cannot be activated with an empty pool, and no
    automatic payment taps it — the tap seam refuses it, the castable
    highlight believes it pays for nothing, and the planner leaves it out."""
    ody = set_pool("ODY")
    (ability,) = _w1g2_compile(ody[name]).activated_abilities
    assert _w1g2_is_mana_ability(ability)

    game = _w1g2_duel(set_pool)
    land = _w1g2_put(game, 0, ody[name])
    assert _w1g2_payable(game) == []
    assert not _w1g2_taps_for_payment(land)
    assert not game.tap_land_for_mana(0, name, "U")
    empty = game.queue_permanent_ability(0, name, ability_index=0)
    assert not empty.supported and not land.tapped

    game = _w1g2_duel(set_pool, pool={"C": 1})
    land = _w1g2_put(game, 0, ody[name])
    result = game.queue_permanent_ability(0, name, ability_index=0)

    assert result.supported and result.details == "resolved"
    assert game.stack == [] and land.tapped
    assert _w1g2_floating(game) == made


def test_crystal_quarry_makes_one_of_each_for_five(set_pool):
    """"{T}: Add {C}." / "{5}, {T}: Add {W}{U}{B}{R}{G}." Four mana is not
    five; the highlight counts the Quarry as the one colourless its free
    ability makes."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, pool={"C": 4})
    quarry = _w1g2_put(game, 0, ody["Crystal Quarry"])
    short = game.queue_permanent_ability(0, "Crystal Quarry", ability_index=1)
    assert not short.supported and not quarry.tapped
    assert _w1g2_floating(game) == {"C": 4}

    game = _w1g2_duel(set_pool, pool={"C": 5})
    _w1g2_put(game, 0, ody["Crystal Quarry"])
    assert game.queue_permanent_ability(0, "Crystal Quarry", ability_index=1).supported
    assert _w1g2_floating(game) == {"W": 1, "U": 1, "B": 1, "R": 1, "G": 1}

    game = _w1g2_duel(set_pool)
    _w1g2_put(game, 0, ody["Crystal Quarry"])
    assert _w1g2_payable(game) == ["{1}"]
    assert game.tap_land_for_mana(0, "Crystal Quarry", "C")
    assert _w1g2_floating(game) == {"C": 1}


# ---------------------------------------------------------------------------
# Tarnished Citadel, Deserted Temple, Petrified Field
# ---------------------------------------------------------------------------

def test_tarnished_citadel_charges_three_only_for_a_colour(set_pool):
    """"{T}: Add {C}." / "{T}: Add one mana of any color. This land deals 3
    damage to you." Two tap-alone mana abilities: the seam's default is the
    free one; a colour asked for runs the painful one, which makes it (the
    player chooses which mana ability to activate, CR 605); and the AI's tap
    executor names the painful one only when its plan needs the colour."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool)
    citadel = _w1g2_put(game, 0, ody["Tarnished Citadel"])
    assert _w1g2_payable(game) == ["{1}", "{W}", "{U}", "{B}", "{R}", "{G}"]
    assert _w1g2_planned_tap_ability(game, citadel, "C") is None
    assert _w1g2_planned_tap_ability(game, citadel, "U") == 1

    assert game.tap_land_for_mana(0, "Tarnished Citadel")
    assert _w1g2_floating(game) == {"C": 1} and game.players[0].life == 20

    game = _w1g2_duel(set_pool)
    _w1g2_put(game, 0, ody["Tarnished Citadel"])
    assert game.tap_land_for_mana(0, "Tarnished Citadel", "U")
    assert _w1g2_floating(game) == {"U": 1} and game.players[0].life == 17

    game = _w1g2_duel(set_pool)
    _w1g2_put(game, 0, ody["Tarnished Citadel"])
    assert game.tap_land_for_mana(0, "Tarnished Citadel", "U", ability_index=1)
    assert _w1g2_floating(game) == {"U": 1} and game.players[0].life == 17


def test_deserted_temple_untaps_a_land_and_only_a_land(set_pool):
    """"{1}, {T}: Untap target land." Any land — an opponent's, or the Temple
    itself, which is tapped as the cost and untapped by the effect — and
    never a creature."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, pool={"C": 3})
    temple = _w1g2_put(game, 0, ody["Deserted Temple"])
    forest = _w1g2_put(game, 0, lea["Forest"])
    island = _w1g2_put(game, 1, lea["Island"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    forest.tapped = island.tapped = bears.tapped = True

    at_a_creature = game.queue_permanent_ability(
        0, "Deserted Temple", ability_index=1, target_permanent_ids=[bears.permanent_id],
    )
    assert not at_a_creature.supported and not temple.tapped
    assert _w1g2_floating(game) == {"C": 3}

    assert game.activate_permanent_ability(
        0, "Deserted Temple", ability_index=1, target_permanent_ids=[forest.permanent_id],
    ).supported
    assert not forest.tapped and temple.tapped

    temple.tapped = False
    assert game.activate_permanent_ability(
        0, "Deserted Temple", ability_index=1, target_permanent_ids=[island.permanent_id],
    ).supported
    assert not island.tapped

    temple.tapped = False
    assert game.activate_permanent_ability(
        0, "Deserted Temple", ability_index=1, target_permanent_ids=[temple.permanent_id],
    ).supported
    assert not temple.tapped and bears.tapped
    assert _w1g2_floating(game) == {}


def test_petrified_field_returns_a_land_card_from_its_own_graveyard(set_pool):
    """"{T}, Sacrifice this land: Return target land card from your graveyard
    to your hand." The target is chosen before the cost is paid (CR 601.2c
    precedes CR 601.2h), so the Field cannot return itself; a creature card
    and an opponent's land card are not offered."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool)
    field = _w1g2_put(game, 0, ody["Petrified Field"])
    game.players[0].graveyard.extend([lea["Grizzly Bears"], lea["Forest"], lea["Island"]])
    game.players[1].graveyard.append(lea["Swamp"])

    spec = game.activation_target_spec(0, game.battlefield_index_of(field), ability_index=1)
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Forest", "Island"]

    at_a_creature_card = game.queue_permanent_ability(
        0, "Petrified Field", ability_index=1, target_permanent_index=0,
    )
    assert not at_a_creature_card.supported and game.is_on_battlefield(field)

    assert game.activate_permanent_ability(
        0, "Petrified Field", ability_index=1, target_permanent_index=2,
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert [card.name for card in game.players[0].graveyard] == [
        "Grizzly Bears", "Forest", "Petrified Field",
    ]

    game = _w1g2_duel(set_pool)
    field = _w1g2_put(game, 0, ody["Petrified Field"])
    alone = game.queue_permanent_ability(0, "Petrified Field", ability_index=1)
    assert not alone.supported and game.is_on_battlefield(field)
    assert game.tap_land_for_mana(0, "Petrified Field", "C")
    assert _w1g2_floating(game) == {"C": 1}

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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
