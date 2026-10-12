"""Odyssey enchantments.

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

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(), their_hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(their_library), hand=list(their_hand), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Bearscape, Screams of the Damned ---------------------------------------
# Driven: the Atog-style graveyard exile costs on two enchantments.

def test_w1g6_bearscape_makes_a_bear_for_two_cards_and_nothing_for_one(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(mine=[ody["Bearscape"]], yard=[lea["Forest"]] * 3)
    game.start_turn(0)

    made = game.activate_permanent_ability(0, "Bearscape")

    assert made.supported, made.details
    assert len(game.players[0].graveyard) == 1 and len(game.players[0].exile) == 2
    bear = next(p for p in game.controlled_by(0) if p.card.name != "Bearscape")
    assert "Bear" in bear.card.type_line and "Creature" in bear.card.type_line
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert tuple(bear.card.colors) == ("G",)

    refused = game.activate_permanent_ability(0, "Bearscape")
    assert not refused.supported
    assert len(game.players[0].graveyard) == 1
    assert len(list(game.controlled_by(0))) == 2


def test_w1g6_screams_of_the_damned_pings_everything_for_one_card(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Screams of the Damned"], lea["Grizzly Bears"]],
        theirs=[lea["Birds of Paradise"], lea["Hill Giant"]],
        yard=[lea["Forest"]],
    )
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Screams of the Damned")
    game.check_state_based_actions()

    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "exile") == ["Forest"]
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert _w1g6_names(game, 1) == ["Hill Giant"]  # the 0/1 Birds died
    assert _w1g6_named(game, 0, "Grizzly Bears").damage_marked == 1

    # An empty graveyard cannot pay, and nothing is dealt.
    refused = game.activate_permanent_ability(0, "Screams of the Damned")
    assert not refused.supported
    assert (game.players[0].life, game.players[1].life) == (19, 19)

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
