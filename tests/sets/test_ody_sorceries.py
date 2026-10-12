"""Odyssey sorceries.

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
from engine.stack_targets import chosen_targets as _w1g6_chosen_targets
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; seat 0's turn has started."""
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
            library=list(library), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game  # _w1g6_game


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


# --- Piper's Melody ---------------------------------------------------------
# "Shuffle any number of target creature cards from your graveyard into your
# library." Gaea's Blessing's chosen cards out of the caster's own pile.

def _w1g6_melody(set_pool, **piles):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    piles.setdefault("yard", [
        lea["Grizzly Bears"], lea["Forest"], lea["Hill Giant"],
        lea["Grizzly Bears"], lea["Lightning Bolt"],
    ])
    return _w1g6_game(
        hand=[ody["Piper's Melody"]], library=[lea["Island"]] * 4,
        their_yard=[lea["Craw Wurm"]], **piles,
    )  # _w1g6_melody


def test_w1g6_pipers_melody_offers_only_your_own_creature_cards(set_pool):
    game = _w1g6_melody(set_pool)
    spec = game.cast_target_spec(0, set_pool("ODY")["Piper's Melody"])

    assert spec["own_graveyard_only"] and spec["card_type"] == "creature"
    assert [(t["seat"], t["index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, 0, "Grizzly Bears"), (0, 2, "Hill Giant"), (0, 3, "Grizzly Bears"),
    ]


def test_w1g6_pipers_melody_shuffles_in_exactly_the_cards_named(set_pool):
    game = _w1g6_melody(set_pool)

    # Both copies of one card: the same object in the pile twice.
    cast = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=0, target_permanent_index=[0, 3]
    )
    assert cast.supported, cast.details
    named = _w1g6_chosen_targets(game, game.stack[-1])
    assert [(t.stamp.card.name, t.stamp.ordinal) for t in named] == [
        ("Grizzly Bears", 0), ("Grizzly Bears", 1),
    ]
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0]) == [
        "Forest", "Hill Giant", "Lightning Bolt", "Piper's Melody",
    ]
    assert sorted(_w1g6_pile(game.players[0], "library")) == [
        "Grizzly Bears", "Grizzly Bears", "Island", "Island", "Island", "Island",
    ]


def test_w1g6_pipers_melody_may_name_none_and_still_resolves(set_pool):
    game = _w1g6_melody(set_pool)

    cast = game.queue_from_hand(0, "Piper's Melody")
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert len(game.players[0].graveyard) == 6   # the five, and the Melody
    assert len(game.players[0].library) == 4


@_w1g6_pytest.mark.parametrize(
    "seat, slots",
    [
        (0, [1]),      # the Forest is not a creature card
        (1, [0]),      # the opponent's Craw Wurm is not in your graveyard
        (0, [0, 0]),   # one card cannot fill two of the slots (CR 115.3)
    ],
)
def test_w1g6_pipers_melody_refuses_a_card_its_picker_does_not_offer(
    set_pool, seat, slots
):
    game = _w1g6_melody(set_pool)

    refused = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=seat, target_permanent_index=slots
    )

    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Piper's Melody"]
    assert len(game.players[0].graveyard) == 5 and len(game.players[0].library) == 4


def test_w1g6_pipers_melody_does_not_replace_a_target_that_left(set_pool):
    game = _w1g6_melody(set_pool)
    cast = game.queue_from_hand(
        0, "Piper's Melody", target_player_index=0, target_permanent_index=[0, 2]
    )
    assert cast.supported
    game.players[0].graveyard.pop(2)   # the Hill Giant leaves in response
    _w1g6_resolve_stack(game)

    # One Bears went in; the other Bears, never named, stayed (CR 608.2b).
    assert sorted(_w1g6_pile(game.players[0], "library")).count("Grizzly Bears") == 1
    assert _w1g6_pile(game.players[0]).count("Grizzly Bears") == 1


# --- Decompose --------------------------------------------------------------
# "Exile up to three target cards from a single graveyard." Driven. The pile
# and the cards are picked as it resolves (Ebony Charm's shipped route, a
# stated deviation from CR 601.2c): one graveyard, and up to three out of it.

def test_w1g6_decompose_exiles_up_to_three_cards_out_of_one_graveyard(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Decompose"]], yard=[lea["Forest"], lea["Island"]],
        their_yard=[
            lea["Hill Giant"], lea["Lightning Bolt"], lea["Craw Wurm"], lea["Sol Ring"],
        ],
    )
    game.interactive_seats = {0, 1}

    assert game.queue_from_hand(0, "Decompose").supported
    game.resolve_top_of_stack()
    pile = game.pending_choices[0]
    assert (pile.kind, pile.player_index, pile.data["seats"]) == (
        "graveyard_pile_choice", 0, [0, 1],
    )
    assert game.confirm_graveyard_pile_choice(0, 1)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.data["owner_index"], pick.data["count"], pick.data["up_to"]) == (
        "graveyard_exile_pick", 1, 3, True,
    )
    # Four is more than three, and a card of the other pile is not in this one.
    assert not game.confirm_graveyard_exile_pick(0, [0, 1, 2, 3])
    assert game.confirm_graveyard_exile_pick(0, [0, 2, 3])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert sorted(_w1g6_pile(game.players[1], "exile")) == [
        "Craw Wurm", "Hill Giant", "Sol Ring",
    ]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Island", "Decompose"]


def test_w1g6_decompose_with_no_card_anywhere_resolves_and_exiles_nothing(set_pool):
    game = _w1g6_game(hand=[set_pool("ODY")["Decompose"]])
    game.interactive_seats = {0, 1}

    assert game.queue_from_hand(0, "Decompose").supported
    _w1g6_resolve_stack(game)

    assert not game.pending_choices
    assert _w1g6_pile(game.players[0]) == ["Decompose"]


# --- Zombify ----------------------------------------------------------------
# "Return target creature card from your graveyard to the battlefield." Driven.

def test_w1g6_zombify_returns_the_creature_card_it_was_aimed_at(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Zombify"]],
        yard=[lea["Forest"], lea["Craw Wurm"], lea["Hill Giant"]],
        their_yard=[lea["Shivan Dragon"]],
    )

    # Not a land card, and not somebody else's creature card.
    assert not game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=0
    ).supported
    assert not game.queue_from_hand(
        0, "Zombify", target_player_index=1, target_permanent_index=0
    ).supported

    cast = game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=2
    )
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert _w1g6_names(game, 0) == ["Hill Giant"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Craw Wurm", "Zombify"]


def test_w1g6_zombify_does_nothing_when_its_target_has_left(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Zombify"]], yard=[lea["Craw Wurm"], lea["Hill Giant"]],
    )
    assert game.queue_from_hand(
        0, "Zombify", target_player_index=0, target_permanent_index=0
    ).supported
    game.players[0].graveyard.pop(0)
    _w1g6_resolve_stack(game)

    # CR 608.2b: the other creature card is not reanimated in its place.
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Hill Giant", "Zombify"]

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
