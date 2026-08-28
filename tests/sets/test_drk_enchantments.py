"""Per-card tests for The Dark's enchantments and Auras.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.models import CardDefinition, Permanent


# --- G2: auras and land statics (The Dark) ---


def test_blood_moon_makes_every_nonbasic_land_a_mountain(set_pool):
    """"Nonbasic lands are Mountains." CR 613 layer 4 with CR 305.7's
    replacement: the dual land is no longer an Island, and it produces the new
    type's mana rather than its printed pair."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    swamp = Permanent(card=set_pool("LEA")["Swamp"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[moon])
    p2 = PlayerState(name="P2", battlefield=[tundra, swamp])
    game = Game(players=[p1, p2])
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()

    assert tundra.has_type("mountain"), game.log
    assert not tundra.has_type("island"), "CR 305.7: the old land types are gone"
    assert tundra.effective_produced_mana == ("R",)
    assert swamp.has_type("swamp"), "a basic land is not a nonbasic one"


def test_blood_moon_stops_applying_when_it_leaves(set_pool):
    """CR 611.3b: the derived channel is rebuilt from the board on every
    recompute, so removal is the absence of a contribution rather than a delta
    anyone has to subtract."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[moon, tundra])
    game = Game(players=[p1, PlayerState(name="P2")])
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    assert tundra.has_type("mountain")

    game.remove_from_battlefield(moon)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()

    assert tundra.has_type("island") and not tundra.has_type("mountain"), game.log


def _caves_on(game: Game, land: Permanent, aura_name: str, set_pool) -> Permanent:
    aura = Permanent(card=set_pool("DRK")[aura_name])
    game.players[0].battlefield.append(aura)
    game._sync_control()
    attach_aura(aura, land)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    return aura


def test_goblin_caves_buffs_goblins_only_while_it_enchants_a_basic_mountain(set_pool):
    """"As long as enchanted land is a basic Mountain, Goblin creatures get
    +0/+2." The condition is asked through ``subject_matches`` — the same
    reader every other noun phrase gets — so it is re-asked on every recompute
    and the anthem switches off with nothing to undo."""
    pool = set_pool("DRK")
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])   # 1/1 Goblin
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[mountain, goblin, bear])
    game = Game(players=[p1, PlayerState(name="P2")])
    aura = _caves_on(game, mountain, "Goblin Caves", set_pool)

    assert (goblin.effective_power, goblin.effective_toughness) == (1, 3), game.log
    assert (bear.effective_power, bear.effective_toughness) == (2, 2), (
        "a Bear is not a Goblin"
    )

    game.remove_from_battlefield(aura)
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1)


def test_goblin_caves_on_a_nonbasic_land_gives_nothing(set_pool):
    """"a **basic** Mountain" is a supertype (CR 205.4a), and dropping it would
    make every dual land in the pool switch the anthem on."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    p1 = PlayerState(name="P1", battlefield=[tundra, goblin])
    game = Game(players=[p1, PlayerState(name="P2")])
    _caves_on(game, tundra, "Goblin Caves", set_pool)

    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1), game.log


def test_blood_moon_does_not_make_a_nonbasic_land_a_basic_mountain(set_pool):
    """The interaction the two cards' printed words decide. Blood Moon changes
    the land's *subtypes* (CR 305.7); it says nothing about the basic
    supertype, so Goblin Caves' "basic Mountain" test still fails — and the
    anthem must ask through the layers to get that right rather than off the
    printed line."""
    tundra = Permanent(card=set_pool("LEA")["Tundra"])
    goblin = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    p1 = PlayerState(name="P1", battlefield=[tundra, goblin, moon])
    game = Game(players=[p1, PlayerState(name="P2")])
    _caves_on(game, tundra, "Goblin Caves", set_pool)

    assert tundra.has_type("mountain"), "Blood Moon still applies"
    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1), game.log


def test_goblin_shrine_burns_every_goblin_when_it_leaves(set_pool):
    """"When this Aura leaves the battlefield, it deals 1 damage to each Goblin
    creature." CR 603.6c, announced from the one transition off the
    battlefield; the noun phrase is the filter the sweep tests, so the Bear
    beside the Goblins is untouched."""
    pool = set_pool("DRK")
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    mine = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    theirs = Permanent(card=set_pool("LEA")["Goblin Balloon Brigade"])
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[mountain, mine])
    p2 = PlayerState(name="P2", battlefield=[theirs, bear])
    game = Game(players=[p1, p2])
    aura = _caves_on(game, mountain, "Goblin Shrine", set_pool)
    assert (mine.effective_power, mine.effective_toughness) == (2, 1), (
        "+1/+0 while it enchants a basic Mountain"
    )

    game.remove_from_battlefield(aura)
    game.resolve_top_of_stack()

    assert mine.damage_marked == 1 and theirs.damage_marked == 1, game.log
    assert bear.damage_marked == 0, "a Bear is not a Goblin"


def test_tangle_kelp_taps_on_entry_and_holds_a_creature_that_attacked(set_pool):
    """"Enchanted creature doesn't untap during its controller's untap step if
    it attacked during its controller's last turn." Goblin Rock Sled's sentence
    about a different subject, answered by the same attack record."""
    pool = set_pool("DRK")
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    p1 = PlayerState(name="P1", battlefield=[bear])
    p2 = PlayerState(name="P2", hand=[pool["Tangle Kelp"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    game.cast_from_hand(1, "Tangle Kelp", target_player_index=0, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert bear.tapped

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: the Bear attacked during P1's last turn
    assert bear.tapped, game.log

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: it sat out, so the Kelp lets it go
    assert not bear.tapped, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _run_upkeep(game: Game, seat: int) -> None:
    """One upkeep step for *seat*, with its triggers resolved off the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


def test_fasting_accrues_a_hunger_counter_each_upkeep_and_dies_at_five(set_pool):
    """"…put a hunger counter on this enchantment. Then destroy this enchantment
    if it has five or more hunger counters on it."

    This whole line compiled to **no instruction at all** — a card reporting
    supported whose upkeep trigger did nothing — because the trailing "if …"
    was unconsumed text. The counter and the threshold are both checked here:
    a threshold read as an equality would still pass at five, so the four
    upkeeps before it are the control.
    """
    fasting = Permanent(card=set_pool("DRK")["Fasting"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[fasting]), PlayerState(name="P2"),
    ])

    for expected in (1, 2, 3, 4):
        _run_upkeep(game, 0)
        assert game.is_on_battlefield(fasting)
        assert counters_on(fasting, "hunger") == expected

    _run_upkeep(game, 0)
    assert not game.is_on_battlefield(fasting)


def test_psychic_allergy_chooses_a_colour_as_it_enters(set_pool):
    """"As this enchantment enters, choose a color."

    The colour half of Jihad's entry line with no opponent beside it, so no
    seat is recorded at all. The headless default is the colour the opponents
    hold most of among nontoken permanents — a colour nobody controls would
    make the card inert, which is a legal choice no player would make.
    """
    lea = set_pool("LEA")
    bears = Permanent(card=lea["Grizzly Bears"])       # green
    wall = Permanent(card=lea["Wall of Wood"])         # green
    knight = Permanent(card=lea["White Knight"])       # white
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("DRK")["Psychic Allergy"]]),
        PlayerState(name="P2", battlefield=[bears, wall, knight]),
    ])

    assert game.cast_from_hand(0, "Psychic Allergy").supported
    allergy = next(p for p in game.all_permanents() if p.card.name == "Psychic Allergy")
    assert allergy.metadata["chosen_color"] == "G"


def test_psychic_allergy_pings_each_opponent_for_their_chosen_colour(set_pool):
    """"At the beginning of each **opponent's** upkeep, this enchantment deals X
    damage to that player, where X is the number of nontoken permanents of the
    chosen color **they** control."

    Three things the card says and this checks: the trigger fires on the
    opponent's upkeep and not the controller's, the count is taken on *that*
    player's battlefield, and the colour is the one recorded on the source as
    it entered — not a colour anything in the sentence names.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    bears = Permanent(card=lea["Grizzly Bears"])       # green, counts
    wall = Permanent(card=lea["Wall of Wood"])         # green, counts
    knight = Permanent(card=lea["White Knight"])       # white, does not
    mine = Permanent(card=lea["Grizzly Bears"])        # green but *mine*
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, mine]),
        PlayerState(name="P2", battlefield=[bears, wall, knight]),
    ])

    _run_upkeep(game, 1)

    assert game.players[1].life == 18
    assert game.players[0].life == 20


def test_psychic_allergy_lets_its_controller_sacrifice_two_islands(set_pool):
    """"At the beginning of your upkeep, destroy this enchantment unless you
    sacrifice two Islands."

    The alternative is decomposed to the `May` the sacrifice twin already uses,
    so accepting really pays the printed cost — two Islands, not one.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    islands = [Permanent(card=lea["Island"]) for _ in range(3)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, *islands]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Psychic Allergy", accept=True)

    assert game.is_on_battlefield(allergy)
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_psychic_allergy_is_destroyed_when_the_islands_are_not_paid(set_pool):
    """The other arm of the same sentence: declining destroys it."""
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    islands = [Permanent(card=lea["Island"]) for _ in range(2)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, *islands]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Psychic Allergy", accept=False)

    assert not game.is_on_battlefield(allergy)
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 2


def test_psychic_allergy_with_one_island_is_never_offered_the_payment(set_pool):
    """"…unless you **sacrifice two Islands**" with one Island on the board.

    A cost a player cannot pay is not an offer (``_action_is_takeable`` counts
    the printed number), so the enchantment simply goes — rather than the
    controller taking the offer, sacrificing one Island and keeping it.
    """
    lea = set_pool("LEA")
    allergy = Permanent(
        card=set_pool("DRK")["Psychic Allergy"], metadata={"chosen_color": "G"}
    )
    island = Permanent(card=lea["Island"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[allergy, island]),
        PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)

    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.is_on_battlefield(allergy)
    assert game.is_on_battlefield(island)


def test_season_of_the_witch_costs_two_life_each_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice this enchantment unless you
    pay 2 life."

    The mana spelling of this sentence was fused into an upkeep-registry kind;
    a *life* payment has no such handler, so it is decomposed into the `May`
    the counted-sacrifice alternative already uses — and CR 118.8's "only with
    a life total at least the amount" comes with it for free.
    """
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season]), PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Season of the Witch", accept=True)

    assert game.is_on_battlefield(season)
    assert game.players[0].life == 18


def test_season_of_the_witch_is_sacrificed_when_the_life_is_not_paid(set_pool):
    """The other arm: declining sacrifices it, and costs no life."""
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season]), PlayerState(name="P2"),
    ])

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Season of the Witch", accept=False)

    assert not game.is_on_battlefield(season)
    assert game.players[0].life == 20


def test_season_of_the_witch_destroys_the_creatures_that_stayed_home(set_pool):
    """"At the beginning of the end step, destroy all untapped creatures that
    didn't attack this turn, except for creatures that couldn't attack."

    The exception is the whole difficulty: "couldn't attack" is a question
    about the declare-attackers step, not about the end step — a Wall is still
    untapped and still idle when the trigger resolves. The answer is frozen at
    CR 508.1's turn-based action, so all four rows below are decided by one
    record taken at the right moment.
    """
    lea = set_pool("LEA")
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    attacker = Permanent(card=lea["Grizzly Bears"])
    idler = Permanent(card=lea["Hill Giant"])
    wall = Permanent(card=lea["Wall of Wood"])       # defender: couldn't attack
    theirs = Permanent(card=lea["Hill Giant"])       # not their turn to attack
    game = Game(players=[
        PlayerState(name="P1", battlefield=[season, attacker, idler, wall]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game._enter_combat_step("declare_attackers")
    ok, _message = game.declare_attackers(0, [1])
    assert ok

    game.resolve_end_step(0)
    while game.stack:
        game.resolve_top_of_stack()

    assert game.is_on_battlefield(attacker)   # it attacked
    assert game.is_on_battlefield(wall)       # it couldn't attack
    assert game.is_on_battlefield(theirs)     # not their turn either
    assert not game.is_on_battlefield(idler)  # untapped, able, and stayed home

# --- G5: zones and characteristics (The Dark) ---------------------------------


def _forest() -> CardDefinition:
    return CardDefinition(
        name="Forest", mana_cost="", cmc=0.0,
        type_line="Basic Land - Forest", oracle_text="",
        colors=(), color_identity=("G",), keywords=(), produced_mana=("G",),
        raw={"name": "Forest", "type_line": "Basic Land - Forest"},
    )


def _touch(set_pool, hand=()):
    pool = set_pool("DRK")
    touch = Permanent(card=pool["Gaea's Touch"])
    touch.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[touch], hand=list(hand))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, touch


def test_gaeas_touch_puts_a_basic_forest_onto_the_battlefield(set_pool):
    """"{0}: You may put a basic Forest card from your hand onto the
    battlefield. Activate only as a sorcery and only once each turn."

    The line compiled *supported* with no instruction behind it for as long as
    the restriction clause refused to parse: the ability existed, could be
    activated, and did nothing. This is the behaviour, not the claim.
    """
    game, p1, p2, touch = _touch(set_pool, hand=[_forest()])

    result = game.activate_permanent_ability(0, "Gaea's Touch", permanent_index=0)

    assert result.supported, result.details
    # The offer is a prompt; a seat that answers by default takes it.
    game.auto_resolve_pending_choices()
    assert [perm.card.name for perm in p1.battlefield] == [
        "Gaea's Touch", "Forest",
    ], game.log
    assert p1.hand == []


def test_gaeas_touch_leaves_a_nonbasic_land_in_hand(set_pool):
    """The control: "**basic** Forest card" is carried into the offer, so a land
    that is not one is never a legal answer."""
    pool = set_pool("DRK")
    game, p1, p2, touch = _touch(set_pool, hand=[pool["City of Shadows"]])

    game.activate_permanent_ability(0, "Gaea's Touch", permanent_index=0)
    game.auto_resolve_pending_choices()

    assert [card.name for card in p1.hand] == ["City of Shadows"], game.log
    assert [perm.card.name for perm in p1.battlefield] == ["Gaea's Touch"]


def test_gaeas_touch_can_still_be_sacrificed_for_two_green(set_pool):
    """The card's other ability, checked here because the round that fixed the
    first one rewrote how its lines are read: "Sacrifice this enchantment: Add
    {G}{G}"."""
    game, p1, p2, touch = _touch(set_pool)

    result = game.activate_permanent_ability(
        0, "Gaea's Touch", permanent_index=0, ability_index=1,
    )

    assert result.supported, result.details
    assert p1.mana_pool["G"] == 2, (dict(p1.mana_pool), game.log)
    assert p1.battlefield == []


# --- H2: land denial and prohibitions (The Dark) ---


def test_mana_vortex_counters_itself_when_no_land_is_sacrificed(set_pool):
    """"When you cast this spell, counter it unless you sacrifice a land."

    CR 603.6d: the ability is on the object being cast and triggers from the
    stack, so no battlefield scan can find it. With no land to give, the offer
    is never made and the decline branch counters the spell — the enchantment
    reaches a graveyard rather than the battlefield.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.players[0].hand = [set_pool("DRK")["Mana Vortex"]]

    game.cast_from_hand(0, "Mana Vortex")
    game.auto_resolve_pending_choices()
    while game.stack:
        game.resolve_top_of_stack()
        game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.players[0].battlefield] == [], game.log
    assert game.players[0].graveyard[-1].name == "Mana Vortex", game.log


def test_mana_vortex_takes_a_land_from_whoever_is_in_upkeep(set_pool):
    """"At the beginning of each player's upkeep, **that player** sacrifices a
    land of their choice."

    The seat is the one the trigger's condition named, frozen by the fire site
    — not the source's controller, which is the wrong seat on every upkeep but
    their own. So P2's upkeep costs P2 a land and leaves P1's alone.
    """
    lea = set_pool("LEA")
    vortex = Permanent(card=set_pool("DRK")["Mana Vortex"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[vortex, Permanent(card=lea["Forest"])]),
        PlayerState(name="P2", battlefield=[Permanent(card=lea["Swamp"])]),
    ])
    game._sync_control()

    _run_upkeep(game, 1)
    game.auto_resolve_pending_choices()

    assert [p.card.name for p in game.players[1].battlefield] == [], game.log
    assert "Forest" in [p.card.name for p in game.players[0].battlefield], game.log


def test_mana_vortex_sacrifices_itself_once_every_land_is_gone(set_pool):
    """"When there are no lands on the battlefield, sacrifice this enchantment."

    A state trigger (CR 603.8) over *every* battlefield, not the controller's:
    the Vortex stays while an opponent still has a land and goes the moment the
    last one anywhere leaves.
    """
    lea = set_pool("LEA")
    vortex = Permanent(card=set_pool("DRK")["Mana Vortex"])
    swamp = Permanent(card=lea["Swamp"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[vortex]),
        PlayerState(name="P2", battlefield=[swamp]),
    ])
    game._sync_control()

    game.check_state_based_actions()
    assert game.is_on_battlefield(vortex), game.log

    game.sacrifice_permanent(swamp)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(vortex), game.log
    assert game.players[0].graveyard[-1].name == "Mana Vortex"
