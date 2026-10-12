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


# --- Painbringer ------------------------------------------------------------
# "{T}, Exile any number of cards from your graveyard: Target creature gets
# -X/-X until end of turn, where X is the number of cards exiled this way."
# The count is the payer's (CR 601.2b) and is named by graveyard slot; X is
# read back off what the cost ate, not off any zone.

def test_w1g6_painbringer_shrinks_by_the_cards_its_payer_names(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    cost = _w1g6_compile(ody["Painbringer"]).activated_abilities[0].cost
    assert (cost.exile_zone, cost.exile_zone_owner, cost.exile_count) == (
        "graveyard", "you", "any",
    )

    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    used = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=[0, 2, 3],
    )

    assert used.supported, used.details
    # One of the two Forests — one object in the pile twice — and exactly one.
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert sorted(_w1g6_pile(game.players[0], "exile")) == [
        "Forest", "Hill Giant", "Lightning Bolt",
    ]
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)


def test_w1g6_painbringer_naming_no_cards_pays_the_cost_and_shrinks_by_zero(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    used = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id]
    )

    # Zero is a number: nothing is defaulted, so no graveyard is eaten for a
    # seat that named nothing.
    assert used.supported, used.details
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert _w1g6_named(game, 0, "Painbringer").tapped


@_w1g6_pytest.mark.parametrize(
    "named, reason",
    [([0, 5], "no card at graveyard position 5"), ([1, 1], "more than once")],
)
def test_w1g6_painbringer_an_unpayable_announcement_is_refused_with_nothing_paid(
    set_pool, named, reason
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    refused = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=named,
    )

    assert not refused.supported and reason in refused.details
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile
    assert not _w1g6_named(game, 0, "Painbringer").tapped


def test_w1g6_painbringer_kills_what_it_shrinks_to_nothing(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * 3,
    )
    game.start_turn(0)
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    queued = game.queue_permanent_ability(
        0, "Painbringer", target_permanent_ids=[bears.permanent_id],
        cost_graveyard_indices=[0, 1],
    )
    assert queued.details == "queued"
    # The cost is paid before the ability is on the stack (CR 601.2h)…
    assert len(game.players[0].exile) == 2
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()

    # …and X is still two when it resolves, with those cards long gone.
    assert _w1g6_names(game, 1) == []
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]


def test_w1g6_the_exile_cost_picker_offers_every_card_not_only_creatures(set_pool):
    """"Exile two cards from your graveyard" names no type, and a graveyard
    spec that names none is read as "a creature card". The picker offered a
    pile of lands nothing to click for a cost the charger takes any card for."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    for name, index in (("Psychatog", 1), ("Sarcatog", 0), ("Painbringer", 0)):
        game = _w1g6_game(
            mine=[ody[name]], theirs=[lea["Grizzly Bears"]],
            yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
            their_yard=[lea["Forest"]],
        )
        game.start_turn(0)
        spec = game.activation_target_spec(0, 0, ability_index=index)
        cost_spec = spec.get("cost_spec", spec)
        assert cost_spec["exile_cost"] and cost_spec["any_card"], (name, cost_spec)
        offered = [
            (entry["seat"], entry["name"]) for entry in cost_spec["valid_targets"]
        ]
        # The payer's own pile, all of it, and nobody else's.
        assert offered == [
            (0, "Forest"), (0, "Lightning Bolt"), (0, "Hill Giant"),
        ], (name, offered)
    assert cost_spec.get("any_number") is True and "count" not in cost_spec


# --- Psychatog, Sarcatog ----------------------------------------------------
# "Exile two cards from your graveyard: This creature gets +1/+1 until end of
# turn." Driven: two cards or nothing, the two the payer names.

def test_w1g6_psychatog_eats_the_two_cards_named_and_refuses_one(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Psychatog"]], hand=[lea["Forest"]],
        yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game.start_turn(0)
    tog = _w1g6_named(game, 0, "Psychatog")

    grown = game.activate_permanent_ability(
        0, "Psychatog", ability_index=1, cost_graveyard_indices=[1, 2]
    )
    assert grown.supported, grown.details
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert (tog.effective_power, tog.effective_toughness) == (2, 3)

    # One card left: no payment of a two-card cost (CR 601.2h).
    refused = game.activate_permanent_ability(0, "Psychatog", ability_index=1)
    assert not refused.supported
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert (tog.effective_power, tog.effective_toughness) == (2, 3)

    # The discard half feeds the graveyard the exile half eats.
    fed = game.activate_permanent_ability(
        0, "Psychatog", ability_index=0, cost_hand_index=0
    )
    assert fed.supported, fed.details
    assert not game.players[0].hand and len(game.players[0].graveyard) == 2
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)

    too_many = game.activate_permanent_ability(
        0, "Psychatog", ability_index=1, cost_graveyard_indices=[0, 1, 0]
    )
    assert not too_many.supported
    assert len(game.players[0].graveyard) == 2


def test_w1g6_sarcatog_pays_each_ability_with_its_own_resource(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Sarcatog"], lea["Sol Ring"]], yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    tog = _w1g6_named(game, 0, "Sarcatog")

    assert game.activate_permanent_ability(0, "Sarcatog", ability_index=0).supported
    assert not game.players[0].graveyard and len(game.players[0].exile) == 2
    assert game.activate_permanent_ability(0, "Sarcatog", ability_index=1).supported
    assert _w1g6_pile(game.players[0]) == ["Sol Ring"]
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)

    # Both resources gone: neither ability activates, and the Sol Ring that
    # just arrived in the graveyard is one card, not two.
    assert not game.activate_permanent_ability(0, "Sarcatog", ability_index=1).supported
    assert not game.activate_permanent_ability(0, "Sarcatog", ability_index=0).supported
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)


# --- Cabal Patriarch --------------------------------------------------------
# "{2}{B}, Exile a creature card from your graveyard: Target creature gets
# -2/-2 until end of turn." The narrowed twin of the costs above.

def test_w1g6_cabal_patriarch_exiles_a_creature_card_and_no_other(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Cabal Patriarch"], lea["Grizzly Bears"]],
        theirs=[lea["Hill Giant"]], yard=[lea["Forest"], lea["Craw Wurm"]],
    )
    game.start_turn(0)
    giant = _w1g6_named(game, 1, "Hill Giant")

    # The Forest is named and is not a creature card: refused, not swapped.
    refused = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=1,
        target_permanent_ids=[giant.permanent_id], cost_permanent_index=0,
    )
    assert not refused.supported
    assert _w1g6_pile(game.players[0]) == ["Forest", "Craw Wurm"]

    used = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=1,
        target_permanent_ids=[giant.permanent_id],
    )
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert _w1g6_pile(game.players[0], "exile") == ["Craw Wurm"]
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)

    # The other ability sacrifices a creature instead, for the same effect.
    again = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[_w1g6_named(game, 0, "Grizzly Bears").permanent_id],
    )
    game.check_state_based_actions()
    assert again.supported, again.details
    assert _w1g6_names(game, 0) == ["Cabal Patriarch"]
    assert _w1g6_names(game, 1) == []

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
