"""Delayed triggered abilities — CR 603.7.

A *delayed* triggered ability is one a resolving spell or ability **creates**,
which then triggers later: "at the beginning of your next main phase, …",
"when that creature dies this turn, …". It has no source permanent to be
scanned off, which is the whole reason this file exists — every other trigger
in the engine is announced by walking the battlefield and reading each
permanent's compiled program, and a delayed ability belongs to no permanent at
all. So it waits in a list on ``Game`` and the fire sites walk that list.

Three things this module is the one home for, because each of them had been
answered per-card before it:

**The entry is an object.** It was a bare dict with six keys, written in one
handler and read in three sites by ``entry.get(...)``, which is a schema nobody
declares and nothing checks; a key spelled differently at one of the four reads
as absent. :class:`DelayedTrigger` is that schema.

**What the creating effect captured is payload.** CR 603.7d: the delayed
ability may refer to objects and values the creating effect knew — "that
creature", "that spell's mana value". Those live in ``bound_permanent_id`` and
``captured``, frozen when the entry is armed, and are merged into the trigger's
context when it fires. They are never part of the event name: "when *that
creature* dies" and "when *that Wall* dies" are one event with different
bindings, exactly as a printed number or a printed noun phrase is payload
everywhere else in this engine.

**Whether it fires again is CR 603.7b, and it is a field.** "A delayed
triggered ability will trigger only once — the next time its trigger event
occurs — unless it has a stated duration, such as 'this turn.'" — a "when …" clause is one-shot, a
"whenever … this turn" clause is not. ``once`` is that word, read by the one
routine that fires entries, so no fire site decides it for itself.

**An event with no fire site is not implemented.** ``DELAYED_EVENTS`` names,
for each event this engine can arm, the site that announces it. The compiler
refuses a clause whose event is not in it, and
``tests/engine/test_delayed_triggers.py`` fails when a listed event is named
nowhere but here — the same question ``test_trigger_dispatchers.py`` asks of
an ordinary trigger condition, asked at the moment the ability is *created*
instead of at the moment it should have fired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import Permanent
    from .oracle_types import OracleInstruction


#: Every delayed-trigger event this engine can arm, mapped to the site that
#: announces it. Prose, because the value is documentation and the *key* is the
#: contract — a fire site is found by grepping the key, and a list of module
#: paths goes stale the way a list of fire sites always does.
DELAYED_EVENTS: dict[str, str] = {
    # Basri Ket's −2 / Basri, Devoted Paladin's −1, and Subira's attack half.
    "creatures_attack": "the declare attackers step",
    # Subira, Tulzidi Caravanner.
    "creature_deals_combat_damage_to_player": "the combat damage step",
    # "When that creature dies this turn, …" (Reincarnation). The dying
    # permanent is named by `bound_permanent_id`, so the event is the death of
    # *whichever* permanent the creating effect bound.
    "bound_permanent_dies": "the leaves-the-battlefield transition",
    # "Whenever that creature is dealt damage by an attacking creature this
    # turn, …" (Glyph of Life). Repeating: CR 603.7b's "unless it
    # has a stated duration", and "this turn" is that duration.
    "bound_permanent_dealt_damage": "the damage event's announcement",
    # "At the beginning of your next main phase, …" (Mana Drain). Either main
    # phase of the controller's — the next one there is.
    "controllers_next_main_phase": "the main phase entry",
    # "At this turn's next end of combat, …" (Glyph of Doom).
    "next_end_of_combat": "the end of combat step",
    # "At the beginning of your next upkeep, …" (Hazezon Tamar, Giant Slug).
    # The controller's own upkeep, however many turns away it is — so unlike
    # the "this turn" rows it survives the turn and is removed only by firing.
    "controllers_next_upkeep": "the upkeep step",
}


#: How long an armed entry that has not fired survives. "This turn" wording
#: expires with the turn (CR 603.7b's "stated duration");
#: an ability that names a future step waits for that step however many turns
#: away it is, so it can only be removed by firing.
END_OF_TURN = "end_of_turn"
UNTIL_IT_TRIGGERS = "until_it_triggers"


# ``eq=False`` so two entries compare by **identity**. Two copies of Reincarnation
# resolved against the same creature arm two abilities with every field equal;
# with the generated ``__eq__`` the expiry sweep below would drop both when one
# fired — the look-alike bug this codebase keeps finding, in a list instead of on
# a battlefield.
@dataclass(eq=False)
class DelayedTrigger:
    """One delayed triggered ability waiting for its event.

    ``controller_index`` is CR 603.7d's answer to whose ability it is: the
    controller of the spell or ability that created it, frozen now, because by
    the time it fires the creating object is long gone.
    """

    controller_index: int
    #: A key of :data:`DELAYED_EVENTS`.
    event: str
    instruction: "OracleInstruction | None"
    #: For the log and the stack item's label. The card that created the
    #: ability, not the object the ability is about.
    source_name: str = "delayed trigger"
    card: Any = None
    #: CR 603.7c, the object half: the permanent "that creature" names, by the
    #: id that survives it leaving the battlefield. None means the event is
    #: not about one particular permanent (Basri Ket's attack trigger, a phase
    #: step).
    bound_permanent_id: int | None = None
    #: CR 608.2h, the value half: what the creating effect knew and the
    #: delayed ability refers to — "that spell's mana value". Merged *under*
    #: the firing event's own context, so an event that measures the same key
    #: (a damage amount) wins over the frozen one.
    captured: dict = field(default_factory=dict)
    #: A printed noun phrase narrowing which object triggers it, tested through
    #: ``subject_matches`` — payload, never part of the event name.
    subject_filter: dict = field(default_factory=dict)
    #: The *other* noun phrase some events print: what did the thing, rather
    #: than what it was done to. "Dealt damage **by an attacking creature**"
    #: (Glyph of Life) is the whole difference between that card and one that
    #: answers to any ping. Its own field rather than more keys in
    #: ``subject_filter``, because the two describe two different objects and
    #: one filter ANDs its keys.
    agent_filter: dict = field(default_factory=dict)
    #: CR 603.7b. True for "when …", False for "whenever … this turn".
    once: bool = True
    duration: str = END_OF_TURN
    # Basri Ket's two spellings, which predate the bound-object model and are
    # read only by the declare-attackers site: one trigger for the whole attack
    # with a count, and "nontoken" as its own word rather than a filter payload.
    batch: bool = False
    nontoken: bool = False

    def matches(
        self,
        game: "Game",
        event: str,
        subject: "Permanent | None",
        agent: "Permanent | None" = None,
    ) -> bool:
        """Whether this entry answers to *event* happening to *subject*.

        **When the event names an object and the entry names one, they must be
        the same object.** A different creature dying is not the event this
        ability is waiting for, and neither is a new permanent that reused the
        id's slot — which is why the id is the comparison and never the
        battlefield index (CR 400.7).

        An event that names no object never asks. "At this turn's next end of
        combat, destroy all creatures that were blocked by that creature" binds
        a Wall and fires at a *step*: the reference is read when the ability
        resolves, and comparing it here would make the ability wait for an end
        of combat that was somehow also the Wall. That is why the question is
        asked of the firing event rather than answered by a flag on the entry —
        a flag has a default, and its safe value differs per card.
        """
        from .subject_filters import subject_matches

        if self.event != event:
            return False
        if self.bound_permanent_id is not None and subject is not None:
            if subject.permanent_id != self.bound_permanent_id:
                return False
        # Gated on the same question as the id above, and deliberately: the
        # printed noun re-states what the id already names, and the two arrive
        # together. Asking it of an event that names no object would make an
        # ability bound to "that creature" wait for a step it can never match.
        if subject is not None and self.subject_filter and not subject_matches(
            game, subject, self.subject_filter, observer=self.controller_index
        ):
            return False
        if self.agent_filter and not subject_matches(
            game, agent, self.agent_filter, observer=self.controller_index
        ):
            return False
        return True

    def trigger_event(
        self,
        *,
        source_permanent: "Permanent | None" = None,
        trigger_context: dict | None = None,
    ) -> dict:
        """The ``_enqueue_triggered_ability`` kwargs for one firing of this
        ability. One builder for every site, so a delayed trigger reaches the
        stack the same way wherever it was announced."""
        context = dict(self.captured)
        # CR 603.7c: an ability that refers to a particular object carries that
        # object with it. The effect addresses it by id, so a clause reading
        # "that creature" resolves the same permanent the creating spell chose
        # however many turns and zone changes later the ability fires.
        if self.bound_permanent_id is not None:
            context["bound_permanent_id"] = self.bound_permanent_id
        context.update(trigger_context or {})
        return {
            "controller_index": self.controller_index,
            "source_permanent": source_permanent,
            "card": self.card,
            "instruction": self.instruction,
            "effect_kind": "triggered_delayed",
            "ability_text": self.source_name,
            "trigger_context": context,
        }


def arm_delayed_trigger(game: "Game", trigger: DelayedTrigger) -> DelayedTrigger:
    """Put *trigger* on the game's waiting list (CR 603.7's "creates")."""
    if trigger.event not in DELAYED_EVENTS:
        # Not a refusal a card can reach — the compiler refuses first — but the
        # entry list is the one place an event with no fire site would sit
        # silently forever, so it is loud here too.
        raise ValueError(f"no fire site announces delayed event {trigger.event!r}")
    game.delayed_triggers.append(trigger)
    return trigger


def fire_delayed_triggers(
    game: "Game",
    event: str,
    *,
    subject: "Permanent | None" = None,
    agent: "Permanent | None" = None,
    seat: int | None = None,
    source_permanent: "Permanent | None" = None,
    trigger_context: dict | None = None,
) -> int:
    """Announce *event*, putting every delayed ability waiting for it onto the
    stack (CR 603.3 — never inline). Returns how many fired.

    *seat* narrows to abilities controlled by one player, which is what "**your**
    next main phase" means: the phase belongs to the active player, and an
    entry armed by their opponent is not waiting for this one.

    A ``once`` entry is removed **before** the batch is enqueued, so an effect
    that re-announces the same event while resolving cannot fire it twice.
    """
    if not game.delayed_triggers:
        return 0
    fired: list[DelayedTrigger] = []
    for entry in list(game.delayed_triggers):
        if seat is not None and entry.controller_index != seat:
            continue
        if not entry.matches(game, event, subject, agent):
            continue
        if entry.instruction is None:
            continue
        fired.append(entry)
    if not fired:
        return 0
    game.delayed_triggers = [
        entry for entry in game.delayed_triggers
        if not (entry.once and entry in fired)
    ]
    game._enqueue_triggered_batch([
        entry.trigger_event(
            # CR 603.7d: the source of a delayed ability created by a spell is
            # *that spell*, not the object the ability watches — so the stack
            # item gets a source permanent only where a fire site deliberately
            # names one ("…deals combat damage to a player, <do something to
            # **it**>"). Defaulting it to the subject would also make the
            # ability doubled by a Strionic-style effect, which
            # `engine/extra_triggers.py` says explicitly it must not be.
            source_permanent=source_permanent,
            trigger_context=trigger_context,
        )
        for entry in fired
    ])
    return len(fired)


def expire_delayed_triggers(game: "Game") -> None:
    """CR 603.7b: a delayed ability scoped to "this turn" that never triggered
    goes away with the turn. One scoped to a future step does not — it is
    waiting for a moment that has not come yet, and only firing removes it."""
    game.delayed_triggers = [
        entry for entry in game.delayed_triggers if entry.duration != END_OF_TURN
    ]
