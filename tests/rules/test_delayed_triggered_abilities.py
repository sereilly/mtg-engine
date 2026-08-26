"""Tests for Comprehensive Rules 603.7 — delayed triggered abilities.

An effect creates the ability as it resolves; the ability triggers later, or
never. It belongs to no permanent, so nothing that scans the battlefield can
find it — ``engine/delayed_triggers.py`` is where it waits and the fire sites
are what announce it.

The engine-side guard that every armed event *has* a fire site lives in
``tests/engine/test_delayed_triggers.py``; what is here is the behaviour the
rule describes, run in a game.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.damage_events import deal_damage
from engine.delayed_triggers import DelayedTrigger, fire_delayed_triggers
from engine.models import CardDefinition, Permanent
from engine.oracle_types import OracleInstruction


def _leg():
    return {
        card.name: card
        for card in load_cards([manifest_set_path("LEG", include_measured=True)])
    }


def _creature(name: str, power: int = 2, toughness: int = 2,
              type_line: str = "Creature - Bear") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _destroy(game: Game, permanent: Permanent) -> None:
    """Destroy one permanent through the sweep every destruction uses, so the
    death reaches the transition the delayed fire site sits on."""
    seat = game.controller_index_of(permanent)
    game._destroy_swept_permanents(
        game.players[seat], lambda perm: perm is permanent
    )


#: A stand-in for the spell that created the ability. CR 603.7d makes that
#: spell the ability's source, so an entry without one is not a delayed
#: triggered ability at all — the stack has nothing to put there.
_SOURCE = CardDefinition(
    name="Creating Spell", mana_cost="", cmc=0.0, type_line="Instant",
    oracle_text="", colors=(), color_identity=(), keywords=(),
    produced_mana=(), raw={"name": "Creating Spell", "type_line": "Instant"},
)


def _gain_life(amount: int) -> OracleInstruction:
    return OracleInstruction(
        "target_gains_life", "", {"amount": amount, "recipient": "caster"}
    )


def _board():
    """P1 owes nothing; P2 controls the creature a delayed ability watches."""
    watched = Permanent(card=_creature("Watched"))
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", battlefield=[watched], life=20)
    game = Game(players=[p1, p2])
    return game, p1, p2, watched


@pytest.mark.cr("603.7")
def test_a_delayed_ability_does_nothing_until_its_event_happens():
    """"An effect may create a delayed triggered ability that can do something
    at a later time." Creating it is not doing it."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dies",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
    ))

    assert p1.life == 20

    _destroy(game, watched)
    game._settle()

    assert p1.life == 23


@pytest.mark.cr("603.7", "603.3")
def test_a_delayed_ability_resolves_off_the_stack():
    """CR 603.3: a triggered ability goes on the stack the next time a player
    would receive priority, delayed or not — it is not performed inline by the
    event that triggered it."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dies",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
    ))

    _destroy(game, watched)

    assert p1.life == 20, "the ability was performed inline instead of stacked"
    assert game.stack, "the ability never reached the stack"

    game._settle()
    assert p1.life == 23


@pytest.mark.cr("603.7b")
def test_an_undurationed_delayed_ability_triggers_only_once():
    """"A delayed triggered ability will trigger only once — the next time its
    trigger event occurs — unless it has a stated duration." A turn has two
    main phases, and Mana Drain's ability answers to one of them."""
    game, p1, _p2, _watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="controllers_next_main_phase",
        instruction=_gain_life(3), card=_SOURCE, once=True, duration="until_it_triggers",
    ))

    game.active_player_index = 0
    game._enter_main_phase(precombat=True)
    game._settle()
    assert p1.life == 23

    game._enter_main_phase(precombat=False)
    game._settle()
    assert p1.life == 23


@pytest.mark.cr("603.7b")
def test_a_stated_duration_keeps_the_ability_triggering():
    """"…unless it has a stated duration, such as 'this turn.'" Glyph of Life's
    "whenever … this turn" is that case, and the entry carries the word rather
    than the fire site deciding for itself."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dealt_damage",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
        once=False, duration="end_of_turn",
    ))
    source = Permanent(card=_creature("Source"))

    for _ in range(2):
        deal_damage(game, {
            "recipient": watched, "amount": 1, "source": source, "combat": False,
        })
        game._settle()

    assert p1.life == 26


@pytest.mark.cr("603.7b")
def test_a_this_turn_ability_that_never_triggered_goes_away():
    """The stated duration bounds the ability, not only its repeats: an entry
    scoped to this turn is gone at cleanup whether it fired or not."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dies",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
        duration="end_of_turn",
    ))

    game.resolve_cleanup_step(0)
    assert game.delayed_triggers == []

    _destroy(game, watched)
    game._settle()
    assert p1.life == 20


@pytest.mark.cr("603.7c", "400.7")
def test_a_bound_ability_does_not_answer_to_a_look_alike():
    """"A delayed triggered ability that refers to a particular object …" — a
    second creature sharing its name and every characteristic is not that
    object, and the permanent id is what says so."""
    game, p1, p2, watched = _board()
    twin = Permanent(card=watched.card)
    p2.battlefield.append(twin)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dies",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
    ))

    _destroy(game, twin)
    game._settle()

    assert p1.life == 20
    assert len(game.delayed_triggers) == 1


@pytest.mark.cr("603.7d")
def test_the_controller_is_the_seat_that_controlled_the_creating_spell():
    """"The controller of that delayed triggered ability is the player who
    controlled that spell as it resolved" — not the controller of the object
    the ability watches, who here is the other player."""
    leg = _leg()
    wall = Permanent(card=_creature("Wall", 0, 6, "Creature - Wall"))
    p1 = PlayerState(name="P1", hand=[leg["Glyph of Life"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[wall], life=20)
    game = Game(players=[p1, p2])

    game.cast_from_hand(
        0, "Glyph of Life", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    entry, = game.delayed_triggers
    assert entry.controller_index == 0
    assert entry.bound_permanent_id == wall.permanent_id


@pytest.mark.cr("603.7")
def test_an_event_narrowed_by_a_second_noun_phrase_refuses_the_wrong_agent():
    """"…dealt damage **by an attacking creature**". What did the thing and
    what it was done to are two objects; one filter over both would answer to
    neither."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dealt_damage",
        instruction=_gain_life(3), card=_SOURCE, bound_permanent_id=watched.permanent_id,
        agent_filter={"type_filter": "creature", "attacking_only": True},
        once=False,
    ))
    quiet = Permanent(card=_creature("Quiet"))
    p1.battlefield.append(quiet)

    deal_damage(game, {
        "recipient": watched, "amount": 1, "source": quiet, "combat": False,
    })
    game._settle()
    assert p1.life == 20

    quiet.attacking = True
    deal_damage(game, {
        "recipient": watched, "amount": 1, "source": quiet, "combat": True,
    })
    game._settle()
    assert p1.life == 23


@pytest.mark.cr("603.7")
def test_firing_an_event_no_entry_waits_for_does_nothing():
    """The fire sites are unconditional calls; an empty answer is the ordinary
    case, not an error."""
    game, p1, _p2, _watched = _board()

    assert fire_delayed_triggers(game, "next_end_of_combat") == 0
    assert p1.life == 20


# ---------------------------------------------------------------------------
# CR 603.7e — an activated ability's delayed ability has that ability's source
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.7e")
def test_an_activated_abilitys_delayed_ability_keeps_that_abilitys_source():
    """"If an activated or triggered ability creates a delayed triggered
    ability, the source of that delayed triggered ability is the same as the
    source of that other ability."

    The rule is what lets a delayed effect say "this creature": Giant Slug's
    "{5}: At the beginning of your next upkeep, … this creature gains landwalk
    of the chosen type" has to reach the Slug a turn later. Recorded on the
    entry at creation, because by the time it fires nothing on the stack knows
    which permanent armed it.
    """
    slug = Permanent(card=_leg()["Giant Slug"])
    slug.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[slug], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    p1.mana_pool["C"] = 5
    game.activate_permanent_ability(0, "Giant Slug")
    game.resolve_stack()
    game._settle()

    entry, = game.delayed_triggers
    assert entry.source_permanent_id == slug.permanent_id

    game.resolve_upkeep(0)
    game._settle()
    game.resolve_stack()
    game._settle()

    assert game._has_keyword(slug, "plainswalk")


@pytest.mark.cr("603.2d")
def test_a_delayed_ability_is_never_doubled_by_an_extra_triggers_effect():
    """"An effect that states a triggered ability of an object triggers
    additional times refers only to triggered abilities that object has, not to
    any delayed or reflexive triggered abilities."

    Asked of the ability rather than inferred from a missing source: a delayed
    ability now *has* a source (CR 603.7e above), so "no source permanent" has
    stopped being a synonym for "delayed".
    """
    from engine.extra_triggers import additional_triggers

    doubler = Permanent(card=_creature("Doubler"))
    p1 = PlayerState(name="P1", battlefield=[doubler], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    assert additional_triggers(game, doubler, 0, delayed=True) == 0
