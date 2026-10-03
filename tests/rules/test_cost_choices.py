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


# ---------------------------------------------------------------------------
# PCY W3G5: the last costs paid by the default — untap, counters, a second
# sacrifice, a card put back on the library
# ---------------------------------------------------------------------------


@pytest.mark.cr("602.1a", "602.2b", "601.2h")
def test_w3g5_benthic_explorers_untaps_the_land_its_controller_names():
    """"{T}, Untap a tapped land an opponent controls: Add one mana of any type
    that land could produce." The picker offers the opponent's **tapped**
    lands only — not their untapped Swamp, not the payer's own — and the land
    named is the one untapped, so the mana is that land's: an Island named,
    blue mana made. The default untaps the first tapped land (the Forest)."""
    game, (_explorers,), (forest, island, swamp) = _table(
        ["Benthic Explorers"], ["Forest", "Island", "Swamp"],
    )
    forest.tapped = island.tapped = True

    cost = game.activation_target_spec(0, 0)
    assert cost["untap_cost"] is True and cost["opponent_only"] is True
    assert [(t["seat"], t["name"]) for t in cost["valid_targets"]] == [
        (1, "Forest"), (1, "Island"),
    ]

    result = game.activate_permanent_ability(
        0, "Benthic Explorers", cost_permanent_ids=[island.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert not island.tapped and forest.tapped and not swamp.tapped
    assert game.players[0].mana_pool["U"] == 1 and game.players[0].mana_pool["G"] == 0


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_wandering_mage_puts_the_counter_on_the_creature_named():
    """"{B}, Put a -1/-1 counter on a creature you control: Prevent the next 2
    damage that would be dealt to target player or planeswalker this turn."
    Which creature shrinks is the payer's: the Giant named takes the counter,
    the Bears and the Mage do not, and the shield lands on the player named."""
    game, (mage, bears, giant), _ = _table(
        ["Wandering Mage", "Grizzly Bears", "Hill Giant"],
    )
    spec = game.activation_target_spec(0, 0, ability_index=2)
    cost = spec["cost_spec"]
    assert cost["put_counter_cost"] is True and cost["counter"] == "-1/-1"
    assert [t["name"] for t in cost["valid_targets"]] == [
        "Wandering Mage", "Grizzly Bears", "Hill Giant",
    ]

    result = game.activate_permanent_ability(
        0, "Wandering Mage", ability_index=2, target_player_index=0,
        cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert (giant.effective_power, giant.effective_toughness) == (2, 2)
    assert bears.effective_toughness == 2 and mage.effective_toughness == 3
    assert "A gains prevention shield for 2 damage" in game.log


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_spike_rogue_offers_only_creatures_holding_the_counter():
    """"{2}, Remove a +1/+1 counter from a creature you control: Put a +1/+1
    counter on this creature." A creature with no +1/+1 counter cannot pay,
    so it is not offered (the charger would replace the answer with its
    default); the Bears named give theirs up and the Rogue gets one."""
    from engine.named_counters import counters_on
    from engine.pt import add_pt_counters

    rogue, bears, giant = (_ready(_POOL[name]) for name in (
        "Spike Rogue", "Grizzly Bears", "Hill Giant",
    ))
    add_pt_counters(rogue, "+1/+1", 2)
    add_pt_counters(bears, "+1/+1", 1)
    game = Game(players=[
        PlayerState(name="A", battlefield=[rogue, bears, giant]),
        PlayerState(name="B"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None

    cost = game.activation_target_spec(0, 0, ability_index=1)
    assert cost["remove_counter_cost"] is True and cost["counter"] == "+1/+1"
    assert [t["name"] for t in cost["valid_targets"]] == ["Spike Rogue", "Grizzly Bears"]

    result = game.activate_permanent_ability(
        0, "Spike Rogue", ability_index=1, cost_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert counters_on(bears, "+1/+1") == 0 and counters_on(rogue, "+1/+1") == 3
    assert "Grizzly Bears gave up 1 +1/+1 counter(s) (Spike Rogue's cost)" in game.log


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_viscerid_drone_sacrifices_the_creature_and_the_swamp_named():
    """"{T}, Sacrifice a creature and a Swamp: Destroy target nonartifact
    creature." Two noun phrases, two choices, one ``cost_permanent_ids`` in the
    picker list's order: the Giant and the *second* Swamp were named, and those
    are the two that go — the default would have taken the smallest creature
    and the first Swamp."""
    game, (_drone, bears, giant, s1, s2), (angel,) = _table(
        ["Viscerid Drone", "Grizzly Bears", "Hill Giant", "Swamp", "Swamp"],
        ["Serra Angel"],
    )
    cost = game.activation_target_spec(0, 0, ability_index=0)["cost_spec"]
    (swamps,) = cost["more_costs"]
    assert cost["sacrifice_cost"] and swamps["sacrifice_cost"]
    assert [t["name"] for t in swamps["valid_targets"]] == ["Swamp", "Swamp"]

    result = game.activate_permanent_ability(
        0, "Viscerid Drone", ability_index=0,
        target_player_index=1, target_permanent_index=0,
        cost_permanent_ids=[giant.permanent_id, s2.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(s1)
    assert not game.is_on_battlefield(giant) and not game.is_on_battlefield(s2)
    assert not game.is_on_battlefield(angel)


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_a_seat_naming_nothing_still_pays_the_default_for_both():
    """Every AI and headless caller names nothing and must keep getting the
    payment it always got: the smallest creature and the first Swamp."""
    game, (drone, bears, giant, s1, s2), (_angel,) = _table(
        ["Viscerid Drone", "Grizzly Bears", "Hill Giant", "Swamp", "Swamp"],
        ["Serra Angel"],
    )
    result = game.activate_permanent_ability(
        0, "Viscerid Drone", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    gone = [p for p in (drone, bears, giant, s1, s2) if not game.is_on_battlefield(p)]
    assert len(gone) == 2 and s1 in gone and giant not in gone


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_urborg_panther_sacrifices_the_feral_shadow_named():
    """"Sacrifice a creature named Feral Shadow, a creature named
    Breathstealer, and this creature: …". Two Feral Shadows on the board, the
    second named: it is the one that goes. The search the ability resolves into
    is then owed as a prompt, which is the effect working rather than the cost."""
    game, (panther, fs1, fs2, breath), _ = _table(
        ["Urborg Panther", "Feral Shadow", "Feral Shadow", "Breathstealer"],
    )
    spec = game.activation_target_spec(0, 0, ability_index=1)
    assert [t["name"] for t in spec["valid_targets"]] == ["Feral Shadow", "Feral Shadow"]
    assert [t["name"] for t in spec["more_costs"][0]["valid_targets"]] == ["Breathstealer"]

    result = game.activate_permanent_ability(
        0, "Urborg Panther", ability_index=1,
        cost_permanent_ids=[fs2.permanent_id, breath.permanent_id],
    )
    assert result.supported, result.details
    assert game.is_on_battlefield(fs1)
    assert not any(game.is_on_battlefield(p) for p in (fs2, breath, panther))


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_hidden_retreat_puts_back_the_card_its_controller_names():
    """"Put a card from your hand on top of your library: Prevent all damage
    that would be dealt by target instant or sorcery spell this turn." The
    Island named goes on top (the default would have put back the Forest), and
    the Bolt aimed at its controller deals nothing."""
    game, (_retreat,), _ = _table(["Hidden Retreat"], hand=["Forest", "Island"])
    game.players[1].hand = [_POOL["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.start_priority_window(0)

    cost = game.activation_target_spec(0, 0)["cost_spec"]
    assert cost["library_top_cost"] is True
    assert [t["name"] for t in cost["valid_targets"]] == ["Forest", "Island"]

    result = game.activate_permanent_ability(
        0, "Hidden Retreat", target_stack_index=0, cost_hand_index=1,
    )
    assert result.supported, result.details
    resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == ["Forest"]
    assert game.players[0].library[0].name == "Island"
    assert game.players[0].life == 20


@pytest.mark.cr("601.2c", "601.2h")
def test_w3g5_peace_talks_leaves_an_exile_cost_its_picker():
    """The Atog test one cost over. City of Shadows' "Exile a creature you
    control" chooses a payment, not a target, so Peace Talks says nothing about
    it — but the enumerator's ban check listed three cost flags and not this
    one, so the picker offered nothing for as long as the ban was up while the
    engine went on accepting the activation."""
    game, (city, bears), _ = _table(["City of Shadows", "Grizzly Bears"], hand=["Peace Talks"])
    assert game.cast_from_hand(0, "Peace Talks").supported
    assert game.targeting_bans

    offered = game.activation_target_spec(0, 0, ability_index=0)["valid_targets"]
    assert [t["name"] for t in offered] == ["Grizzly Bears"]
    result = game.activate_permanent_ability(
        0, "City of Shadows", ability_index=0, cost_permanent_index=1,
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]


@pytest.mark.cr("602.2b", "601.2h")
def test_w3g5_cadaverous_bloom_exiles_the_card_its_controller_names():
    """"Exile a card from your hand: Add {B}{B} or {G}{G}." The picker is a
    hand-card list (it was a list of the payer's *permanents*), the answer
    rides ``cost_hand_index`` like every other hand-card cost, and the card
    named is the one exiled — the default takes the first."""
    game, (_bloom,), _ = _table(["Cadaverous Bloom"], hand=["Forest", "Island"])
    cost = game.activation_target_spec(0, 0)
    assert cost["kind"] == "hand_card" and cost["exile_cost"] is True
    assert [t["name"] for t in cost["valid_targets"]] == ["Forest", "Island"]

    result = game.activate_permanent_ability(
        0, "Cadaverous Bloom", cost_hand_index=1, mana_color="B",
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].exile] == ["Island"]
    assert [c.name for c in game.players[0].hand] == ["Forest"]


@pytest.mark.cr("601.2h", "702.18a")
def test_w3g5_a_shrouded_creature_is_offered_to_an_exile_cost():
    """Shroud stops a permanent being *targeted* (CR 702.18a), and exiling one
    to pay City of Shadows' cost targets nothing. The engine has always taken
    Autumn Willow as the payment; the picker offered nothing, because its
    "a cost is not a target" test listed the sacrifice, tap and return flags
    and not the exile — so a player whose only creature had shroud was told
    there was nothing to exile while the engine would have exiled it."""
    game, (_city, willow), _ = _table(["City of Shadows", "Autumn Willow"])
    offered = game.activation_target_spec(0, 0, ability_index=0)["valid_targets"]
    assert [t["name"] for t in offered] == ["Autumn Willow"]
