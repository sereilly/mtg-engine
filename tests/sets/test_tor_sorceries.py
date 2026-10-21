"""Torment sorceries.

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

import random as _w1g5_random

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.cast_costs import cast_announces_x as _w1g5_cast_announces_x
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_game(spell, *, hand=(), graveyard=(), bf0=(), bf1=(), library=None):
    """Seat 0 on its own main phase holding *spell* first in hand, mana free."""
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library) if library is not None else [filler] * 10,
            hand=[spell, *hand], graveyard=list(graveyard),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10,
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def _w1g5_names(cards):
    return [card.name for card in cards]


def test_w1g5_restless_dreams_at_x_zero_is_cast_at_an_empty_graveyard(set_pool):
    """"Return **X** target creature cards": at an X of zero it names nobody
    (CR 601.2c), so an empty graveyard is a legal cast that discards and
    returns nothing — the per-kind arm refused it "no valid target"."""
    dreams = set_pool("TOR")["Restless Dreams"]
    forest = set_pool("LEA")["Forest"]
    game = _w1g5_game(dreams, hand=[forest])

    result = game.cast_from_hand(0, dreams.name, x_value=0)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g5_names(game.players[0].hand) == ["Forest"]
    assert _w1g5_names(game.players[0].graveyard) == ["Restless Dreams"]


def test_w1g5_restless_dreams_at_x_two_discards_the_two_named_and_returns_two(set_pool):
    """X=2: the caster names both discards (the second was refused "discards 1
    card(s)" — the gate compared with the printed field, not the announced X)
    and two creature cards come back."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Restless Dreams"]
    forest, bolt, island = lea["Forest"], lea["Lightning Bolt"], lea["Island"]
    bears, giant = lea["Grizzly Bears"], lea["Hill Giant"]
    game = _w1g5_game(
        dreams, hand=[forest, bolt, island], graveyard=[bears, giant, forest],
    )

    result = game.cast_from_hand(
        0, dreams.name, x_value=2, target_permanent_index=[0, 1],
        cost_hand_index=2, cost_other_hand_indices=[3],
    )
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    assert sorted(_w1g5_names(game.players[0].hand)) == [
        "Forest", "Grizzly Bears", "Hill Giant",
    ]
    assert sorted(_w1g5_names(game.players[0].graveyard)) == [
        "Forest", "Island", "Lightning Bolt", "Restless Dreams",
    ]
    assert "A discarded Lightning Bolt to cast Restless Dreams" in game.log
    assert "A discarded Island to cast Restless Dreams" in game.log


def test_w1g5_restless_dreams_at_x_two_needs_two_creature_cards(set_pool):
    """The other direction: once X is one or more the count is exact."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Restless Dreams"]
    game = _w1g5_game(
        dreams, hand=[lea["Forest"], lea["Island"]],
        graveyard=[lea["Grizzly Bears"], lea["Forest"]],
    )

    result = game.cast_from_hand(0, dreams.name, x_value=2, target_permanent_index=[0])

    assert not result.supported
    assert _w1g5_names(game.players[0].hand) == ["Restless Dreams", "Forest", "Island"]


def test_w1g5_devastating_dreams_announces_x_and_charges_it_at_random(set_pool):
    """"Discard X cards **at random**" is one clause with two modifiers: the X
    is announced (CR 107.3a) and the discards are chance's, so a named card
    is not what goes. Each player then sacrifices X lands and every creature
    is dealt X."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    assert _w1g5_cast_announces_x(dreams)
    forest, mountain, island = lea["Forest"], lea["Mountain"], lea["Island"]
    bears, giant = lea["Grizzly Bears"], lea["Hill Giant"]
    hand = [forest, lea["Lightning Bolt"], island, giant]
    game = _w1g5_game(
        dreams, hand=hand, bf0=[mountain, mountain, forest, bears],
        bf1=[island, island, island, giant, bears],
    )
    _w1g5_random.seed(11)

    result = game.cast_from_hand(0, dreams.name, x_value=2)
    _w1g5_resolve_stack(game)

    assert result.supported, result.details
    a, b = game.players
    assert len(a.hand) == 2  # four held, two discarded at random
    discarded = [line for line in game.log if "to cast Devastating Dreams" in line]
    assert len(discarded) == 2
    lands = lambda seat: [  # noqa: E731
        p.card.name for p in game.controlled_by(seat) if p.has_type("land")
    ]
    assert len(lands(0)) == 1 and len(lands(1)) == 1
    # Two damage to each creature: the Bears die, the Giant (3/3) lives.
    creatures = lambda seat: [  # noqa: E731
        p.card.name for p in game.controlled_by(seat) if p.is_creature
    ]
    assert creatures(0) == [] and creatures(1) == ["Hill Giant"]
    assert a.life == 20 and b.life == 20


def test_w1g5_devastating_dreams_x_is_bounded_by_the_hand(set_pool):
    """CR 601.2h: X=3 with two other cards in hand cannot be paid."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    game = _w1g5_game(dreams, hand=[lea["Forest"], lea["Island"]], bf0=[lea["Mountain"]])

    result = game.cast_from_hand(0, dreams.name, x_value=3)

    assert not result.supported
    assert _w1g5_names(game.players[0].hand) == ["Devastating Dreams", "Forest", "Island"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Mountain"]


def test_w1g5_devastating_dreams_asks_an_interactive_seat_which_lands(set_pool):
    """"…lands **of their choice**": a person is asked, through the standing
    sacrifice prompt, and the spell waits on the stack for the answer."""
    lea = set_pool("LEA")
    dreams = set_pool("TOR")["Devastating Dreams"]
    game = _w1g5_game(
        dreams, hand=[lea["Forest"]], bf0=[lea["Mountain"]],
        bf1=[lea["Island"], lea["Forest"]],
    )
    game.interactive_seats = {1}

    result = game.cast_from_hand(0, dreams.name, x_value=1)

    assert result.supported, result.details
    owed = [choice for choice in game.pending_choices if choice.kind == "sacrifice"]
    assert [choice.player_index for choice in owed] == [1]
    assert game.stack, "the spell resolves only once the choice is made"

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
