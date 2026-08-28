"""Per-card tests for The Dark's artifacts.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.shields import PREVENT_HALF, shields_of_kind
from engine.models import CardDefinition, Permanent
from tests.helpers import _mk_creature_card, _nosick
from engine.oracle import compile_card_oracle


# --- G1: damage family (The Dark) ---


def _dark_sphere(set_pool):
    sphere = Permanent(card=set_pool("DRK")["Dark Sphere"])
    sphere.summoning_sick = False
    burner = Permanent(card=set_pool("LEA")["Rod of Ruin"])
    burner.summoning_sick = False
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [sphere]
    players[1].battlefield = [burner]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._sync_control()
    return game, players, sphere, burner


def test_dark_sphere_arms_a_half_shield_against_the_chosen_source(set_pool):
    game, players, sphere, burner = _dark_sphere(set_pool)

    result = game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    assert result.supported, result.details
    shields = shields_of_kind(players[0], PREVENT_HALF)
    assert len(shields) == 1 and shields[0].half == "down", game.log


def test_dark_sphere_prevents_half_the_damage_rounded_down(set_pool):
    """"prevent half that damage, **rounded down**": 7 damage becomes 4, not 3.
    The share is computed when the event exists, because half of an event
    nobody has sized yet is not a number."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 7, source=burner)

    assert players[0].life == 16, game.log


def test_dark_sphere_is_spent_on_the_first_event_it_answers(set_pool):
    """"The **next time** a source … would deal damage": one instance, and the
    second event is unshielded."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 4, source=burner)
    game._deal_damage_to_player(players[0], 4, source=burner)

    assert players[0].life == 14, game.log
    assert shields_of_kind(players[0], PREVENT_HALF) == []


def test_dark_sphere_ignores_damage_from_a_source_it_did_not_choose(set_pool):
    """"a source of your choice" is a property the shield records and CR 615.9
    rechecks. A shield that answered every source is a strictly larger card.

    Two *different* cards, deliberately: the chosen-source matcher the shield
    path uses compares by ``CardDefinition`` as well as by identity, so a second
    printing of the same card is matched as though it were the chosen one. That
    is the look-alike bug ``damage_redirects.source_matches`` was written to
    avoid, still live on the prevention side — see this branch's report.
    """
    game, players, sphere, burner = _dark_sphere(set_pool)
    other = Permanent(card=set_pool("LEA")["Wall of Fire"])
    players[1].battlefield.append(other)
    game._sync_control()
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 4, source=other)

    assert players[0].life == 16, game.log
    assert len(shields_of_kind(players[0], PREVENT_HALF)) == 1


def test_a_one_point_event_leaves_the_half_shield_armed(set_pool):
    """Half of 1, rounded down, is 0 — and a shield that would prevent nothing
    does not apply, the same reading Forcefield's cap is given."""
    game, players, sphere, burner = _dark_sphere(set_pool)
    game.activate_permanent_ability(
        0, "Dark Sphere", target_permanent_ids=[burner.permanent_id]
    )

    game._deal_damage_to_player(players[0], 1, source=burner)

    assert players[0].life == 19, game.log
    assert len(shields_of_kind(players[0], PREVENT_HALF)) == 1

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


def test_living_armor_gives_counters_equal_to_the_targets_mana_value(set_pool):
    """"Put **X** +0/+1 counters on target creature, where X is **that
    creature's** mana value."

    The where-clause's referent is spelled out as a possessive rather than as
    "its", and it means the same thing - one production for both word orders,
    so which characteristics a card may name does not depend on how it was
    printed.
    """
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            _nosick(Permanent(card=pool["Living Armor"])),
            Permanent(card=pool["Necropolis"]),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    wall = p1.battlefield[1]
    printed = wall.effective_toughness
    mana_value = int(pool["Necropolis"].cmc)
    assert mana_value > 1, "the fixture needs a target worth more than one counter"

    result = game.activate_permanent_ability(
        0, "Living Armor", permanent_index=0,
        target_player_index=0, target_permanent_ids=[wall.permanent_id],
    )

    assert result.supported, result.details
    assert wall.effective_toughness == printed + mana_value, game.log
    assert wall.effective_power == 0, "+0/+1 adds no power"
    assert "Living Armor" not in {
        perm.card.name for perm in p1.battlefield
    }, "the sacrifice is part of the cost"


def test_fellwar_stone_copies_a_color_an_opponents_land_makes(set_pool):
    """"Add one mana of any color **that a land an opponent controls could
    produce**." The restriction is read off the opponents' board through the
    control seam, not off the Stone."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1", battlefield=[_nosick(Permanent(card=pool["Fellwar Stone"]))],
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=_basic("Swamp", "Swamp", "B"))])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)

    assert result.supported, result.details
    assert p1.mana_pool["B"] == 1, (dict(p1.mana_pool), game.log)
    assert sum(p1.mana_pool.values()) == 1


def test_fellwar_stone_makes_nothing_when_no_opponent_land_makes_color(set_pool):
    """The control: with the set empty there is no colour to copy, so the
    ability produces nothing rather than defaulting to green."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1", battlefield=[_nosick(Permanent(card=pool["Fellwar Stone"]))],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    game.activate_permanent_ability(0, "Fellwar Stone", permanent_index=0)

    assert sum(p1.mana_pool.values()) == 0, (dict(p1.mana_pool), game.log)

# --- G4: combat, prevention, control (The Dark) ---


def _board(set_pool, artifact_name: str, *others: Permanent):
    artifact = Permanent(card=set_pool("DRK")[artifact_name])
    p1 = PlayerState(name="P1", battlefield=[artifact])
    p2 = PlayerState(name="P2", battlefield=list(others))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, artifact


def test_barls_cage_holds_a_creature_down_for_one_untap_step(set_pool):
    """"{3}: Target creature doesn't untap during its controller's next untap
    step." A one-shot marker, not the standing restriction
    ``engine/untap_restrictions.py`` holds — and one step only, so the creature
    untaps on the turn after."""
    victim = Permanent(card=_mk_creature_card("Victim", 2, 2))
    victim.tapped = True
    game, _cage = _board(set_pool, "Barl's Cage", victim)

    result = game.activate_permanent_ability(
        0, "Barl's Cage", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert victim.metadata.get("skip_next_untap") == 1

    game.start_turn(1)
    assert victim.tapped is True, "it was held down for its controller's untap step"

    game.start_turn(0)
    game.start_turn(1)
    assert victim.tapped is False, "and only for one of them"


def test_barls_cage_needs_a_creature(set_pool):
    """The printed noun is enforced at resolution: an explicitly chosen
    non-creature fizzles rather than sliding onto whatever else is legal."""
    rock = Permanent(card=_mk_creature_card("Rock", 0, 0))
    rock.card = rock.card.__class__(
        **{**rock.card.__dict__, "type_line": "Artifact", "power": None, "toughness": None}
    )
    rock.tapped = True
    game, _cage = _board(set_pool, "Barl's Cage", rock)

    game.activate_permanent_ability(
        0, "Barl's Cage", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert "skip_next_untap" not in rock.metadata


def test_tower_of_coireall_stops_only_the_named_blockers(set_pool):
    """"{T}: Target creature can't be blocked by Walls this turn."

    The blocker class is payload, tested by the declare-blockers step through
    the same ``subject_matches`` the printed static restrictions go through —
    so a Wall may not block and anything else still may.
    """
    attacker = _nosick(Permanent(card=_mk_creature_card("Attacker", 2, 2)))
    wall = Permanent(card=_mk_creature_card("Stone Wall", 0, 4))
    wall.card = wall.card.__class__(
        **{**wall.card.__dict__, "type_line": "Creature — Wall"}
    )
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))

    tower = Permanent(card=set_pool("DRK")["Tower of Coireall"])
    p1 = PlayerState(name="P1", battlefield=[tower, attacker])
    p2 = PlayerState(name="P2", battlefield=[wall, bear])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Tower of Coireall", target_player_index=0, target_permanent_index=1
    )
    game._settle()
    assert result.supported

    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()  # declare blockers

    assert not game.declare_blockers(1, {0: 1})[0], "a Wall can't block it"
    assert game.declare_blockers(1, {1: 1})[0], "anything else still can"


def test_tower_of_coireall_carries_the_printed_noun(set_pool):
    """The restriction is the noun phrase, not the word "Wall" baked into a
    kind — a card printed with another subtype is the same instruction."""
    program = compile_card_oracle(set_pool("DRK")["Tower of Coireall"])
    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "grant_cant_be_blocked_by_until_eot"
    assert ability.instruction.payload["blocker_filter"] == {
        "type_filter": "creature",
        "subtype_filter": "wall",
    }


# --- H3: delayed triggers (The Dark) ---


def _war_barge_board(set_pool):
    """War Barge and an opposing creature, on a board that can activate it."""
    barge = _nosick(Permanent(card=set_pool("DRK")["War Barge"]))
    sailor = _nosick(Permanent(card=_mk_creature_card("Sailor", 2, 2)))
    p1 = PlayerState(name="P1", battlefield=[barge])
    p2 = PlayerState(name="P2", battlefield=[sailor])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, barge, sailor


def test_war_barge_grants_islandwalk_to_the_creature_it_targets(set_pool):
    """"{3}: Target creature gains islandwalk until end of turn." The first of
    the two halves, and the one that says which creature the delayed ability
    behind it is about."""
    game, _p1, _p2, _barge, sailor = _war_barge_board(set_pool)

    result = game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[sailor.permanent_id]
    )
    game._settle()

    assert result.supported, result.details
    assert game._has_keyword(sailor, "islandwalk"), game.log


def test_war_barge_destroys_its_target_when_the_barge_itself_leaves(set_pool):
    """"When this artifact leaves the battlefield this turn, destroy that
    creature."

    The mirror of Sandals of Abdallah, which watches the creature and destroys
    the artifact. Here the artifact is what the delay *watches* and the
    targeted creature is what the ability is *about* — two objects, so the
    entry carries two ids.
    """
    game, _p1, p2, barge, sailor = _war_barge_board(set_pool)
    game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[sailor.permanent_id]
    )
    game._settle()

    game.remove_from_battlefield(barge)
    game._settle()

    assert not any(p is sailor for p in p2.battlefield), game.log
    assert "Sailor" in p2.graveyard[-1].name, game.log


def test_war_barge_leaving_spares_a_creature_it_never_targeted(set_pool):
    """The entry watches the artifact and is *about* the creature it named. A
    second creature is neither, and a delayed ability bound to the wrong object
    is silent — so the check is that the bystander is still there."""
    game, _p1, p2, barge, sailor = _war_barge_board(set_pool)
    bystander = _nosick(Permanent(card=_mk_creature_card("Bystander", 1, 1)))
    p2.battlefield.append(bystander)
    game._sync_control()
    game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[sailor.permanent_id]
    )
    game._settle()

    game.remove_from_battlefield(barge)
    game._settle()

    assert any(p is bystander for p in p2.battlefield), game.log


def test_war_barge_denies_regeneration_to_what_it_destroys(set_pool):
    """"A creature destroyed this way can't be regenerated." (CR 701.19c.)

    The rider is printed as a sentence about the effect rather than about a
    pronoun, because the destruction it qualifies was arranged a sentence
    earlier inside the delayed ability — but it is the same ``no_regen`` the
    "It can't be regenerated" spelling sets.
    """
    game, _p1, p2, barge, sailor = _war_barge_board(set_pool)
    game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[sailor.permanent_id]
    )
    game._settle()
    sailor.regeneration_shield = 1

    game.remove_from_battlefield(barge)
    game._settle()

    assert not any(p is sailor for p in p2.battlefield), game.log


def test_war_barge_delay_expires_with_the_turn(set_pool):
    """"…leaves the battlefield **this turn**" is CR 603.7b's stated duration.
    Dropping those two words would make the boat's target answerable to a
    destruction on a later turn."""
    game, _p1, p2, barge, sailor = _war_barge_board(set_pool)
    game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[sailor.permanent_id]
    )
    game._settle()

    game.resolve_cleanup_step(0)
    game.start_turn(1)
    game.remove_from_battlefield(barge)
    game._settle()

    assert any(p is sailor for p in p2.battlefield), game.log


def _runesword_board(set_pool):
    """Runesword, an attacking creature of its controller's, and a victim."""
    sword = _nosick(Permanent(card=set_pool("DRK")["Runesword"]))
    attacker = _nosick(Permanent(card=_mk_creature_card("Raider", 2, 2)))
    attacker.attacking = True
    victim = _nosick(Permanent(card=_mk_creature_card("Victim", 1, 5)))
    p1 = PlayerState(name="P1", battlefield=[sword, attacker])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, sword, attacker, victim


def _activate_runesword(game, attacker):
    result = game.activate_permanent_ability(
        0, "Runesword",
        target_player_index=0, target_permanent_ids=[attacker.permanent_id],
    )
    game._settle()
    assert result.supported, result.details
    return result


def test_runesword_pumps_the_attacking_creature_it_targets(set_pool):
    """"{3}, {T}: Target attacking creature gets +2/+0 until end of turn." —
    the first of four sentences, and the one the other three refer back to."""
    game, _p1, _p2, _sword, attacker, _victim = _runesword_board(set_pool)

    _activate_runesword(game, attacker)

    assert attacker.effective_power == 4, game.log


def test_runesword_is_sacrificed_when_its_creature_leaves(set_pool):
    """"When that creature leaves the battlefield this turn, sacrifice this
    artifact." CR 603.6c's wider event about the bound object — a bounce is
    this and is not a death, which is why it is not the dies row."""
    game, p1, _p2, sword, attacker, _victim = _runesword_board(set_pool)
    _activate_runesword(game, attacker)

    game.remove_from_battlefield(attacker)
    game._settle()

    assert not any(p is sword for p in p1.battlefield), game.log


def test_runesword_denies_regeneration_to_what_its_creature_damages(set_pool):
    """"If the creature deals damage to a creature this turn, the creature
    dealt damage can't be regenerated this turn."

    The marker rides the *damager* and is read at the damage seam, so what the
    creature hits carries the rider however the damage was dealt.
    """
    game, _p1, _p2, _sword, attacker, victim = _runesword_board(set_pool)
    _activate_runesword(game, attacker)

    game._mark_damage_on_permanent(victim, 1, attacker)

    assert victim.metadata.get("cant_be_regenerated_this_turn"), game.log


def test_runesword_exiles_a_creature_its_creature_kills(set_pool):
    """"If a creature dealt damage by the targeted creature would die this
    turn, exile that creature instead." (CR 614.)

    Written as a delayed *trigger* the exile would never happen: a trigger
    resolves after state-based actions have already put the creature in a
    graveyard. So the check is the graveyard — nothing there, and the card in
    exile.
    """
    game, _p1, p2, _sword, attacker, victim = _runesword_board(set_pool)
    _activate_runesword(game, attacker)

    game._mark_damage_on_permanent(victim, 5, attacker)
    game.check_state_based_actions()
    game._settle()

    assert not any(p is victim for p in p2.battlefield), game.log
    assert not any(card.name == "Victim" for card in p2.graveyard), game.log
    assert any(card.name == "Victim" for card in p2.exile), game.log


def test_runesword_riders_reach_only_the_creature_it_targeted(set_pool):
    """The markers are on the creature the ability named. Damage from anything
    else this turn carries neither rider — a marker on the wrong object is
    silent, so the check is that an untouched damager leaves no trace."""
    game, p1, _p2, _sword, attacker, victim = _runesword_board(set_pool)
    other = _nosick(Permanent(card=_mk_creature_card("Bystander", 2, 2)))
    p1.battlefield.append(other)
    game._sync_control()
    _activate_runesword(game, attacker)

    game._mark_damage_on_permanent(victim, 1, other)

    assert not victim.metadata.get("cant_be_regenerated_this_turn"), game.log
    assert not victim.metadata.get("exile_if_dies_this_turn"), game.log


def _wand_of_ith_board(set_pool, held):
    """Wand of Ith, untapped, and an opponent holding exactly *held*."""
    wand = _nosick(Permanent(card=set_pool("DRK")["Wand of Ith"]))
    p1 = PlayerState(name="P1", battlefield=[wand])
    p2 = PlayerState(name="P2", hand=list(held))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, wand


def test_wand_of_ith_reveals_one_card_from_the_targeted_hand(set_pool):
    """"{3}, {T}: Target player reveals a card at random from their hand."

    One card, not the hand: the sentences behind it ask what "it" is, and a
    hand reveal leaves no "it".
    """
    swamp = set_pool("LEA")["Swamp"]
    game, _p1, p2, _wand = _wand_of_ith_board(set_pool, [swamp])

    result = game.activate_permanent_ability(0, "Wand of Ith", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert any("reveals Swamp at random" in line for line in game.log), game.log


def test_wand_of_ith_offers_one_life_for_a_revealed_land(set_pool):
    """"If it's a land card, that player discards it unless they pay 1 life."

    The offer goes to the *targeted* seat, and the payment is charged to that
    seat rather than to the wand's controller.
    """
    swamp = set_pool("LEA")["Swamp"]
    game, _p1, p2, _wand = _wand_of_ith_board(set_pool, [swamp])
    game.activate_permanent_ability(0, "Wand of Ith", target_player_index=1)
    game._settle()

    owed = [c for c in game.pending_choices if c.player_index == 1]
    assert owed, game.log
    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    assert p2.life == 19, game.log
    assert [card.name for card in p2.hand] == ["Swamp"], game.log


def test_wand_of_ith_discards_the_land_when_the_life_is_not_paid(set_pool):
    """Declining is the printed default consequence: the card is discarded."""
    swamp = set_pool("LEA")["Swamp"]
    game, _p1, p2, _wand = _wand_of_ith_board(set_pool, [swamp])
    game.activate_permanent_ability(0, "Wand of Ith", target_player_index=1)
    game._settle()

    assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert p2.hand == [], game.log
    assert [card.name for card in p2.graveyard] == ["Swamp"], game.log
    assert p2.life == 20, game.log


def test_wand_of_ith_charges_a_nonland_its_mana_value(set_pool):
    """"If it isn't a land card, the player discards it unless they pay life
    equal to its mana value."

    The number is not printed — it is read off the card the reveal named, and
    the negated condition is the same test as the land branch read the other
    way.
    """
    counterspell = set_pool("LEA")["Counterspell"]
    game, _p1, p2, _wand = _wand_of_ith_board(set_pool, [counterspell])
    game.activate_permanent_ability(0, "Wand of Ith", target_player_index=1)
    game._settle()

    assert game.confirm_optional_pay(1, accept=True)
    game._settle()

    # Counterspell's mana value is 2 — not the 1 the land branch charges, which
    # is what separates the two sentences.
    assert p2.life == 18, game.log
    assert [card.name for card in p2.hand] == ["Counterspell"], game.log
