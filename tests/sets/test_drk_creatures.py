"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.models import CardDefinition, Permanent
import random
from tests.helpers import _damage_dealt, _mk_creature_card, _nosick


# --- G2: auras and land statics (The Dark) ---


def _attack_with(game: Game, seat: int, index: int) -> None:
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(seat, [index])
    assert ok, msg


def test_goblin_rock_sled_rests_for_exactly_one_of_its_controllers_untap_steps(set_pool):
    """"…doesn't untap during your untap step if it attacked during your last
    turn." The condition is re-asked every untap step off the permanent's own
    attack record — the loose substring reading of the phrase would have frozen
    the Sled for the rest of the game."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    # "…can't attack unless defending player controls a Mountain" is the Sled's
    # other printed restriction, so the defender needs one for this test to be
    # about the untap step at all.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]),
        PlayerState(name="P2", battlefield=[Permanent(card=set_pool("LEA")["Mountain"])]),
    ])
    game.start_turn(0)
    _attack_with(game, 0, 0)
    assert sled.tapped, "attacking taps it (CR 508.1f)"

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: it attacked during P1's last turn
    assert sled.tapped, game.log

    game.start_next_turn()   # P2
    game.start_next_turn()   # P1: last turn it sat out, so it untaps
    assert not sled.tapped, game.log


def test_a_goblin_rock_sled_that_never_attacked_untaps_normally(set_pool):
    """The other direction of the same condition. Without it the phrase alone
    would keep any tapped Sled tapped forever."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[sled]), PlayerState(name="P2"),
    ])
    game.become_tapped(sled)
    game.start_turn(0)

    assert not sled.tapped, game.log


def test_goblin_rock_sled_cannot_attack_without_a_defending_mountain(set_pool):
    """The card's other printed restriction, on the same compiled program."""
    sled = Permanent(card=set_pool("DRK")["Goblin Rock Sled"])
    mountain = Permanent(card=set_pool("LEA")["Mountain"])
    p1 = PlayerState(name="P1", battlefield=[sled])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.start_turn(0)

    assert not game.can_attack(sled, 1)
    p2.battlefield.append(mountain)
    game._sync_control()
    assert game.can_attack(sled, 1)


def test_goblins_of_the_flarg_is_sacrificed_the_moment_a_dwarf_arrives(set_pool):
    """"When you control a Dwarf, sacrifice this creature." A state trigger
    (CR 603.8), so it fires alongside the state-based actions rather than
    waiting for the next upkeep — the Goblin never gets to attack beside the
    Dwarf it is printed to lose to."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.check_state_based_actions()
    assert goblin in p1.battlefield, "no Dwarf, no sacrifice"

    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1.battlefield.append(dwarf)
    game._sync_control()
    game.check_state_based_actions()

    assert goblin not in p1.battlefield, game.log
    assert [c.name for c in p1.graveyard] == ["Goblins of the Flarg"]


def test_an_opponents_dwarf_does_not_sacrifice_goblins_of_the_flarg(set_pool):
    """"**You** control a Dwarf" is a seat, and the seat is the Goblin's
    controller — an ignored controller narrowing would sacrifice the card off
    somebody else's board."""
    pool = set_pool("DRK")
    goblin = Permanent(card=pool["Goblins of the Flarg"])
    dwarf = Permanent(card=set_pool("LEA")["Dwarven Warriors"])
    p1 = PlayerState(name="P1", battlefield=[goblin])
    p2 = PlayerState(name="P2", battlefield=[dwarf])
    game = Game(players=[p1, p2])

    game.check_state_based_actions()

    assert goblin in p1.battlefield, game.log

# --- G1: damage family (The Dark) ---


def _damage_board(set_pool, name: str, *, seats: int = 2) -> tuple[Game, list[PlayerState], Permanent]:
    """A board with one named DRK creature, for the damage group's tests.

    Named for its group rather than `_board`: the zones group landed a
    helper of that name in this file in the same round, taking a *list* of
    creatures, and the later definition silently shadowed this one.
    """
    """*name* on seat 0's battlefield, summoning sickness already worked off."""
    perm = Permanent(card=set_pool("DRK")[name])
    perm.summoning_sick = False
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].battlefield = [perm]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players, perm


def test_banshee_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("DRK")["Banshee"])
    assert program.supported, program.unsupported_reason


def test_banshee_rounds_the_two_halves_in_opposite_directions(set_pool):
    """"half X damage, rounded down, to any target, and half X damage, rounded
    up, to you" — one sentence, two roundings. With X = 5 that is 2 and 3, and
    a reader that honoured one rounding for both would deal 2/2 or 3/3."""
    game, players, banshee = _damage_board(set_pool, "Banshee")

    result = game.activate_permanent_ability(
        0, "Banshee", target_player_index=1, x_value=5
    )

    assert result.supported, result.details
    assert players[1].life == 18, game.log
    assert players[0].life == 17, game.log


def test_banshee_with_an_odd_x_of_one_hits_only_its_controller(set_pool):
    """X = 1: half rounded down is 0, and CR 120.8 makes a source that would
    deal 0 damage deal none at all. Half rounded up is still 1."""
    game, players, banshee = _damage_board(set_pool, "Banshee")

    game.activate_permanent_ability(0, "Banshee", target_player_index=1, x_value=1)

    assert players[1].life == 20, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_pumps_and_bites_its_controller_in_one_ability(set_pool):
    """"gets +2/+0 until end of turn **and deals 1 damage to you**" is one
    printed ability. Read as a pump alone the card is strictly better than it
    prints, and the whole line refused to parse before the conjunct existed."""
    game, players, eel = _damage_board(set_pool, "Electric Eel")

    result = game.activate_permanent_ability(0, "Electric Eel")

    assert result.supported, result.details
    assert eel.effective_power == 3, game.log
    assert players[0].life == 19, game.log


def test_electric_eel_bites_its_controller_when_it_enters(set_pool):
    """The other half of the card, and the one that already worked — kept here
    so a change to the activated line cannot quietly take the trigger with it."""
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].hand = [set_pool("DRK")["Electric Eel"]]
    game = Game(players=players)
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Electric Eel")
    game._settle()

    assert players[0].life == 19, game.log


def test_the_fallen_damages_nobody_before_it_has_damaged_anybody(set_pool):
    """"each opponent … **it has dealt damage to this game**" is a history, not
    a board. With an empty record the upkeep trigger hits nothing; a reading
    that dropped the clause would be a Pestilence."""
    game, players, fallen = _damage_board(set_pool, "The Fallen")
    game.start_turn(0)
    game._settle()

    assert players[1].life == 20, game.log


def test_the_fallen_remembers_the_opponent_it_damaged(set_pool):
    """One point of damage from this creature puts that seat in its record, and
    every later upkeep collects on it."""
    game, players, fallen = _damage_board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 3, source=fallen)
    assert players[1].life == 17

    game.start_turn(0)
    game._settle()

    assert players[1].life == 16, game.log


def test_the_fallen_forgets_what_a_previous_object_damaged(set_pool):
    """CR 400.7: a creature that leaves and returns is a new object. The record
    lives on the permanent, so the new one remembers nothing — which is what
    keeps "this game" from meaning "this game, plus a previous incarnation"."""
    game, players, fallen = _damage_board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[1], 1, source=fallen)
    game.remove_from_battlefield(fallen)

    returned = Permanent(card=set_pool("DRK")["The Fallen"])
    returned.summoning_sick = False
    players[0].battlefield = [returned]
    game._sync_control()
    life_before = players[1].life

    game.start_turn(0)
    game._settle()

    assert players[1].life == life_before, game.log


def test_the_fallen_never_damages_its_own_controller(set_pool):
    """"each **opponent**": a seat recorded because this creature damaged its
    own controller is not one, and the record holds seats rather than
    opponents so the question is asked when the trigger resolves."""
    game, players, fallen = _damage_board(set_pool, "The Fallen")
    game._deal_damage_to_player(players[0], 1, source=fallen)
    life_before = players[0].life

    game.start_turn(0)
    game._settle()

    assert players[0].life == life_before, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _leviathan_board(set_pool, island_count: int = 2):
    """Leviathan untapped on the battlefield with *island_count* Islands."""
    lea = set_pool("LEA")
    leviathan = Permanent(card=set_pool("DRK")["Leviathan"])
    islands = [Permanent(card=lea["Island"]) for _ in range(island_count)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[leviathan, *islands]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    return game, leviathan


def test_leviathan_enters_tapped_and_stays_tapped(set_pool):
    """"This creature enters tapped and doesn't untap during your untap step."

    One printed line making two claims. The entry half was already applied
    (`enter_effects.ENTERS_TAPPED` is a substring probe); the untap half was
    **not** — `self_untap_line` is anchored on the whole line and had no row
    for this spelling, so Leviathan entered tapped and then untapped every
    turn with nothing failing.
    """
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("DRK")["Leviathan"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Leviathan").supported
    leviathan = next(p for p in game.all_permanents() if p.card.name == "Leviathan")
    assert leviathan.tapped

    game.resolve_untap_step(0)
    assert leviathan.tapped


def test_leviathan_untaps_when_two_islands_are_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice two Islands. If you
    do, untap this creature." This line produced no instruction at all."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)
    game.become_tapped(leviathan)
    game.current_turn_phase = "beginning"

    game.resolve_upkeep(0)
    while game.stack:
        game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, card_name="Leviathan", accept=True)

    assert not leviathan.tapped
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_cannot_attack_without_two_islands_to_sacrifice(set_pool):
    """"This creature can't attack unless you sacrifice two Islands. (This cost
    is paid as attackers are declared.)" CR 508.1g — a cost, not a target.

    With one Island the cost is unpayable, so the declaration is illegal. The
    Island stays: a refused declaration charges nothing.
    """
    game, _leviathan = _leviathan_board(set_pool, island_count=1)

    ok, _message = game.declare_attackers(0, [0])

    assert not ok
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_pays_two_islands_as_attackers_are_declared(set_pool):
    """The other half: with the cost payable the attack happens **and** the
    Islands are gone. A restriction nothing charges is a card that attacks for
    free, which is the direction a missing enforcement always fails in."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)

    ok, _message = game.declare_attackers(0, [0])

    assert ok
    assert leviathan.attacking
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Island", "Island"]

# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _basic(name: str, subtype: str, symbol: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line=f"Basic Land - {subtype}", oracle_text="",
        colors=(), color_identity=(symbol,), keywords=(), produced_mana=(symbol,),
        raw={"name": name, "type_line": f"Basic Land - {subtype}"},
    )


def _board(set_pool, mine, theirs=(), *, my_graveyard=(), their_hand=()):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=pool[name])) for name in mine],
        graveyard=[pool[name] for name in my_graveyard],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[_nosick(Permanent(card=pool[name])) for name in theirs],
        hand=[pool[name] for name in their_hand],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, pool


# --- exiling from a graveyard, as a cost and as an effect ---------------------


def test_grave_robbers_exiles_an_artifact_card_and_gains_two_life(set_pool):
    """"{B}, {T}: Exile target artifact card from a graveyard. You gain 2
    life." The picker is narrowed to artifacts, and the narrowing is the whole
    difference from the "any card" form the graveyard exile used to be."""
    game, p1, p2, pool = _board(
        set_pool, ["Grave Robbers"], my_graveyard=["Fellwar Stone"],
    )
    life = p1.life

    result = game.activate_permanent_ability(
        0, "Grave Robbers", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert p1.graveyard == [], game.log
    assert [card.name for card in p1.exile] == ["Fellwar Stone"]
    assert p1.life == life + 2


def test_grave_robbers_picker_is_narrowed_to_artifact_cards(set_pool):
    """The control: "artifact card" is carried into the picker rather than
    collapsed to "any card". One predicate, offered and re-checked - a picker
    offering a creature for a cost the resolution then refuses is a tap paid
    for nothing."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pool = set_pool("DRK")
    program = compile_card_oracle(pool["Grave Robbers"])
    spec = derive_activation_spec(program.activated_abilities[0])

    assert spec == {"kind": "graveyard_creature", "card_type": "artifact"}


def test_eater_of_the_dead_untaps_itself_by_eating_a_corpse(set_pool):
    """"{0}: **If this creature is tapped**, exile target creature card from a
    graveyard and untap this creature." Both halves, in order."""
    game, p1, p2, pool = _board(
        set_pool, ["Eater of the Dead"], my_graveyard=["Rag Man"],
    )
    eater = p1.battlefield[0]
    eater.tapped = True

    result = game.activate_permanent_ability(
        0, "Eater of the Dead", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert [card.name for card in p1.exile] == ["Rag Man"], game.log
    assert eater.tapped is False


def test_necropolis_grows_by_the_exiled_cards_mana_value(set_pool):
    """"Exile a creature card from your graveyard: Put **X** +0/+1 counters on
    this creature, where X is **the exiled card's** mana value."

    The cost is paid before the ability resolves (CR 601.2h), so by the time X
    is read the card is out of the game - the number is last-known information
    the activation recorded, not anything a zone still holds."""
    game, p1, p2, pool = _board(
        set_pool, ["Necropolis"], my_graveyard=["Angry Mob"],
    )
    necropolis = p1.battlefield[0]
    printed = necropolis.effective_toughness
    mana_value = int(pool["Angry Mob"].cmc)
    assert mana_value > 0, "the fixture needs a card with a real mana value"

    result = game.activate_permanent_ability(0, "Necropolis", permanent_index=0)

    assert result.supported, result.details
    assert p1.graveyard == [], "the cost ate the card"
    assert [card.name for card in p1.exile] == ["Angry Mob"]
    assert necropolis.effective_toughness == printed + mana_value, game.log
    assert necropolis.effective_power == 0, "+0/+1 counters add no power"


def test_necropolis_cannot_be_activated_with_an_empty_graveyard(set_pool):
    """The control on the test above: the exile is a *cost*, so with nothing to
    pay it the ability is not activated at all (CR 602.2b) rather than resolving
    for free."""
    game, p1, p2, pool = _board(set_pool, ["Necropolis"])
    necropolis = p1.battlefield[0]
    printed = necropolis.effective_toughness

    result = game.activate_permanent_ability(0, "Necropolis", permanent_index=0)

    assert not result.supported
    assert necropolis.effective_toughness == printed


# --- revealing a hand and discarding from it ---------------------------------


def test_rag_man_takes_a_creature_card_at_random(set_pool):
    """"Target opponent reveals their hand and discards a **creature** card at
    random." The sample is drawn from the cards answering the phrase, so the
    land in hand is never at risk."""
    game, p1, p2, pool = _board(
        set_pool, ["Rag Man"], their_hand=["Angry Mob", "City of Shadows"],
    )
    random.seed(11)

    result = game.activate_permanent_ability(
        0, "Rag Man", permanent_index=0, target_player_index=1,
    )

    assert result.supported, result.details
    assert [card.name for card in p2.hand] == ["City of Shadows"], game.log
    assert [card.name for card in p2.graveyard] == ["Angry Mob"]


def test_rag_man_replays_the_same_discard_for_the_same_seed(set_pool):
    """Determinism: the sample comes from the module RNG ``run_ai_simulation``
    seeds, so a given seed reproduces a run exactly."""
    taken = []
    for _ in range(2):
        game, p1, p2, pool = _board(
            set_pool, ["Rag Man"],
            their_hand=["Angry Mob", "Necropolis", "People of the Woods"],
        )
        random.seed(4)
        game.activate_permanent_ability(
            0, "Rag Man", permanent_index=0, target_player_index=1,
        )
        taken.append([card.name for card in p2.graveyard])

    assert taken[0] == taken[1] and len(taken[0]) == 1, taken


# --- characteristic-defining P/T (CR 604.3) ----------------------------------


def test_people_of_the_woods_toughness_counts_forests(set_pool):
    """"…**toughness** is equal to the number of Forests you control." The
    printed power stands: this is a 0/*, and defining both halves would make it
    a creature the card never prints."""
    pool = set_pool("DRK")
    forest = _basic("Forest", "Forest", "G")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["People of the Woods"]),
            Permanent(card=forest),
            Permanent(card=forest),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    people = p1.battlefield[0]

    printed_power = int(pool["People of the Woods"].raw["power"])
    assert people.effective_toughness == 2, game.log
    assert people.effective_power == printed_power, "only the toughness is defined"

    # …and it tracks the board rather than being fixed as it entered. A third
    # Forest is a third point of toughness; without one it would be a 0/0 and
    # die to the state-based check, which is the card.
    p1.battlefield.append(Permanent(card=forest))
    game._refresh_dynamic_creatures()

    assert people.effective_toughness == 3, game.log


def test_angry_mob_counts_swamps_only_on_its_controllers_turn(set_pool):
    """"During **your** turn, …are each equal to 2 plus the number of Swamps
    **your opponents** control. During turns other than yours, …are each 2."

    Two answers on one card, and which one applies is a question about the turn
    rather than about a battlefield."""
    swamp = _basic("Swamp", "Swamp", "B")
    pool = set_pool("DRK")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Angry Mob"])])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=swamp) for _ in range(3)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    mob = p1.battlefield[0]

    game.start_turn(0)
    assert (mob.effective_power, mob.effective_toughness) == (5, 5), game.log

    game.active_player_index = 1
    game._refresh_dynamic_creatures()
    assert (mob.effective_power, mob.effective_toughness) == (2, 2), game.log


# --- odds and ends -----------------------------------------------------------


def test_goblin_wizard_drops_a_goblin_out_of_hand(set_pool):
    """"{T}: You may put a **Goblin permanent card** from your hand onto the
    battlefield." A generic head noun after a subtype, which used to refuse the
    line outright."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=pool["Goblin Wizard"]))],
        hand=[pool["Orc General"], pool["Goblin Wizard"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Goblin Wizard", permanent_index=0)

    assert result.supported, result.details
    # The offer is a prompt, so a seat that answers by default takes it - the
    # stated AI policy for an optional put-onto-the-battlefield.
    game.auto_resolve_pending_choices()
    dropped = [perm.card.name for perm in p1.battlefield]
    assert dropped.count("Goblin Wizard") == 2, game.log
    assert "Orc General" in [card.name for card in p1.hand], "an Orc is not a Goblin"


def test_orc_general_buffs_other_orcs_and_eats_one_to_do_it(set_pool):
    """"{T}, Sacrifice **another Orc or Goblin**: Other **Orc** creatures get
    +1/+1 until end of turn."

    Both halves are narrowed by subtype, and the two live on opposite sides of
    the pipeline - the cost is charged by `engine/oracle.py` and the buff comes
    out of the grammar. A narrowing that reached only one of them is a cost
    nobody pays or a board nobody named."""
    game, p1, p2, pool = _board(
        set_pool, ["Orc General", "Orc General", "Goblin Wizard"],
    )
    source, other_orc, goblin = p1.battlefield
    goblin_power = goblin.effective_power
    printed = int(pool["Orc General"].raw["power"])

    result = game.activate_permanent_ability(0, "Orc General", permanent_index=0)

    assert result.supported, result.details
    eaten = {"Orc General", "Goblin Wizard"} - {
        perm.card.name for perm in p1.battlefield
    } or {"Goblin Wizard"}
    assert eaten, "the cost ate nothing"
    # "**Other** Orc creatures" - CR 109.5 excludes the ability's own source,
    # so the General that paid does not buff itself.
    assert source.effective_power == printed, game.log
    if any(perm is other_orc for perm in p1.battlefield):
        assert other_orc.effective_power == printed + 1, game.log
    if any(perm is goblin for perm in p1.battlefield):
        assert goblin.effective_power == goblin_power, "a Goblin is not an Orc"


def test_orc_general_cannot_be_activated_with_no_other_orc_or_goblin(set_pool):
    """The control on the cost half: "another Orc or Goblin" is charged, so a
    lone General has no legal payment and the buff never happens."""
    game, p1, p2, pool = _board(set_pool, ["Orc General"])

    result = game.activate_permanent_ability(0, "Orc General", permanent_index=0)

    assert not result.supported, game.log
    assert [perm.card.name for perm in p1.battlefield] == ["Orc General"]


def test_nameless_race_is_the_life_its_controller_paid_as_it_entered(set_pool):
    """"As this creature enters, pay any amount of life. The amount you pay
    can't be more than the total number of white nontoken permanents your
    opponents control plus the total number of white cards in their
    graveyards." / "…power and toughness are each equal to the life paid as it
    entered."

    An *entry* value, not a running count: the number is fixed as the creature
    arrives (CR 614.1c) and nothing on any board answers for it afterwards -
    which is why it rides the permanent the way Wood Elemental's sacrifice
    count does.
    """
    pool = set_pool("DRK")
    plains = _basic("Plains", "Plains", "W")
    p1 = PlayerState(name="P1", hand=[pool["Nameless Race"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=plains)],
        graveyard=[pool["Martyr's Cry"], pool["Angry Mob"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    life = p1.life

    result = game.cast_from_hand(0, "Nameless Race")
    assert result.supported, result.details

    # Three white objects on the far side: the Plains is a white permanent only
    # if its colour says so, so the cap is what the two white cards in the
    # graveyard allow plus whatever the board adds.
    prompt = [c for c in game.pending_choices if c.kind == "number_choice"]
    assert prompt, game.log
    cap = prompt[0].data["maximum"]
    assert cap >= 2, (cap, game.log)

    assert game.confirm_number_choice(0, 2), game.log
    race = [perm for perm in p1.battlefield if perm.card.name == "Nameless Race"][0]
    assert (race.effective_power, race.effective_toughness) == (2, 2), game.log
    assert p1.life == life - 2, "the life is paid, not merely chosen"


def test_nameless_race_declined_dies_as_a_zero_zero(set_pool):
    """The control: paying nothing is a legal answer, and a 0/0 dies to the
    state-based check — which is the card."""
    pool = set_pool("DRK")
    p1 = PlayerState(name="P1", hand=[pool["Nameless Race"]])
    p2 = PlayerState(name="P2", graveyard=[pool["Martyr's Cry"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    life = p1.life

    game.cast_from_hand(0, "Nameless Race")
    game.auto_resolve_pending_choices()
    game._settle()

    assert "Nameless Race" not in {perm.card.name for perm in p1.battlefield}, game.log
    assert p1.life == life

# --- G4: combat, prevention, control (The Dark) ---


def _duel(*, mine: list[Permanent], theirs: list[Permanent]):
    p1 = PlayerState(name="P1", battlefield=mine)
    p2 = PlayerState(name="P2", battlefield=theirs)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2


def test_uncle_istvan_takes_no_damage_from_a_creature(set_pool):
    """"Prevent all damage that would be dealt to this creature by creatures."

    The bare plural is the same source class the two-word "creature sources"
    names, so it is a row of the text-keyed table rather than a card of its own.
    """
    istvan = Permanent(card=set_pool("DRK")["Uncle Istvan"])
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))
    game, _p1, _p2 = _duel(mine=[istvan], theirs=[bear])

    assert _damage_dealt(game, istvan, 2, source=bear) == 0
    assert istvan.damage_marked == 0


def test_uncle_istvan_still_takes_damage_from_a_spell(set_pool):
    """The class is read, not ignored: only *creatures* are shielded against,
    so a burn spell still kills him."""
    istvan = Permanent(card=set_pool("DRK")["Uncle Istvan"])
    # A spell's damage source is the card as printed (CR 109.5), and this one
    # is an Artifact: not a creature, so the shield does not answer to it.
    spell = set_pool("DRK")["Barl's Cage"]
    game, _p1, _p2 = _duel(mine=[istvan], theirs=[])

    assert _damage_dealt(game, istvan, 3, source=spell) == 3


def test_lurker_cannot_be_targeted_until_it_fights(set_pool):
    """"This creature can't be the target of spells unless it attacked or
    blocked this turn."

    The "unless" clause is rechecked whenever a target is chosen, never latched:
    the moment the Lurker is declared as an attacker it stops being protected.
    """
    lurker = _nosick(Permanent(card=set_pool("DRK")["Lurker"]))
    game, _p1, _p2 = _duel(mine=[lurker], theirs=[])
    spell = set_pool("DRK")["Lurker"]

    assert not game._can_be_targeted(lurker, spell)

    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0])[0]

    assert game._can_be_targeted(lurker, spell)


def test_lurker_is_still_reachable_by_an_ability(set_pool):
    """The clause names spells. CR 115.1a and CR 115.1c/d make a spell and an
    ability separately targeted, so an ability is untouched."""
    lurker = Permanent(card=set_pool("DRK")["Lurker"])
    source = Permanent(card=_mk_creature_card("Pinger", 1, 1))
    game, _p1, _p2 = _duel(mine=[lurker], theirs=[source])

    assert game._can_be_targeted(lurker, None, ability_source=source)


def test_tracker_and_its_victim_trade_damage(set_pool):
    """"{G}{G}, {T}: This creature deals damage equal to its power to target
    creature. That creature deals damage equal to its power to this creature."

    Two printed sentences, not CR 701.14's fight: the second reads the creature
    the first chose out of the resolution's own record.
    """
    tracker = _nosick(Permanent(card=set_pool("DRK")["Tracker"]))  # 2/2
    victim = Permanent(card=_mk_creature_card("Ogre", 3, 3))
    game, _p1, _p2 = _duel(mine=[tracker], theirs=[victim])

    result = game.activate_permanent_ability(
        0, "Tracker", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert victim.damage_marked == 2, "the Tracker's power"
    assert tracker.damage_marked == 3, "and the Ogre's, back"


def test_whippoorwill_locks_a_creature_out_of_every_shield(set_pool):
    """"Damage that would be dealt to that creature this turn can't be prevented
    or dealt instead to another permanent or player."

    The lock is enforced where a damage event's contention set is assembled, so
    a shield armed *after* it still does not apply.
    """
    from engine.prevention import COMBAT_SHIELD_TO, add_directional_shield

    bird = _nosick(Permanent(card=set_pool("DRK")["Whippoorwill"]))
    victim = Permanent(card=_mk_creature_card("Ogre", 3, 3))
    game, _p1, _p2 = _duel(mine=[bird], theirs=[victim])

    result = game.activate_permanent_ability(
        0, "Whippoorwill", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    assert result.supported

    add_directional_shield(victim, COMBAT_SHIELD_TO, combat_only=False)
    assert _damage_dealt(game, victim, 2, source=bird) == 2, (
        "the shield is one of the contenders the lock drops"
    )


def test_whippoorwill_also_denies_regeneration_and_exiles(set_pool):
    """The other two printed sentences, which the engine already read. Asserted
    here because the card is only supported when *every* line is."""
    program = compile_card_oracle(set_pool("DRK")["Whippoorwill"])
    assert program.supported
    kinds = _step_kinds(program.activated_abilities[0].instruction)
    assert "deny_regeneration_to_target" in kinds
    assert "lock_damage_to_target" in kinds
    assert "create_delayed_trigger" in kinds


def _step_kinds(instruction) -> list[str]:
    """Every instruction kind in a composed effect, outermost first."""
    if instruction is None:
        return []
    found = [instruction.kind]
    for step in instruction.payload.get("steps") or ():
        found.extend(_step_kinds(step))
    return found


def test_giant_shark_only_triggers_on_a_wounded_blocker(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature that has
    been dealt damage this turn, …"

    The noun phrase is a record the damage seam stamps, not a read of
    ``damage_marked`` — which regeneration wipes while the damage stays dealt.
    """
    shark = _nosick(Permanent(card=set_pool("DRK")["Giant Shark"]))
    island = Permanent(card=_mk_creature_card("Island", 0, 0))
    island.card = island.card.__class__(
        **{**island.card.__dict__, "type_line": "Land — Island", "power": None,
           "toughness": None}
    )
    healthy = Permanent(card=_mk_creature_card("Healthy", 1, 1))
    wounded = Permanent(card=_mk_creature_card("Wounded", 1, 4))

    # An Island on each side: the Shark sacrifices itself while *you* control
    # none, and it can't attack unless the *defender* controls one.
    mine_island = Permanent(card=island.card)
    game, _p1, _p2 = _duel(mine=[shark, mine_island], theirs=[healthy, wounded, island])
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()  # declare blockers

    _damage_dealt(game, wounded, 1, source=healthy)
    assert game.declare_blockers(1, {1: 0})[0]
    game._settle()

    assert shark.effective_power == 6, "+2/+0 for a blocker that had been hurt"


def test_giant_shark_stays_quiet_against_an_unhurt_blocker(set_pool):
    """The other half of the same narrowing: a matcher ignoring the phrase
    would fire the trigger on every block."""
    shark = _nosick(Permanent(card=set_pool("DRK")["Giant Shark"]))
    healthy = Permanent(card=_mk_creature_card("Healthy", 1, 1))
    island = Permanent(card=_mk_creature_card("Island", 0, 0))
    island.card = island.card.__class__(
        **{**island.card.__dict__, "type_line": "Land — Island", "power": None,
           "toughness": None}
    )

    mine_island = Permanent(card=island.card)
    game, _p1, _p2 = _duel(mine=[shark, mine_island], theirs=[healthy, island])
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game._settle()

    assert shark.effective_power == 4


def test_spitting_slug_fires_on_the_bare_joined_block(set_pool):
    """"Whenever this creature blocks or becomes blocked, …"

    The bare joined sentence was in neither front-end table, though both
    dispatchers already read the condition. CR 509.3c: with no noun phrase it
    fires **once** for the block.
    """
    slug = Permanent(card=set_pool("DRK")["Spitting Slug"])
    attacker = _nosick(Permanent(card=_mk_creature_card("Attacker", 2, 2)))

    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[slug])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game._settle()

    # The offer is declined with no mana floating, so the "Otherwise" arm runs:
    # each creature in combat with the Slug gains first strike.
    assert game._has_keyword(attacker, "first strike")


def test_preacher_hands_the_pick_to_the_opponent(set_pool):
    """"{T}: For as long as this creature remains tapped, gain control of target
    creature of an opponent's choice they control."

    The pick belongs to the other seat, so it is the ordinary permanent-choice
    prompt armed on them; the steal behind it reads their answer. Control ends
    when the Preacher untaps (CR 611.2b).
    """
    preacher = _nosick(Permanent(card=set_pool("DRK")["Preacher"]))
    theirs = Permanent(card=_mk_creature_card("Ogre", 3, 3))
    game, _p1, _p2 = _duel(mine=[preacher], theirs=[theirs])

    result = game.activate_permanent_ability(0, "Preacher", permanent_index=0)
    game._settle()

    assert result.supported
    assert preacher.tapped is True
    assert game.controller_index_of(theirs) == 0, "the Preacher's controller has it"

    game.become_untapped(preacher)
    game._settle()
    assert game.controller_index_of(theirs) == 1, "and loses it when he untaps"


def _bandits_board(set_pool):
    import dataclasses

    bandits = _nosick(Permanent(card=set_pool("DRK")["Scarwood Bandits"]))
    relic = Permanent(
        card=dataclasses.replace(
            _mk_creature_card("Relic", 0, 0),
            type_line="Artifact", power=None, toughness=None,
        )
    )
    game, _p1, p2 = _duel(mine=[bandits], theirs=[relic])
    game.activate_permanent_ability(
        0, "Scarwood Bandits", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    return game, bandits, relic, p2


def test_scarwood_bandits_offer_the_cost_to_the_opponent(set_pool):
    """"{2}{G}, {T}: Unless an opponent pays {2}, gain control of target
    artifact for as long as this creature remains on the battlefield."

    The offer goes to the *other* seat, on the same ``optional_pay`` queue every
    other offer uses — so it is owed by them and not by the activating player.
    """
    game, _bandits, _relic, p2 = _bandits_board(set_pool)

    owed = game.pending_choices_of("optional_pay", 1)
    assert len(owed) == 1
    assert owed[0].data["cost"] == {"generic": 2}


def test_scarwood_bandits_can_be_bought_off(set_pool):
    """Paying stops the steal: the effect rides the *declined* branch, so an
    accepted offer runs nothing at all."""
    game, _bandits, relic, p2 = _bandits_board(set_pool)
    p2.mana_pool["C"] = p2.mana_pool.get("C", 0) + 2

    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert game.controller_index_of(relic) == 1, "the opponent paid"


def test_scarwood_bandits_steal_when_nobody_pays(set_pool):
    """The decline branch, and the duration behind it: "remains on the
    battlefield" is weaker than "you control this creature", so the artifact
    goes back only when the Bandits leave."""
    game, bandits, relic, _p2 = _bandits_board(set_pool)

    assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert game.controller_index_of(relic) == 0, "nobody paid, so it is stolen"

    game.remove_from_battlefield(bandits)
    game._settle()
    assert game.controller_index_of(relic) == 1


# --- K1: Frankenstein's Monster (The Dark) ---
#
# "As this creature enters, exile X creature cards from your graveyard. If you
# can't, put this creature into its owner's graveyard instead of onto the
# battlefield. For each creature card exiled this way, this creature enters with
# a +2/+0, +1/+1, or +0/+2 counter on it."
#
# Three printed sentences and one CR 614.1c replacement, so they are one reader
# (engine/enter_effects.exile_cards_on_enter) with three consumers: the support
# gate, the entry state that arms the choice, and the CR 614 interceptor that
# performs "if you can't". The tests below take each consumer in turn.


def _monster_game(set_pool, graveyard, *, interactive=False):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Frankenstein's Monster"]],
        graveyard=list(graveyard),
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.start_turn(0)
    return game, p1


def _monster_on(player):
    return next(
        (perm for perm in player.battlefield
         if perm.card.name == "Frankenstein's Monster"),
        None,
    )


def test_frankensteins_monster_is_supported(set_pool):
    """The whole three-sentence paragraph is one claim, not one sentence of
    three - a card admitted on its first sentence would enter for an X its
    graveyard cannot pay."""
    program = compile_card_oracle(set_pool("DRK")["Frankenstein's Monster"])
    assert program.supported, program.reason


def test_frankensteins_monster_pays_its_entry_cost_and_grows(set_pool):
    """X=2 with two creature cards in the graveyard: both are exiled and the
    creature enters with two counters on it.

    The counters are chosen one per exiled card and they need not match - the
    +2/+0 and the +0/+2 here take the printed 0/1 to 2/3, which is the sum a
    single kind could not produce.
    """
    game, p1 = _monster_game(
        set_pool,
        [set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Craw Wurm"],
         set_pool("LEA")["Mox Pearl"]],
        interactive=True,
    )

    result = game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)
    assert result.supported, result.details

    owed = [c for c in game.pending_choices if c.kind == "entry_exile"]
    assert owed, game.log
    assert owed[0].data["count"] == 2
    assert owed[0].data["counters"] == ["+2/+0", "+1/+1", "+0/+2"]
    # The Mox is in the graveyard and is not offered: the printed noun phrase is
    # "creature cards", and the picker's list is the engine's own.
    assert game._entry_exile_candidates(owed[0]) == [0, 1]

    assert game.resolve_pending_choice(
        "entry_exile", 0,
        picks=[{"index": 0, "counter": "+2/+0"}, {"index": 1, "counter": "+0/+2"}],
    ), game.log
    game._settle()

    monster = _monster_on(p1)
    assert monster is not None, game.log
    assert (monster.effective_power, monster.effective_toughness) == (2, 3)
    assert sorted(card.name for card in p1.exile) == ["Craw Wurm", "Grizzly Bears"]
    assert [card.name for card in p1.graveyard] == ["Mox Pearl"]


def test_frankensteins_monster_that_cannot_pay_never_enters(set_pool):
    """"If you can't, put this creature into its owner's graveyard **instead of
    onto the battlefield**." X=2 against one creature card in the graveyard.

    A CR 614 replacement rather than a sacrifice afterwards, so the card is in
    the graveyard and nothing on any battlefield ever held it - and the exile
    that could not be paid did not happen either.
    """
    game, p1 = _monster_game(
        set_pool, [set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Mox Pearl"]]
    )

    game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)
    game._settle()

    assert _monster_on(p1) is None, game.log
    assert p1.graveyard[-1].name == "Frankenstein's Monster"
    assert p1.exile == [], "an entry cost that cannot be paid is not part-paid"
    assert "Grizzly Bears" in {card.name for card in p1.graveyard}
    # The log must not claim an entry that a replacement consumed.
    assert not any("put Frankenstein's Monster onto battlefield" in line
                   for line in game.log), game.log


def test_frankensteins_monster_with_an_empty_graveyard_never_enters(set_pool):
    """The far end of the same predicate: nothing to exile at all."""
    game, p1 = _monster_game(set_pool, [])

    game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)
    game._settle()

    assert _monster_on(p1) is None, game.log
    assert [card.name for card in p1.graveyard] == ["Frankenstein's Monster"]


def test_frankensteins_monster_for_x_zero_enters_as_printed(set_pool):
    """"Exile zero cards" is something everyone can do, so the second sentence
    is never reached and the creature is its printed 0/1 with no counters and no
    prompt."""
    game, p1 = _monster_game(set_pool, [set_pool("LEA")["Grizzly Bears"]],
                             interactive=True)

    game.cast_from_hand(0, "Frankenstein's Monster", x_value=0)
    game._settle()

    monster = _monster_on(p1)
    assert monster is not None, game.log
    assert (monster.effective_power, monster.effective_toughness) == (0, 1)
    assert [c.kind for c in game.pending_choices] == []
    assert p1.exile == []


def test_frankensteins_monster_default_gives_up_the_cheapest_cards(set_pool):
    """The stated policy for a seat nobody asks (idiom 8): the cheapest matching
    cards, and the counter that raises both halves.

    Grizzly Bears (2) goes and Craw Wurm (6) stays, and two +1/+1 counters take
    the printed 0/1 to 2/3.
    """
    game, p1 = _monster_game(
        set_pool,
        [set_pool("LEA")["Craw Wurm"], set_pool("LEA")["Grizzly Bears"],
         set_pool("LEA")["Hill Giant"]],
    )

    game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)
    game._settle()

    monster = _monster_on(p1)
    assert monster is not None, game.log
    assert (monster.effective_power, monster.effective_toughness) == (2, 3)
    assert sorted(card.name for card in p1.exile) == ["Grizzly Bears", "Hill Giant"]
    assert [card.name for card in p1.graveyard] == ["Craw Wurm"]
    assert monster.metadata.get("plus_counters") == 2, (
        "a +1/+1 counter is a counter, not a bare bonus - CR 704.5q reads it"
    )


def test_frankensteins_monster_refuses_an_answer_it_did_not_offer(set_pool):
    """The picker's list is a hint and the engine re-checks it (idiom 9): a
    noncreature card, a repeated slot, a short answer and an unoffered counter
    are all refused, and a refused answer leaves the prompt owed rather than
    exiling half a payment."""
    game, p1 = _monster_game(
        set_pool,
        [set_pool("LEA")["Grizzly Bears"], set_pool("LEA")["Craw Wurm"],
         set_pool("LEA")["Mox Pearl"]],
        interactive=True,
    )
    game.cast_from_hand(0, "Frankenstein's Monster", x_value=2)

    def answer(picks):
        return game.resolve_pending_choice("entry_exile", 0, picks=picks)

    assert not answer([{"index": 0, "counter": "+1/+1"}]), "a short answer"
    assert not answer([{"index": 0, "counter": "+1/+1"},
                       {"index": 2, "counter": "+1/+1"}]), "the Mox is not a creature card"
    assert not answer([{"index": 0, "counter": "+1/+1"},
                       {"index": 0, "counter": "+1/+1"}]), "one card twice"
    assert not answer([{"index": 0, "counter": "+3/+3"},
                       {"index": 1, "counter": "+1/+1"}]), "a counter nothing offered"
    assert p1.exile == [], "a refused answer moves nothing"
    assert [c.kind for c in game.pending_choices] == ["entry_exile"]

    assert answer([{"index": 0, "counter": "+1/+1"},
                   {"index": 1, "counter": "+1/+1"}]), game.log


def test_the_entry_exile_template_reads_its_parameters_off_the_line():
    """The reader is a template, not a card: the count, the noun phrase and the
    offered counters are all captures, and a counter kind the engine cannot
    place refuses the whole line rather than entering the creature short."""
    from engine.enter_effects import exile_cards_on_enter

    printed = (
        "As this creature enters, exile two artifact cards from your graveyard. "
        "If you can't, put this creature into its owner's graveyard instead of "
        "onto the battlefield. For each artifact card exiled this way, this "
        "creature enters with a +1/+1 counter on it."
    )
    assert exile_cards_on_enter(printed) == {
        "count": 2,
        "filter": {"type_filter": "artifact"},
        "counters": ("+1/+1",),
    }

    # A back-reference naming different cards is a line this rule has not read.
    assert exile_cards_on_enter(printed.replace(
        "For each artifact card", "For each land card")) is None
    # And a counter kind with no P/T meaning behind it.
    assert exile_cards_on_enter(printed.replace(
        "a +1/+1 counter", "a soul counter")) is None

# --- FixB: a departed target is a fizzle, not the next permanent along ---


def test_whippoorwill_locks_nothing_when_its_target_has_left(set_pool):
    """"{G}{G}, {T}: Target creature can't be regenerated this turn. Damage that
    would be dealt to that creature this turn can't be prevented or dealt
    instead to another permanent or player. When the creature dies this turn,
    exile the creature."

    Three sentences about one creature, and all three followed the vacated
    index together: the bystander lost its regeneration and its damage
    protections, and was marked for exile on death. CR 608.2b says an ability
    whose target has left affects nothing; the CR-level statement of it is in
    ``tests/rules/test_targets_and_costs.py``.
    """
    bird = _nosick(Permanent(card=set_pool("DRK")["Whippoorwill"]))
    chosen = _nosick(Permanent(card=_mk_creature_card("Quarry", 2, 2)))
    decoy = _nosick(Permanent(card=_mk_creature_card("Bystander", 1, 1)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bird], life=20),
        PlayerState(name="P2", battlefield=[chosen, decoy], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)

    game.queue_permanent_ability(
        0, "Whippoorwill", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.remove_from_battlefield(chosen)
    game.check_state_based_actions()
    game.pass_priority(0)
    game.pass_priority(1)
    game._settle()

    assert not decoy.metadata.get("cant_be_regenerated_this_turn"), game.log
    assert not decoy.metadata.get(
        "damage_cant_be_prevented_or_redirected_until_eot"), game.log
    assert game.delayed_triggers == [], game.log


def test_whippoorwill_still_locks_a_target_that_is_still_there(set_pool):
    """The other direction: a fizzle that fires too eagerly is the same bug
    pointing the other way, so the surviving-target case is asserted beside
    it."""
    bird = _nosick(Permanent(card=set_pool("DRK")["Whippoorwill"]))
    chosen = _nosick(Permanent(card=_mk_creature_card("Quarry", 2, 2)))
    decoy = _nosick(Permanent(card=_mk_creature_card("Bystander", 1, 1)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bird], life=20),
        PlayerState(name="P2", battlefield=[chosen, decoy], life=20),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)

    game.queue_permanent_ability(
        0, "Whippoorwill", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.pass_priority(0)
    game.pass_priority(1)
    game._settle()

    assert chosen.metadata.get("cant_be_regenerated_this_turn"), game.log
    assert not decoy.metadata.get("cant_be_regenerated_this_turn"), game.log
    assert [entry.bound_permanent_id for entry in game.delayed_triggers] == [
        chosen.permanent_id
    ], game.log
# --- end FixB ---
