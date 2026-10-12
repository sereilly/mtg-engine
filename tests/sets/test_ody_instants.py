"""Odyssey instants.

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


# --- Skeletal Scrying -------------------------------------------------------
# "As an additional cost to cast this spell, exile X cards from your
# graveyard. / You draw X cards and you lose X life." Refused at the support
# gate ("printed cost nothing charges"): the graveyard-exile clause reader
# admitted only a phrase naming a card type, and this one prints "cards".

def test_w1g6_skeletal_scrying_charges_x_cards_for_x_cards_and_x_life(set_pool):
    from engine.cast_costs import additional_costs

    lea, ody = set_pool("LEA"), set_pool("ODY")
    scrying = ody["Skeletal Scrying"]
    (cost,) = additional_costs(scrying)
    assert cost.exile_graveyard_filter == {} and cost.exile_graveyard_count_x

    game = _w1g6_game(
        hand=[scrying],
        yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)
    # The X box is capped by what the graveyard can pay.
    assert game.cast_target_spec(0, scrying)["max_x"] == 3

    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    # Paid as it is cast (CR 601.2h): two cards are gone before it resolves.
    assert len(game.players[0].exile) == 2 and len(game.players[0].graveyard) == 1
    assert not game.players[0].hand and game.players[0].life == 20
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0], "hand") == ["Island", "Island"]
    assert game.players[0].life == 18
    assert len(game.players[0].library) == 4


def test_w1g6_skeletal_scrying_cannot_announce_more_than_the_graveyard_holds(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"], lea["Lightning Bolt"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)

    refused = game.queue_from_hand(0, "Skeletal Scrying", x_value=3)

    assert not refused.supported
    assert "holds 2 card(s) and its additional cost exiles 3" in refused.details
    assert _w1g6_pile(game.players[0], "hand") == ["Skeletal Scrying"]
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile


def test_w1g6_skeletal_scrying_pays_x_in_mana_as_well_as_in_cards(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"]] * 3,
        library=[lea["Island"]] * 6,
    )
    game.enforce_mana_costs = True
    game.start_turn(0)

    game.players[0].mana_pool["B"] = 2
    short = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert not short.supported
    assert len(game.players[0].graveyard) == 3, "a refused cast exiled nothing"

    game.players[0].mana_pool["B"] = 3
    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 18 and len(game.players[0].hand) == 2

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
