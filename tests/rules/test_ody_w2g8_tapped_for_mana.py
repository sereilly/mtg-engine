"""A land is tapped for mana by three roads, and it is one event (CR 106.12).

"To 'tap [a permanent] for mana' is to activate a mana ability of that
permanent that includes the {T} symbol in its activation cost." CR 605.3a
then says when a player may do that: with priority, while paying for a spell
or ability, "or whenever a rule or effect asks for a mana payment, even if
it's in the middle of casting or resolving a spell".

So a land is tapped for mana by

* the player's own tap (``Game.tap_land_for_mana``);
* **a cost an effect collects** — a counterspell's "unless its controller
  pays {1}", an upkeep price, an attack toll. The payer has no priority
  window, so the engine plans the payment and activates the mana abilities
  for them (``Game._pay_planned_cost``);
* **a land whose mana ability costs more than the tap** — a filter land, a
  sacrifice land — which the activation path resolves inline (CR 605.3b).

Until Odyssey's wave 2 only the first of those was the event. The second
tapped the lands with ``become_tapped``: no mana ability ran at all, so a
painland dealt no damage, an Ancient Tomb neither hurt nor made its second
mana, and nothing watching for a land tapped for mana heard anything —
Price of Glory, whose whole use is an opponent paying on your turn, never
destroyed a land that paid a toll. The third produced its mana and announced
nothing. ``tests/regressions/test_ody_w2g8_tapped_for_mana_census.py`` is the
census; these are the rules it stands on.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.mana_payment import plan_payment, untapped_mana_lands
from engine.models import Permanent
from tests.helpers import resolve_stack

_SETS = ("ODY", "LEA", "ICE", "TMP", "USG", "ULG", "FEM", "ALL", "VIS", "7ED", "INV")


def _card(set_pool, name):
    for code in _SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, *, active=0, hands=((), ()), interactive=()):
    forest = _card(set_pool, "Forest")
    game = Game(players=[
        PlayerState(
            f"P{seat + 1}", library=[forest] * 20,
            hand=[_card(set_pool, name) for name in hands[seat]],
        )
        for seat in (0, 1)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.turn += 1
    game.start_turn(active)
    for player in game.players:
        player.mana_pool = {symbol: 0 for symbol in player.mana_pool}
        player.tapped_land_for_mana_this_turn = False
    return game


def _put(game, set_pool, seat, name):
    permanent = Permanent(card=_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    permanent.metadata["summoning_sickness_turn"] = -99
    if permanent.tapped:
        game.become_untapped(permanent)
    return permanent


def _floating(player) -> int:
    units = sum(int(amount) for amount in player.mana_pool.values())
    for bucket in player.restricted_mana.values():
        units += sum(int(amount) for amount in bucket.values())
    return units


def _spike(game, set_pool):
    """Seat 1 casts a Lightning Bolt at seat 0 and seat 0 answers with a Force
    Spike: seat 1 owes {1} with no priority window to tap for it."""
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Force Spike", target_stack_index=0).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


# --- a cost an effect collects ------------------------------------------------

@pytest.mark.cr("106.12", "605.3a", "603.4")
def test_price_of_glory_destroys_a_land_tapped_to_pay_a_toll_on_another_turn(set_pool):
    """"Whenever a player taps a land for mana, if it's not that player's
    turn, destroy that land." The opponent pays the Force Spike out of their
    one Island, on the other player's turn."""
    game = _table(
        set_pool, active=0, hands=(("Force Spike",), ("Lightning Bolt",)),
    )
    _put(game, set_pool, 0, "Price of Glory")
    island = _put(game, set_pool, 1, "Island")

    _spike(game, set_pool)

    assert not game.is_on_battlefield(island)
    assert "Island" in [card.name for card in game.players[1].graveyard]
    assert game.players[0].life == 17          # the Bolt was paid for


@pytest.mark.cr("106.12", "603.4")
def test_price_of_glory_spares_a_land_tapped_on_its_controllers_own_turn(set_pool):
    game = _table(
        set_pool, active=1, hands=(("Force Spike",), ("Lightning Bolt",)),
    )
    _put(game, set_pool, 0, "Price of Glory")
    island = _put(game, set_pool, 1, "Island")

    _spike(game, set_pool)

    assert game.is_on_battlefield(island) and island.tapped
    assert game.players[0].life == 17


@pytest.mark.cr("106.12", "106.12a", "605.3a")
def test_manabarbs_hears_a_land_tapped_to_pay_a_counterspells_price(set_pool):
    game = _table(
        set_pool, active=0, hands=(("Force Spike",), ("Lightning Bolt",)),
    )
    _put(game, set_pool, 0, "Manabarbs")
    _put(game, set_pool, 1, "Island")

    _spike(game, set_pool)

    assert [player.life for player in game.players] == [17, 19]
    assert game.players[1].tapped_land_for_mana_this_turn


@pytest.mark.cr("106.12a", "605.1b", "605.4a")
def test_mana_flares_extra_mana_pays_the_cost_it_was_made_under(set_pool):
    """One land under Mana Flare makes two, so a price of {2} taps one land
    and the other stays untapped — the adder is a triggered mana ability and
    resolves at once (CR 605.4a), inside the payment."""
    game = _table(
        set_pool, active=0, hands=(("Miscalculation",), ("Lightning Bolt",)),
    )
    _put(game, set_pool, 0, "Mana Flare")
    islands = [_put(game, set_pool, 1, "Island") for _ in range(2)]

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(0, "Miscalculation", target_stack_index=0).supported
    resolve_stack(game)

    assert sorted(island.tapped for island in islands) == [False, True]
    assert _floating(game.players[1]) == 0
    assert game.players[0].life == 17


@pytest.mark.cr("605.3a", "405.6c")
def test_a_planned_tap_runs_the_lands_whole_mana_ability(set_pool):
    """Ancient Tomb: "{T}: Add {C}{C}. This land deals 2 damage to you." A
    price of {2} is one tap of it — both mana, and the damage — and the Island
    beside it is left alone."""
    game = _table(set_pool, active=0)
    tomb = _put(game, set_pool, 1, "Ancient Tomb")
    island = _put(game, set_pool, 1, "Island")
    player = game.players[1]

    assert game._pay_planned_cost(
        player, lambda: game._optional_pay_plan(player, {"cost": {"generic": 2}}),
    )

    assert tomb.tapped and not island.tapped
    assert player.life == 18
    assert _floating(player) == 0


@pytest.mark.cr("605.3a", "106.12")
def test_a_painland_pays_a_coloured_pip_with_the_ability_that_makes_it(set_pool):
    """Adarkar Wastes' first ability is "{T}: Add {C}". A {U} is its second,
    and that one hurts; a generic pip takes the first, which does not."""
    for cost, life in (({"U": 1}, 19), ({"generic": 1}, 20)):
        game = _table(set_pool, active=0)
        wastes = _put(game, set_pool, 0, "Adarkar Wastes")
        player = game.players[0]

        assert game._pay_planned_cost(
            player, lambda: game._optional_pay_plan(player, {"cost": dict(cost)}),
        )

        assert wastes.tapped
        assert player.life == life
        assert _floating(player) == 0


@pytest.mark.cr("106.12b", "605.3a")
def test_a_painland_under_a_swap_pays_with_the_ability_that_does_not_hurt(set_pool):
    """Infernal Darkness makes every land's mana {B}, whichever ability made
    it — so Adarkar Wastes' free "{T}: Add {C}" is a {B}, and a plan that asks
    it for {B} must not go looking for the ability that *prints* one."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Infernal Darkness")
    wastes = _put(game, set_pool, 0, "Adarkar Wastes")
    player = game.players[0]

    assert game._pay_planned_cost(
        player, lambda: game._optional_pay_plan(player, {"cost": {"B": 1}}),
    )

    assert wastes.tapped
    assert player.life == 20
    assert _floating(player) == 0


@pytest.mark.cr("106.12a", "118.3")
def test_a_land_that_makes_no_mana_pays_for_nothing(set_pool):
    """Tolarian Academy beside no artifact makes none. It used to be tapped
    and the {1} deemed paid."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 0, "Tolarian Academy")
    player = game.players[0]

    paid = game._pay_planned_cost(
        player, lambda: game._optional_pay_plan(player, {"cost": {"generic": 1}}),
    )

    assert not paid


@pytest.mark.cr("106.12", "605.3a")
@pytest.mark.parametrize("site", [
    "optional", "upkeep", "attack toll", "block toll", "any amount",
])
def test_every_payer_of_an_effects_cost_taps_its_lands_for_mana(set_pool, site):
    """Six payers share one writer; each is driven with a {1} price and one
    Island under Manabarbs."""
    game = _table(set_pool, active=0, interactive=(0,))
    _put(game, set_pool, 1, "Manabarbs")
    island = _put(game, set_pool, 0, "Island")
    player = game.players[0]
    cost = {"generic": 1}

    def plan():
        return plan_payment(
            player.mana_pool, untapped_mana_lands(game.controlled_by(0)), cost,
            payer=player,
        )

    if site == "optional":
        game._pay_optional(0, {"cost": cost, "card_name": "a price"})
    elif site == "upkeep":
        game._spend_upkeep_mana(player, cost)
    elif site == "attack toll":
        game._pay_declaration_mana(0, cost, plan())
    elif site == "block toll":
        game._pay_block_declaration_mana(0, cost, plan())
    else:
        game.arm_pending_choice("pay_any_amount", 0, card_name="a price")
        assert game.resolve_pending_choice("pay_any_amount", 0, amount=1)

    assert island.tapped
    assert player.life == 19
    assert _floating(player) == 0


# --- a land whose mana ability costs more than the tap --------------------------

@pytest.mark.cr("106.12", "605.3b")
@pytest.mark.parametrize("watcher, life, extra", [
    ("Manabarbs", 19, 0), ("Mana Flare", 20, 1),
])
def test_a_filter_land_is_tapped_for_mana(set_pool, watcher, life, extra):
    """Darkwater Catacombs: "{1}, {T}: Add {U}{B}." {T} is in the cost, so the
    activation is the land being tapped for mana."""
    game = _table(set_pool, active=0)
    game.enforce_mana_costs = True
    _put(game, set_pool, 1, watcher)
    catacombs = _put(game, set_pool, 0, "Darkwater Catacombs")
    player = game.players[0]
    player.mana_pool["C"] = 1

    result = game.activate_permanent_ability(
        0, "Darkwater Catacombs",
        permanent_index=game.battlefield_index_of(catacombs), ability_index=0,
    )

    assert result.supported
    assert player.life == life
    assert _floating(player) == 2 + extra
    assert player.tapped_land_for_mana_this_turn


@pytest.mark.cr("106.12b")
def test_a_land_sacrificed_for_its_mana_still_meets_the_production_replacement(set_pool):
    """Ebon Stronghold: "{T}, Sacrifice this land: Add {B}{B}." Under
    Contamination the production is one {B} — the replacement is over the
    production event, which the land's ability is still performing after the
    land itself is gone."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Contamination")
    stronghold = _put(game, set_pool, 0, "Ebon Stronghold")
    index = next(
        position for position, ability in enumerate(game.usable_abilities_of(stronghold))
        if ability.cost.sacrifice_self
    )

    result = game.activate_permanent_ability(
        0, "Ebon Stronghold",
        permanent_index=game.battlefield_index_of(stronghold), ability_index=index,
    )

    assert result.supported
    assert game.players[0].mana_pool["B"] == 1
    assert _floating(game.players[0]) == 1


@pytest.mark.cr("106.12", "605.3b")
def test_storm_cauldron_cannot_return_a_land_sacrificed_as_it_was_tapped(set_pool):
    """Storm Cauldron's ruling of 2004-10-04: "If a land is tapped for mana
    and sacrificed all in one action, it goes to the graveyard before the
    Cauldron can return it to the player's hand." """
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Storm Cauldron")
    stronghold = _put(game, set_pool, 0, "Ebon Stronghold")
    index = next(
        position for position, ability in enumerate(game.usable_abilities_of(stronghold))
        if ability.cost.sacrifice_self
    )

    assert game.activate_permanent_ability(
        0, "Ebon Stronghold",
        permanent_index=game.battlefield_index_of(stronghold), ability_index=index,
    ).supported

    assert [card.name for card in game.players[0].graveyard] == ["Ebon Stronghold"]
    assert "Ebon Stronghold" not in [card.name for card in game.players[0].hand]


# --- and what is not a land tapped for mana --------------------------------------

@pytest.mark.cr("106.12")
def test_a_land_tapped_by_an_effect_is_not_tapped_for_mana(set_pool):
    """Icy Manipulator taps a land. No mana ability was activated."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 0, "Manabarbs")
    icy = _put(game, set_pool, 0, "Icy Manipulator")
    island = _put(game, set_pool, 1, "Island")

    assert game.activate_permanent_ability(
        0, "Icy Manipulator", permanent_index=game.battlefield_index_of(icy),
        target_permanent_ids=[island.permanent_id],
    ).supported
    resolve_stack(game)

    assert island.tapped
    assert [player.life for player in game.players] == [20, 20]
    assert not game.players[1].tapped_land_for_mana_this_turn


@pytest.mark.cr("106.12")
def test_a_creatures_mana_ability_is_not_a_land_tapped_for_mana(set_pool):
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Manabarbs")
    elves = _put(game, set_pool, 0, "Llanowar Elves")

    assert game.activate_permanent_ability(
        0, "Llanowar Elves", permanent_index=game.battlefield_index_of(elves),
    ).supported

    assert game.players[0].mana_pool["G"] == 1
    assert game.players[0].life == 20
    assert not game.players[0].tapped_land_for_mana_this_turn


@pytest.mark.cr("106.12a")
def test_a_tap_that_makes_no_mana_is_not_announced(set_pool):
    """CR 106.12a: the ability "triggers whenever such a mana ability resolves
    **and produces mana**"."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Manabarbs")
    academy = _put(game, set_pool, 0, "Tolarian Academy")

    assert game.tap_land_for_mana(
        0, "Tolarian Academy", "U", permanent_id=academy.permanent_id,
    )

    assert academy.tapped
    assert game.players[0].life == 20


# --- the adders name what the land made -------------------------------------------

@pytest.mark.cr("106.12a", "605.1b")
def test_mana_flare_adds_a_type_the_land_produced_not_the_one_it_was_asked_for(set_pool):
    """"…that player adds one mana of any type **that land produced**." An
    Ancient Tomb asked for the route's default {G} made {C}{C}; the extra
    mana was the {G}."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 0, "Mana Flare")
    tomb = _put(game, set_pool, 0, "Ancient Tomb")

    assert game.tap_land_for_mana(0, "Ancient Tomb", "G", permanent_id=tomb.permanent_id)

    assert game.players[0].mana_pool["C"] == 3
    assert game.players[0].mana_pool["G"] == 0


@pytest.mark.cr("105.1", "106.12b")
@pytest.mark.parametrize("road", ["tap", "activate"])
def test_a_land_that_offers_a_colour_can_be_asked_for_colourless(set_pool, road):
    """Under Ritual of Subdual every land pays {C}, so {C} is what the AI's
    plan and the client's colour fan ask a land for. Asked of a land whose
    ability reads "{G} or {W}" it raised ``ValueError`` out of the seam."""
    game = _table(set_pool, active=0)
    _put(game, set_pool, 1, "Ritual of Subdual")
    palace = _put(game, set_pool, 0, "Elfhame Palace")       # "{T}: Add {G} or {W}."

    if road == "tap":
        assert game.tap_land_for_mana(0, "Elfhame Palace", "C", permanent_id=palace.permanent_id)
    else:
        assert game.activate_permanent_ability(
            0, "Elfhame Palace", permanent_index=game.battlefield_index_of(palace),
            ability_index=0, mana_color="C",
        ).supported

    assert game.players[0].mana_pool["C"] == 1
    assert _floating(game.players[0]) == 1


@pytest.mark.cr("106.12a")
def test_wild_growth_adds_its_mana_to_a_planned_tap(set_pool):
    game = _table(set_pool, active=0)
    forest = _put(game, set_pool, 0, "Forest")
    growth = Permanent(card=_card(set_pool, "Wild Growth"))
    game._put_permanent_onto_battlefield(0, growth, None)
    attach_aura(growth, forest)
    spare = _put(game, set_pool, 0, "Forest")
    player = game.players[0]

    assert game._pay_planned_cost(
        player, lambda: game._optional_pay_plan(player, {"cost": {"generic": 2}}),
    )

    assert forest.tapped and not spare.tapped
    assert _floating(player) == 0
