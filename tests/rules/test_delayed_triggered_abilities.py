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
from engine.delayed_triggers import (WHILE_SOURCE_TAPPED, DelayedTrigger,
                                     end_source_tapped_delayed_triggers,
                                     fire_delayed_triggers)
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


# ---------------------------------------------------------------------------
# "…at the beginning of the next turn's upkeep" (Ice Age's cantrip cycle)
# ---------------------------------------------------------------------------


def _draw(amount: int = 1) -> OracleInstruction:
    return OracleInstruction("draw_controller_cards", "", {"amount": amount})


def _library(player: PlayerState, count: int) -> None:
    player.library.extend(_creature(f"Top {i}") for i in range(count))


@pytest.mark.cr("603.7")
def test_the_next_turns_upkeep_is_whichever_upkeep_comes_next():
    """"At the beginning of the next turn's upkeep" names an upkeep, not one of
    the controller's — so an ability P1 creates fires in P2's upkeep.

    That is the difference from ``controllers_next_upkeep`` beside it, and it is
    a whole turn wide: a cantrip cast on an opponent's turn would otherwise draw
    a turn late.
    """
    game, p1, p2, _watched = _board()
    _library(p1, 3)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_turns_upkeep",
        instruction=_draw(), card=_SOURCE,
    ))

    game.resolve_upkeep(1)  # P2's upkeep
    game._settle()

    assert len(p1.hand) == 1
    assert not game.delayed_triggers, "CR 603.7b: a 'when' delay fires once"


@pytest.mark.cr("603.7")
def test_the_controllers_next_upkeep_skips_an_opponents():
    """The twin, asserted so the two events cannot quietly become one: "your"
    next upkeep waits for the controller's."""
    game, p1, p2, _watched = _board()
    _library(p1, 3)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="controllers_next_upkeep",
        instruction=_draw(), card=_SOURCE,
    ))

    game.resolve_upkeep(1)
    game._settle()
    assert p1.hand == []

    game.resolve_upkeep(0)
    game._settle()
    assert len(p1.hand) == 1


@pytest.mark.cr("603.7b")
def test_a_next_turns_upkeep_delay_survives_the_turn_it_was_created_in():
    """It names a future step rather than carrying a "this turn" duration, so
    the end-of-turn sweep must not take it (CR 603.7b's "stated duration").

    The duration is what the grammar's opener row writes, and it is the whole
    card here: swept at end of turn, a cantrip created on any turn but the last
    step of one would be swept before the upkeep it names ever arrived."""
    from engine.delayed_triggers import UNTIL_IT_TRIGGERS

    game, p1, _p2, _watched = _board()
    _library(p1, 3)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_turns_upkeep",
        instruction=_draw(), card=_SOURCE, duration=UNTIL_IT_TRIGGERS,
    ))

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)

    assert game.delayed_triggers, "the ability waits for the step it names"


# ---------------------------------------------------------------------------
# Which object the ability names (CR 603.7, CR 701.21a)
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.7")
def test_603_7_the_pronoun_names_what_the_sentence_in_front_of_it_chose():
    """"Target creature you control gains flying until end of turn. **Sacrifice
    it** at the beginning of the next end step." (Krovikan Elementalist.)

    "It" is the creature the first sentence targeted. The sentence reached the
    general delayed-trigger production instead, which reads the pronoun as the
    ability's *source* — so the card armed the sacrifice on itself and left the
    creature it had just given flying to alone. Glyph of Destruction prints the
    same pronoun in the same position with "destroy" and has always bound the
    target; one sentence, one production.
    """
    from engine.grammar import compile_line

    sacrificed = compile_line(
        "Sacrifice it at the beginning of the next end step."
    ).instructions
    destroyed = compile_line(
        "Destroy it at the beginning of the next end step."
    ).instructions

    assert [i.kind for i in sacrificed] == ["arm_self_action_at_next_end_step"]
    assert sacrificed[0].payload["subject"] == "bound"
    assert destroyed[0].payload["subject"] == "bound", "the sibling it joins"


@pytest.mark.cr("603.7")
def test_603_7_the_source_spelling_still_names_the_source():
    """"Sacrifice **this creature** at the beginning of the next end step." The
    referent is not decided by the production — the printed word is — so the
    explicit spelling keeps the reading every card printing it had."""
    from engine.grammar import compile_line

    armed = compile_line(
        "Sacrifice this creature at the beginning of the next end step."
    ).instructions

    assert "subject" not in armed[0].payload, "absent means the source"


@pytest.mark.cr("701.21a")
def test_701_21a_naming_the_controller_of_a_sacrifice_narrows_nothing():
    """"**Its controller** sacrifices it at the beginning of the next end step."
    (Celestial Sword.)

    A sacrifice is its controller moving their own permanent to the graveyard
    and nobody else can perform it, so writing the actor out says what the rule
    already says. It was refused as "another player sacrificing", which is the
    one reading the sentence cannot have.
    """
    from engine.grammar import compile_line

    spelled_out = compile_line(
        "Its controller sacrifices it at the beginning of the next end step."
    ).instructions
    bare = compile_line(
        "Sacrifice it at the beginning of the next end step."
    ).instructions

    assert [i.kind for i in spelled_out] == [i.kind for i in bare]
    assert spelled_out[0].payload == bare[0].payload


@pytest.mark.cr("701.21a")
def test_701_21a_the_delayed_sacrifice_is_recorded_as_one_not_as_a_destruction():
    """The end step sweeps both flags and keeps them apart deliberately: a
    sacrifice is not a destruction (no replacement effect applies to it), so
    the armed action writes its own key rather than borrowing the neighbour's.
    """
    from engine.handlers import EFFECT_HANDLERS
    from engine.game_types import OracleExecutionContext

    game = Game(players=[PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)])
    bear = Permanent(card=_creature("Bear"))
    game.players[0].battlefield.append(bear)
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[0], card=_SOURCE,
        source_permanent=bear,
    )

    EFFECT_HANDLERS["arm_self_action_at_next_end_step"](
        game, OracleInstruction("arm_self_action_at_next_end_step", "",
                                {"self_action": "sacrifice"}), context,
    )

    assert bear.metadata.get("sacrifice_at_next_end_step") is True
    assert "destroy_at_next_end_step" not in bear.metadata

    game.resolve_end_step(0)

    assert bear not in game.players[0].battlefield
    assert [c.name for c in game.players[0].graveyard] == ["Bear"]


@pytest.mark.cr("603.7c")
def test_a_bound_object_can_be_the_recipient_of_the_delayed_damage():
    """"This creature deals 2 damage to **that creature** at end of combat."
    (Dwarven Sea Clan.)

    CR 603.7c's "particular object" as a *damage* recipient rather than a
    destroy's victim. Asserted against a look-alike beside it, because a
    recipient resolved by anything but the recorded id — the resolution
    context's leftover target, the first creature on a battlefield — would hit
    the twin just as readily.
    """
    game, p1, p2, watched = _board()
    twin = Permanent(card=watched.card)
    p2.battlefield.append(twin)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_end_of_combat", card=_SOURCE,
        bound_permanent_id=watched.permanent_id,
        instruction=OracleInstruction(
            "deal_damage", "", {"amount": 2, "recipient": "bound_permanent"}
        ),
    ))

    fire_delayed_triggers(game, "next_end_of_combat")
    game._settle()

    assert watched.damage_marked == 2
    assert twin.damage_marked == 0


@pytest.mark.cr("603.7c", "608.2b")
def test_the_delayed_damage_finds_nobody_when_its_object_has_gone():
    """"…if that object is no longer in the zone it's expected to be in at the
    time the delayed triggered ability resolves, the ability won't affect it."
    Nothing else on the board takes the damage instead."""
    game, p1, p2, watched = _board()
    bystander = Permanent(card=_creature("Bystander"))
    p2.battlefield.append(bystander)
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_end_of_combat", card=_SOURCE,
        bound_permanent_id=watched.permanent_id,
        instruction=OracleInstruction(
            "deal_damage", "", {"amount": 2, "recipient": "bound_permanent"}
        ),
    ))
    game.remove_from_battlefield(watched)

    fire_delayed_triggers(game, "next_end_of_combat")
    game._settle()

    assert bystander.damage_marked == 0


# ---------------------------------------------------------------------------
# The draw step, and a duration that is a *state* rather than a moment
# (CR 504.1, CR 603.7b, CR 611.2a) — Giant Oyster's round.
# ---------------------------------------------------------------------------


def _tapped_source(game: Game, seat: int = 0) -> Permanent:
    """A tapped permanent on *seat*'s battlefield, standing in for the object
    whose staying tapped is a delayed ability's stated duration."""
    holder = Permanent(card=_creature("Holder", type_line="Creature - Oyster"))
    holder.tapped = True
    game.players[seat].battlefield.append(holder)
    game._settle()
    return holder


def _draw_step_entry(game: Game, holder: Permanent, seat: int = 0) -> DelayedTrigger:
    entry = DelayedTrigger(
        controller_index=seat, event="controllers_draw_step",
        instruction=_gain_life(1), card=_SOURCE,
        source_permanent_id=holder.permanent_id,
        once=False, duration=WHILE_SOURCE_TAPPED,
    )
    game.delayed_triggers.append(entry)
    return entry


@pytest.mark.cr("603.7", "504.1")
def test_a_delayed_ability_can_wait_for_the_draw_step():
    """"At the beginning of each of your draw steps, …" The draw step is a step
    like the upkeep and the end step, and an ability armed for it is announced
    there — beside the battlefield's own draw-step triggers, and before the
    turn-based draw the step is otherwise for."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    game.resolve_draw_step(0)
    game._settle()

    assert p1.life == 21


@pytest.mark.cr("603.7", "504.1")
def test_your_draw_step_is_not_an_opponents():
    """The event is seated: a draw step belongs to one player, so an ability
    its opponent created is not waiting for this one. Asserted beside the row
    above, because an unseated announcement passes that one too."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    game.resolve_draw_step(1)
    game._settle()

    assert p1.life == 20
    assert game.delayed_triggers, "the entry was spent on the wrong seat's step"


@pytest.mark.cr("603.7b")
def test_a_stated_duration_makes_the_draw_step_ability_repeat():
    """"A delayed triggered ability will trigger only once — the next time its
    trigger event occurs — **unless it has a stated duration**." "For as long as
    this creature remains tapped" is that duration, so the ability fires at
    every one of its controller's draw steps."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    for _ in range(3):
        game.resolve_draw_step(0)
        game._settle()

    assert p1.life == 23


@pytest.mark.cr("603.7b", "611.2a")
def test_the_ability_ends_when_its_source_stops_being_tapped():
    """CR 611.2a: the ability lasts as long as the card states and no longer.
    Untapping the permanent ends the duration, so the entry is gone rather than
    merely skipped."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    game.become_untapped(holder)

    assert game.delayed_triggers == []

    game.resolve_draw_step(0)
    game._settle()
    assert p1.life == 20


@pytest.mark.cr("603.7b", "611.2a")
def test_the_ended_ability_does_not_come_back_when_the_source_taps_again():
    """The point of ending it rather than skipping it. Nothing re-creates a
    delayed ability whose stated duration has run out — only activating the
    ability that made it would — so a permanent that taps again is not holding
    anybody down."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    game.become_untapped(holder)
    game.become_tapped(holder)

    game.resolve_draw_step(0)
    game._settle()

    assert p1.life == 20


@pytest.mark.cr("603.7b", "611.2a")
def test_the_ability_ends_when_its_source_leaves_the_battlefield():
    """The other half of the condition: a permanent off the battlefield is not
    a tapped permanent on it. CR 400.7 makes what comes back a different
    object, so nothing can restart the duration either."""
    game, p1, _p2, _watched = _board()
    holder = _tapped_source(game)
    _draw_step_entry(game, holder)

    game.remove_from_battlefield(holder)
    game._settle()

    assert game.delayed_triggers == []

    game.resolve_draw_step(0)
    game._settle()
    assert p1.life == 20


@pytest.mark.cr("603.7b")
def test_only_the_ending_permanents_own_abilities_end():
    """The sweep is keyed to the permanent whose duration it is. Two Oysters
    each holding something down are two abilities, and one untapping must not
    take the other's with it — the look-alike bug, in a list this time."""
    game, p1, _p2, _watched = _board()
    first = _tapped_source(game)
    second = _tapped_source(game)
    _draw_step_entry(game, first)
    _draw_step_entry(game, second)

    assert end_source_tapped_delayed_triggers(game, first) == 1
    assert len(game.delayed_triggers) == 1
    assert game.delayed_triggers[0].source_permanent_id == second.permanent_id

    game.resolve_draw_step(0)
    game._settle()
    assert p1.life == 21


# --- W1G5: the cleanup step's own delayed event ---


@pytest.mark.cr("603.7", "514.3a")
def test_an_ability_can_wait_for_the_next_cleanup_step():
    """CR 514.3a names this ability shape in the rule itself: the cleanup step's
    exception to "no player receives priority" exists *because* a trigger can be
    waiting for it ("including those that trigger 'at the beginning of the next
    cleanup step'")."""
    game, p1, _p2, _watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_cleanup_step",
        instruction=_gain_life(3), card=_SOURCE,
        duration="until_it_triggers",
    ))

    game.resolve_cleanup_step(0)

    assert p1.life == 23
    assert game.delayed_triggers == []


@pytest.mark.cr("514.2", "514.3a", "603.7b")
def test_the_cleanup_delay_survives_the_sweep_that_runs_in_the_same_step():
    """CR 514.2 ends "this turn" effects and CR 514.3a looks for triggers
    *after* that, so the two happen in one step in that order.

    An entry that named this step must not be swept by the sweep that runs
    before it, and one scoped to "this turn" must not be woken by an
    announcement that comes after: those are the two halves of the same
    ordering, and getting either wrong is silent — a delayed ability that never
    fires looks exactly like one that was never created."""
    game, p1, _p2, watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_cleanup_step",
        instruction=_gain_life(3), card=_SOURCE,
        duration="until_it_triggers",
    ))
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="bound_permanent_dies",
        instruction=_gain_life(7), card=_SOURCE,
        bound_permanent_id=watched.permanent_id, duration="end_of_turn",
    ))

    game.resolve_cleanup_step(0)

    assert p1.life == 23
    assert game.delayed_triggers == []


@pytest.mark.cr("514.3a")
def test_the_cleanup_delay_is_unseated():
    """CR 514 gives every turn a cleanup step, and "the next cleanup step" is
    whichever comes next — not one of the ability's controller's. Announced
    unseated for `next_end_step`'s reason and told apart from
    `controllers_next_upkeep` by exactly that."""
    game, p1, _p2, _watched = _board()
    game.delayed_triggers.append(DelayedTrigger(
        controller_index=0, event="next_cleanup_step",
        instruction=_gain_life(3), card=_SOURCE,
        duration="until_it_triggers",
    ))

    game.active_player_index = 1
    game.resolve_cleanup_step(1)

    assert p1.life == 23
