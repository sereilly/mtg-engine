"""Torment creatures (legendary ones too).

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
# Madness (CR 702.35): the two madness creatures, and the creature half of the
# drive list — every Torment creature whose ability discards, each driven by
# discarding a madness card through it. Each is a different road into the
# discard seam (a cost, a cost "at random"), and a road that skipped the seam
# would be a madness card that never offered its cast.

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick, resolve_stack as _w1g1_resolve


def _w1g1_seat(set_pool, battlefield, hand, *, library=("Forest",) * 4):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    pool = {**lea, **tor}
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[_w1g1_nosick(_w1g1_Permanent(card=pool[n])) for n in battlefield],
            hand=[pool[n] for n in hand],
            library=[pool[n] for n in library],
        ),
        _w1g1_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = True
    return game


def test_w1g1_arrogant_wurm_enters_for_its_madness_cost(set_pool):
    """Discarded to Aquamoeba with three Forests out — its mana cost {3}{G}{G}
    is five — the Wurm is cast for {2}{G} by a seat nobody asks and enters as a
    4/4 trampler."""
    game = _w1g1_seat(
        set_pool, ["Aquamoeba", "Forest", "Forest", "Forest"], ["Arrogant Wurm"],
    )
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    wurm = next(p for p in game.players[0].battlefield if p.card.name == "Arrogant Wurm")
    assert (wurm.effective_power, wurm.effective_toughness) == (4, 4)
    assert game._has_keyword(wurm, "trample")
    assert all(
        land.tapped for land in game.players[0].battlefield if land.card.name == "Forest"
    )
    assert not game.players[0].exile and not game.players[0].graveyard


def test_w1g1_basking_rootwalla_enters_free_and_pumps_only_once_a_turn(set_pool):
    """Madness {0}: discarded with no land at all, it is cast for nothing.
    Then "{1}{G}: … +2/+2 until end of turn. Activate only once each turn." —
    the second activation in the turn is refused (CR 602.5b)."""
    game = _w1g1_seat(set_pool, ["Aquamoeba"], ["Basking Rootwalla"])
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    walla = next(
        p for p in game.players[0].battlefield if p.card.name == "Basking Rootwalla"
    )
    assert (walla.effective_power, walla.effective_toughness) == (1, 1)
    walla.metadata["summoning_sickness_turn"] = -99
    game.enforce_mana_costs = False
    assert game.activate_permanent_ability(0, "Basking Rootwalla").supported
    assert (walla.effective_power, walla.effective_toughness) == (3, 3)
    again = game.activate_permanent_ability(0, "Basking Rootwalla")
    assert not again.supported and "only once each turn" in again.details
    assert (walla.effective_power, walla.effective_toughness) == (3, 3)


#: The drive list's creatures: ``outlet -> (lands to tap for its own cost,
#: target seat or None)``. Each discards Obsessive Search (madness {U}), whose
#: cast is paid by the one Island left untapped.
_W1G1_CREATURE_OUTLETS = {
    "Aquamoeba": ((), None),
    "Skywing Aven": ((), None),
    "Aven Trooper": (("Plains", "Plains", "Plains"), None),
    "Hell-Bent Raider": ((), None),
    "Pardic Lancer": ((), None),
    "Putrid Imp": ((), None),
    "Grotesque Hybrid": ((), None),
}


@_w1g1_pytest.mark.parametrize("outlet", sorted(_W1G1_CREATURE_OUTLETS))
def test_w1g1_every_creature_discard_outlet_offers_the_madness_cast(set_pool, outlet):
    lands, _target = _W1G1_CREATURE_OUTLETS[outlet]
    game = _w1g1_seat(
        set_pool, [outlet, *lands, "Island"], ["Obsessive Search"],
    )
    for slot, land in enumerate(lands, start=1):
        assert game.tap_land_for_mana(0, land, permanent_index=slot)
    result = game.activate_permanent_ability(0, outlet, cost_hand_index=0)
    assert result.supported, (outlet, result.details)
    _w1g1_resolve(game)
    assert any(
        "discarded Obsessive Search into exile (madness)" in line for line in game.log
    ), outlet
    assert any(
        "cast Obsessive Search for its madness cost" in line for line in game.log
    ), outlet
    assert [c.name for c in game.players[0].graveyard] == ["Obsessive Search"], outlet
    # The card the Search drew (Skywing Aven's own ability returns it to the
    # hand beside it).
    assert "Forest" in [c.name for c in game.players[0].hand], outlet


def test_w1g1_pitchstone_wall_finds_no_madness_card_in_the_graveyard(set_pool):
    """The meeting point with W1G5's Pitchstone Wall ("Whenever you discard a
    card, you may sacrifice this creature. If you do, return the discarded card
    from your graveyard to your hand.").

    A madness card is discarded **into exile**, so it is not in the graveyard
    the Wall's ability looks in: the madness trigger goes on the stack inside
    the discard and the Wall's when the discard is announced, so the Wall's
    resolves first and finds nothing (CR 400.7). Whatever the Wall's
    controller then does, the card is cast or binned by madness and never
    returned to the hand. (Had the madness trigger resolved first and been
    declined, CR 400.7k would let the Wall find it — which is why the order is
    asserted, not assumed.)

    Skipped while the Wall is unsupported: it lands with W1G5, and the
    integrator merges that branch first.
    """
    from engine.oracle import compile_card_oracle

    tor, lea = set_pool("TOR"), set_pool("LEA")
    if not compile_card_oracle(tor["Pitchstone Wall"]).supported:
        _w1g1_pytest.skip("Pitchstone Wall lands with W1G5")
    game = _w1g1_seat(
        set_pool, ["Aquamoeba", "Pitchstone Wall", "Mountain"], ["Fiery Temper"],
    )
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert "Fiery Temper" not in [c.name for c in game.players[0].hand]
    log = game.log
    exiled = next(i for i, line in enumerate(log) if "Fiery Temper into exile" in line)
    offered = [
        i for i, line in enumerate(log)
        if "for its madness cost" in line and "Fiery Temper" in line
    ]
    assert offered and offered[0] > exiled


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

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
