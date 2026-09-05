"""Visions creatures.

Opened at the set's ingest with the yield of Phase 1's suite run — see
SET_PLAYBOOK.md, "treat what fires as yield, not noise".
"""

from engine.oracle import compile_card_oracle
from engine import Game, PlayerState
from engine.models import Permanent
from engine.game_types import OracleExecutionContext
from engine.models import CardDefinition, Permanent
from engine.pt import add_pt_counters
from tests.helpers import _damage_dealt, _nosick

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


# --- W1G2: land animation with a colour ---



def _w1g2_druid_board(set_pool):
    druid = Permanent(card=set_pool("VIS")["Quirion Druid"])
    forest = Permanent(card=set_pool("LEA")["Forest"])
    druid.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[druid, forest]),
        PlayerState(name="P2", battlefield=[]),
    ])
    game.enforce_mana_costs = False
    return game, forest


def test_quirion_druid_animates_a_land_indefinitely(set_pool):
    """"{G}, {T}: Target land becomes a 2/2 green creature that's still a land.
    (This effect lasts indefinitely.)"

    The indefinite animation already existed (Mishra's Groundbreaker); what this
    card added was the **colour word** inside the creature body, which the
    production stopped at.
    """
    game, forest = _w1g2_druid_board(set_pool)
    assert not forest.is_creature

    result = game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (2, 2)
    assert forest.has_type("land"), "that's still a land"


def test_quirion_druid_makes_the_land_green(set_pool):
    """CR 613 layer 5, the half of the sentence the animation record cannot
    carry. A colourless land animated without its colour is a permanent Circle
    of Protection: Green does not stop — a word consumed and dropped."""
    game, forest = _w1g2_druid_board(set_pool)
    game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    assert forest.effective_colors == {"G"}


def test_quirion_druid_s_animation_survives_the_turn(set_pool):
    """CR 611.2a: no stated duration, so it lasts as long as the game does. The
    printed reminder says so and the lexer drops it, which is why the *absence*
    of "until end of turn" is what the production reads."""
    game, forest = _w1g2_druid_board(set_pool)
    game.activate_permanent_ability(
        0, "Quirion Druid", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    game.start_turn(1)
    game.start_turn(0)

    assert forest.is_creature
    assert forest.effective_colors == {"G"}


# --- VIS w1g3: prevention, redirection and lethal damage --------------------
#
# Imports live inside the block by the per-set convention, so a merge that
# appends another group's block cannot lose one. Every test here drives a real
# ``Game``: a shield that is armed and never consumed looks exactly like one
# that works.



def _w1g3c_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g3c_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g3c_activate(game, permanent, ability, *, caster, target=None,
                    target_permanent_index=None):
    context = OracleExecutionContext(
        card=permanent.card, caster=caster, target=target or caster,
        source_permanent=permanent,
        target_permanent_index=target_permanent_index,
    )
    game._execute_oracle_instruction(ability.instruction, context)
    return context


def test_resistance_fighter_stops_the_creature_it_named_dealing_combat_damage(set_pool):
    """"Sacrifice this creature: Prevent all combat damage **target creature
    would deal** this turn."

    The active voice of a sentence the engine has read in the passive since Kry
    Shield - the printed subject moved in front of the verb and nothing else -
    so the test that matters is that the shield really stops that creature's
    combat damage and leaves its noncombat damage and everybody else's alone.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    fighter = _nosick(Permanent(card=set_pool("VIS")["Resistance Fighter"]))
    dangerous = _nosick(Permanent(card=_w1g3c_bear("Dangerous Bear")))
    bystander = _nosick(Permanent(card=_w1g3c_bear("Other Bear")))
    p1.battlefield.append(fighter)
    p2.battlefield.extend([dangerous, bystander])

    program = compile_card_oracle(fighter.card)
    assert len(program.activated_abilities) == 1
    _w1g3c_activate(
        game, fighter, program.activated_abilities[0], caster=p1, target=p2,
        target_permanent_index=0,
    )

    assert _damage_dealt(game, p1, 3, source=dangerous, combat=True) == 0
    # Only combat damage, and only that creature's.
    assert _damage_dealt(game, p1, 3, source=dangerous, combat=False) == 3
    assert _damage_dealt(game, p1, 3, source=bystander, combat=True) == 3


def test_zhalfirin_crusader_moves_one_point_onto_the_target_it_chose(set_pool):
    """"{1}{W}: The next 1 damage that would be dealt to this creature this turn
    is dealt to **any target** instead."

    A redirect, not a shield: the damage is still dealt in full by the same
    source, and only its recipient changes for the one point the record covers.
    So the assertion is on both ends - nothing extra marked on the Crusader, and
    the point landing on what the ability named - and on the *remainder*,
    because a record that ate the whole event would be a shield wearing a
    redirect's name.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    crusader = _nosick(Permanent(card=set_pool("VIS")["Zhalfirin Crusader"]))
    taker = _nosick(Permanent(card=_w1g3c_bear("Taker", toughness=5)))
    p1.battlefield.append(crusader)
    p2.battlefield.append(taker)

    program = compile_card_oracle(crusader.card)
    ability = next(
        a for a in program.activated_abilities
        if a.instruction.kind == "redirect_next_damage_from_source_until_eot"
    )
    _w1g3c_activate(
        game, crusader, ability, caster=p1, target=p2, target_permanent_index=0,
    )

    game._mark_damage_on_permanent(crusader, 3)

    assert taker.damage_marked == 1, "one point moved, as the card counts them"
    assert crusader.damage_marked == 2, "and the rest landed where it was aimed"


def test_lichenthrope_turns_damage_into_counters_and_takes_none(set_pool):
    """"If damage would be dealt to this creature, put that many -1/-1 counters
    on it instead."

    CR 614's substitution: the damage is **not dealt at all**, which is why the
    assertion is on ``damage_marked`` staying zero as well as on the counters
    arriving. A version that marked the damage *and* added the counters would
    kill the Plant twice as fast while looking implemented.
    """
    game = _w1g3c_duel()
    p1, _ = game.players
    plant = _nosick(Permanent(card=set_pool("VIS")["Lichenthrope"]))
    p1.battlefield.append(plant)
    printed_toughness = plant.effective_toughness

    assert _damage_dealt(game, plant, 3) == 0
    assert plant.damage_marked == 0
    assert plant.effective_toughness == printed_toughness - 3


def test_lichenthrope_sheds_one_counter_each_upkeep(set_pool):
    """The card's other line, and the reason the substitution above is
    survivable. Asserted in the same file because the two sentences are one
    card: counters that nothing removes are a Plant that dies to a single
    Shock, eventually."""
    game = _w1g3c_duel()
    p1, _ = game.players
    plant = _nosick(Permanent(card=set_pool("VIS")["Lichenthrope"]))
    p1.battlefield.append(plant)
    printed_toughness = plant.effective_toughness
    add_pt_counters(plant, "-1/-1", 2)
    assert plant.effective_toughness == printed_toughness - 2

    game.start_turn(0)
    game._close_current_priority_step()
    game._close_current_priority_step()

    assert plant.effective_toughness == printed_toughness - 1


def test_ogre_enforcer_survives_lethal_damage_spread_across_two_sources(set_pool):
    """"This creature can't be destroyed by lethal damage unless lethal damage
    dealt by a **single source** is marked on it."

    Two 3/3s hitting the Ogre mark lethal damage between them and it lives; one
    source that dealt lethal on its own kills it. CR 704.5g is a state-based
    action, so the only way to test this is to let the sweep run.
    """
    game = _w1g3c_duel()
    p1, p2 = game.players
    ogre = _nosick(Permanent(card=set_pool("VIS")["Ogre Enforcer"]))
    first = _nosick(Permanent(card=_w1g3c_bear("First Biter", power=3)))
    second = _nosick(Permanent(card=_w1g3c_bear("Second Biter", power=3)))
    p1.battlefield.append(ogre)
    p2.battlefield.extend([first, second])
    half = ogre.effective_toughness - 1

    game._mark_damage_on_permanent(ogre, half, source=first)
    game._mark_damage_on_permanent(ogre, half, source=second)
    game.check_state_based_actions()

    assert ogre.damage_marked >= ogre.effective_toughness, "the damage is lethal"
    assert any(p is ogre for p in p1.battlefield), "and the Ogre is still here"


def test_ogre_enforcer_dies_to_one_source_that_dealt_lethal(set_pool):
    """The other half, which is what makes the exception an exception rather
    than indestructibility."""
    game = _w1g3c_duel()
    p1, p2 = game.players
    ogre = _nosick(Permanent(card=set_pool("VIS")["Ogre Enforcer"]))
    big = _nosick(Permanent(card=_w1g3c_bear("Big Biter", power=9, toughness=9)))
    p1.battlefield.append(ogre)
    p2.battlefield.append(big)

    game._mark_damage_on_permanent(ogre, ogre.effective_toughness, source=big)
    game.check_state_based_actions()

    assert not any(p is ogre for p in p1.battlefield)


def test_an_ordinary_creature_still_dies_to_shared_lethal_damage(set_pool):
    """The control: the narrowing is derived from the Ogre's own text, so every
    other creature keeps CR 704.5g exactly as printed. A sweep that had learned
    the exception generally would be a board nothing can kill by ganging up."""
    game = _w1g3c_duel()
    p1, p2 = game.players
    victim = _nosick(Permanent(card=_w1g3c_bear("Ordinary Bear", toughness=4)))
    first = _nosick(Permanent(card=_w1g3c_bear("First Biter", power=3)))
    second = _nosick(Permanent(card=_w1g3c_bear("Second Biter", power=3)))
    p1.battlefield.append(victim)
    p2.battlefield.extend([first, second])

    game._mark_damage_on_permanent(victim, 3, source=first)
    game._mark_damage_on_permanent(victim, 3, source=second)
    game.check_state_based_actions()

    assert not any(p is victim for p in p1.battlefield)
# --- end VIS w1g3 ---
