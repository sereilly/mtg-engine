"""Torment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Madness (CR 702.35): the two madness Auras, cast out of exile for their
# madness cost and targeting as they are cast (CR 303.4a, CR 601.2c), and the
# enchantment half of the drive list (Compulsion, Pyromania).

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick, resolve_stack as _w1g1_resolve


def _w1g1_aura_board(set_pool, aura, land):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    bears = _w1g1_nosick(_w1g1_Permanent(card=lea["Grizzly Bears"]))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[
                _w1g1_nosick(_w1g1_Permanent(card=tor["Aquamoeba"])),
                _w1g1_Permanent(card=lea[land]),
                bears,
            ],
            hand=[tor[aura]],
        ),
        _w1g1_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = {0}
    return game, bears


@_w1g1_pytest.mark.parametrize(
    "aura,land,pt,quality",
    [
        ("Strength of Isolation", "Plains", (3, 4), ("color", "B")),
        ("Strength of Lunacy", "Swamp", (4, 3), ("color", "W")),
    ],
)
def test_w1g1_a_madness_aura_is_cast_out_of_exile_onto_the_creature_it_names(
    set_pool, aura, land, pt, quality,
):
    """Discarded to Aquamoeba, the Aura is cast for its one-mana madness cost
    and enchants the creature the cast named — not the first creature a scan
    meets (Aquamoeba is first on the battlefield)."""
    game, bears = _w1g1_aura_board(set_pool, aura, land)
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert game.pending_choice_of("madness_cast", 0) is not None
    assert game.tap_land_for_mana(0, land)
    assert game.confirm_madness_cast(0, True, target_permanent_ids=[bears.permanent_id])
    _w1g1_resolve(game)
    enchanting = next(p for p in game.players[0].battlefield if p.card.name == aura)
    assert enchanting.metadata.get("attached_to") is bears
    assert (bears.effective_power, bears.effective_toughness) == pt
    assert quality in game._protection_qualities(bears)


#: The drive list's enchantments: ``outlet -> (lands for its own cost, the
#: target its ability names)``.
_W1G1_ENCHANTMENT_OUTLETS = {
    "Compulsion": (("Island", "Island"), None),
    "Pyromania": (("Mountain", "Mountain"), 1),
}


@_w1g1_pytest.mark.parametrize("outlet", sorted(_W1G1_ENCHANTMENT_OUTLETS))
def test_w1g1_every_enchantment_discard_outlet_offers_the_madness_cast(set_pool, outlet):
    """Compulsion's "{1}{U}, Discard a card" and Pyromania's "{1}{R}, Discard a
    card at random", each discarding Obsessive Search (madness {U}): the cast
    is offered and made by a seat nobody asks, paid by the Island left over."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    lands, target = _W1G1_ENCHANTMENT_OUTLETS[outlet]
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[_w1g1_Permanent(card=tor[outlet])]
            + [_w1g1_Permanent(card=lea[land]) for land in (*lands, "Island")],
            hand=[tor["Obsessive Search"]],
            library=[lea["Forest"]] * 4,
        ),
        _w1g1_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = True
    for slot, land in enumerate(lands, start=1):
        assert game.tap_land_for_mana(0, land, permanent_index=slot)
    result = game.activate_permanent_ability(
        0, outlet, cost_hand_index=0, target_player_index=target,
    )
    assert result.supported, (outlet, result.details)
    _w1g1_resolve(game)
    assert any(
        "cast Obsessive Search for its madness cost" in line for line in game.log
    ), outlet
    assert [c.name for c in game.players[0].graveyard] == ["Obsessive Search"]
    hand = [c.name for c in game.players[0].hand]
    # The Search's draw, and Compulsion's own "Draw a card" behind it.
    assert hand == (["Forest", "Forest"] if outlet == "Compulsion" else ["Forest"])
    if outlet == "Pyromania":
        assert game.players[1].life == 19

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
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine.activation_prohibitions import activation_prohibition as _w1g6_activation_prohibition  # noqa: E402
from engine.board_payment import board_can_pay as _w1g6_board_can_pay  # noqa: E402
from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick, resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_touch_table(set_pool, catalog_by_name, theirs):
    """Seat 0 holds Stupefying Touch and a library; seat 1 has *theirs*."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", hand=[set_pool("TOR")["Stupefying Touch"]],
            library=[catalog_by_name["Island"]] * 3,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=[
                _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name])) for name in theirs
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game


def _w1g6_touch(game, host) -> None:
    assert game.cast_from_hand(
        0, "Stupefying Touch",
        target_permanent_ids=[host.permanent_id], target_player_index=1,
    ).supported
    _w1g6_resolve_stack(game)


def test_w1g6_stupefying_touch_draws_and_shuts_off_the_creature_s_abilities(
    set_pool, catalog_by_name,
):
    """"Enchant creature / When this Aura enters, draw a card. / Enchanted
    creature's activated abilities can't be activated." A Prodigal Sorcerer
    under it cannot ping; its controller draws a card as it enters; when the
    Aura leaves, the Sorcerer pings again."""
    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Prodigal Sorcerer"])
    sorcerer = game.players[1].battlefield[0]
    _w1g6_touch(game, sorcerer)
    assert [c.name for c in game.players[0].hand] == ["Island"], "the entry trigger drew"
    refused = game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    assert not refused.supported and "can't be activated" in refused.details
    assert game.players[0].life == 20 and not sorcerer.tapped

    touch = next(p for p in game.controlled_by(0) if p.card.name == "Stupefying Touch")
    game.remove_from_battlefield(touch)
    assert game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 19


def test_w1g6_stupefying_touch_stops_mana_abilities_too(set_pool, catalog_by_name):
    """The card's ruling (2016-06-08): "Unlike many similar abilities,
    Stupefying Touch's last ability stops mana abilities from being
    activated." A Llanowar Elves under it adds nothing through the activation
    path, and the payment planner does not count it. A Forest that Living
    Lands has made a creature is a legal host too, and the land's own tap
    door refuses it as well — the second door to the same ability."""
    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Llanowar Elves", "Forest"])
    elves = game.players[1].battlefield[0]
    game.enforce_mana_costs = True
    assert _w1g6_board_can_pay(game, 1, {"G": 2}, nonland_sources=True)
    game.enforce_mana_costs = False
    _w1g6_touch(game, elves)
    game.enforce_mana_costs = True
    mana = next(a for a in game.usable_abilities_of(elves))
    assert _w1g6_activation_prohibition(game, 1, elves, mana) is not None
    assert not _w1g6_board_can_pay(game, 1, {"G": 2}, nonland_sources=True)
    assert _w1g6_board_can_pay(game, 1, {"G": 1}, nonland_sources=True)
    refused = game.activate_permanent_ability(1, "Llanowar Elves")
    assert not refused.supported
    assert game.players[1].mana_pool["G"] == 0 and not elves.tapped

    game = _w1g6_touch_table(set_pool, catalog_by_name, ["Living Lands", "Forest", "Forest"])
    forest, other = game.players[1].battlefield[1:]
    assert forest.is_creature
    _w1g6_touch(game, forest)
    assert not game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    assert game.players[1].mana_pool["G"] == 0 and not forest.tapped
    assert game.log[-1] == "Forest's activated abilities can't be activated"
    # The Forest beside it, unenchanted, taps as ever.
    assert game.tap_land_for_mana(1, "Forest", permanent_id=other.permanent_id)
    assert game.players[1].mana_pool["G"] == 1

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
