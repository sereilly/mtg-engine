"""Odyssey creatures, W2G7: Bomb Squad.

    {T}: Put a fuse counter on target creature.
    At the beginning of your upkeep, put a fuse counter on each creature with a
    fuse counter on it.
    Whenever a creature has four or more fuse counters on it, remove all fuse
    counters from it and destroy it. That creature deals 4 damage to its
    controller.

Declined by wave 1 on its third line, a CR 603.8 **state trigger about another
permanent**. What landed is general, and every piece is asked of an invented
card at the foot of this file:

* the condition "whenever <noun phrase> has N or more K counters on it"
  (``permanent_counters_reach_threshold``), announced once per watched
  permanent by ``engine/state_triggers.announce_watched_counter_thresholds``;
* "remove all K counters from **it**" over the event's object;
* "**that creature** deals N damage to **its controller**" — the event's
  object as the *dealer*, as it exists or as it last existed (CR 608.2h), and
  its controller read as the damage is dealt rather than frozen when the
  ability triggered.

Scryfall's two rulings for the card (2004-10-04), both pinned below:

    If the creature regenerates, the fuse counters are still removed and the
    four damage is still dealt.

    If there are two Bomb Squads on the battlefield when a creature ends up
    with 4 or more fuse counters, both Bomb Squad abilities will trigger
    causing 4 damage each even though the first to resolve will destroy the
    creature.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import CardDefinition, Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

STATE_LINE = "Whenever a creature has four or more fuse counters on it"


def _table(set_pool):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("Sapper", library=[lea["Mountain"]] * 12),
        PlayerState("Victim", library=[lea["Mountain"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _invented(name, text, *, type_line="Creature — Probe", keywords=(), colors=()):
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="2", toughness="2")
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=tuple(keywords), produced_mana=(), raw=raw,
    )


def _lit(set_pool, *, seat=1, card=None, counters=4, squads=1):
    """A board with *squads* Bomb Squads (seat 0) and one creature holding
    *counters* fuse counters, swept once: the state trigger is on the stack."""
    game = _table(set_pool)
    squad = [_put(game, 0, set_pool("ODY")["Bomb Squad"]) for _ in range(squads)]
    victim = _put(game, seat, card or set_pool("LEA")["Grizzly Bears"])
    add_counters(victim, "fuse", counters)
    game.check_state_based_actions()
    return game, squad, victim


def _state_triggers(game):
    return [
        item for item in game.stack
        if (item.ability_text or "").startswith(STATE_LINE)
    ]


def _bury(game, permanent):
    owner = game.players[game.owner_index_of(permanent)]
    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(owner, permanent)


# -- the three lines ---------------------------------------------------------


def test_bomb_squad_compiles_every_line(set_pool):
    program = compile_card_oracle(set_pool("ODY")["Bomb Squad"])
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert ability.supported and ability.instruction is not None
    upkeep, state = program.triggered_abilities
    assert upkeep.condition.kind == "upkeep_self" and upkeep.instruction is not None
    assert state.condition.kind == "permanent_counters_reach_threshold"
    assert state.condition.payload == {
        "counter_count": 4, "counter_kind": "fuse",
        "countered_filter": {"type_filter": "creature"},
    }
    assert state.supported and state.instruction is not None


def test_the_fuse_is_lit_on_a_creature_and_on_nothing_else(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool)
    squad = _put(game, 0, set_pool("ODY")["Bomb Squad"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    forest = _put(game, 1, lea["Forest"])

    refused = game.activate_permanent_ability(
        0, "Bomb Squad", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert not squad.tapped and counters_on(forest, "fuse") == 0

    lit = game.activate_permanent_ability(
        0, "Bomb Squad", target_permanent_ids=[bears.permanent_id]
    )
    assert lit.supported, lit.details
    resolve_stack(game)
    assert squad.tapped
    assert counters_on(bears, "fuse") == 1


def test_the_fuse_burns_down_on_its_controllers_upkeep_only(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, set_pool("ODY")["Bomb Squad"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    unlit = _put(game, 1, lea["Hill Giant"])
    add_counters(bears, "fuse", 1)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    resolve_stack(game)
    assert counters_on(bears, "fuse") == 1  # not its controller's upkeep

    game.active_player_index = 0
    game.resolve_upkeep(0)
    resolve_stack(game)
    assert counters_on(bears, "fuse") == 2
    assert counters_on(unlit, "fuse") == 0  # no fuse, nothing to burn


def test_it_goes_off_as_an_object_of_its_own_between_priority_passes(set_pool):
    """The table's road: the upkeep trigger resolves, state-based actions see
    four counters, and the state trigger is a new stack object both players
    may respond to before anything is destroyed."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, set_pool("ODY")["Bomb Squad"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    add_counters(bears, "fuse", 3)

    game.resolve_upkeep(0, defer_priority=True)
    assert len(game.stack) == 1 and not _state_triggers(game)
    game.pass_priority(0)
    assert game.pass_priority(1) == "resolved_top"

    assert counters_on(bears, "fuse") == 4
    assert len(_state_triggers(game)) == 1
    assert bears in game.controlled_by(1)  # still there, and it can be answered
    assert game.priority_player_index == 0

    game.pass_priority(0)
    assert game.pass_priority(1) == "resolved_top"
    assert bears not in game.controlled_by(1)
    assert game.players[1].graveyard[-1].name == "Grizzly Bears"
    assert [player.life for player in game.players] == [20, 16]
    # The creature dealt it, not Bomb Squad (CR 120.7).
    assert "Grizzly Bears dealt 4 damage to Victim" in game.log
    assert not game.stack


def test_a_board_that_has_not_changed_is_announced_once(set_pool):
    game, _squad, _bears = _lit(set_pool)
    for _ in range(3):
        game.check_state_based_actions()
    assert len(_state_triggers(game)) == 1


def test_five_counters_is_four_or_more_and_takes_them_all_off(set_pool):
    game, _squad, bears = _lit(set_pool, counters=6)
    bears.regeneration_shield = 1
    resolve_stack(game)
    assert counters_on(bears, "fuse") == 0
    assert game.players[1].life == 16


# -- the rulings -------------------------------------------------------------


def test_a_regenerated_creature_still_loses_its_counters_and_deals_the_four(set_pool):
    """Ruling 2004-10-04. And the order is what ends it: the counters come off
    before the destruction is replaced, so the state is no longer true and
    nothing triggers again."""
    game, _squad, bears = _lit(set_pool)
    bears.regeneration_shield = 1

    resolve_stack(game)

    assert bears in game.controlled_by(1) and bears.tapped
    assert counters_on(bears, "fuse") == 0
    assert game.players[1].life == 16
    game.check_state_based_actions()
    assert not game.stack


def test_two_bomb_squads_deal_four_each_though_the_first_destroys_it(set_pool):
    """Ruling 2004-10-04. The second trigger finds no creature to defuse or
    destroy, and the creature *as it last existed* still deals 4 to the player
    who last controlled it (CR 608.2h)."""
    game, _squads, bears = _lit(set_pool, squads=2)
    assert len(_state_triggers(game)) == 2

    resolve_stack(game)

    assert bears not in game.controlled_by(1)
    assert game.players[1].life == 12
    assert game.log.count("Grizzly Bears dealt 4 damage to Victim") == 2
    assert game.players[1].graveyard.count(bears.card) == 1


# -- what can happen in response --------------------------------------------


def test_a_creature_gone_in_response_still_deals_the_four(set_pool):
    game, _squad, bears = _lit(set_pool)
    _bury(game, bears)

    resolve_stack(game)

    assert game.players[1].life == 16
    assert "Grizzly Bears dealt 4 damage to Victim" in game.log


def test_an_indestructible_creature_is_defused_and_deals_the_four(set_pool):
    wall = _invented("W2G7 Bunker", "Indestructible", keywords=("Indestructible",))
    game, _squad, bunker = _lit(set_pool, card=wall)

    resolve_stack(game)

    assert bunker in game.controlled_by(1)
    assert counters_on(bunker, "fuse") == 0
    assert game.players[1].life == 16
    game.check_state_based_actions()
    assert not game.stack


def test_its_controller_is_whoever_controls_it_as_the_ability_resolves(set_pool):
    """Not the seat that controlled it when the ability triggered: the creature
    is still on the battlefield while the trigger waits (CR 608.2h reads an
    object in its expected zone as it is *now*)."""
    game, _squad, bears = _lit(set_pool)
    change_control(bears, 0, source="w2g7-theft")
    game._sync_control()

    resolve_stack(game)

    assert [player.life for player in game.players] == [16, 20]
    # Destroyed all the same, and into its owner's graveyard (CR 400.3).
    assert game.players[1].graveyard[-1].name == "Grizzly Bears"


def test_a_stolen_creature_that_then_left_burns_the_player_who_last_had_it(set_pool):
    """The last-known controller is the thief, not the seat the creature
    entered under — the one fact about a departed permanent that is not on the
    object, stamped by the one removal transition."""
    game, _squad, bears = _lit(set_pool)
    change_control(bears, 0, source="w2g7-theft")
    game._sync_control()
    _bury(game, bears)
    assert game.controller_index_of(bears) is None
    assert game.controller_or_last_known(bears) == 0

    resolve_stack(game)

    assert [player.life for player in game.players] == [16, 20]


def test_bomb_squad_gone_in_response_changes_nothing(set_pool):
    """CR 113.7a: an ability on the stack exists independently of its source."""
    game, (squad,), bears = _lit(set_pool)
    _bury(game, squad)

    resolve_stack(game)

    assert bears not in game.controlled_by(1)
    assert game.players[1].life == 16


def test_bomb_squad_can_light_its_own_fuse(set_pool):
    game = _table(set_pool)
    squad = _put(game, 0, set_pool("ODY")["Bomb Squad"])
    add_counters(squad, "fuse", 4)
    game.check_state_based_actions()

    resolve_stack(game)

    assert squad not in game.controlled_by(0)
    assert [player.life for player in game.players] == [16, 20]


def test_the_damage_is_the_creatures_own(set_pool):
    """CR 120.7 and CR 702.15b: a lifelink creature that deals 4 damage to its
    own controller gains that controller 4 life — which only happens if the
    damage's source is the creature and not Bomb Squad. It has left the
    battlefield by then, so this is the creature as it last existed."""
    linker = _invented(
        "W2G7 Chorister", "Lifelink", keywords=("Lifelink",), colors=("W",),
    )
    game, _squad, chorister = _lit(set_pool, card=linker)

    resolve_stack(game)

    assert chorister not in game.controlled_by(1)
    assert game.players[1].life == 20
    assert any("gained 4 life from lifelink" in line for line in game.log)


def test_a_stolen_lifelinker_is_the_thiefs_source_when_it_deals_the_four(set_pool):
    """One seat for every reader of the dealer's controller. The creature is
    destroyed while the thief controls it, so the 4 is dealt to the thief —
    and the lifelink is the thief's too, not the seat the creature entered
    under, which is who gained before the departed source's seat was read off
    the same stamp."""
    linker = _invented(
        "W2G7 Chorister", "Lifelink", keywords=("Lifelink",), colors=("W",),
    )
    game, _squad, chorister = _lit(set_pool, card=linker)
    change_control(chorister, 0, source="w2g7-theft")
    game._sync_control()

    resolve_stack(game)

    assert "W2G7 Chorister dealt 4 damage to Sapper" in game.log
    assert any("Sapper gained 4 life from lifelink" in line for line in game.log)
    assert [player.life for player in game.players] == [20, 20]


def test_a_departed_sources_seat_is_the_seat_that_last_controlled_it(set_pool):
    """``damage_source_seat`` — "a source **you** control" — for a permanent
    that has left: the seat that controlled it as it left (CR 608.2h), which
    differs from the seat it entered under exactly when it had been stolen."""
    from engine.damage_events import damage_source_seat

    lea = set_pool("LEA")
    game = _table(set_pool)
    stolen = _put(game, 1, lea["Grizzly Bears"])
    assert damage_source_seat(game, stolen) == 1
    change_control(stolen, 0, source="w2g7-theft")
    game._sync_control()
    assert damage_source_seat(game, stolen) == 0
    _bury(game, stolen)
    assert damage_source_seat(game, stolen) == 0

    kept = _put(game, 1, lea["Grizzly Bears"])
    _bury(game, kept)
    assert damage_source_seat(game, kept) == 1


def test_a_countered_trigger_triggers_again_while_the_state_holds(set_pool):
    """CR 603.8: "doesn't trigger again until the ability has resolved, has
    been countered, or has otherwise left the stack. Then, if … the game state
    still matches its trigger condition, the ability will trigger again.\""""
    game, _squad, bears = _lit(set_pool)
    (first,) = _state_triggers(game)

    game.counter_stack_object(first)
    assert not game.stack and counters_on(bears, "fuse") == 4
    game.check_state_based_actions()

    (again,) = _state_triggers(game)
    assert again is not first
    resolve_stack(game)
    assert bears not in game.controlled_by(1) and game.players[1].life == 16


def test_only_creatures_are_watched_and_each_is_its_own_trigger(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, set_pool("ODY")["Bomb Squad"])
    ring = _put(game, 1, lea["Sol Ring"])
    theirs = _put(game, 1, lea["Grizzly Bears"])
    mine = _put(game, 0, lea["Hill Giant"])
    cold = _put(game, 1, lea["Hill Giant"])
    for permanent, counters in ((ring, 6), (theirs, 4), (mine, 5), (cold, 3)):
        add_counters(permanent, "fuse", counters)

    game.check_state_based_actions()
    assert len(_state_triggers(game)) == 2
    resolve_stack(game)

    assert ring in game.controlled_by(1) and counters_on(ring, "fuse") == 6
    assert cold in game.controlled_by(1) and counters_on(cold, "fuse") == 3
    assert theirs not in game.controlled_by(1) and mine not in game.controlled_by(0)
    assert [player.life for player in game.players] == [16, 16]


# -- the sentences, on cards nobody printed ---------------------------------


def test_an_invented_threshold_destroys_what_it_watches(set_pool):
    """The brief's own sentence: another number, another counter, no damage."""
    lea = set_pool("LEA")
    blight = _invented(
        "W2G7 Blight",
        "Whenever a creature has three or more spore counters on it, destroy it.",
        type_line="Enchantment",
    )
    assert compile_card_oracle(blight).supported
    game = _table(set_pool)
    _put(game, 0, blight)
    bears = _put(game, 1, lea["Grizzly Bears"])
    giant = _put(game, 1, lea["Hill Giant"])
    add_counters(bears, "spore", 3)
    add_counters(giant, "spore", 2)
    add_counters(giant, "fuse", 9)  # another kind of counter is not this state

    game.check_state_based_actions()
    resolve_stack(game)

    assert bears not in game.controlled_by(1)
    assert giant in game.controlled_by(1)
    assert [player.life for player in game.players] == [20, 20]


def test_the_noun_phrase_narrows_what_is_watched(set_pool):
    """"An artifact **you control**": the observer is the watcher's controller
    (CR 109.5), under the other trigger word and a printed digit."""
    lea = set_pool("LEA")
    overload = _invented(
        "W2G7 Overload",
        "When an artifact you control has 2 or more charge counters on it, "
        "destroy it.",
        type_line="Enchantment",
    )
    program = compile_card_oracle(overload)
    assert program.supported, program.reason
    assert program.triggered_abilities[0].condition.payload == {
        "counter_count": 2, "counter_kind": "charge",
        "countered_filter": {"type_filter": "artifact", "controller": "you"},
    }
    game = _table(set_pool)
    _put(game, 0, overload)
    mine = _put(game, 0, lea["Sol Ring"])
    theirs = _put(game, 1, lea["Sol Ring"])
    bears = _put(game, 0, lea["Grizzly Bears"])
    for permanent in (mine, theirs, bears):
        add_counters(permanent, "charge", 2)

    game.check_state_based_actions()
    resolve_stack(game)

    assert mine not in game.controlled_by(0)
    assert theirs in game.controlled_by(1) and bears in game.controlled_by(0)


def test_that_creatures_controller_is_a_seat_the_event_recorded(set_pool):
    """Another family's reading of the same event: "that creature's controller
    loses 2 life" has no dealer to ask, so it reads the seat the sweep stamped
    — never the resolution's target slot, which for a trigger that targets
    nothing is whatever the context was carrying."""
    lea = set_pool("LEA")
    dread = _invented(
        "W2G7 Dread",
        "Whenever a creature has two or more doom counters on it, that "
        "creature's controller loses 2 life.",
        type_line="Enchantment",
    )
    assert compile_card_oracle(dread).supported
    for seat in (0, 1):
        game = _table(set_pool)
        _put(game, 0, dread)
        add_counters(_put(game, seat, lea["Grizzly Bears"]), "doom", 2)
        game.check_state_based_actions()
        resolve_stack(game)
        assert game.players[seat].life == 18 and game.players[1 - seat].life == 20


def test_a_counted_removal_from_the_events_object_refuses():
    """Nothing decrements the event's object, and lowering a printed count
    onto the emptying handler would take every counter off."""
    from engine.grammar import compile_line

    result = compile_line(
        "Whenever a creature has four or more fuse counters on it, remove a "
        "fuse counter from it.",
        card_name="W2G7 Probe",
    )
    assert not result.parse_error, result.parse_error
    assert "takes every counter" in (result.lowering_error or "")
