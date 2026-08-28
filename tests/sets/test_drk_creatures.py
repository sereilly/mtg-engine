"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt, _mk_creature_card, _nosick


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
