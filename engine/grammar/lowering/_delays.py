"""Which delayed-trigger event froze which object (CR 603.7).

Split out of `_events` when two wave-2 branches' additions summed one line past
the thousand-line guard with neither at fault. The seam is a narrowing of that
module's own question rather than a new one: `_events` answers "what did the
firing event freeze", across every event there is, and these three answer it for
the one class of event that does not fire when it is created — a *delayed*
ability, whose bound object was chosen a turn-step or a whole turn earlier.
That is the same cut `_deaths` took out of the same module, one event class at
a time.

A floor, not a family: eight lowering families read
:data:`_BOUND_OBJECT_DELAYED_EVENTS` and it reads nothing back.

:func:`end_step_action_on_made_permanent` is the one builder here, and it is
here for the tables' reason: it answers "which object is this delayed entry
about" for the case where the creating effect *made* that object a step ago.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction


#: Delayed-trigger events (CR 603.7) whose entry names a **particular object**
#: — CR 603.7c. `create_delayed_trigger` stamps that permanent's id into the
#: trigger's context, so a clause back-referring to it ("that creature", "…that
#: were blocked by that creature this turn") is admitted only under one of
#: these. Under any other event the words name an object nobody recorded, and a
#: sweep that dropped the relation would take the whole board.
#:
#: Held to `delayed_triggers.DELAYED_EVENTS` by
#: `tests/engine/test_delayed_triggers.py`, so a renamed event cannot leave a
#: row here pointing at nothing.
_BOUND_OBJECT_DELAYED_EVENTS: frozenset[str] = frozenset({
    "bound_permanent_dies",              # Reincarnation
    "bound_permanent_dealt_damage",      # Glyph of Life
    "bound_permanent_becomes_blocked",   # Barreling Attack
    "next_end_of_combat",                # Glyph of Doom
    # "Flip a coin at the beginning of the next end step. If you lose the flip,
    # sacrifice **that creature**." (Goblin Kites.) A *step* event that names an
    # object, exactly as the end-of-combat row above is: the step says when, and
    # the sentence behind it says what the ability is about.
    "next_end_step",
    # War Barge ("when this artifact leaves the battlefield this turn, destroy
    # **that creature**") and Runesword. The object the ability is *about* is
    # not always the object it watches: this membership is the acted-on half,
    # and `DelayedTrigger.watched_permanent_id` carries the watched one.
    "bound_permanent_leaves_battlefield",
    # Merieke Ri Berit: watches its own source, destroys **that creature** —
    # the same two-object shape War Barge prints, with the wider event.
    "bound_permanent_leaves_or_untaps",
    # Coffin Queen: watches its own source, exiles **that creature** — the row
    # above's shape with the other pairing of events. Both halves of it name
    # the source and the sentence behind it names the creature the ability's
    # own reanimation put onto the battlefield, so the entry is bound to one
    # object and watches another, exactly as War Barge's is.
    "bound_permanent_untaps_or_control_lost",
    # "…at the beginning of each of your draw steps, put a -1/-1 counter on
    # **that creature**." (Giant Oyster.) A *step* event that names an object,
    # exactly as the two rows above it are: the step says when, and the sentence
    # behind it says what the ability is about.
    "controllers_draw_step",
    # "…remove a +1/+1 counter from **that creature** at the beginning of the
    # next cleanup step." (Bounty of the Hunt.) A *step* event that names an
    # object, exactly as the three rows above it are: the step says when, and
    # the sentence behind it says what the ability is about. CR 514 gives every
    # turn one cleanup step, so the step itself names nobody.
    "next_cleanup_step",
    # "You gain control of that creature **if it regenerates this way**."
    # (Debt of Loyalty.) CR 701.19a's shield being spent, about the creature
    # the creating *spell* targeted — so the entry names an object exactly
    # as the step rows above do, and the event says when rather than what.
    #
    # Soldevi Sentry prints the same event about its own source and names a
    # **player** in the sentence behind it, which is `binds_player` and not
    # this membership; the two readings coexist because the arming handler
    # collapses a watched object into the bound one when a card names only
    # one.
    "source_regenerates",
})

#: Delayed-trigger events whose fire site stamps the **agent** — the object at
#: the other end of the event from the one the entry is bound to. "Whenever
#: target creature deals combat damage to **a non-Wall creature** this turn,
#: destroy **that non-Wall creature**" (Acidic Dagger): the entry is bound to
#: the damager and the sentence acts on what it damaged.
#:
#: Its own table beside `_BOUND_OBJECT_DELAYED_EVENTS` rather than more entries
#: in it, and for that table's own reason: the two answer different questions
#: off different frozen keys, and reading one from the other's key is how a
#: sentence destroys the creature its controller aimed the ability at instead
#: of the creature it hit.
_DELAYED_AGENT_EVENTS: frozenset[str] = frozenset({
    "bound_permanent_deals_combat_damage",   # Acidic Dagger
})


#: The payload key the delayed machinery stamps that object's id under.
BOUND_PERMANENT_ID = "bound_permanent_id"


#: What "<verb> it at the beginning of the next end step" does to a permanent
#: an earlier step of the same effect **made**, as the kind that acts on a
#: delayed entry's bound object (CR 603.7c).
_MADE_PERMANENT_END_STEP_ACTIONS = {
    "destroy": "destroy_bound_permanent",
    "sacrifice": "sacrifice_bound_permanent",
    "bounce": "return_bound_permanent_to_hand",
}


def end_step_action_on_made_permanent(action: str, record: str) -> OracleInstruction:
    """The delayed ability "<action> **it** at the beginning of the next end
    step" creates when "it" is a permanent this effect made.

    "Create a 3/1 black and red Graveborn creature token with haste. Sacrifice
    it at the beginning of the next end step." (Balduvian Dead; Hornet Cannon
    and Tidal Wave print the sentence too.) "You may put a creature card from
    your hand onto the battlefield. … Its controller sacrifices it at the
    beginning of the next end step." (Cauldron Dance.)

    The pronoun names what the step in front made — a token, a reanimated card,
    a card put from a hand — which nothing targeted and which did not exist
    when the ability was announced. ``arm_self_action_at_next_end_step`` reads
    it as "the ability's target, else its source", and behind a maker both are
    wrong: Balduvian Dead marked **itself** for the sacrifice and kept the
    token, Tidal Wave (a spell, so no source) armed nothing at all, and
    Cauldron Dance resolved its *graveyard slot* as a battlefield slot.

    So the id is frozen out of the maker's *record* as the entry is created
    (CR 603.7c), the shape Sneak Attack and Shallow Grave already compile to:
    an empty record arms nothing, and a permanent that leaves and returns is a
    new object the entry no longer names (CR 400.7).
    """
    return OracleInstruction("create_delayed_trigger", "", {
        "event": "next_end_step",
        "once": True,
        "duration": "until_it_triggers",
        "binds_recorded": record,
        "binds_target": False,
        "instruction": OracleInstruction(
            _MADE_PERMANENT_END_STEP_ACTIONS[action], "", {}
        ),
    })
