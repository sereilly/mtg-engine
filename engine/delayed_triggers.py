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
    # "Whenever a creature blocks **this turn**, …" (Battle Cry). The blocking
    # half of the row above, and a separate event for the reason the two
    # declaration steps are two steps: a block is announced by the defending
    # player at CR 509.1g and an attack by the active player at CR 508.1f, and
    # an entry armed for one must not be woken by the other.
    #
    # Announced **per blocking creature**, so the fire site names that creature
    # as the ability's source: "…, <do something to **it**>" is the shape every
    # card printing this opener has, and CR 603.7d's own-source default would
    # point the effect at a spell that is already in a graveyard.
    "creature_blocks": "the declare blockers step",
    # "Until end of turn, whenever a creature you control **attacks and isn't
    # blocked**, …" (Gaze of Pain.) The same step as the row above and a
    # different moment inside it: a block is announced as it is declared
    # (CR 509.1g), and this is the state of the *attack* once every declaration
    # is in (CR 509.1h) — an attacker nobody blocked. Its own event for that
    # reason rather than a narrowing of `creatures_attack`, which fires at
    # CR 508.1 when no blocker has been declared and the question cannot yet be
    # answered.
    #
    # Announced per unblocked attacker, so the fire site names that creature as
    # the ability's source: "…have **it** deal damage equal to **its** power"
    # is the shape the card prints, and CR 603.7d's own-source default would
    # point it at a sorcery already in a graveyard.
    "creature_attacks_unblocked": "the declare blockers step",
    # "…whenever **this creature** blocks or becomes blocked by a creature this
    # combat, that creature gains first strike until end of turn." (Goblin
    # Flotilla.) The joined block event of CR 509.3a–d, watched about **one**
    # permanent rather than about a described class — which is why it is not
    # `creature_blocks` above: that one is announced per blocking creature and
    # answers to any of them, and this one answers only to the creature whose
    # ability armed it, on either side of the block.
    #
    # Announced **per pair**, with the other half of it in the trigger's
    # context under the same `blocked_permanent_ids` key the printed static
    # form uses — so "that creature" is one reader for both, and a card that
    # prints the sentence as a static needs nothing new.
    "source_blocks_or_blocked_by": "the declare blockers step",
    # Subira, Tulzidi Caravanner.
    "creature_deals_combat_damage_to_player": "the combat damage step",
    # "When that creature **becomes blocked** this turn, …" (Barreling Attack).
    # CR 509.1h's state, about the one creature the creating spell chose — so
    # the fire site announces it per *attacker* with that attacker named, and
    # the entry answers only for the one it was bound to.
    #
    # Its own event rather than a narrowing of `creature_blocks`: that one is
    # announced per *blocking* creature and answers to any of them, and this is
    # the other side of the same declaration about one particular attacker.
    "bound_permanent_becomes_blocked": "the declare blockers step",
    # "When that creature dies this turn, …" (Reincarnation). The dying
    # permanent is named by `bound_permanent_id`, so the event is the death of
    # *whichever* permanent the creating effect bound.
    "bound_permanent_dies": "the leaves-the-battlefield transition",
    # "Exile that token **when Stangg leaves the battlefield**" / "Sacrifice
    # Stangg **when that token leaves the battlefield**" (Stangg). Wider than
    # the death above and deliberately a separate event: CR 603.6c's
    # leaves-the-battlefield is any move off the battlefield, so a bounce, a
    # tuck and an exile all announce it while only one of them is a death.
    "bound_permanent_leaves_battlefield": "the leaves-the-battlefield transition",
    # "When Merieke Ri Berit leaves the battlefield **or becomes untapped**,
    # destroy that creature." One delayed ability with two trigger events
    # (CR 603.7), which is why it is one key announced from two sites rather
    # than two entries: the ability fires the first time *either* happens and,
    # having no stated duration, is done (CR 603.7b). Two entries would each be
    # one-shot on their own and the second would still be waiting.
    #
    # Tawnos's Coffin prints the identical clause, so the pairing is a template
    # rather than a card — it reaches its return through
    # ``engine/linked_exile.py`` instead, which is that file's registry doing
    # for an exile what this event does for an effect the grammar lowers.
    "bound_permanent_leaves_or_untaps":
        "the leaves-the-battlefield transition and become_untapped",
    # "Whenever that creature is dealt damage by an attacking creature this
    # turn, …" (Glyph of Life). Repeating: CR 603.7b's "unless it
    # has a stated duration", and "this turn" is that duration.
    "bound_permanent_dealt_damage": "the damage event's announcement",
    # "Whenever target creature **deals** combat damage to a non-Wall creature
    # this turn, destroy that non-Wall creature." (Acidic Dagger.) The mirror of
    # the row above with the two ends of the event swapped: there the entry is
    # bound to what *took* the damage and the noun phrase describes what dealt
    # it, here the entry is bound to what *dealt* it and the phrase describes
    # what took it.
    #
    # And it is the first event whose effect acts on the **agent** rather than
    # on the object the entry is about, which is why the fire site stamps that
    # creature's id: "that non-Wall creature" is the one damaged, and by the
    # time the ability resolves the combat damage step has moved on.
    #
    # Announced from the same seam, and only for *combat* damage — a creature's
    # ping ability is not what this card watches.
    "bound_permanent_deals_combat_damage": "the damage event's announcement",
    # "At the beginning of your next main phase, …" (Mana Drain). Either main
    # phase of the controller's — the next one there is.
    "controllers_next_main_phase": "the main phase entry",
    # "At this turn's next end of combat, …" (Glyph of Doom).
    "next_end_of_combat": "the end of combat step",
    # "At the beginning of the next end step, …" (Infinite Authority). CR 513.1:
    # one end step per turn, and the next one is whoever's turn it falls in — so
    # the site announces it for every seat rather than for the creator's.
    "next_end_step": "the end step",
    # "At the beginning of **your** next end step, …" (Necropotence). The
    # controller's own end step rather than the next one there is — see the
    # `next_end_step` row above, and the two upkeep rows below, for why that is
    # a separate event and not a second spelling.
    "controllers_next_end_step": "the end step",
    # "Take an extra turn after this one. At the beginning of **that turn's**
    # end step, you lose the game." (Final Fortune.) Not the two rows above and
    # not a narrowing of either: "that turn" is the turn the *same effect* just
    # queued (CR 500.7 inserts it directly after this one), so the ability
    # names neither the next end step there is nor the controller's next one —
    # it names the end step of an extra turn that does not exist yet.
    #
    # Seated, because an extra turn belongs to whoever was granted it, and
    # guarded by ``EVENTS_AFTER_THIS_TURN`` below, because the card's main line
    # is casting it *during* an extra turn: without that guard the second Final
    # Fortune of a chain would lose the game at the end of the turn it was cast
    # in rather than at the end of the one it bought.
    "granted_extra_turns_end_step": "the end step",
    # "At the beginning of your next upkeep, …" (Hazezon Tamar, Giant Slug).
    # The controller's own upkeep, however many turns away it is — so unlike
    # the "this turn" rows it survives the turn and is removed only by firing.
    "controllers_next_upkeep": "the upkeep step",
    # "…at the beginning of **each of your draw steps**, put a -1/-1 counter
    # on that creature." (Giant Oyster.) The controller's own draw step, and
    # **every** one of them for as long as the ability lasts — CR 603.7b's
    # repeating half, where the two upkeep rows below are one-shot. Seated for
    # the reason `controllers_next_upkeep` is: a draw step belongs to one
    # player, so an entry an opponent created is not waiting for this one.
    "controllers_draw_step": "the draw step",
    # "…at the beginning of **the next turn's** upkeep" (Ice Age's cantrip
    # cycle: Portent, Pyknite, Urza's Bauble, …). Not the same event as the row
    # above, and the difference is the one that matters at the table: "your
    # next upkeep" waits for an upkeep belonging to the ability's controller,
    # skipping every opponent's, while "the next turn's upkeep" is whichever
    # upkeep comes next. On the opponent's turn those are one turn apart, and a
    # cantrip that drew a turn late would be the wrong card. So it is announced
    # unseated, exactly as `next_end_step` is and for the same reason.
    "next_turns_upkeep": "the upkeep step",
    # "…that player gets a poison counter. The player gets another poison
    # counter at the beginning of **their** next upkeep …" (Sabertooth Cobra.)
    # The third upkeep row, and the seat is what makes it a third: "your" waits
    # for the *ability's controller's* upkeep and "the next turn's" waits for
    # whichever comes next, where this one waits for the upkeep of the player
    # the creating event was about. In a duel the Cobra's damage lands on its
    # controller's turn and the two other readings happen to agree; at three
    # seats they do not, and the counter would land on the wrong player's
    # upkeep or on nobody's.
    #
    # Seated by ``bound_player_index`` rather than ``controller_index`` — see
    # :data:`EVENTS_SEATED_BY_BOUND_PLAYER`.
    "damaged_players_next_upkeep": "the upkeep step",
    # "…at the beginning of **the next cleanup step**" (Thawing Glaciers,
    # Bounty of the Hunt). CR 514.3a names this ability shape in the rule
    # itself — the cleanup step's own exception to "no player receives
    # priority" exists *because* a trigger can be waiting for it.
    #
    # Unseated, like `next_end_step` and `next_turns_upkeep` and for their
    # reason: CR 514 gives every turn a cleanup step and the ability names the
    # next one there is, whoever's turn it falls in. The two cards printing it
    # both arm during a turn they mean to end — a land that returns to hand
    # this turn and counters that come off this turn — and a seated reading
    # would hold Thawing Glaciers on the board through an opponent's whole
    # turn.
    #
    # Announced **after** CR 514.2's sweeps rather than at the step's entry,
    # which is the rule's own order: 514.1 discards, 514.2 ends the turn's
    # effects, and only then does 514.3a look for triggers. An entry armed
    # "this turn" is therefore already gone by the time this fires, which is
    # correct — it never named this step.
    "next_cleanup_step": "the cleanup step",
    # "Until end of turn, whenever **you cast a black spell**, put a +1/+1
    # counter on this creature." (Mountain Titan.) The one event in this table
    # whose subject is a **card** rather than a permanent — a spell on the stack
    # has no battlefield object — which is why :meth:`DelayedTrigger.matches`
    # asks the card matcher for it. Repeating, with "until end of turn" as
    # CR 603.7b's stated duration.
    "you_cast_spell": "the cast announcement in mixins/oracle_instructions.py",
    # "Until end of turn, … **whenever a player taps a Mountain for mana**, that
    # player adds an additional {R}." (Chaos Moon's odd branch.) Gauntlet of
    # Might prints the same triggered mana ability as a static of its own; this
    # is that ability created for a turn, so it is the same event announced from
    # the same seam.
    #
    # The one entry in this table whose fire site does **not** put the ability
    # on the stack, and the rules say so rather than the engine: CR 605.4a makes
    # a triggered mana ability resolve without using the stack, and the rule's
    # own example is this clause. See ``matching_delayed_triggers`` — the
    # enumeration half that exists so a site can resolve an entry where it
    # stands instead of enqueuing it.
    "land_tapped_for_mana": "the tap-for-mana seam in mixins/turn_management.py",
    # "When it regenerates this way, that player may draw a card." (Soldevi
    # Sentry.) The shield being *spent*, which is CR 701.19a's replacement
    # actually applying — not the shield being created, which CR 701.19c says
    # is a different thing entirely ("neither activating an ability that
    # creates a regeneration shield nor casting a spell that creates one is the
    # same as regenerating a permanent"). ``engine/regeneration.py`` is the one
    # place either happens, which is why the announcement is there.
    "source_regenerates": "the shield branch of engine/regeneration.py",
}


#: The trigger-context key a fire site stamps the event's **agent** under —
#: the object at the other end of the event from the one the entry is bound to
#: ("a non-Wall creature" in Acidic Dagger's "target creature deals combat
#: damage to a non-Wall creature"). One constant, because the fire site writes
#: it and the handler reads it, and two copies of a string is how they come
#: apart.
#:
#: An agent used to be *matched* and never carried: `agent_filter` decides
#: whether the entry answers and nothing could then act on the creature it
#: answered about.
DELAYED_AGENT_ID = "delayed_agent_permanent_id"


#: How long an armed entry that has not fired survives. "This turn" wording
#: expires with the turn (CR 603.7b's "stated duration");
#: an ability that names a future step waits for that step however many turns
#: away it is, so it can only be removed by firing.
END_OF_TURN = "end_of_turn"
#: "…**this combat**" (Melee). CR 603.7b's stated duration again, over a
#: shorter window: a turn may hold several combat phases, so an entry armed for
#: one of them must not still be waiting in the next. Its own sweep at the end
#: of combat (:func:`expire_combat_delayed_triggers`) and, belt and braces, the
#: turn sweep drops it too — a combat-scoped ability cannot outlive the turn its
#: combat was in, and a phase the game never reached is exactly when the
#: narrower sweep does not run.
END_OF_COMBAT = "end_of_combat"
UNTIL_IT_TRIGGERS = "until_it_triggers"
#: "**For as long as this creature remains tapped,** … at the beginning of each
#: of your draw steps, put a -1/-1 counter on that creature." (Giant Oyster.)
#: CR 603.7b's stated duration once more, and the first one that is a **state**
#: rather than a moment: the ability lasts while the permanent that created it
#: stays tapped on the battlefield, so nothing ever announces its end.
#:
#: That is why it is not swept with the turn-scoped pair above and not read at
#: the fire site either. CR 603.7b gives the ability its stated duration and
#: CR 611.2a makes that duration the whole of its life — so once the permanent
#: has untapped the ability is gone, and only activating again creates another.
#: An entry left in the list and merely skipped would come back to life the next
#: time the permanent tapped, which is an ability nobody created. It is ended
#: where the condition can stop being true, by
#: :func:`end_source_tapped_delayed_triggers`, which the two sites that already
#: announce ``bound_permanent_leaves_or_untaps`` call for the same moment.
WHILE_SOURCE_TAPPED = "while_source_tapped"

#: Events whose printed words name a turn **after** the one the ability was
#: created in, so an entry must not answer to the announcement made in its own
#: turn. One row, and it is Final Fortune's main line rather than an edge case:
#: the card is cast to chain into another copy, so the second is cast *during*
#: an extra turn — the very turn whose end step the fire site is about to
#: announce — and without this guard it would end the game a turn early.
#:
#: A set here rather than a flag on the entry, for :data:`DELAYED_EVENTS`'
#: reason: which turn a printed phrase names is a fact about the *event*, and a
#: per-entry flag would have a default whose safe value differs per card.
EVENTS_AFTER_THIS_TURN: frozenset[str] = frozenset({"granted_extra_turns_end_step"})


#: Events whose *seat* is the player the creating effect recorded rather than
#: the ability's controller. "The player gets another poison counter at the
#: beginning of **their** next upkeep" (Sabertooth Cobra): the possessive names
#: the damaged player, and the ability is still controlled by the Cobra's
#: controller (CR 603.7d) — two different seats, one of which decides *when* the
#: ability fires and the other *whose* ability it is.
#:
#: A set beside the table for :data:`EVENTS_AFTER_THIS_TURN`' reason: which seat
#: a printed possessive names is a fact about the event, and the fire site asks
#: for one seat either way.
EVENTS_SEATED_BY_BOUND_PLAYER: frozenset[str] = frozenset({
    "damaged_players_next_upkeep",
})


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
    #: CR 603.7c's *other* half: the **player** the creating ability chose.
    #: "Choose target opponent. … When it regenerates this way, **that player**
    #: may draw a card." (Soldevi Sentry.)
    #:
    #: Its own field beside the permanent id rather than a key in ``captured``,
    #: because it is not last-known information: a seat cannot change zones or
    #: stop existing, and every reader of "that player" in this engine already
    #: goes through the stack item's ``target_player_index``. Carried here and
    #: handed to that field when the ability fires, so the delayed effect reads
    #: the chosen seat the same way an ordinary targeted ability does — the
    #: alternative was a branch in ``_offered_seats`` for a key only this card
    #: writes.
    bound_player_index: int | None = None
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
    #: CR 603.7d, the *source* half: "the source of a delayed triggered ability
    #: is the source of the spell or ability that created it". By id, because
    #: the object may have left the battlefield by the time it fires (CR 400.7
    #: makes a returning permanent a different one, and the id is what says so).
    #:
    #: Distinct from ``bound_permanent_id``, which is what the ability is
    #: *about*. Giant Slug's "{5}: at the beginning of your next upkeep, …
    #: **this creature** gains landwalk" is the case that needs it: the sentence
    #: names its own source, the stack object carried none, and the ability
    #: resolved, logged, and granted nothing at all.
    source_permanent_id: int | None = None
    #: CR 603.7c's *other* half: the object the **event** must be about, which
    #: is not always the object the ability is about.
    #:
    #: Sandals of Abdallah watches the creature it targeted and destroys its own
    #: source; War Barge prints the mirror — it watches its own source and
    #: destroys the creature it targeted. One field could only spell one of the
    #: two, and it spelled the wrong one: ``bound_permanent_id`` is what the
    #: effect addresses, and this is what the firing event is compared against.
    #:
    #: None means "the same object the ability is about", which is what every
    #: card naming only one object prints. The arming handler sets it outright
    #: either way, so the fallback in :meth:`watched_id` serves only an entry
    #: built by hand.
    watched_permanent_id: int | None = None
    #: CR 603.7b. True for "when …", False for "whenever … this turn".
    once: bool = True
    duration: str = END_OF_TURN
    #: Which turn the ability was created in, for the one event whose printed
    #: words name a turn that does not exist yet — see
    #: :data:`EVENTS_AFTER_THIS_TURN`. Stamped by the arming handler for every
    #: entry, because a fact about when an ability was created cannot be
    #: recovered afterwards and no entry is harmed by carrying it.
    armed_turn: int | None = None
    # Basri Ket's two spellings, which predate the bound-object model and are
    # read only by the declare-attackers site: one trigger for the whole attack
    # with a count, and "nontoken" as its own word rather than a filter payload.
    batch: bool = False
    nontoken: bool = False

    @property
    def watched_id(self) -> int | None:
        """Which object's event this entry answers to (CR 603.7c).

        The explicit ``watched_permanent_id`` when there is one, and otherwise
        the object the ability is about — the identity every card that names
        only one object prints, and the reading this engine had before War
        Barge printed the mirror of it.
        """
        if self.watched_permanent_id is not None:
            return self.watched_permanent_id
        return self.bound_permanent_id

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
        from .handlers._common import _card_matches_filter
        from .subject_filters import subject_matches

        if self.event != event:
            return False
        if (
            event in EVENTS_AFTER_THIS_TURN
            and self.armed_turn is not None
            and getattr(game, "turn", None) == self.armed_turn
        ):
            # The ability names a turn the creating effect had only just
            # queued, so the announcement made in the turn it was armed in is
            # not the one it is waiting for.
            return False
        watched = self.watched_id
        if watched is not None and subject is not None:
            if subject.permanent_id != watched:
                return False
        # Gated on the same question as the id above, and deliberately: the
        # printed noun re-states what the id already names, and the two arrive
        # together. Asking it of an event that names no object would make an
        # ability bound to "that creature" wait for a step it can never match.
        if subject is not None and self.subject_filter:
            # A **card** subject (a spell being cast) has no computed
            # characteristics at all (CR 613.1), so the battlefield matcher
            # cannot answer about it — the card matcher can, and the lowering
            # that armed the entry gated its filter on exactly the keys that one
            # reads. Told apart by what the object *is* rather than by the event
            # name, because a list of which events carry a card goes stale the
            # way every list of fire sites in this engine has.
            answers = (
                subject_matches(
                    game, subject, self.subject_filter,
                    observer=self.controller_index,
                )
                if hasattr(subject, "has_type")
                else _card_matches_filter(subject, self.subject_filter)
            )
            if not answers:
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
            # CR 603.7c for a chosen *player*: the ability is about the seat the
            # creating ability targeted, handed over on the field every "that
            # player" in this engine already reads. None on every other entry,
            # which leaves the stack item exactly as it was.
            "target_player_index": self.bound_player_index,
            "trigger_context": context,
        }


def arm_delayed_trigger(game: "Game", trigger: DelayedTrigger) -> DelayedTrigger:
    """Put *trigger* on the game's waiting list (CR 603.7's "creates")."""
    if trigger.event not in DELAYED_EVENTS:
        # Not a refusal a card can reach — the compiler refuses first — but the
        # entry list is the one place an event with no fire site would sit
        # silently forever, so it is loud here too.
        raise ValueError(f"no fire site announces delayed event {trigger.event!r}")
    # When the ability was created, stamped here rather than at each arming site
    # for the reason every other frozen fact in this file is: one place, so a
    # new arming path cannot forget it. Read only by
    # :data:`EVENTS_AFTER_THIS_TURN`, and left alone when the caller set it.
    if trigger.armed_turn is None:
        trigger.armed_turn = getattr(game, "turn", None)
    game.delayed_triggers.append(trigger)
    return trigger


def matching_delayed_triggers(
    game: "Game",
    event: str,
    *,
    subject: "Permanent | None" = None,
    agent: "Permanent | None" = None,
    seat: int | None = None,
) -> list[DelayedTrigger]:
    """Every armed ability answering to *event*, with the one-shot ones already
    taken off the waiting list.

    The half of :func:`fire_delayed_triggers` that is *not* about the stack, and
    it is separate because one event's abilities do not use it. CR 605.4a: a
    triggered mana ability resolves without using the stack, so the tap-for-mana
    seam has to resolve the entries where it stands — and everything before that
    point (whose ability it is, whether it answers to this object, and CR
    603.7b's "will trigger only once") is the same question the stack path asks.
    A second copy of it in the seam is the second-copy bug this codebase keeps
    finding; one that skipped the ``once`` bookkeeping would be an ability that
    fires forever.

    *seat* narrows to abilities controlled by one player, which is what "**your**
    next main phase" means: the phase belongs to the active player, and an entry
    armed by their opponent is not waiting for this one.

    A ``once`` entry is removed **before** the caller does anything with it, so
    an effect that re-announces the same event while resolving cannot fire it
    twice.
    """
    if not game.delayed_triggers:
        return []
    fired: list[DelayedTrigger] = []
    for entry in list(game.delayed_triggers):
        # Whose ability it is, or whose *turn* the printed possessive named —
        # see :data:`EVENTS_SEATED_BY_BOUND_PLAYER`. An entry of one of those
        # events with no bound seat answers to nobody rather than falling back
        # to its controller, which would fire "their next upkeep" on the wrong
        # player's turn.
        entry_seat = (
            entry.bound_player_index
            if entry.event in EVENTS_SEATED_BY_BOUND_PLAYER
            else entry.controller_index
        )
        if seat is not None and entry_seat != seat:
            continue
        if not entry.matches(game, event, subject, agent):
            continue
        if entry.instruction is None:
            continue
        fired.append(entry)
    if fired:
        game.delayed_triggers = [
            entry for entry in game.delayed_triggers
            if not (entry.once and entry in fired)
        ]
    return fired


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
    stack (CR 603.3). Returns how many fired.

    Not every event reaches the stack: CR 605.4a exempts a triggered mana
    ability, and the tap-for-mana seam resolves its entries inline through
    :func:`matching_delayed_triggers` instead of calling this.

    *seat* narrows to abilities controlled by one player, which is what "**your**
    next main phase" means: the phase belongs to the active player, and an
    entry armed by their opponent is not waiting for this one.

    A ``once`` entry is removed **before** the batch is enqueued, so an effect
    that re-announces the same event while resolving cannot fire it twice.
    """
    fired = matching_delayed_triggers(
        game, event, subject=subject, agent=agent, seat=seat
    )
    if not fired:
        return 0
    game._enqueue_triggered_batch([
        entry.trigger_event(
            # CR 603.7d: "the source of a delayed triggered ability is the
            # source of the spell or ability that created it". So the entry's
            # own recorded source wins whenever it is still a permanent — a
            # sentence naming itself ("…you put a cube counter on **this
            # artifact**", Delif's Cube) has to reach the artifact that armed the
            # ability, not the creature the event was about.
            #
            # A fire site's named object is the **fallback**, for the case the
            # rule leaves open: a spell's source is the card as printed and
            # never a permanent, so Gaze of Pain's entry has no source to give
            # and its sentence ("…have **it** deal damage equal to **its**
            # power") needs one. The attacker the site names is that object.
            #
            # Defaulting to the *subject* with neither would be the wrong object
            # twice over, which is why that is still not done here.
            source_permanent=(
                game.permanent_by_id(entry.source_permanent_id)
                or source_permanent
            ),
            trigger_context=trigger_context,
        )
        for entry in fired
    ])
    return len(fired)


#: The durations a turn ends. Both are CR 603.7b's "stated duration"; neither
#: can outlive the turn it was armed in, and the shorter one is listed here as
#: well as swept at end of combat because a combat that never happened (a turn
#: with no combat phase entered, an effect that skipped it) never runs the
#: narrower sweep.
_TURN_SCOPED = frozenset({END_OF_TURN, END_OF_COMBAT})


def expire_delayed_triggers(game: "Game") -> None:
    """CR 603.7b: a delayed ability scoped to "this turn" that never triggered
    goes away with the turn. One scoped to a future step does not — it is
    waiting for a moment that has not come yet, and only firing removes it."""
    game.delayed_triggers = [
        entry for entry in game.delayed_triggers
        if entry.duration not in _TURN_SCOPED
    ]


def end_source_tapped_delayed_triggers(game: "Game", permanent: "Permanent") -> int:
    """CR 603.7b's stated duration for :data:`WHILE_SOURCE_TAPPED`: *permanent*
    has stopped being a tapped permanent on the battlefield, so every ability it
    created under that duration ends. Returns how many were dropped.

    Called from the two sites that already announce
    ``bound_permanent_leaves_or_untaps`` — ``Game.become_untapped`` and the
    leaves-the-battlefield transition — because they are the same moment: those
    are the one place a permanent stops being tapped and the one place it leaves
    the battlefield, which is exactly when this condition can stop holding.

    Ended here rather than re-asked at the fire site, and the difference is the
    rule: CR 611.2a makes an ability last exactly as long as its creator stated,
    and nothing re-creates this one except activating the ability again. An
    entry skipped while the permanent was untapped would fire again the next
    time it tapped — an ability nobody created.
    """
    ending = [
        entry for entry in game.delayed_triggers
        if entry.duration == WHILE_SOURCE_TAPPED
        and entry.source_permanent_id == permanent.permanent_id
    ]
    if not ending:
        return 0
    game.delayed_triggers = [
        entry for entry in game.delayed_triggers
        if not any(entry is done for done in ending)
    ]
    return len(ending)


def expire_combat_delayed_triggers(game: "Game") -> None:
    """CR 603.7b for the shorter window: "…this combat" (Melee) ends where every
    other until-end-of-combat effect does, in the end of combat step (CR 511).

    Its own sweep rather than a branch of the turn one, because they are two
    moments: a turn may hold several combat phases, and an entry left waiting
    would fire again in the next one on a declaration the card never saw.
    """
    game.delayed_triggers = [
        entry for entry in game.delayed_triggers
        if entry.duration != END_OF_COMBAT
    ]
