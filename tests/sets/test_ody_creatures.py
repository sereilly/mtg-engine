"""Odyssey creatures.

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
    hand=(),
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
            library=list(their_library), life=20,
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


# --- Zombie Assassin --------------------------------------------------------
# "{T}, Exile two cards from your graveyard and this creature: Destroy target
# nonblack creature. It can't be regenerated." A chosen set and the source
# under one printed verb — Sandstone Deadfall's "two lands and this artifact"
# with the exile's verb, and read by the charger through the same reader.

def test_w1g6_zombie_assassin_exiles_two_cards_and_itself(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    cost = _w1g6_compile(ody["Zombie Assassin"]).activated_abilities[0].cost
    assert cost.requires_tap and cost.exile_self
    assert (cost.exile_zone, cost.exile_zone_owner, cost.exile_count) == (
        "graveyard", "you", 2,
    )

    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]],
        theirs=[lea["Grizzly Bears"], lea["Drudge Skeletons"]],
        yard=[lea["Forest"], lea["Forest"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    # The payer names the Bolt; the second card is the first other one.
    used = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[bears.permanent_id],
        cost_permanent_index=2,
    )

    assert used.supported, used.details
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Forest"], "exactly two of the three left"
    assert sorted(_w1g6_pile(game.players[0], "exile")) == [
        "Forest", "Lightning Bolt", "Zombie Assassin",
    ]
    assert _w1g6_names(game, 1) == ["Drudge Skeletons"]
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]


@_w1g6_pytest.mark.parametrize(
    "yard_size, tapped, named_slot, reason",
    [
        (1, False, None, "nothing available to exile"),
        (2, True, None, "already tapped"),
        (2, False, 5, "no card at graveyard position 5"),
    ],
)
def test_w1g6_zombie_assassin_refusals_pay_nothing(
    set_pool, yard_size, tapped, named_slot, reason
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * yard_size,
    )
    game.start_turn(0)
    _w1g6_named(game, 0, "Zombie Assassin").tapped = tapped
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    refused = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[bears.permanent_id],
        cost_permanent_index=named_slot,
    )

    assert not refused.supported
    assert reason in refused.details
    assert _w1g6_names(game, 0) == ["Zombie Assassin"]
    assert len(game.players[0].graveyard) == yard_size
    assert not game.players[0].exile
    assert _w1g6_names(game, 1) == ["Grizzly Bears"]


def test_w1g6_zombie_assassin_cannot_be_aimed_at_a_black_creature(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]], theirs=[lea["Drudge Skeletons"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    skeletons = _w1g6_named(game, 1, "Drudge Skeletons")

    refused = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[skeletons.permanent_id]
    )

    assert not refused.supported
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile

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
