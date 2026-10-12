"""Odyssey creatures, continued: whole group sections moved out of `test_ody_creatures.py`.

`test_ody_creatures.py` reached the per-set size cap at wave 1's integration, on no
group's branch - nine groups each wrote a test per driven card, which is what
the briefs asked for. The sections below were moved **whole**, byte for byte,
under the marker pairs they had; a section carries its own imports and its
own `_w<wave>g<n>_` prefix, so nothing here depends on its old neighbours.
Their empty marker pairs stay behind in `test_ody_creatures.py` so a branch still in
flight merges against unchanged context.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` (`tests/sets/README.md`).
"""


# ==== W1G6 ==========================================================

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

import random as _w1g7_random

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.hand_size import maximum_hand_size as _w1g7_maximum_hand_size
from engine.handlers._common import permanent_effective_colors as _w1g7_colors
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (ODY over LEA).
    A seat in *interactive* is asked its decisions instead of defaulting."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g7_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g7_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g7_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def _w1g7_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Thought Nibbler / Eater / Devourer: a maximum hand size that is changed --

@_w1g7_pytest.mark.parametrize(
    "name, limit",
    [("Thought Nibbler", 5), ("Thought Eater", 4), ("Thought Devourer", 3)],
)
def test_a_thought_beast_lowers_its_controllers_maximum_hand_size(
    set_pool, name, limit
):
    """"Your maximum hand size is reduced by two / three / four." Its
    controller alone, for as long as it is on the battlefield (CR 611.3a), and
    enforced where CR 514.1 enforces it: the cleanup step."""
    game = _w1g7_duel(
        set_pool, bf0=[name],
        hand0=["Grizzly Bears"] * 7, hand1=["Grizzly Bears"] * 7,
    )
    assert _w1g7_maximum_hand_size(game, 0) == limit
    assert _w1g7_maximum_hand_size(game, 1) == 7

    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == limit
    assert len(game.players[0].graveyard) == 7 - limit

    game.resolve_cleanup_step(1)
    assert len(game.players[1].hand) == 7, "the opponent keeps seven"

    game.remove_from_battlefield(_w1g7_on_board(game, 0, name))
    assert _w1g7_maximum_hand_size(game, 0) == 7


def test_the_thought_beasts_stack_and_stop_at_no_cards(set_pool):
    """Two static abilities, both applied (CR 613.11): seven less two less
    three is two; all three beasts are seven less nine, and a hand cannot be
    smaller than empty (CR 107.1b)."""
    two = _w1g7_duel(
        set_pool, bf0=["Thought Nibbler", "Thought Eater"],
        hand0=["Grizzly Bears"] * 6,
    )
    assert _w1g7_maximum_hand_size(two, 0) == 2
    two.resolve_cleanup_step(0)
    assert len(two.players[0].hand) == 2

    three = _w1g7_duel(
        set_pool,
        bf0=["Thought Nibbler", "Thought Eater", "Thought Devourer"],
        hand0=["Grizzly Bears"] * 3,
    )
    assert _w1g7_maximum_hand_size(three, 0) == 0
    three.resolve_cleanup_step(0)
    assert three.players[0].hand == []


def test_a_thought_beast_and_a_cursed_rack_apply_in_the_order_they_entered(set_pool):
    """The beasts' own ruling (Scryfall, 2009-10-01): "if you are affected by
    Cursed Rack … and then put Thought Eater onto the battlefield, your maximum
    hand size would be one. However, if those permanents entered in the
    opposite order, your maximum hand size would be four." """
    pool = {**set_pool("ATQ"), **set_pool("ODY")}

    def board(*order):
        game = _w1g7_duel(set_pool)
        for name in order:
            perm = _w1g7_Permanent(card=pool[name])
            seat = 1 if name == "Cursed Rack" else 0
            game._put_permanent_onto_battlefield(seat, perm, None)
            if name == "Cursed Rack":
                perm.metadata["chosen_player_index"] = 0
        return game

    assert _w1g7_maximum_hand_size(board("Cursed Rack", "Thought Eater"), 0) == 1
    assert _w1g7_maximum_hand_size(board("Thought Eater", "Cursed Rack"), 0) == 4


def test_a_thought_beast_under_another_controller_lowers_that_players_maximum(
    set_pool,
):
    """"Your" is whoever controls it now (CR 613 layer 2 through the control
    seam), not who it entered under."""
    from engine.control import change_control

    game = _w1g7_duel(set_pool, bf0=["Thought Devourer"])
    beast = _w1g7_on_board(game, 0, "Thought Devourer")
    change_control(beast, 1, source="test")
    game._sync_control()
    assert _w1g7_maximum_hand_size(game, 0) == 7
    assert _w1g7_maximum_hand_size(game, 1) == 3


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


# --- Confessor: "whenever a player discards a card" ---------------------------

def test_confessor_watches_every_players_discards_its_controllers_included(
    set_pool,
):
    """"Whenever **a player** discards a card, you may gain 1 life." The third
    printed seat of the discard trigger, and the widest: an opponent's discard
    to a spell and the controller's own discard to a cost both fire it, once
    per card (CR 701.9a)."""
    pool = {**set_pool("LEA"), **set_pool("ODY"), **set_pool("7ED")}
    game = _w1g7_duel(
        set_pool, bf0=["Confessor", "Wild Mongrel"], hand0=["Forest", "Forest"],
        hand1=["Grizzly Bears", "Grizzly Bears", "Forest"],
    )
    game.players[0].hand.append(pool["Mind Rot"])

    assert game.cast_from_hand(0, "Mind Rot", target_player_index=1).supported
    _w1g7_settle(game)
    assert len(game.players[1].graveyard) == 2
    assert game.players[0].life == 22, "one trigger per card an opponent discarded"

    assert game.activate_permanent_ability(
        0, "Wild Mongrel", cost_hand_index=0
    ).supported
    _w1g7_settle(game)
    assert game.players[0].life == 23, "its controller's own discard counts too"
    assert game.players[1].life == 20


def test_confessor_sees_a_cleanup_discard_and_each_copy_answers_for_its_owner(
    set_pool,
):
    """No spell or ability caused the cleanup discard (CR 514.1) and it is a
    discard all the same; and "you" is each Confessor's own controller."""
    game = _w1g7_duel(
        set_pool, bf0=["Confessor"], bf1=["Confessor"],
        hand1=["Grizzly Bears"] * 9,
    )
    game.resolve_cleanup_step(1)
    _w1g7_settle(game)
    assert len(game.players[1].hand) == 7
    assert (game.players[0].life, game.players[1].life) == (22, 22)


def test_confessor_asks_its_controller_and_no_is_an_answer(set_pool):
    """"You may": an interactive seat is asked once per trigger, and declining
    gains nothing."""
    game = _w1g7_duel(
        set_pool, bf0=["Confessor"], hand1=["Grizzly Bears"] * 8,
        interactive=(0,),
    )
    game.resolve_cleanup_step(1)
    _w1g7_resolve_stack(game)
    offers = game.pending_choices_of("optional_pay", 0)
    assert len(offers) == 1
    assert game.resolve_pending_choice("optional_pay", 0, accept=False)
    assert game.players[0].life == 20

    game.players[1].hand.extend([game.players[1].hand[0]])
    game.resolve_cleanup_step(1)
    _w1g7_resolve_stack(game)
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    assert game.players[0].life == 21


def test_the_discard_trigger_still_tells_its_three_seats_apart():
    """The narrowing is data on one condition kind, so all three spellings are
    asked of one fire site — and an invented card printing each must hear only
    what it names."""
    def watcher(name, who):
        card = _w1g7_mk_card(
            name, "{1}", "Enchantment",
            f"Whenever {who} a card, you gain 1 life.",
        )
        assert _w1g7_compile(card).supported, name
        return card

    yours = watcher("Own Discards", "you discard")
    theirs = watcher("Their Discards", "an opponent discards")
    anyones = watcher("Any Discards", "a player discards")
    filler = _w1g7_mk_card("Filler", "", "Sorcery", "")

    def life_after(discarder):
        seats = [_w1g7_PlayerState(name="P0", life=20), _w1g7_PlayerState(name="P1", life=20)]
        game = _w1g7_Game(players=seats)
        game.enforce_mana_costs = False
        for card in (yours, theirs, anyones):
            game._put_permanent_onto_battlefield(0, _w1g7_Permanent(card=card), None)
        seats[discarder].hand = [filler] * 8
        game.resolve_cleanup_step(discarder)
        _w1g7_settle(game)
        return seats[0].life

    assert life_after(0) == 22, "'you' and 'a player'"
    assert life_after(1) == 22, "'an opponent' and 'a player'"


def _w1g7_attack(game, seat, name, blocks=None):
    """*seat* attacks with its creature *name*; combat walks to the second
    main phase, or stops where a prompt holds it. True if it got there."""
    game.start_turn(seat)
    game._close_current_priority_step()
    slot = [p.card.name for p in game.controlled_by(seat)].index(name)
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(seat, [slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(1 - seat, dict(blocks or {}))
    assert blocked[0], blocked
    for _ in range(10):
        if game.current_step == "postcombat_main":
            return True
        game.advance_combat_phase()
        if game.pending_choices:
            return False
        _w1g7_resolve_stack(game)
    return game.current_step == "postcombat_main"


# --- Balshan Beguiler: the damaged player's top two, and its controller picks ---

_W1G7_BEGUILED = ["Forest", "Grizzly Bears", "Island", "Terror"]


def test_balshan_beguiler_bins_one_of_the_damaged_players_top_two(set_pool):
    """"Whenever this creature deals combat damage to a player, that player
    reveals the top two cards of their library. You choose one of those cards
    and put it into their graveyard." The pile is the damaged player's, the
    choice is the Beguiler's controller's, and the card not chosen stays where
    it was — the sentence moves one card."""
    game = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5,
        lib1=_W1G7_BEGUILED, interactive=(0,),
    )
    assert not _w1g7_attack(game, 0, "Balshan Beguiler"), "held: a pick is owed"
    assert game.players[1].life == 19
    (pick,) = game.pending_choices
    assert (pick.kind, pick.player_index) == ("look_top_pick", 0)
    assert (pick.data["pile_index"], pick.data["top_count"]) == (1, 2)
    assert any("P1 reveals Forest, Grizzly Bears" in line for line in game.log)

    assert game.resolve_pending_choice("look_top_pick", 0, keep_index=1)
    assert _w1g7_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert _w1g7_names(game.players[1].library) == ["Forest", "Island", "Terror"]
    assert not game.pending_choices, "one card left: nothing to order"
    assert len(game.players[0].library) == 5


def test_balshan_beguiler_does_nothing_when_blocked_and_reads_the_seat_it_hit(
    set_pool,
):
    """Blocked, it dealt no combat damage to a player. And "that player" is
    whoever was damaged: under the other seat's control it opens *this*
    seat's library and that seat's controller chooses."""
    blocked = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], bf1=["Grizzly Bears"],
        lib0=["Mountain"] * 5, lib1=_W1G7_BEGUILED, interactive=(0,),
    )
    assert _w1g7_attack(blocked, 0, "Balshan Beguiler", blocks={0: 0})
    assert blocked.players[1].graveyard == []
    assert _w1g7_names(blocked.players[1].library) == _W1G7_BEGUILED

    theirs = _w1g7_duel(
        set_pool, bf1=["Balshan Beguiler"], lib0=_W1G7_BEGUILED,
        lib1=["Mountain"] * 5, interactive=(1,),
    )
    assert not _w1g7_attack(theirs, 1, "Balshan Beguiler")
    (pick,) = theirs.pending_choices
    assert (pick.player_index, pick.data["pile_index"]) == (1, 0)
    assert theirs.resolve_pending_choice("look_top_pick", 1, keep_index=0)
    assert _w1g7_names(theirs.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(theirs.players[0].library) == ["Grizzly Bears", "Island", "Terror"]


def test_balshan_beguiler_over_a_library_of_one_or_none(set_pool):
    one = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5, lib1=["Forest"],
        interactive=(0,),
    )
    _w1g7_attack(one, 0, "Balshan Beguiler")
    assert one.resolve_pending_choice("look_top_pick", 0, keep_index=0)
    assert _w1g7_names(one.players[1].graveyard) == ["Forest"]

    none = _w1g7_duel(
        set_pool, bf0=["Balshan Beguiler"], lib0=["Mountain"] * 5, interactive=(0,),
    )
    assert _w1g7_attack(none, 0, "Balshan Beguiler")
    assert not none.pending_choices and not none.players[1].lost


def test_that_player_reveals_and_you_choose_needs_an_event_that_froze_a_seat():
    """Under a trigger that damaged nobody, "that player" names a seat no fire
    site recorded, and a pile nobody named is not opened."""
    card = _w1g7_mk_card(
        "Idle Beguiler", "{U}", "Enchantment",
        "At the beginning of your upkeep, that player reveals the top two "
        "cards of their library. You choose one of those cards and put it "
        "into their graveyard.",
    )
    assert not _w1g7_compile(card).supported


# --- The sheet's creatures that compiled before this round, driven --------------

_W1G7_CHOSEN_DISCARD_COSTS = [
    "Amugaba", "Balshan Griffin", "Face of Fear", "Fledgling Imp",
    "Krosan Archer", "Patrol Hound", "Phantatog", "Pulsating Illusion",
    "Stalking Bloodsucker", "Tireless Tribe", "Wild Mongrel",
]
_W1G7_RANDOM_DISCARD_COSTS = [
    "Dwarven Strike Force", "Frenetic Ogre", "Pardic Swordsmith",
]


def _w1g7_discard_ability(set_pool, name):
    program = _w1g7_compile(set_pool("ODY")[name])
    return next(
        index for index, ability in enumerate(program.activated_abilities)
        if "discard" in ability.source_line.lower()
    )


@_w1g7_pytest.mark.parametrize(
    "name", _W1G7_CHOSEN_DISCARD_COSTS + _W1G7_RANDOM_DISCARD_COSTS
)
def test_a_discard_cost_takes_exactly_one_of_two_identical_cards(set_pool, name):
    """"Discard a card: …" A hand holds one immutable card object per copy, so
    paying with one of two Forests has to leave the other (CR 701.9a moves a
    card, not a name). And an empty hand cannot pay: the activation is refused
    with nothing spent."""
    index = _w1g7_discard_ability(set_pool, name)
    game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Forest"])
    assert game.activate_permanent_ability(
        0, name, ability_index=index, cost_hand_index=0
    ).supported
    _w1g7_settle(game)
    hand = _w1g7_names(game.players[0].hand)
    assert hand.count("Forest") == 1, hand
    assert _w1g7_names(game.players[0].graveyard) == ["Forest"]

    empty = _w1g7_duel(set_pool, bf0=[name])
    refused = empty.activate_permanent_ability(0, name, ability_index=index)
    assert not refused.supported and "discard" in refused.details
    assert _w1g7_on_board(empty, 0, name) is not None


@_w1g7_pytest.mark.parametrize("name", _W1G7_CHOSEN_DISCARD_COSTS)
def test_a_chosen_discard_cost_discards_the_card_its_payer_named(set_pool, name):
    index = _w1g7_discard_ability(set_pool, name)
    game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Forest", "Island"])
    assert game.activate_permanent_ability(
        0, name, ability_index=index, cost_hand_index=2
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].graveyard) == ["Island"]


@_w1g7_pytest.mark.parametrize("name", _W1G7_RANDOM_DISCARD_COSTS)
def test_a_random_discard_cost_is_chances_and_replays_per_seed(set_pool, name):
    """"Discard a card **at random**:" the payer names nothing — an index sent
    with the activation does not choose — and the seeded RNG picks, so a seed
    replays and different seeds differ."""
    def gone(seed):
        _w1g7_random.seed(seed)
        game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest", "Island", "Swamp"])
        assert game.activate_permanent_ability(0, name, cost_hand_index=0).supported
        _w1g7_settle(game)
        return tuple(_w1g7_names(game.players[0].graveyard))

    assert gone(5) == gone(5)
    assert len({gone(seed) for seed in range(20)}) == 3, "every card can be the one"


def test_what_the_discard_cost_creatures_buy(set_pool):
    """One line per card: what the ability does, and that it ends at cleanup."""
    def after(name, **zones):
        game = _w1g7_duel(set_pool, bf0=[name], hand0=["Forest"], **zones)
        index = _w1g7_discard_ability(set_pool, name)
        assert game.activate_permanent_ability(0, name, ability_index=index).supported
        _w1g7_settle(game)
        return game

    def body(game, name):
        permanent = _w1g7_on_board(game, 0, name)
        return permanent.effective_power, permanent.effective_toughness

    for name, expected in (
        ("Krosan Archer", (2, 5)), ("Phantatog", (2, 3)),
        ("Pulsating Illusion", (4, 5)), ("Stalking Bloodsucker", (6, 6)),
        ("Tireless Tribe", (1, 5)), ("Frenetic Ogre", (5, 3)),
        ("Pardic Swordsmith", (3, 1)), ("Wild Mongrel", (3, 3)),
    ):
        game = after(name)
        assert body(game, name) == expected, name
        game.resolve_cleanup_step(0)
        printed = set_pool("ODY")[name].raw
        assert body(game, name) == (int(printed["power"]), int(printed["toughness"])), name

    for name, keywords in (
        ("Face of Fear", ["fear"]), ("Fledgling Imp", ["flying"]),
        ("Patrol Hound", ["first strike"]),
        ("Dwarven Strike Force", ["first strike", "haste"]),
    ):
        game = after(name)
        permanent = _w1g7_on_board(game, 0, name)
        assert all(game._has_keyword(permanent, word) for word in keywords), name
        game.resolve_cleanup_step(0)
        assert not any(game._has_keyword(permanent, word) for word in keywords), name

    for name in ("Amugaba", "Balshan Griffin"):
        game = after(name)
        assert name in _w1g7_names(game.players[0].hand), name
        assert name not in [p.card.name for p in game.controlled_by(0)]


def test_pulsating_illusion_may_be_activated_once_each_turn(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Pulsating Illusion"], hand0=["Forest", "Island"])
    assert game.activate_permanent_ability(0, "Pulsating Illusion").supported
    _w1g7_settle(game)
    second = game.activate_permanent_ability(0, "Pulsating Illusion")
    assert not second.supported and "once each turn" in second.details
    assert len(game.players[0].hand) == 1, "the refused activation discarded nothing"


def test_wild_mongrels_colour_is_chosen_as_the_ability_resolves(set_pool):
    """CR 608.2d: "the color of your choice" is asked during resolution, not
    announced with the activation; the colour is written through the layer and
    is gone with the turn."""
    game = _w1g7_duel(
        set_pool, bf0=["Wild Mongrel"], hand0=["Forest", "Island"], interactive=(0,),
    )
    mongrel = _w1g7_on_board(game, 0, "Wild Mongrel")
    assert game.activate_permanent_ability(0, "Wild Mongrel", cost_hand_index=0).supported
    (choice,) = game.pending_choices
    assert choice.kind == "color_choice"
    assert sorted(_w1g7_colors(mongrel)) == ["G"], "nothing chosen yet"
    assert not game.resolve_pending_choice("color_choice", 0, mana_color="purple")
    assert game.resolve_pending_choice("color_choice", 0, mana_color="U")
    assert sorted(_w1g7_colors(mongrel)) == ["U"]
    assert (mongrel.effective_power, mongrel.effective_toughness) == (3, 3)

    game.activate_permanent_ability(0, "Wild Mongrel", cost_hand_index=0)
    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")
    assert sorted(_w1g7_colors(mongrel)) == ["R"], "the later choice (CR 613.7)"
    game.resolve_cleanup_step(0)
    assert sorted(_w1g7_colors(mongrel)) == ["G"]


def test_phantatogs_other_ability_sacrifices_an_enchantment(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Phantatog", "Think Tank"], hand0=["Forest"])
    assert game.activate_permanent_ability(0, "Phantatog", ability_index=0).supported
    _w1g7_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Phantatog"]
    assert _w1g7_names(game.players[0].hand) == ["Forest"]

    bare = _w1g7_duel(set_pool, bf0=["Phantatog"], hand0=["Forest"])
    assert not bare.activate_permanent_ability(0, "Phantatog", ability_index=0).supported


def test_overeager_apprentice_pays_both_costs_for_three_black_mana(set_pool):
    game = _w1g7_duel(set_pool, bf0=["Overeager Apprentice"], hand0=["Forest", "Island"])
    assert game.activate_permanent_ability(
        0, "Overeager Apprentice", cost_hand_index=1
    ).supported
    _w1g7_settle(game)
    assert game.players[0].mana_pool["B"] == 3
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert list(game.controlled_by(0)) == []

    empty = _w1g7_duel(set_pool, bf0=["Overeager Apprentice"])
    assert not empty.activate_permanent_ability(0, "Overeager Apprentice").supported
    assert len(list(empty.controlled_by(0))) == 1, "not sacrificed for a cost unpaid"


def test_the_cephalids_loot_for_a_player_their_controller_targets(set_pool):
    """"{T}: **Target player** draws a card, then discards a card." The picker
    offers both seats and the targeted player chooses the discard."""
    for name, count in (("Cephalid Looter", 1), ("Cephalid Broker", 2)):
        game = _w1g7_duel(
            set_pool, bf0=[name], hand1=["Forest"],
            lib0=["Mountain"] * 3, lib1=["Island", "Swamp", "Plains"],
            interactive=(1,),
        )
        spec = game.activation_target_spec(0, 0, 0)
        assert spec["kind"] == "player" and len(spec["valid_targets"]) == 2
        assert game.activate_permanent_ability(0, name, target_player_index=1).supported
        (choice,) = game.pending_choices
        assert (choice.kind, choice.player_index, choice.data["count"]) == ("discard", 1, count)
        assert len(game.players[1].hand) == 1 + count
        assert game.confirm_discard(1, list(range(count)))
        assert len(game.players[1].hand) == 1 and len(game.players[0].library) == 3
        assert not game.activate_permanent_ability(0, name, target_player_index=1).supported, (
            "tapped"
        )


def test_mindslicer_empties_every_hand_when_it_dies_and_only_then(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Mindslicer"], hand0=["Forest", "Island"], hand1=["Swamp"],
    )
    game.sacrifice_permanent(_w1g7_on_board(game, 0, "Mindslicer"))
    assert len(game.stack) == 1, "a dies trigger is a stack object"
    _w1g7_settle(game)
    assert game.players[0].hand == [] and game.players[1].hand == []

    moved = _w1g7_duel(set_pool, bf0=["Mindslicer"], hand0=["Forest"], hand1=["Swamp"])
    moved.remove_from_battlefield(_w1g7_on_board(moved, 0, "Mindslicer"))
    _w1g7_settle(moved)
    assert len(moved.players[0].hand) == 1 and len(moved.players[1].hand) == 1


def test_minotaur_explorer_is_sacrificed_unless_a_random_card_goes(set_pool):
    def enter(hand, accept):
        game = _w1g7_duel(
            set_pool, hand0=["Minotaur Explorer", *hand], interactive=(0,),
        )
        assert game.cast_from_hand(0, "Minotaur Explorer").supported
        # The cast runs on until the entry trigger's offer holds it (or, with
        # nothing to discard, until the trigger has resolved); the offer is
        # answered by hand, since ``resolve_stack`` would give it its default.
        if game.pending_choices:
            assert len(game.stack) == 1, "the entry trigger is a stack object"
            assert game.resolve_pending_choice("optional_pay", 0, accept=accept)
        _w1g7_settle(game)
        return game

    _w1g7_random.seed(9)
    kept = enter(["Forest", "Island"], True)
    assert [p.card.name for p in kept.controlled_by(0)] == ["Minotaur Explorer"]
    assert len(kept.players[0].hand) == 1 and len(kept.players[0].graveyard) == 1

    declined = enter(["Forest"], False)
    assert list(declined.controlled_by(0)) == []
    assert _w1g7_names(declined.players[0].hand) == ["Forest"]

    unable = enter([], True)
    assert list(unable.controlled_by(0)) == [], "no card to discard is no choice"


def test_cursed_monstrosity_asks_for_a_land_card_whenever_it_is_targeted(set_pool):
    """By a spell or by an ability, and the discard is of a *land* card: a
    hand with none cannot pay, so the creature is sacrificed and the spell
    that targeted it finds nothing (CR 608.2b)."""
    def aimed(hand):
        game = _w1g7_duel(
            set_pool, hand0=["Giant Growth"], bf1=["Cursed Monstrosity"],
            hand1=hand, interactive=(1,),
        )
        monster = _w1g7_on_board(game, 1, "Cursed Monstrosity")
        assert game.queue_from_hand(
            0, "Giant Growth", target_permanent_ids=[monster.permanent_id]
        ).supported
        assert [item.card.name for item in game.stack] == [
            "Giant Growth", "Cursed Monstrosity",
        ]
        game.resolve_top_of_stack()
        return game, monster

    game, monster = aimed(["Grizzly Bears", "Forest"])
    assert game.resolve_pending_choice("optional_pay", 1, accept=True)
    assert not game.confirm_discard(1, [0]), "a creature card is not a land card"
    assert game.confirm_discard(1, [1])
    _w1g7_settle(game)
    assert (monster.effective_power, monster.effective_toughness) == (7, 6)
    assert _w1g7_names(game.players[1].graveyard) == ["Forest"]

    game, _monster = aimed(["Grizzly Bears"])
    _w1g7_settle(game)
    assert list(game.controlled_by(1)) == []
    assert "Cursed Monstrosity" in _w1g7_names(game.players[1].graveyard)

    pinged = _w1g7_duel(
        set_pool, bf0=["Prodigal Sorcerer"], bf1=["Cursed Monstrosity"],
        hand1=["Forest"], interactive=(1,),
    )
    monster = _w1g7_on_board(pinged, 1, "Cursed Monstrosity")
    assert pinged.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[monster.permanent_id]
    ).supported
    assert [item.card.name for item in pinged.stack][-1] == "Cursed Monstrosity"


def test_aven_windreader_shows_the_top_card_and_moves_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Aven Windreader"], lib1=["Terror", "Swamp"],
    )
    assert game.activate_permanent_ability(
        0, "Aven Windreader", target_player_index=1
    ).supported
    _w1g7_settle(game)
    assert any("revealed Terror" in line for line in game.log)
    assert _w1g7_names(game.players[1].library) == ["Terror", "Swamp"]


def test_sadistic_hypnotist_is_a_sorcery_speed_sacrifice_outlet(set_pool):
    game = _w1g7_duel(
        set_pool, bf0=["Sadistic Hypnotist", "Grizzly Bears"],
        hand1=["Forest", "Island", "Swamp"], interactive=(1,),
    )
    game.start_turn(0)
    game._close_current_priority_step()
    bears = _w1g7_on_board(game, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(
        0, "Sadistic Hypnotist", target_player_index=1,
        cost_permanent_ids=[bears.permanent_id],
    ).supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Sadistic Hypnotist"]
    assert game.confirm_discard(1, [0, 1])
    assert _w1g7_names(game.players[1].hand) == ["Swamp"]

    theirs = _w1g7_duel(
        set_pool, bf0=["Sadistic Hypnotist", "Grizzly Bears"], hand1=["Forest"],
    )
    theirs.start_turn(1)
    theirs._close_current_priority_step()
    refused = theirs.activate_permanent_ability(
        0, "Sadistic Hypnotist", target_player_index=1
    )
    assert not refused.supported and "sorcery" in refused.details
    assert len(list(theirs.controlled_by(0))) == 2, "nothing was sacrificed"

# ==== end W1G7 ======================================================
