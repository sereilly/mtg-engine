"""What a back-reference in a *triggered* ability names.

Beside `_common` rather than inside it, and beside the families rather than in
one of them: every value here is keyed by **trigger-condition kind**, and every
one answers the same question — the sentence says "that player", "that much" or
"they", and the referent is not in the sentence. It is whatever the firing event
froze (CR 603.10), because by the time the trigger resolves the creature is in a
graveyard, the blocker has left combat, or the upkeep has moved on.

Each is a *table* rather than a rule, and that is load-bearing. An event either
carried a subject, a seat or a number or it did not; a rule would have to guess,
and guessing here is silent in both directions — a back-reference reading zero
off an empty context compiles clean and does nothing, and one reading the wrong
seat compiles clean and does something to the wrong player. So a condition absent
from a table refuses the line instead.

Split out of `_common` when it crossed the thousand-line guard: `_common` is
"payload shapes every family needs" and these are "what the event left behind",
which is a different question with a different key. Both are shared modules —
six lowering families read something here — so `test_grammar_layering.py` names
this one beside `_common` in its `shared` tuple.
"""

from __future__ import annotations

from ...oracle_types import PER_OBJECT_SEAT_RECORDS

from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER, COUNTERS_REMOVED,
                             SEARCHED_PERMANENTS,
                             LAST_TARGET_CONTROLLER,
                             COUNTERS_PLACED_THIS_WAY,
                             EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS,
                             HAND_CARDS_TO_LIBRARY)
from ...tokens import CREATED_TOKEN_RESULT_KEY
from .. import ast
from ..errors import LoweringError

# Trigger events that hand a *damaged player* to the effect after them: "that
# player" names the player the trigger recorded taking the damage
# (``defending_player_index`` in the trigger's context), and nothing in the
# instruction's own payload. Under any other trigger the same words would name
# a player nobody recorded. Here rather than beside one reader because two
# effect families ask it — a discard (Hypnotic Specter) and a player counter
# (Pit Scorpion) — and a fragment two families need belongs in the shared
# module.
_DAMAGED_PLAYER_EVENTS: frozenset[str] = frozenset({
    "damage_dealt",
    # "…that player gets a poison counter. The player gets another poison
    # counter at the beginning of their next upkeep …" (Sabertooth Cobra.) The
    # second sentence is a *delayed* ability, so its own event is the upkeep
    # rather than the damage — but "the player" still names the seat the damage
    # froze, and it is the only seat this event has: the ability is created by
    # a damage trigger, is seated on that player's upkeep
    # (`EVENTS_SEATED_BY_BOUND_PLAYER`), and `create_delayed_trigger` freezes
    # the whole of the creating trigger's context into ``captured``, which is
    # where the handler reads the record back from.
    "damaged_players_next_upkeep",
})


# Trigger events that freeze **which seat is being attacked** into the trigger's
# context (`trigger_defending_player_index`), so an effect after them may say
# "defending player" and mean a seat rather than a guess. CR 506.2: who is
# defending is a fact about a combat, not about the ability's controller or its
# target — under any other event the phrase names nobody, and an offer made to
# nobody is an effect that silently does not happen.
_DEFENDING_PLAYER_EVENTS: frozenset[str] = frozenset({
    "creature_attacks",
    # "Whenever this creature attacks and isn't blocked, … **defending player**
    # discards a card at random." (Cloak of Confusion.) The declare-blockers
    # fire site stamps the same key the declare-attackers one does, which is
    # what makes the phrase name a seat here — the set is the list of events
    # that stamped it, and an event added here without the stamp is a phrase
    # naming nobody.
    "attacks_unblocked",
})

#: Which *frozen seat* a printed player word names, per event that froze one:
#: the events that froze it, and the record key the handler reads it back from.
#:
#: The two rows are not two spellings of one thing. A damage event freezes the
#: player the damage went to; a combat one freezes CR 506.2's defender, and on a
#: trampling attacker those are the same seat only by coincidence. So the word
#: decides which record is asked, and a word whose event froze neither has no
#: seat at all — which is the answer this table exists to give, because an
#: effect aimed at a seat nobody recorded compiles clean and then lands on
#: whichever player the resolution happened to be carrying.
#:
#: A table beside the two sets it reads rather than an if-chain beside one
#: caller, for this module's own reason: two effect families ask it — a poison
#: counter (``lowering/counters.py``) and a life loss (``lowering/game.py``).
_FROZEN_SEAT_WORDS: dict[str, tuple[frozenset[str], str]] = {
    "that_player": (_DAMAGED_PLAYER_EVENTS, "damaged_player"),
    "defending_player": (_DEFENDING_PLAYER_EVENTS, "defending_player"),
}


def frozen_seat_record(player_kind: str, event: str | None) -> str | None:
    """The record key holding the seat *player_kind* names under *event*.

    ``None`` when the firing event froze no seat for that word — the caller
    refuses the line there rather than emitting an instruction that would read
    a missing key and act on a default.
    """
    entry = _FROZEN_SEAT_WORDS.get(player_kind)
    if entry is None or event is None or event not in entry[0]:
        return None
    return entry[1]



# Trigger events after which "that player" names the controller of the object
# the event was about, frozen into the trigger's context by the fire site.
#
# Here rather than beside either reader: two effect families ask it — a life
# loss (Massacre Wurm) and a damage event (Backfire) — and a fragment two
# families need belongs in the shared module, which is the same rule the parse
# side's `phrases.py` follows.
_EVENT_SUBJECT_CONTROLLERS: frozenset[str] = frozenset({
    "creature_opponent_controls_dies",   # Massacre Wurm — the dead creature's
    # Earthlink — the dead creature's, from the same stamp
    # (`_fire_creature_dies_triggers` freezes one `died_context` for every
    # death condition it announces). The unscoped spelling of the row above:
    # "whenever **a** creature dies" watches every battlefield, and "that
    # creature's controller" is still the seat that controlled the one that
    # died — which under a control-change effect is not its owner.
    "creature_dies",
    "creature_becomes_blocked",          # Gloom Sower — the blocker's
    # Binding Agony — the **damaged** creature's, which for an Aura watching
    # its host is the host's controller. Frozen by `_fire_dealt_damage_triggers`
    # while the creature is still on the battlefield: this trigger resolves off
    # the stack (CR 603.3), and lethal damage is exactly the case where the
    # creature is in a graveyard by then and CR 400.7 leaves nothing with a
    # controller to read.
    #
    # The subject of *this* event is the damaged object, not the damager — the
    # `damage_dealt` row below is the other way round, and reading one for the
    # other on a creature that traded would charge the wrong player.
    "creature_dealt_damage",
    # Backfire — the damager's. The subject of a damage event is whatever dealt
    # it, so "that creature's controller" is the seat `deal_damage` derives for
    # every event and freezes into the announcement.
    "damage_dealt",
    # Psychic Venom — the tapped land's. Both tap announcements stamp the key
    # (`become_tapped`), because the words name the object the event was about
    # and not the seat that did the tapping: an Icy Manipulator taps a land its
    # controller does not own, and the printed sentence still means the land's
    # controller. Absent from this table the phrase fell through to
    # `target_player`, which is a choice the card never offers — so Psychic
    # Venom damaged the Aura controller's opponent, and did it even when the
    # enchanted land was the Aura controller's own.
    "permanent_becomes_tapped",
    # Haunting Wind, Artifact Possession — the tapped artifact's, for the same
    # reason and from the same stamp. This condition has two announcements (a
    # tap, and an ability activated without {T}); both freeze the *subject's*
    # controller, which is the artifact's, never the activating seat.
    "permanent_tapped_or_ability_activated",
    # Thelon's Chant, Tourach's Chant — the entering permanent's. Their printed
    # condition names the *player* ("whenever a player puts a Swamp onto the
    # battlefield"), and the seat the words mean is the one that permanent
    # entered under, which `_initialize_permanent_state` freezes on every entry
    # path. Absent from this table the phrase fell through to `target_player`,
    # a choice neither card offers — which is Psychic Venom's bug one row up.
    "matching_permanent_enters",
    # Funeral March — the departing host's. CR 603.6c's event about the
    # permanent an Aura or Equipment is attached to, announced from the one
    # transition off the battlefield (`remove_all_from_battlefield`), which
    # freezes the seat while the host is still on a battlefield. "Its
    # controller" cannot be re-derived at resolution: by then the host is in a
    # graveyard, an exile or a hand, and under a control-change effect that
    # seat was never its owner.
    "attached_creature_leaves_battlefield",
    # Ankh of Mishra — the entering land's, frozen by `_process_land_enters`
    # (mixins/effects.py). The unnarrowed sibling of `matching_permanent_enters`
    # two rows up, admitted for its reason: "that land's controller" is the seat
    # the land entered under, whatever put it there. Absent from this table the
    # phrase fell through to `target_player` — a choice the card never offers —
    # and the fire site papered over it by swapping in a hand-built instruction
    # carrying its own victim, so the compiled program was never what ran.
    "land_enters",
    # Dingus Egg — the dead land's, from `_process_land_dies`, which freezes
    # the seat while announcing the death. It cannot be re-derived at
    # resolution: by then the land is a card in a graveyard (CR 400.7), and
    # under a control-change effect that seat was never its owner. The same
    # fire-site accident as the row above, and retired with it.
    "land_dies",
})


#: Trigger conditions whose fire site freezes the **object** the event was about
#: (``event_subject_permanent_id``), so a bare "it" in the effect names that
#: permanent rather than the ability's own source.
#:
#: A third table beside the two above rather than more entries in either,
#: because the three answer different questions off different frozen keys: the
#: seat that controlled the subject, the seat that *was* the subject, and the
#: subject itself. Reading one from another's key is how a phrase resolves
#: against whatever an empty context defaults to.
#:
#: Membership is a claim about the fire site, and the site is what makes it
#: true: ``become_tapped`` stamps the id (CR 400.7 — an index is not an
#: identity, and by resolution the permanent may have moved). Kudzu's "destroy
#: it" already reads the same key from its own handler.
_EVENT_SUBJECT_OBJECTS: frozenset[str] = frozenset({
    "permanent_becomes_tapped",         # Freyalise's Winds, Kudzu
    # "Whenever a creature attacks you, **it** loses flanking until end of
    # turn" / "…this enchantment deals 1 damage to **it**" (Barbed Foliage).
    # The declared attacker, stamped by `_fire_matching_creature_attacks_triggers`
    # for the same reason `become_tapped` stamps its subject: the announcement
    # is game-wide and per object, and by resolution the creature may have been
    # removed from combat or destroyed.
    "matching_creature_attacks",
})


#: The trigger events whose fire site records the dying card, so "that card" /
#: "it" in the effect behind them names something the handler can find. Written
#: as a set rather than one literal because three fire sites stamp ``dead_card``
#: and a fourth would only have to be added here — where an event *not* listed
#: refuses the sentence rather than resolving to nothing.
#:
#: Public, because it is not this family's question: ``zones`` asks it too, for
#: "put **that card** onto the battlefield under your control" (Seraph,
#: Krovikan Vampire). One set, so a fire site taught to record the card reaches
#: both readings of the phrase at once — two copies would let a card be returned
#: to a hand and refused onto the battlefield under the same trigger.
BOUND_CARD_EVENTS = frozenset({
    "attached_creature_dies",
    "permanent_dies",
    # "Whenever a creature dealt damage by this creature this turn dies, …"
    # (Seraph, Krovikan Vampire, Sengir Vampire). The scan in
    # ``mixins/helpers._fire_creature_dies_triggers`` stamps the same
    # ``dead_card`` its three sibling scans do — it did not until Seraph asked,
    # which is why the set is what says an event is admitted rather than the
    # condition table that merely names it.
    "creature_dealt_damage_by_self_dies",
})

#: The private spelling this module used before ``zones`` needed the same set.


#: Trigger conditions whose subject **is a player** rather than an object, so
#: "that player" (and its pronoun "they") names the seat the event was about
#: directly — there is no object in between to take a controller from.
#:
#: A separate table from `_EVENT_SUBJECT_CONTROLLERS` rather than more entries
#: in it, because the two answer different questions and the fire sites freeze
#: different things. Folding "each player's upkeep" into the controller table
#: would have read the seat out of `event_subject_controller`, a key no upkeep
#: fire site stamps, and every such card would have resolved against whatever
#: an empty context defaults to.
#:
#: `upkeep_self` is deliberately absent: "at the beginning of **your** upkeep"
#: has only one seat and it is already spelled "you". Only the conditions whose
#: seat *varies* need freezing, and `upkeep_each` is the one the ordinary
#: (non-registry) upkeep path admits — see `_ORDINARY_UPKEEP_SEATS`.
#: The pseudo-event a modal spell's bullet is lowered under when the head names
#: somebody other than the controller as the mode's chooser (CR 700.2e:
#: "An opponent chooses one —"). It is not a trigger condition and never reaches
#: `emit`; it is the name the *position* has, exactly as `activated` and
#: `condition_kind` name a line's position in `engine/oracle.py`. What it buys
#: is one reading of "that player" across the three families that read it.
OPPONENT_CHOSE_MODE = "mode_chosen_by_opponent"


_EVENT_SUBJECT_PLAYERS: frozenset[str] = frozenset({
    "upkeep_each",
    # "At the beginning of **the chosen player's** upkeep, this enchantment
    # deals 3 damage to **that player** …" (Energy Vortex). The seat an earlier
    # effect chose and the permanent recorded, frozen into the trigger's
    # context by the upkeep loop exactly as `upkeep_each`'s is — the loop
    # stamps ``event_subject_player`` on every ordinary upkeep firing, and this
    # condition is one of the four it names a seat for.
    "upkeep_chosen",
    # "When a player doesn't pay this enchantment's cumulative upkeep,
    # **that player** exiles all cards from their library." (Thought Lash.)
    # Nothing on a board records who declined to pay, so the seat exists only
    # on the event the upkeep handler announces — which is the whole reason
    # this table is the gate rather than a fall-back to the controller.
    "cumulative_upkeep_unpaid",
    # "At the beginning of each player's end step, … **that player** …"
    # (Monsoon.) The upkeep row's twin one step of the turn later, and admitted
    # for the same reason: the seat varies per firing and the end-step
    # announcement now freezes it. ``end_step_self`` stays out, exactly as
    # ``upkeep_self`` does — "your end step" has one seat and it is spelled
    # "you".
    "end_step",                       # Spiritual Sanctuary, Storm World
    # "Whenever an opponent draws a card, this enchantment deals 1 damage to
    # **that player**" (Underworld Dreams). CR 121.2 makes a draw a per-card
    # event about one seat, and which seat varies per firing — an opponent in a
    # three-player game is not "the opponent" — so it is frozen by the draw
    # sweep that announces it rather than re-derived at resolution.
    "draws_card",
    # "Whenever an opponent casts an instant spell …, this creature deals 4
    # damage to **that player**" (Ichneumon Druid). The condition names one
    # seat — whoever cast the spell — and nothing chose it, so it is the seat
    # the cast froze rather than a target. Read as `target_player` instead, the
    # ability would ask for a choice the card never offers.
    "opponent_casts_spell",
    # "Whenever a player attacks with one or more creatures, destroy all …
    # creatures **that player** controls" (Total War). The declaration names
    # the attacking seat and the declare-attackers step freezes it; under the
    # seat-narrowed readings of this same condition ("whenever **you** attack")
    # the phrase would mean the controller, which is the same answer — so one
    # entry covers every row of the kind.
    "attackers_declared",
    # "Whenever a player taps a land for mana, this enchantment deals 1 damage
    # to **that player**" (Manabarbs). The condition names the tapping seat and
    # nothing chose it. This event's trigger resolves *inline* at the
    # tap-for-mana seam in `mixins/turn_management.py` (CR 605.4a keeps its
    # triggered-mana siblings off the stack, and the damage rides the same
    # moment) — so the fire site is still holding the seat when it executes
    # the instruction, which is the freeze.
    "land_tapped_for_mana",
    # "At the beginning of the upkeep of enchanted <noun>'s controller, …
    # **that player** …" (the punishment Auras: Cursed Land, Feedback,
    # Maddening Wind, Mind Whip, Wanderlust, Warp Artifact, Curse Artifact).
    # The seat varies with the attachment, and the ordinary upkeep loop
    # (`phases/upkeep_step.py`) freezes whose upkeep the firing is as it
    # enqueues the trigger — after checking, through
    # `upkeep_trigger_seat_matches`, that it is the host's controller's.
    "upkeep_enchanted_controller",
    # "At the beginning of the chosen player's upkeep, this enchantment deals
    # 1 damage to **that player**" (Takklemaggot's granted line). The same
    # loop and the same stamp, gated the same way: the seat is whichever
    # player the returning enchantment was told to watch.
    "upkeep_chosen",
    # "**An opponent** chooses one — … • You put a -1/-1 counter on each
    # creature **that player** controls and this deals 4 damage to **that
    # player**." (Misfortune; Fatal Lore prints the same back-reference.)
    #
    # Not a trigger, and admitted here anyway, because this table is not about
    # triggers: it is about the events that *froze* a seat under
    # `EVENT_SUBJECT_PLAYER`. CR 700.2e names a player who makes the mode
    # choice, and the choice is where that seat comes into existence — nothing
    # on a board says who chose, and in a three-player game "an opponent" is
    # not "the opponent". `_resolve_opponent_mode_choice` stamps the chooser
    # into the spell's context as it records the mode, which is the same freeze
    # a fire site makes, so every reader of the phrase — the damage recipient
    # here, the draw's seat, `subject_filters`' `controller: that_player` —
    # gets one answer from one key.
    OPPONENT_CHOSE_MODE,
})

#: Delayed-trigger events (CR 603.7) whose fire site freezes the **owner** of
#: the object the event was about, under `EVENT_SUBJECT_OWNER` below.
#:
#: Its own table beside `_EVENT_SUBJECT_CONTROLLERS` rather than more entries in
#: it, and for that table's own stated reason: ownership is CR 108.3 and never
#: changes, control is CR 613 layer 2 and does. Reincarnation returns the card
#: under the *owner's* control, so reading the controller instead would hand the
#: creature to whoever had stolen the one that died.
_EVENT_SUBJECT_OWNERS: frozenset[str] = frozenset({
    "bound_permanent_dies",              # Reincarnation
})

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

#: The scratchpad key a token maker writes the created token's ``permanent_id``
#: under. Imported rather than spelled again: ``engine/tokens.py`` is the one
#: home for it, because the handler that writes it lives on the other side of
#: the pipeline from the lowering that gates the phrase on it.
CREATED_TOKEN = CREATED_TOKEN_RESULT_KEY

#: What "**exiled this way**" names (Martyr's Cry): the `produced` marker a
#: sweep that exiles stamps, and the scratchpad key it records the objects
#: under. Imported rather than spelled again for ``CREATED_TOKEN``'s reason —
#: the sweep handler writes them and this lowering gates on them, so the two
#: sides live on opposite ends of the pipeline and a second copy would rot.

#: The payload key those fire sites stamp it under. One constant for the same
#: reason `EVENT_SUBJECT_PLAYER` is one: the fire site writes it and the handler
#: reads it, and three copies of a string is how they come apart.
EVENT_SUBJECT_OWNER = "event_subject_owner"

#: The payload spelling both a recipient and a condition subject use for that
#: seat. One constant, because the fire site writes it, the life handler reads
#: it and `evaluate_condition` reads it — three copies of a string is how they
#: come apart.
EVENT_SUBJECT_PLAYER = "event_subject_player"

#: The marker `lower.py` adds to *produced* while lowering the body of a
#: "for each player" loop: inside it, "that player" is the seat the iteration
#: is on — `handlers/control_flow.for_each` rebinds the resolution's target to
#: each seat in turn — and not anything a trigger's fire site froze. A marker
#: rather than a scratchpad key: nothing is recorded under it, it only says
#: the loop is the pronoun's binder. It is what lets Lim-Dûl's Hex's damage,
#: written under "at the beginning of your upkeep", lower to the target-slot
#: reading while the same words under a bare trigger refuse — the loop is the
#: innermost binder, so it is checked before the event tables above.
LOOP_BOUND_PLAYER = "loop_bound_player"

#: The same marker for a loop over **objects** rather than seats: added to
#: *produced* while lowering the body of "for each <noun> destroyed / exiled /
#: tapped / chosen this way", where ``handlers/control_flow.for_each`` binds
#: each object in turn (``iteration_target``, and the per-object seats beside
#: it).
#:
#: A marker rather than a scratchpad key, exactly as its seat-shaped sibling
#: above is: nothing is recorded under it, it only says the loop is what a bare
#: "it" / "its controller" / "its mana value" refers to. Without it those
#: phrases are gated on the *record* alone, which is present after any sweep at
#: all -- so "Destroy all artifacts. Its controller gains 2 life." would compile
#: to a per-iteration read with no iteration around it and gain nobody anything.
LOOP_BOUND_OBJECT = "loop_bound_object"

#: The per-object seat map a destroy or exile step freezes about what it took,
#: read two ways: one entry per iteration inside an object loop ("its
#: controller"), and as a per-seat tally outside one ("the number of artifacts
#: **they controlled** that were put into a graveyard this way").
#:
#: Named here rather than spelled from ``PER_OBJECT_SEAT_RECORDS`` at each
#: reader for this module's own reason: two lowering families cite it (life and
#: damage) and a name defined twice is the duplicate this package keeps
#: removing.
SWEPT_CONTROLLER_SEATS = PER_OBJECT_SEAT_RECORDS["controller"]

#: And the seat that *controlled* what the event was about, from
#: `_EVENT_SUBJECT_CONTROLLERS` above. A constant for `EVENT_SUBJECT_PLAYER`'s
#: reason, one table over: the fire site writes it, the damage lowering and the
#: sacrifice lowering both emit it, and three handlers read it.
EVENT_SUBJECT_CONTROLLER = "event_subject_controller"


# What a bare "that much" names when the effect is a *triggered ability*: the
# quantity the firing event carried, frozen into the trigger's context by the
# fire site. Keyed by trigger-condition kind, and deliberately a table rather
# than a rule — an event either carries a number or it does not, and a kind
# absent here refuses the back-reference instead of reading a zero out of an
# empty context.
#: The scratchpad key "that creature's power" falls back to when the sentence
#: sits under no trigger — the power an earlier step of the same effect froze
#: about the permanent it acted on (Broken Visage's destroy). Named here beside
#: the event table because ``_back_reference_payload`` is what chooses between
#: the two, and ``_records._PRODUCES`` writes the same string: a second spelling
#: would make the producer gate vacuous while the handler read an empty record.
_EVENT_SUBJECT_POWER_RECORD = "its_power"

#: Its toughness twin, for the other half of the same printed sentence. A
#: constant rather than a literal for the reason above, and separate from the
#: power because the two are different characteristics of one object rather than
#: one number under two names.
_EVENT_SUBJECT_TOUGHNESS_RECORD = "its_toughness"

_EVENT_QUANTITIES: dict[str, str] = {
    "you_gain_life": "life_gained",
    # The mirror, from the state-based sweep that announces it: "for each 1
    # life you lost" (Oath of Lim-Dûl) counts the drop the sweep measured, not
    # the amount an effect set out to take — a life loss that a replacement
    # reduced is the smaller number, exactly as the gain above is.
    "you_lose_life": "life_lost",
    # "Whenever another creature you control enters, this creature deals damage
    # equal to **that creature's** power…" (Terror of the Peaks). The entering
    # creature's power, frozen by the fire site — by the time the trigger
    # resolves the creature may have been pumped or destroyed, and CR 608.2's
    # number is the one the event had.
    "matching_permanent_enters": "entering_power",
    # "Whenever this creature **is dealt damage**, it deals that much damage to
    # target opponent." (Brash Taunter.) The number is frozen by the fire site,
    # because by resolution the marked damage may have been added to or wiped.
    "creature_dealt_damage": "damage_dealt",
    # **The whole "deals damage" family, in one row.** "You gain that much
    # life" (Spirit Link, El-Hajjâj), "this creature deals that much damage to
    # …" (Chandra's Incinerator, Backfire), "look at that many cards"
    # (Garruk's Harbinger) — one event, one number, recorded once by
    # `damage_events._announce`. It is the damage *dealt* (CR 120.4b), not what
    # the life total lost: Ali from Cairo caps the second without capping the
    # first.
    #
    # This row is what retires a *deliberate refusal*. El-Hajjâj's "you gain
    # that much life" was recorded as one, on the grounds that "its fire site
    # records the amount under a different key" — which was true of a fire
    # site, not of the rule, and stopped being true the moment there was one
    # seam to record it at.
    "damage_dealt": "amount",
    # "Whenever that creature is dealt damage by an attacking creature this
    # turn, you gain **that much** life." (Glyph of Life.) A delayed triggered
    # ability (CR 603.7) reads its number from the same place an ordinary one
    # does — the context its fire site froze — so it is a row here rather than
    # anything the delayed machinery answers for itself.
    "bound_permanent_dealt_damage": "damage_dealt",
}

# The scratchpad key the untap records and two later sentences read ("remove
# **it** from combat", "gain control of **that creature**" — Disharmony). One
# name in one place, shared by the ``board`` and ``combat`` lowering families,
# because a fragment two families need lives here rather than in either of
# them — and because ``_records._PRODUCES`` writes the same string, so a
# second spelling would make the producer gate vacuous while the handler read
# an empty record.
_UNTAPPED_PERMANENTS = "untapped_permanents"

# What a one-way bite recorded it damaged, so the sentence after it can name the
# same creature: "This creature deals damage equal to its power to target
# creature. **That creature** deals damage equal to its power to this creature."
# (Tracker.) Named here for the reason the key above is - the `damage` lowering
# family and ``_records._PRODUCES`` both write the string, and a second
# spelling would make the producer gate vacuous while the handler read an empty
# record.
_DAMAGED_PERMANENTS = "damaged_permanents"

# The seat "Choose a player who cast one or more sorcery spells this turn."
# records, and the number "the damage dealt by one of those sorcery spells this
# turn" records once one of them is chosen (Backdraft). Named here beside the
# two above and for their reason: the `game` and `damage` lowering families and
# ``_records._PRODUCES`` all write these strings, so a second spelling would
# make one producer gate vacuous while the handler read an empty record — and
# on this card that is a spell that reports itself resolved and deals nothing.
CHOSEN_PLAYER = "chosen_player"

#: "That player chooses and sacrifices one of those creatures. Put a -1/-1
#: counter on **the other**." (Retribution.) The member of a chosen pair the
#: pick did *not* take, written by the same step that records the pick — the
#: only moment both are in hand. Asking the board instead would find whichever
#: of the two is still there, which is the same permanent on a card whose
#: sacrifice was replaced and a different one on a card whose other half died
#: to something else in between.
OTHER_CHOSEN_PERMANENT = "other_chosen_permanent"

# The scratchpad key a "<player> chooses <permanent>" step writes and the
# sentences behind it read — "attach it to **that** permanent" (Enchantment
# Alteration), "return this card … **attached to that creature**"
# (Takklemaggot). Named here for the reason every other key on this page is:
# the ``board`` and ``zones`` lowering families and ``_records._PRODUCES``
# all write the string, and a second spelling would make one producer gate
# vacuous while the handler read an empty record.
CHOSEN_PERMANENT = "attach_host"
CHOSEN_CAST_DAMAGE = "damage_dealt_by_chosen_cast"

#: The number "Count the number of permanents." records and "if **the number**
#: is odd" reads (Chaos Moon). Named here for the reason every other key on this
#: page is: the ``game`` and ``conditions`` lowering families and
#: ``_records._PRODUCES`` all write the string, and a second spelling would make
#: the producer gate vacuous while the condition read an empty record — which on
#: this card is a board that is neither odd nor even and a trigger that does
#: nothing.
#:
#: Deliberately **not** in ``_PRODUCED_QUANTITIES`` below. No card prints "draw
#: that many cards" after a count, and a bare back-reference resolving to this
#: would be a reading nothing exercises; the condition names the key outright.
COUNTED_NUMBER = "counted_number"

# The scratchpad keys that are *quantities*. `_records._PRODUCES` also records
# things no amount can read — a controller's seat, a list of exiled cards — so
# a bare back-reference resolves against this narrower set. A producer added
# there and not here fails safe: the bare reading refuses rather than reading a
# number out of something that is not one.
_PRODUCED_QUANTITIES: frozenset[str] = frozenset({
    "damage_dealt",
    # The power and toughness a destroy froze about the permanent it was aimed
    # at, which is where a token's stated P/T reads them (Broken Visage). Both,
    # because the card states both halves and a bare "that much" after a
    # destroy would otherwise have two numbers to choose between — which
    # `_back_reference_payload` refuses outright rather than picking one.
    _EVENT_SUBJECT_POWER_RECORD,
    _EVENT_SUBJECT_TOUGHNESS_RECORD,
    # How many counters a "loses all <kind> counters" step took off (Leeches),
    # which is what "deals **that much** damage to that player" reads.
    COUNTERS_REMOVED,
    # How many cards a discard this effect asked for actually went (Recall).
    "discarded_count",
    # How many cards a "puts the cards from their hand on top of their library"
    # step moved (Jester's Mask), which is what the search behind it counts.
    HAND_CARDS_TO_LIBRARY,
    CHOSEN_CAST_DAMAGE,
})

# The scratchpad keys that hold *permanents*, by id — what an earlier step of
# this effect acted on rather than a number it computed. A clause reading a
# characteristic off "that creature" (Energy Tap's mana value) resolves against
# these: the permanent is still on the battlefield, so the characteristic is
# read at resolution instead of being remembered. The mirror of
# `_PRODUCED_QUANTITIES` above and narrow for the same reason — a producer
# missing from here refuses the words rather than reading a mana value out of
# something that is not a permanent.
#: The tap half of the pair, named for the same reason ``_UNTAPPED_PERMANENTS``
#: is: two lowering families and ``_records._PRODUCES`` all write this string,
#: and a second spelling would make one of the producer gates vacuous while the
#: handler read an empty record.
_TAPPED_PERMANENTS = "tapped_permanents"

#: What ``deal_damage`` recorded about the object or player it damaged: which
#: kind of thing it was, and how much it could absorb *before* the damage
#: landed. The only place "…but not more life than the player's life total
#: before the damage was dealt" (Drain Life, Soul Burn) can be read from — by
#: the time the gain runs, the life total is the one the damage left behind.
#: Named here rather than spelled in both files for ``_TAPPED_PERMANENTS``'
#: reason: a second spelling makes the producer gate vacuous while the handler
#: reads an empty record.
DAMAGE_RECIPIENT = "damage_recipient"

#: "Target creature you control can't be blocked this turn. **Destroy it** …"
#: (Goblin Sappers.) The grant records which creature it chose, for the reason
#: the tap and untap pair do: the sentence after it names that creature and
#: nothing else in the resolution can say which one it was.
_UNBLOCKABLE_PERMANENTS = "unblockable_permanents"

#: "…put a paralyzation counter on each creature blocking or blocked by this
#: creature and tap **those creatures**." (Dread Wight.) The placement records
#: which permanents it marked, because the three sentences behind it — the tap,
#: the untap restriction and the granted ability — all name that set and none of
#: them can be asked to work it out again: the relation is to a combat that ends
#: in the same step the trigger resolves in (CR 511.2), so by the next sentence
#: there may be no combat left to read.
_PERMANENTS_GIVEN_COUNTERS = "permanents_given_counters"

#: "Distribute three +1/+1 counters among one, two, or three target creatures.
#: **For each +1/+1 counter you put on a creature this way,** …" (Bounty of the
#: Hunt.) Re-exported from ``oracle_types`` under this module's private spelling,
#: the way every other record name here is: the handler that writes it and the
#: lowering that gates on it sit at opposite ends of the pipeline, so the string
#: lives in the module neither imports from.
_COUNTERS_PLACED_THIS_WAY = COUNTERS_PLACED_THIS_WAY

#: "Return target … creature card from your graveyard to the battlefield.
#: **That creature** gains "Cumulative upkeep {2}."" (Dreams of the Dead.) The
#: reanimation records the permanent it created, because it is the only step
#: that can name it: the permanent did not exist when the ability was
#: activated, so nothing on the stack or on the board points at it.
_REANIMATED_PERMANENTS = "reanimated_permanents"
#: "Take an extra turn after this one. At the beginning of **that turn's** end
#: step, you lose the game." (Final Fortune.) The turn the step before it
#: queued, recorded so the delay behind it has a producer to name: "that turn"
#: with nothing in front of it that made one is a back-reference to nothing, and
#: the delayed ability it would arm answers to an event that only ever happens
#: on somebody's extra turn — inert rather than wrong, which is the failure this
#: whole registry exists to refuse.
EXTRA_TURN_GRANTED = "extra_turn_granted"

#: "You may put a creature card from your hand onto the battlefield. If you do,
#: sacrifice **it** unless you pay…" (Flash.) The permanent that step created,
#: for the reanimation's reason one entry down: the card was in a hand when the
#: spell was cast, so nothing on the stack or on the board pointed at the
#: permanent until this step made it.
PUT_FROM_HAND_PERMANENTS = "put_from_hand_permanents"


_RECORDED_PERMANENTS: frozenset[str] = frozenset({
    _TAPPED_PERMANENTS, _UNTAPPED_PERMANENTS, _UNBLOCKABLE_PERMANENTS,
    _PERMANENTS_GIVEN_COUNTERS, _REANIMATED_PERMANENTS,
    PUT_FROM_HAND_PERMANENTS,
    # What a search put onto the battlefield (Zirilan of the Claw). The
    # reanimation's twin one zone over, and a member of this set for that
    # entry's reason: "that creature" behind either step names the permanent
    # the step created, and a reader that knew only one of them would refuse
    # the other for no reason a card could see.
    SEARCHED_PERMANENTS,
})


#: What the bare possessive "**its** <characteristic>" reads when the step in
#: front of it acted on a *spell* rather than on a permanent.
#:
#: "Destroy target artifact. You gain life equal to **its** mana value" (Divine
#: Offering) and "Counter target artifact or enchantment spell. Its controller
#: gains life equal to **its** mana value" (Illumination) print the same word
#: for the same question, and the two steps answer it in two records —
#: ``its_mana_value`` off a permanent, ``countered_spell_mana_value`` off a
#: stack object. Two records rather than one, for the reason
#: ``oracle_types.COUNTERED_SPELL_CONTROLLER`` gives one file over: a spell on
#: the stack is not a permanent, it is written by a different handler at a
#: different moment, and a card can only ever be in front of one of them.
#:
#: So the *pronoun* is resolved here, in the one place that already decides
#: where a back-reference reads from, rather than by making one handler write
#: the other's key — which would be the same number under two names, free to
#: disagree the day either is computed differently.
_SPELL_POSSESSIVE_RECORDS: dict[str, str] = {
    "its_mana_value": "countered_spell_mana_value",
}


def _back_reference_payload(
    amount: ast.ThatMuch,
    produced: frozenset[str],
    event: str | None,
) -> dict[str, object]:
    """Where a handler should read *amount* from, as payload keys.

    ``amount_from`` is a key in this resolution's scratchpad (an earlier step of
    the same effect recorded it); ``amount_from_trigger`` is a key in the firing
    event's captured context. Which one applies is decided here, once, rather
    than by each effect family guessing — reading a trigger's number out of the
    scratchpad silently yields zero, which is the failure this refuses on
    behalf of every caller.
    """
    if amount.source == "event_subject_power":
        # "That creature's power" names the *event's* object, so under a trigger
        # the only place it can be read is the firing event's captured context —
        # and only under an event whose fire site records one.
        key = _EVENT_QUANTITIES.get(event or "")
        if key is not None:
            return {"amount_from_trigger": key}
        # "Destroy target nonartifact attacking creature. … Its power is equal
        # to **that creature's power**." (Broken Visage.) With no trigger at all
        # there is no event for the words to be about, and the creature the
        # sentence names is the one an earlier step of this same effect acted on
        # — which is the reading "that creature's mana value" already takes one
        # characteristic over. Gated on the record existing, so a spell with no
        # such step still refuses by name rather than reading a zero: by the
        # time the token is built the creature is a card in a graveyard with no
        # characteristics at all (CR 613.1), so the number has to have been
        # frozen when it left (CR 608.2h).
        if _EVENT_SUBJECT_POWER_RECORD in produced:
            return {"amount_from": _EVENT_SUBJECT_POWER_RECORD}
        raise LoweringError(
            "\"that creature's power\" needs a trigger whose event records "
            "one, or a step of this effect that recorded one",
            node=amount,
        )
    if amount.source is not None:
        # The words named the producer ("equal to the damage dealt"), so a step
        # of this same effect has to have recorded it.
        if amount.source in produced:
            return {"amount_from": amount.source}
        # …or recorded it about a **spell**, under the key the spell's own
        # handler writes. See ``_SPELL_POSSESSIVE_RECORDS``.
        alias = _SPELL_POSSESSIVE_RECORDS.get(amount.source)
        if alias is not None and alias in produced:
            return {"amount_from": alias}
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this effect",
            node=amount,
        )
    key = _EVENT_QUANTITIES.get(event or "")
    if key is not None:
        return {"amount_from_trigger": key}
    within = tuple(sorted(produced & _PRODUCED_QUANTITIES))
    if len(within) == 1:
        return {"amount_from": within[0]}
    raise LoweringError(
        "bare back-reference with no producer in this effect and no quantity "
        "on its trigger",
        node=amount,
    )


# Trigger events that bind a *blocking pair*, so "that creature" names the other
# half of it — "destroy that creature at end of combat" (Thicket Basilisk),
# "that creature becomes green" (Aisling Leprechaun). The sentence only means
# what it says while one of these fired, so anywhere else the pronoun refuses.
#
# **Which** half fired decides how the handler finds the creature, and the two
# fire sites answer differently: the becomes-blocked half makes it the stack
# item's target, the blocks half puts it in `blocked_permanent_ids` and targets
# the blocker itself. `handlers/_common.block_pair_permanents` is the one reader
# of both, so an effect added here does not have to rediscover the difference.
_BLOCK_PAIR_EVENTS = frozenset({
    "creature_blocks_or_blocked_by",           # Thicket Basilisk, Cockatrice,
                                               # Abomination, Aisling Leprechaun
    "creature_becomes_blocked",                # Battering Ram
    "creature_blocks",                         # Infernal Medusa
    # The **delayed** spelling of the first row (Goblin Flotilla), announced by
    # the same two fire sites with the same `blocked_permanent_ids` key — so
    # "that creature" under it is the same question with the same answer, and a
    # set that left it out would refuse the created ability while admitting the
    # printed one.
    "source_blocks_or_blocked_by",
})


def binds_block_pair(event: str | None, event_subject: object | None) -> bool:
    """Whether "that creature" under *event* names exactly one creature.

    **The kind alone cannot answer**, and reading it as though it could was
    wrong in both directions at once. CR 509.3c/509.3d: "whenever this creature
    becomes blocked" fires *once* however many creatures block it, while
    "…becomes blocked **by a creature**" fires once for each one the phrase
    admits — the narrowing is the whole difference, and the two spellings are
    the same kind.

    So a bare firing has several creatures and no way to say which "that
    creature" is (the fire site takes ``blockers[:1]``, an arbitrary one), and a
    narrowed firing has exactly the one that admitted it. Keyed on the kind
    alone, this table admitted the bare becomes-blocked form — a sentence that
    would destroy whichever blocker happened to be first — and refused the
    narrowed *blocks* form, which is why Infernal Medusa was supported with its
    first line lowering to nothing.

    `creature_blocks_or_blocked_by` carries a subject by construction: both
    front ends require the noun phrase to end the condition, so the joined
    sentence cannot reach here bare.
    """
    return event in _BLOCK_PAIR_EVENTS and event_subject is not None


def _chosen_cast_amount(
    amount: ast.Amount,
) -> "tuple[ast.DamageDealtByChosenCast, str | None] | None":
    """"[half] the damage dealt by one of those <type> spells this turn", and
    how the card said to round it — or None when the amount is something else.

    The halving is unwrapped here rather than inside the branch below, for the
    reason ``lower_where_x`` unwraps ``ast.Times``: the rounding belongs to the
    printed quantity and rides the count spec every computed amount already
    travels on (CR 107.2).
    """
    rounding = None
    if isinstance(amount, ast.Half):
        rounding = amount.rounding
        amount = amount.of
    return (amount, rounding) if isinstance(amount, ast.DamageDealtByChosenCast) else None


#: Trigger events whose *condition* already names the permanent the source is
#: attached to. Under one of them a later "that <noun>" in the same sentence is
#: that same permanent — "At the beginning of the upkeep of enchanted land's
#: controller, destroy **that land**" (Erosion), "…unless they sacrifice **that
#: artifact**" (Curse Artifact).
#:
#: Idiom 20's rule with the noun repeated instead of "it": the pronoun names the
#: object the sentence already named. It has to be an event set rather than a
#: property of the noun phrase, because "that land" under any *other* event is
#: the firing event's object (Hooded Blightfang's damaged planeswalker) and
#: under most events is nothing at all — and a "that" resolved against the
#: wrong one of those does not fail, it acts on a different permanent.
ATTACHED_SUBJECT_EVENTS: frozenset[str] = frozenset({
    "upkeep_enchanted_controller",
    # "At the beginning of the end step of enchanted creature's controller,
    # destroy **that creature** …" (Aggression). The same printed shape one
    # step later, and the same referent — which is why the parse side reads
    # both through one production.
    "end_step_enchanted_controller",
})


def names_attached_permanent(subject, event: str | None) -> bool:
    """Whether *subject* names the permanent the ability's source is attached to.

    One reader for both spellings — "it"/"enchanted <noun>", which the noun
    parser already marks, and the repeated "that <noun>" above — so a lowering
    that learns one gets the other and the two cannot come to disagree about
    which permanent an Aura's sentence is talking about.
    """
    from ._common import _is_enchanted

    if _is_enchanted(subject):
        return True
    return (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
        and event in ATTACHED_SUBJECT_EVENTS
    )
