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


# --- combat helpers ---------------------------------------------------------

def _w1g6_slot(game, seat, permanent):
    return next(
        index for index, held in enumerate(game.controlled_by(seat))
        if held is permanent
    )  # _w1g6_slot


def _w1g6_to_declare_attackers(game, seat):
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step


def _w1g6_answer(game, *, accept, pick=None):
    """Resolve the stack, answering each prompt it stops for: a "may" by
    *accept*, a graveyard pick with *pick*."""
    for _ in range(12):
        if game.stack:
            game.resolve_top_of_stack()
        if not game.pending_choices:
            if not game.stack:
                return
            continue
        choice = game.pending_choices[0]
        if choice.kind == "optional_pay":
            assert game.confirm_optional_pay(choice.player_index, accept=accept)
        elif choice.kind == "graveyard_exile_pick":
            assert game.confirm_graveyard_exile_pick(choice.player_index, [pick])
        else:
            raise AssertionError(f"unexpected prompt {choice.kind}")
    raise AssertionError("the stack did not settle")  # _w1g6_answer


# --- Rotting Giant ----------------------------------------------------------
# "Whenever this creature attacks or blocks, sacrifice it unless you exile a
# card from your graveyard." A toll whose price is an action
# (``tolls.accept_graveyard_exile_price``): offered only where it can be paid.

def _w1g6_giant_attacks(set_pool, yard):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Rotting Giant"]], theirs=[lea["Grizzly Bears"]], yard=yard,
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 0)
    giant = _w1g6_named(game, 0, "Rotting Giant")
    assert game.declare_attackers(0, [_w1g6_slot(game, 0, giant)])[0]
    assert len(game.stack) == 1 and game.stack[0].is_ability
    return game  # _w1g6_giant_attacks


def test_w1g6_rotting_giant_stays_when_its_controller_exiles_a_card(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_giant_attacks(set_pool, [lea["Forest"], lea["Lightning Bolt"]])

    _w1g6_answer(game, accept=True, pick=1)

    assert _w1g6_names(game, 0) == ["Rotting Giant"]
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert _w1g6_pile(game.players[0], "exile") == ["Lightning Bolt"]


def test_w1g6_rotting_giant_is_sacrificed_when_the_price_is_declined(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_giant_attacks(set_pool, [lea["Forest"]])

    _w1g6_answer(game, accept=False)

    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Forest", "Rotting Giant"]
    assert not game.players[0].exile


def test_w1g6_rotting_giant_with_an_empty_graveyard_is_not_offered_the_price(
    set_pool,
):
    game = _w1g6_giant_attacks(set_pool, [])

    game.resolve_top_of_stack()

    # Nothing to exile is not a choice: no prompt, and the penalty stands.
    assert not game.pending_choices
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Rotting Giant"]


def test_w1g6_rotting_giant_owes_the_same_toll_when_it_blocks(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Rotting Giant"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]],
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 1)
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    assert game.declare_attackers(1, [_w1g6_slot(game, 1, bears)])[0]
    game.advance_combat_phase()
    giant = _w1g6_named(game, 0, "Rotting Giant")
    blocked = game.declare_blockers(
        0, {_w1g6_slot(game, 0, giant): _w1g6_slot(game, 1, bears)}
    )
    assert blocked[0], blocked

    _w1g6_answer(game, accept=True, pick=0)

    assert _w1g6_names(game, 0) == ["Rotting Giant"]
    assert not game.players[0].graveyard
    assert _w1g6_pile(game.players[0], "exile") == ["Forest"]


# --- Zombie Cannibal --------------------------------------------------------
# "Whenever this creature deals combat damage to a player, you may exile
# target card from that player's graveyard." One card out of the pile the
# damage event named, picked by the Cannibal's controller as it resolves.

def _w1g6_cannibal_connects(set_pool, their_yard, *, blocked=False):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Cannibal"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Craw Wurm"]], their_yard=their_yard,
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 0)
    cannibal = _w1g6_named(game, 0, "Zombie Cannibal")
    assert game.declare_attackers(0, [_w1g6_slot(game, 0, cannibal)])[0]
    game.advance_combat_phase()
    blocks = (
        {_w1g6_slot(game, 1, _w1g6_named(game, 1, "Grizzly Bears")):
         _w1g6_slot(game, 0, cannibal)}
        if blocked else {}
    )
    assert game.declare_blockers(1, blocks)[0]
    for _ in range(4):
        if game.stack or game.pending_choices or game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
    return game  # _w1g6_cannibal_connects


def test_w1g6_zombie_cannibal_exiles_a_chosen_card_from_the_damaged_players_pile(
    set_pool,
):
    lea = set_pool("LEA")
    game = _w1g6_cannibal_connects(
        set_pool, [lea["Forest"], lea["Hill Giant"], lea["Lightning Bolt"]]
    )
    assert game.players[1].life == 19

    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=True)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.player_index, pick.data["owner_index"]) == (
        "graveyard_exile_pick", 0, 1,
    )
    assert game.confirm_graveyard_exile_pick(0, [1])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest", "Lightning Bolt"]
    assert _w1g6_pile(game.players[1], "exile") == ["Hill Giant"]
    # Never the Cannibal's own graveyard.
    assert _w1g6_pile(game.players[0]) == ["Craw Wurm"]


def test_w1g6_zombie_cannibal_may_decline_and_asks_nothing_of_an_empty_pile(
    set_pool,
):
    lea = set_pool("LEA")
    declined = _w1g6_cannibal_connects(set_pool, [lea["Forest"]])
    assert declined.confirm_optional_pay(0, accept=False)
    _w1g6_resolve_stack(declined)
    assert _w1g6_pile(declined.players[1]) == ["Forest"]
    assert not declined.players[1].exile

    # Their graveyard is empty and the Cannibal's own is not: there is no
    # legal card, so nothing is offered and nothing is taken from anywhere.
    empty = _w1g6_cannibal_connects(set_pool, [])
    _w1g6_resolve_stack(empty)
    assert empty.players[1].life == 19
    assert not empty.pending_choices
    assert _w1g6_pile(empty.players[0]) == ["Craw Wurm"] and not empty.players[0].exile


def test_w1g6_zombie_cannibal_blocked_deals_no_damage_to_a_player(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_cannibal_connects(set_pool, [lea["Forest"]], blocked=True)
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g6_resolve_stack(game)

    assert game.players[1].life == 20 and not game.pending_choices
    assert _w1g6_pile(game.players[1]) == ["Forest"]


# --- Crypt Creeper, Famished Ghoul ------------------------------------------
# Driven. "Sacrifice this creature: Exile target card from a graveyard."

def test_w1g6_crypt_creeper_exiles_the_card_it_was_aimed_at(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Crypt Creeper"]], yard=[lea["Forest"]],
        their_yard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    spec = game.activation_target_spec(0, 0, ability_index=0)
    # Any card in any graveyard — and not itself, which is still a permanent
    # when the target is chosen (CR 601.2c precedes CR 601.2h).
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [
        (0, "Forest"), (1, "Grizzly Bears"), (1, "Lightning Bolt"),
    ]

    used = game.activate_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=1
    )

    assert used.supported, used.details
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]
    assert _w1g6_pile(game.players[1], "exile") == ["Lightning Bolt"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Crypt Creeper"]


def test_w1g6_crypt_creeper_is_not_sacrificed_for_nothing(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    # No card in any graveyard: no legal target, so it cannot be activated.
    game = _w1g6_game(mine=[ody["Crypt Creeper"]])
    game.start_turn(0)
    assert not game.activate_permanent_ability(0, "Crypt Creeper").supported
    assert _w1g6_names(game, 0) == ["Crypt Creeper"]

    # A slot that names no card is refused with nothing paid.
    game = _w1g6_game(mine=[ody["Crypt Creeper"]], their_yard=[lea["Grizzly Bears"]])
    game.start_turn(0)
    refused = game.activate_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=4
    )
    assert not refused.supported and _w1g6_names(game, 0) == ["Crypt Creeper"]


def test_w1g6_crypt_creeper_does_nothing_once_its_target_has_left(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Crypt Creeper"]],
        their_yard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    queued = game.queue_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=0
    )
    assert queued.details == "queued"
    game.players[1].graveyard.pop(0)
    _w1g6_resolve_stack(game)

    # CR 608.2b: the Bolt is not exiled in the Bears' place.
    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert not game.players[1].exile


def test_w1g6_famished_ghoul_exiles_up_to_two_cards_from_one_graveyard(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Famished Ghoul"]], yard=[lea["Forest"]],
        their_yard=[lea["Hill Giant"], lea["Lightning Bolt"], lea["Craw Wurm"]],
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)

    queued = game.queue_permanent_ability(0, "Famished Ghoul")
    assert queued.details == "queued"
    assert _w1g6_pile(game.players[0]) == ["Forest", "Famished Ghoul"]
    game.resolve_top_of_stack()
    assert game.confirm_graveyard_pile_choice(0, 1)
    pick = game.pending_choices[0]
    assert (pick.data["owner_index"], pick.data["count"], pick.data["up_to"]) == (
        1, 2, True,
    )
    assert not game.confirm_graveyard_exile_pick(0, [0, 1, 2])   # three is too many
    assert game.confirm_graveyard_exile_pick(0, [0, 2])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert sorted(_w1g6_pile(game.players[1], "exile")) == ["Craw Wurm", "Hill Giant"]


# --- Anarchist, Auramancer, Cartographer, Gravedigger, Scrivener ------------
# Driven. "When this creature enters, you may return target <type> card from
# your graveyard to your hand." Five types, one template.

_W1G6_RETURNERS = [
    ("Anarchist", "Fireball", "LEA"),
    ("Auramancer", "Crusade", "LEA"),
    ("Cartographer", "Forest", "LEA"),
    ("Gravedigger", "Grizzly Bears", "LEA"),
    ("Scrivener", "Lightning Bolt", "LEA"),
]


def _w1g6_returner(set_pool, name, wanted, code, *, yard=None):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    found = set_pool(code)[wanted]
    # A card of a type none of the five returns sits in slot 0.
    game = _w1g6_game(
        hand=[ody[name]], yard=[lea["Sol Ring"], found, found] if yard is None else yard,
        their_yard=[found],
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    return game, found  # _w1g6_returner


@_w1g6_pytest.mark.parametrize("name, wanted, code", _W1G6_RETURNERS)
def test_w1g6_an_entering_returner_takes_back_the_card_it_named(
    set_pool, name, wanted, code
):
    game, _found = _w1g6_returner(set_pool, name, wanted, code)
    spec = game.cast_target_spec(0, set_pool("ODY")[name])
    # Only its own type, and only your own graveyard.
    assert [(t["seat"], t["index"]) for t in spec["valid_targets"]] == [(0, 1), (0, 2)]

    cast = game.queue_from_hand(
        0, name, target_player_index=0, target_permanent_index=2
    )
    assert cast.supported, cast.details
    game.resolve_top_of_stack()
    # The entry trigger is its own stack object (CR 603.3).
    assert _w1g6_names(game, 0) == [name] and len(game.stack) == 1
    _w1g6_answer(game, accept=True)

    # Exactly one of the two copies came back.
    assert _w1g6_pile(game.players[0], "hand") == [wanted]
    assert _w1g6_pile(game.players[0]) == ["Sol Ring", wanted]
    assert _w1g6_pile(game.players[1]) == [wanted]


@_w1g6_pytest.mark.parametrize("name, wanted, code", _W1G6_RETURNERS)
def test_w1g6_an_entering_returner_may_decline_and_cannot_reach_other_piles(
    set_pool, name, wanted, code
):
    game, _found = _w1g6_returner(set_pool, name, wanted, code)
    assert game.queue_from_hand(
        0, name, target_player_index=0, target_permanent_index=1
    ).supported
    game.resolve_top_of_stack()
    _w1g6_answer(game, accept=False)
    assert not game.players[0].hand and len(game.players[0].graveyard) == 3

    # With no card of its type in your own graveyard there is no target: the
    # trigger leaves the stack and the opponent's copy stays where it is.
    lea = set_pool("LEA")
    game, found = _w1g6_returner(set_pool, name, wanted, code, yard=[lea["Sol Ring"]])
    assert game.queue_from_hand(0, name).supported
    _w1g6_answer(game, accept=True)
    assert _w1g6_names(game, 0) == [name]
    assert not game.players[0].hand
    assert _w1g6_pile(game.players[1]) == [wanted]


# --- Zoologist --------------------------------------------------------------
# Driven. "{3}{G}, {T}: Reveal the top card of your library. If it's a
# creature card, put it onto the battlefield. Otherwise, put it into your
# graveyard."

@_w1g6_pytest.mark.parametrize(
    "top, onto_battlefield",
    [("Craw Wurm", True), ("Forest", False), ("Lightning Bolt", False)],
)
def test_w1g6_zoologist_puts_a_creature_into_play_and_bins_anything_else(
    set_pool, top, onto_battlefield
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(mine=[ody["Zoologist"]], library=[lea[top], lea["Island"]])
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Zoologist")

    assert used.supported, used.details
    assert len(game.players[0].library) == 1
    assert (top in _w1g6_names(game, 0)) is onto_battlefield
    assert _w1g6_pile(game.players[0]) == ([] if onto_battlefield else [top])


def test_w1g6_zoologist_with_an_empty_library_reveals_nothing(set_pool):
    game = _w1g6_game(mine=[set_pool("ODY")["Zoologist"]], library=[])
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Zoologist")

    assert used.supported, used.details
    assert _w1g6_names(game, 0) == ["Zoologist"] and not game.players[0].graveyard

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
