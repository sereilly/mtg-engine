"""The player pays the cost, and every choice inside it is the player's.

CR 601.2h (reached for an ability through CR 602.2b) and CR 508.1h / 509.1d
for a declaration: *which* creature taps, *which* cards are discarded, *which*
Islands are sacrificed is part of paying, and it is the payer's. The engine
has always had a deterministic answer for a seat that names nothing — that is
what keeps AI and headless play unblocked — and these tests are about the
other half: a seat that **does** name its payment gets exactly what it named,
and a named payment that cannot pay is refused with nothing spent rather than
quietly replaced by the default.

Every card here is shipped; the Prophecy cards that print the same costs are
tested in ``tests/sets/test_pcy_creatures.py``'s W2G4 block.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _ready(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _table(mine, theirs=(), *, hand=()):
    """Seat 0 holds *mine* and *hand*, seat 1 *theirs*; mana not enforced."""
    me = [_ready(_POOL[name]) for name in mine]
    them = [_ready(_POOL[name]) for name in theirs]
    game = Game(players=[
        PlayerState(name="A", battlefield=list(me), hand=[_POOL[n] for n in hand]),
        PlayerState(name="B", battlefield=list(them)),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, me, them


# ---------------------------------------------------------------------------
# A tap cost: "Tap an untapped creature you control"
# ---------------------------------------------------------------------------


@pytest.mark.cr("602.2b", "601.2h")
def test_opposition_taps_the_creature_its_controller_names():
    """"Tap an untapped creature you control: Tap target artifact, creature, or
    land." The default taps the first creature on the board (the Bears); the
    payer named the Giant, and the Giant is what taps."""
    game, (_opposition, bears, giant), (forest,) = _table(
        ["Opposition", "Grizzly Bears", "Hill Giant"], ["Forest"],
    )
    result = game.activate_permanent_ability(
        0, "Opposition", target_player_index=1, target_permanent_index=0,
        cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    assert giant.tapped and not bears.tapped
    assert forest.tapped


@pytest.mark.cr("602.2b", "601.2h")
def test_a_tap_cost_derives_a_picker_over_the_untapped_creatures_only():
    """The picker a human answers on: ``tap_cost`` beside Opposition's target,
    enumerating the payer's own **untapped** creatures — a tapped one cannot
    pay a tap cost and is not offered."""
    game, (_opposition, bears, giant), _ = _table(
        ["Opposition", "Grizzly Bears", "Hill Giant"], ["Forest"],
    )
    bears.tapped = True
    spec = game.activation_target_spec(0, 0)

    cost = spec["cost_spec"]
    assert cost["tap_cost"] is True and cost["count"] == 1
    assert [t["name"] for t in cost["valid_targets"]] == ["Hill Giant"]
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears", "Hill Giant", "Forest"]


@pytest.mark.cr("602.2b", "601.2c")
def test_a_cost_only_ability_is_not_a_targeted_one():
    """Llanowar Behemoth's whole announcement is the creature it taps, which
    is a payment and not a target (CR 601.2b vs 601.2c): the activation gate
    asks for no target, and the creature named is the one tapped."""
    game, (behemoth, bears), _ = _table(["Llanowar Behemoth", "Grizzly Bears"])
    (ability,) = compile_card_oracle(behemoth.card).activated_abilities
    assert game.activation_target_refusal(0, behemoth, ability) is None

    result = game.activate_permanent_ability(
        0, "Llanowar Behemoth", cost_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    assert bears.tapped and not behemoth.tapped
    assert behemoth.effective_power == 5


@pytest.mark.cr("601.2c", "601.2h")
def test_peace_talks_does_not_refuse_an_ability_whose_only_choice_is_its_cost():
    """"…players and permanents can't be the targets of spells or activated
    abilities." Atog's "Sacrifice an artifact" chooses a payment, not a
    target, so the ban says nothing about it. It used to be refused — "Atog
    has no legal target" — because the ban's gate read the sacrifice picker's
    noun as a target kind."""
    game, (atog, thopter), _ = _table(
        ["Atog", "Ornithopter"], hand=["Peace Talks"],
    )
    assert game.cast_from_hand(0, "Peace Talks").supported
    assert game.targeting_bans

    result = game.activate_permanent_ability(
        0, "Atog", cost_permanent_ids=[thopter.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(thopter)
    assert atog.effective_power == 3


@pytest.mark.cr("602.2b", "601.2h")
def test_quirion_ranger_returns_the_forest_its_controller_names():
    """"Return a Forest you control to its owner's hand: Untap target
    creature." Which Forest is the payer's — the tapped one, so the mana it
    made is not lost — and the picker offers both; the default would have
    returned the first."""
    game, (ranger, untapped, tapped, bears), _ = _table(
        ["Quirion Ranger", "Forest", "Forest", "Grizzly Bears"],
    )
    tapped.tapped = True
    bears.tapped = True
    spec = game.activation_target_spec(0, 0)
    cost = spec["cost_spec"]
    assert cost["return_cost"] is True and cost["count"] == 1
    assert [t["index"] for t in cost["valid_targets"]] == [1, 2]

    result = game.activate_permanent_ability(
        0, "Quirion Ranger", target_player_index=0, target_permanent_index=3,
        cost_permanent_ids=[tapped.permanent_id],
    )
    assert result.supported, result.details
    assert game.is_on_battlefield(untapped) and not game.is_on_battlefield(tapped)
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert not bears.tapped


# ---------------------------------------------------------------------------
# A counted discard: "Buyback—Discard two cards"
# ---------------------------------------------------------------------------


def _forbid_table(hand):
    caster = PlayerState(name="A", hand=[_POOL[name] for name in hand])
    opponent = PlayerState(name="B", hand=[_POOL["Lightning Bolt"]])
    game = Game(players=[caster, opponent])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    return game, caster


@pytest.mark.cr("601.2b", "601.2h")
def test_forbid_discards_the_two_cards_its_caster_named():
    """Both cards of a two-card buyback are the caster's: the first on
    ``cost_hand_index``, the second on ``cost_other_hand_indices``. The
    default would bin the first two cards in hand (the Bears and the Giant);
    the caster named the Forest and the Island."""
    game, caster = _forbid_table(
        ["Forbid", "Grizzly Bears", "Hill Giant", "Forest", "Island"]
    )
    result = game.queue_from_hand(
        0, "Forbid", target_stack_index=0,
        optional_cost_payments={"discard two cards": 1},
        cost_hand_index=3, cost_other_hand_indices=[4],
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert sorted(c.name for c in caster.graveyard) == ["Forest", "Island"]
    assert sorted(c.name for c in caster.hand) == ["Forbid", "Grizzly Bears", "Hill Giant"]


@pytest.mark.cr("601.2h")
def test_forbid_refuses_a_card_named_twice_and_spends_nothing():
    """One card named twice is one card, and a two-card cost paid with it is
    paid with half — refused before anything leaves the hand."""
    game, caster = _forbid_table(["Forbid", "Grizzly Bears", "Hill Giant"])
    result = game.queue_from_hand(
        0, "Forbid", target_stack_index=0,
        optional_cost_payments={"discard two cards": 1},
        cost_hand_index=1, cost_other_hand_indices=[1],
    )
    assert not result.supported
    assert "each named once" in result.details
    assert len(caster.hand) == 3 and not caster.graveyard


# ---------------------------------------------------------------------------
# A declaration's cost: "can't attack unless you sacrifice two Islands"
# ---------------------------------------------------------------------------


def _leviathan_table():
    game, mine, _ = _table(["Leviathan", "Island", "Island", "Island", "Island", "Forest"])
    leviathan = mine[0]
    leviathan.tapped = False
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    return game, mine


@pytest.mark.cr("508.1h", "508.1j")
def test_leviathan_sacrifices_the_islands_its_controller_names():
    """CR 508.1h: the active player determines the total cost to attack, and
    which two Islands go is part of it. The default takes the first two; the
    player named the last two (the ones still untapped, say), and those are
    the two sacrificed."""
    game, (leviathan, i1, i2, i3, i4, forest) = _leviathan_table()
    i1.tapped = i2.tapped = True
    ok, why = game.declare_attackers(
        0, [0], cost_permanent_ids=[i3.permanent_id, i4.permanent_id],
    )
    assert ok, why

    assert game.is_on_battlefield(i1) and game.is_on_battlefield(i2)
    assert not game.is_on_battlefield(i3) and not game.is_on_battlefield(i4)
    assert leviathan.attacking


@pytest.mark.cr("508.1h", "508.1j")
def test_a_named_permanent_that_cannot_pay_refuses_the_declaration():
    """A Forest is not an Island. Naming it is a choice the engine would have
    had to override, so the declaration is refused and nothing is sacrificed
    — partial and substituted payments alike are not allowed (CR 508.1j)."""
    game, (leviathan, *islands, forest) = _leviathan_table()
    ok, why = game.declare_attackers(
        0, [0], cost_permanent_ids=[forest.permanent_id, islands[0].permanent_id],
    )
    assert not ok and "Forest cannot pay" in why
    assert all(game.is_on_battlefield(land) for land in (*islands, forest))
    assert not leviathan.attacking


@pytest.mark.cr("508.1h")
def test_a_declaration_naming_nothing_pays_the_default_as_it_always_did():
    """Every AI and headless caller names nothing, and must keep getting the
    plan it always got: the first two Islands by the sacrifice preference."""
    game, (leviathan, i1, i2, i3, i4, _forest) = _leviathan_table()
    ok, why = game.declare_attackers(0, [0])
    assert ok, why
    assert not game.is_on_battlefield(i1) and not game.is_on_battlefield(i2)
    assert game.is_on_battlefield(i3) and game.is_on_battlefield(i4)


@pytest.mark.cr("508.1h")
def test_the_declaration_cost_reader_names_the_choice_for_the_client():
    """What the client is told before it sends the declaration: Leviathan owes
    a sacrifice of two, payable by any of the four Islands."""
    game, (leviathan, *islands, _forest) = _leviathan_table()
    (choice,) = game.declaration_cost_choices(leviathan, "attack")
    assert choice["verb"] == "sacrifice" and choice["count"] == 2
    assert choice["candidate_ids"] == [land.permanent_id for land in islands]
