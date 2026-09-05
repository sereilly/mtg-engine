"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle


def test_kyscu_drake_charges_both_halves_of_its_conjoined_sacrifice(set_pool):
    """"Sacrifice this creature **and a creature named Spitting Drake**".

    Two objects under one printed verb, joined by a bare "and" with no comma —
    the shape every reader in the charger declined. The Oxford-list regex needs
    a comma before its "and", the single-object delimiter is switched off once
    "sacrifice this ..." has set ``sacrifice_self``, and the "any number of"
    reader wants a set. So the Drake's own sacrifice was charged and the second
    creature was not: an ability activated for less than the card prints, which
    is the failure that neither crashes nor goes missing.
    """
    drake = set_pool("VIS")["Kyscu Drake"]
    program = compile_card_oracle(drake)

    tutor = [
        ability
        for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(tutor) == 1, "the tutor ability is the one that sacrifices itself"
    cost = tutor[0].cost

    # The source in its flag and the chosen permanent in the filter — the same
    # encoding the Oxford-list path already gives the same two facts.
    assert cost.sacrifice_self is True
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "named": "spitting drake",
    }


# --- G1: the return-to-hand family ---
#
# Imports at the top of this block, so a merge that appends another group's
# block below cannot lose them (SET_PLAYBOOK.md, "give every group's test block
# its own imports").
from engine import Game, PlayerState
from engine.models import Permanent


def _g1_rig():
    """A two-seat game with seat 0 interactive.

    Interactive on purpose: the prompts this family arms take their default at
    arm time for a non-interactive seat, so a headless rig answers its own
    questions and a test written against it proves only that the default runs.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, alice, bob


def _g1_enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _g1_names(permanents):
    return [permanent.card.name for permanent in permanents]


def test_bull_elephant_takes_exactly_two_forests(set_pool, catalog_by_name):
    """"When this creature enters, sacrifice it unless you return two Forests
    you control to their owner's hand."

    The printed count is indivisible: one Forest is not half the price. The
    prompt refuses an answer below the floor and stays owed, which is what
    stops the Elephant staying on the battlefield for half of what it costs.
    """
    game, alice, _ = _g1_rig()
    forests = [_g1_enters(game, 0, catalog_by_name["Forest"]) for _ in range(3)]
    _g1_enters(game, 0, set_pool("VIS")["Bull Elephant"])

    assert game.confirm_optional_pay(0, accept=True) is True
    assert game.confirm_permanent_set_choice(0, [forests[0].permanent_id]) is False
    assert game.confirm_permanent_set_choice(0, []) is False
    assert game.confirm_permanent_set_choice(
        0, [f.permanent_id for f in forests]
    ) is False, "three is over the ceiling as surely as one is under the floor"
    assert game.confirm_permanent_set_choice(
        0, [forests[0].permanent_id, forests[1].permanent_id]
    ) is True

    assert _g1_names(alice.battlefield) == ["Forest", "Bull Elephant"]
    assert [card.name for card in alice.hand] == ["Forest", "Forest"]


def test_bull_elephant_is_sacrificed_when_one_forest_is_all_there_is(
    set_pool, catalog_by_name
):
    """A board that cannot cover the count is never offered the price.

    Accepting an offer it could only half-pay would run the return and skip the
    sacrifice, which is Mold Demon's rule one family over stated for a bounce.
    """
    game, alice, _ = _g1_rig()
    _g1_enters(game, 0, catalog_by_name["Forest"])
    _g1_enters(game, 0, set_pool("VIS")["Bull Elephant"])

    assert game.pending_choices == []
    assert _g1_names(alice.battlefield) == ["Forest"]
    assert [card.name for card in alice.graveyard] == ["Bull Elephant"]


def test_ovinomancer_returns_three_basic_lands(set_pool, catalog_by_name):
    """"...sacrifice it unless you return three basic lands you control to
    their owner's hand."

    "Basic land" rather than a named type, and three rather than one - the same
    production with the noun phrase and the count as data. The nonbasic on the
    board is what proves the supertype is honoured rather than dropped.
    """
    game, alice, _ = _g1_rig()
    basics = [
        _g1_enters(game, 0, catalog_by_name[name])
        for name in ("Forest", "Island", "Mountain")
    ]
    _g1_enters(game, 0, catalog_by_name["Bayou"])
    _g1_enters(game, 0, set_pool("VIS")["Ovinomancer"])

    assert game.confirm_optional_pay(0, accept=True) is True
    assert game.confirm_permanent_set_choice(
        0, [basics[0].permanent_id, basics[1].permanent_id]
    ) is False
    assert game.confirm_permanent_set_choice(
        0, [b.permanent_id for b in basics]
    ) is True

    assert _g1_names(alice.battlefield) == ["Bayou", "Ovinomancer"]
    assert sorted(card.name for card in alice.hand) == ["Forest", "Island", "Mountain"]


def test_ovinomancer_gives_the_sheep_to_the_destroyed_creatures_controller(
    set_pool, catalog_by_name
):
    """"{T}, Return this creature to its owner's hand: Destroy target creature.
    It can't be regenerated. **That creature's controller** creates a 0/1 green
    Sheep creature token."

    Three things in one activation, and the possessive is the one that had no
    reader: the module beside it already read "that creature's controller" for
    Transmogrify's reveal and only "its controller" for a token, so one printed
    spelling of one seat worked and the other did not.
    """
    game, alice, bob = _g1_rig()
    for name in ("Forest", "Island", "Mountain"):
        _g1_enters(game, 0, catalog_by_name[name])
    ovinomancer = _g1_enters(game, 0, set_pool("VIS")["Ovinomancer"])
    ovinomancer.metadata["summoning_sickness_turn"] = -99
    _g1_enters(game, 1, catalog_by_name["Grizzly Bears"])
    game.confirm_optional_pay(0, accept=True)
    game.confirm_permanent_set_choice(
        0,
        [
            permanent.permanent_id
            for permanent in alice.battlefield
            if permanent.card.primary_type == "land"
        ],
    )

    result = game.activate_permanent_ability(
        0, "Ovinomancer", target_player_index=1, target_permanent_index=0
    )

    assert result.supported is True
    # The cost sent it home before the ability resolved (CR 118.3, CR 603.6).
    assert "Ovinomancer" in [card.name for card in alice.hand]
    assert [card.name for card in bob.graveyard] == ["Grizzly Bears"]
    assert _g1_names(bob.battlefield) == ["Sheep Token"]
    assert _g1_names(alice.battlefield) == []


def test_waterspout_djinn_pays_its_upkeep_with_an_untapped_island(
    set_pool, catalog_by_name
):
    """"At the beginning of your upkeep, sacrifice this creature unless you
    return an untapped Island you control to its owner's hand."

    The same price as the Karoo lands', on an upkeep trigger rather than an
    entry one - which is what makes the production a production.
    """
    game, alice, _ = _g1_rig()
    island = _g1_enters(game, 0, catalog_by_name["Island"])
    djinn = _g1_enters(game, 0, set_pool("VIS")["Waterspout Djinn"])

    game.turn = 3
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, accept=True) is True
    assert game.confirm_permanent_set_choice(0, [island.permanent_id]) is True

    assert _g1_names(alice.battlefield) == ["Waterspout Djinn"]
    assert [card.name for card in alice.hand] == ["Island"]
    assert game.is_on_battlefield(djinn)


def test_waterspout_djinn_is_sacrificed_when_the_upkeep_cannot_be_paid(
    set_pool, catalog_by_name
):
    """A tapped Island is no payment, so the Djinn goes."""
    game, alice, _ = _g1_rig()
    island = _g1_enters(game, 0, catalog_by_name["Island"])
    game.become_tapped(island)
    _g1_enters(game, 0, set_pool("VIS")["Waterspout Djinn"])

    game.turn = 3
    game.resolve_upkeep(0)

    assert _g1_names(alice.battlefield) == ["Island"]
    assert [card.name for card in alice.graveyard] == ["Waterspout Djinn"]


def test_shrieking_drake_bounces_a_creature_its_controller_picks(
    set_pool, catalog_by_name
):
    """"When this creature enters, return a creature you control to its owner's
    hand."

    Mandatory and unconditional - no offer, no penalty branch - so the only
    decision is *which*, and it is a choice rather than a target (CR 115.1):
    nothing is announced and shroud cannot save a creature from its own
    controller's hand.
    """
    game, alice, _ = _g1_rig()
    bear = _g1_enters(game, 0, catalog_by_name["Grizzly Bears"])
    drake = _g1_enters(game, 0, set_pool("VIS")["Shrieking Drake"])

    assert game.confirm_permanent_set_choice(0, [bear.permanent_id]) is True

    assert _g1_names(alice.battlefield) == ["Shrieking Drake"]
    assert [card.name for card in alice.hand] == ["Grizzly Bears"]
    assert game.is_on_battlefield(drake)


def test_shrieking_drake_can_only_pick_itself_on_an_empty_board(set_pool):
    """The Drake is a creature its controller controls, so it is a legal answer
    to its own trigger - and the only one when nothing else is there."""
    game, alice, _ = _g1_rig()
    drake = _g1_enters(game, 0, set_pool("VIS")["Shrieking Drake"])

    assert game.confirm_permanent_set_choice(0, [drake.permanent_id]) is True

    assert alice.battlefield == []
    assert [card.name for card in alice.hand] == ["Shrieking Drake"]


def test_stampeding_wildebeests_only_offers_green_creatures(
    set_pool, catalog_by_name
):
    """"At the beginning of your upkeep, return a green creature you control to
    its owner's hand."

    The colour is the narrowing, and a prompt that dropped it would let the
    Wildebeests' controller send back anything - a strictly better card. The
    white Lions are on the board so the refusal has something to refuse.
    """
    game, alice, _ = _g1_rig()
    lions = _g1_enters(game, 0, catalog_by_name["Savannah Lions"])
    wildebeests = _g1_enters(game, 0, set_pool("VIS")["Stampeding Wildebeests"])

    game.turn = 3
    game.resolve_upkeep(0)

    assert game.confirm_permanent_set_choice(0, [lions.permanent_id]) is False
    assert game.confirm_permanent_set_choice(0, [wildebeests.permanent_id]) is True

    assert _g1_names(alice.battlefield) == ["Savannah Lions"]
    assert [card.name for card in alice.hand] == ["Stampeding Wildebeests"]


def test_quirion_ranger_charges_a_forest_and_may_untap_once_a_turn(
    set_pool, catalog_by_name
):
    """"Return a Forest you control to its owner's hand: Untap target creature.
    Activate only once each turn."

    Two halves that fail in opposite directions. A cost nothing charges is a
    free untap every turn; a cap nothing enforces is an unlimited one. Both are
    silent, and the second was already enforced - this is the assertion that
    says so rather than an assumption that it is.
    """
    game, alice, _ = _g1_rig()
    forests = [_g1_enters(game, 0, catalog_by_name["Forest"]) for _ in range(2)]
    ranger = _g1_enters(game, 0, set_pool("VIS")["Quirion Ranger"])
    ranger.metadata["summoning_sickness_turn"] = -99
    game.become_tapped(ranger)

    first = game.activate_permanent_ability(
        0, "Quirion Ranger", target_player_index=0,
        target_permanent_ids=[ranger.permanent_id],
    )
    assert first.supported is True
    assert ranger.tapped is False
    assert [card.name for card in alice.hand] == ["Forest"]
    assert _g1_names(alice.battlefield) == ["Forest", "Quirion Ranger"]

    game.become_tapped(ranger)
    second = game.activate_permanent_ability(
        0, "Quirion Ranger", target_player_index=0,
        target_permanent_ids=[ranger.permanent_id],
    )
    assert second.supported is False
    assert "only once each turn" in (second.details or "")
    # The refused activation spent nothing: the second Forest is still there.
    assert len(alice.hand) == 1
    assert any(permanent is forests[1] for permanent in alice.battlefield)


def test_quirion_ranger_is_refused_with_no_forest(set_pool, catalog_by_name):
    """CR 601.2h via 602.2b: an unpayable cost refuses the activation with
    nothing spent, rather than making the ability free."""
    game, alice, _ = _g1_rig()
    _g1_enters(game, 0, catalog_by_name["Island"])
    ranger = _g1_enters(game, 0, set_pool("VIS")["Quirion Ranger"])
    ranger.metadata["summoning_sickness_turn"] = -99
    game.become_tapped(ranger)

    result = game.activate_permanent_ability(
        0, "Quirion Ranger", target_player_index=0,
        target_permanent_ids=[ranger.permanent_id],
    )

    assert result.supported is False
    assert ranger.tapped is True
    assert alice.hand == []
