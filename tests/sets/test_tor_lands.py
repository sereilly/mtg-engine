"""Torment lands.

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

import pytest as _w1g8_pytest

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.ai_policy import _plan_land_taps as _w1g8_plan_land_taps
from engine.board_payment import (board_can_pay as _w1g8_board_can_pay,
                                  tap_alone_symbols as _w1g8_tap_alone_symbols)
from engine.models import Permanent as _W1G8Permanent

#: Each Tainted land and the colour its second ability adds beside {B}.
_W1G8_TAINTED = (
    ("Tainted Field", "W"), ("Tainted Isle", "U"),
    ("Tainted Peak", "R"), ("Tainted Wood", "G"),
)


def _w1g8_lands(set_pool, names, *, enforce=False):
    lea, tor = set_pool("LEA"), set_pool("TOR")
    game = _W1G8Game(players=[
        _W1G8Player("A"), _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = enforce
    game.start_turn(0)
    game._close_current_priority_step()
    placed = []
    for name in names:
        permanent = _W1G8Permanent(card=tor.get(name) or lea[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        placed.append(permanent)
    return game, placed


def _w1g8_pool(game):
    return {k: v for k, v in game.players[0].mana_pool.items() if v}


@_w1g8_pytest.mark.parametrize("name, colour", _W1G8_TAINTED)
def test_w1g8_a_tainted_land_taps_for_its_colour_beside_a_swamp(set_pool, name, colour):
    """"{T}: Add {C}." / "{T}: Add {W} or {B}. Activate only if you control a
    Swamp." The tap seam refused every mana ability printing an "Activate
    only …" clause, so with a Swamp in play the land still made {C} and
    nothing else: a tap asked for its colour got {C}, and the planner and the
    castable highlight never counted the colour (a {W}{B} spell over a
    Tainted Field and a Swamp stayed dark). The clause is a board condition,
    which the seam now asks itself (``land_mana_tap_refusal``)."""
    game, (land, _swamp) = _w1g8_lands(set_pool, [name, "Swamp"])
    assert _w1g8_tap_alone_symbols(game, land) == ("C",) + tuple(
        sorted({colour, "B"}, key="WUBRG".index)
    )
    assert _w1g8_board_can_pay(game, 0, {colour: 1, "B": 1})
    assert game.tap_land_for_mana(0, name, chosen_color=colour)
    assert _w1g8_pool(game) == {colour: 1}

    game, (land, _swamp) = _w1g8_lands(set_pool, [name, "Swamp"])
    assert game.tap_land_for_mana(0, name)
    assert _w1g8_pool(game) == {"C": 1}, "a bare tap runs the free default"


@_w1g8_pytest.mark.parametrize("name, colour", _W1G8_TAINTED)
def test_w1g8_a_tainted_land_without_a_swamp_makes_only_colourless(set_pool, name, colour):
    """The clause enforced at the seam's door as at the activation path's:
    with no Swamp the coloured ability is no answer — asked for by colour the
    land makes its {C}, asked for by index it is refused with nothing tapped,
    and nothing that plans a payment counts the colour."""
    game, (land,) = _w1g8_lands(set_pool, [name])
    assert _w1g8_tap_alone_symbols(game, land) == ("C",)
    assert not _w1g8_board_can_pay(game, 0, {colour: 1})
    assert not _w1g8_board_can_pay(game, 0, {"B": 1})
    assert game.land_mana_tap_refusal(land, 1) == "activation_restricted"
    assert not game.tap_land_for_mana(0, name, ability_index=1)
    assert not land.tapped and not _w1g8_pool(game)
    assert game.tap_land_for_mana(0, name, chosen_color=colour)
    assert _w1g8_pool(game) == {"C": 1}


def test_w1g8_the_ai_plans_a_tainted_land_for_its_colour(set_pool):
    """The AI's tap planner reads the same yields: a {W}{B} cost over a Tainted
    Field and a Swamp is planned, the Field asked for {W}; take the Swamp away
    and there is no plan at all."""
    game, (field, swamp) = _w1g8_lands(set_pool, ["Tainted Field", "Swamp"])
    slots, colours = _w1g8_plan_land_taps(game, game.players[0], {"W": 1, "B": 1})
    assert sorted(zip(slots, colours)) == sorted([
        (game.battlefield_index_of(field), "W"),
        (game.battlefield_index_of(swamp), "B"),
    ])

    game, (field,) = _w1g8_lands(set_pool, ["Tainted Field"])
    assert _w1g8_plan_land_taps(game, game.players[0], {"W": 1}) is None


def test_w1g8_cabal_coffers_adds_a_black_for_each_swamp(set_pool):
    """"{2}, {T}: Add {B} for each Swamp you control." With three Swamps:
    two of them tapped pay the {2}, the Coffers adds three, and the third
    Swamp one more — four black from the four lands, the Swamps counted
    tapped or not."""
    game, (coffers, *swamps) = _w1g8_lands(
        set_pool, ["Cabal Coffers", "Swamp", "Swamp", "Swamp"], enforce=True,
    )
    for swamp in swamps[:2]:
        assert game.tap_land_for_mana(0, "Swamp", permanent_id=swamp.permanent_id)
    result = game.activate_permanent_ability(0, "Cabal Coffers")
    assert result.supported, result.details
    assert coffers.tapped and _w1g8_pool(game) == {"B": 3}
    assert game.tap_land_for_mana(0, "Swamp", permanent_id=swamps[2].permanent_id)
    assert _w1g8_pool(game) == {"B": 4}


def test_w1g8_cabal_coffers_cannot_be_tapped_without_its_two(set_pool):
    """The {2} is a cost (CR 602.2b): a bare tap through the seam is refused
    rather than adding free mana, and an activation with an empty pool is
    refused with the Coffers untapped."""
    game, (coffers, _swamp) = _w1g8_lands(
        set_pool, ["Cabal Coffers", "Swamp"], enforce=True,
    )
    assert game.land_mana_tap_refusal(coffers) == "priced_mana_ability"
    assert not game.tap_land_for_mana(0, "Cabal Coffers")
    assert not game.activate_permanent_ability(0, "Cabal Coffers").supported
    assert not coffers.tapped and not _w1g8_pool(game)

# ==== end W1G8 ======================================================
