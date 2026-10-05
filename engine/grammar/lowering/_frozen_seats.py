"""Which **seat** a firing event froze — the referent behind "that player".

The first of the three questions ``_events`` names in its own opening sentence
("that player", "that much", "they") and the first to leave it, at Mercadian
Masques' second Phase 0, when that module reached 990 of the thousand-line
guard as a *floor* every lowering family reads — so no single group would have
crossed it alone and none could be told to expect the split. ``_records`` next
door had already drawn the line this follows: "three tables, three keys, three
questions".

Everything here is keyed by **trigger-condition kind**, which is what separates
it from ``_seats`` one file over: that module answers "which seats does this
printed ``PlayerRef`` name", a question about the *sentence*, and this one
answers "which seat did the event that fired this leave behind", a question
about CR 603.10's frozen context. Two questions, two keys, and folding them
would give one table two meanings.

Each is a *table* rather than a rule, for the reason ``_events`` states and
this half is the sharper case of: a seat rule would have to guess, and a guessed
seat is silent in the worst direction — the effect lands on whichever player the
resolution happened to be carrying. A condition absent from a table refuses the
line instead.

A **floor**, not a family: ``_events`` re-exports every name below under the
spelling it had, so not one family's import moved at the split.
"""

from __future__ import annotations


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
    # "Whenever this creature becomes blocked, **defending player** discards a
    # card." (Alley Grifters, Corrupt Official, Port Inspector, Robber Fly.)
    # The declare-*blockers* fire site
    # (`declare_blockers_step._fire_becomes_blocked_triggers`) stamps the same
    # key off `combat_attackers`, which is what puts the kind in this set — the
    # entry is the list of events that stamped it, never the list of events on
    # which the phrase reads plausibly.
    "creature_becomes_blocked",
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
    # Death Watch, Decomposition — the dead **enchanted** creature's, from the
    # same ``died_context`` the two rows below read. Not the Aura's controller
    # and not the caster: an Aura on somebody else's creature is the point.
    "attached_creature_dies",
    "creature_opponent_controls_dies",   # Massacre Wurm — the dead creature's
    # Earthlink — the dead creature's, from the same stamp
    # (`_fire_creature_dies_triggers` freezes one `died_context` for every
    # death condition it announces). The unscoped spelling of the row above:
    # "whenever **a** creature dies" watches every battlefield, and "that
    # creature's controller" is still the seat that controlled the one that
    # died — which under a control-change effect is not its owner.
    "creature_dies",
    # "Whenever **a creature** blocks, this enchantment deals 1 damage to **that
    # creature's controller**." (Heat of Battle.) The board-wide spelling of the
    # row below: the watcher is neither combatant, so the seat cannot be read
    # off the source — the declare-blockers announcement freezes it, exactly as
    # the source-scoped scan does for the creature it is about.
    "matching_creature_blocks",
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
    # "Whenever a green creature dies, **its controller** discards a card."
    # (Bereavement.) The dead permanent's, frozen by
    # ``_fire_permanent_dies_triggers`` while the seat is still knowable — by
    # resolution the permanent is a card in a graveyard, which CR 108.4 gives no
    # controller, and under a control-change effect that seat was never its
    # owner either. The board-wide sibling of ``creature_dies`` above: CR 700.4
    # makes "dies" mean "put into a graveyard from the battlefield", and this is
    # the kind a *narrowed* death compiles to.
    "permanent_dies",
})


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
    # "Whenever a permanent is returned to a player's hand, **that player**
    # discards a card." (Warped Devotion.) The seat whose hand it is — the
    # permanent's owner (CR 400.3), never its controller and never whoever
    # bounced it — frozen by ``Game.put_card_into_hand``'s announcement,
    # because by resolution the object is a card in a hand among many and
    # nothing on a board says which move this trigger was about.
    "permanent_returned_to_hand",
    # "At the beginning of combat on each opponent's turn, separate all
    # creatures **that player** controls into two piles." (Fight or Flight.)
    # The seat whose combat it is, frozen by `phases/combat_phase.py`'s
    # announcement — it varies per firing exactly as `upkeep_each`'s does.
    # `combat_your_turn` stays out for `upkeep_self`'s reason.
    "combat_opponent_turn",
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
    # "Whenever an opponent discards a card, this enchantment deals 2 damage to
    # **that player**" (Megrim). The draw row's twin one action over, admitted
    # for its reason: CR 701.9a's discard is about one seat, which seat varies
    # per firing, and the two discard seams (`Game._discard_card` and
    # `_resolve_one_discard`) announce it through `announce_discard` — which
    # freezes the discarding seat because nothing on a board records it once the
    # card is in a graveyard.
    "discards_card",
    # "At the beginning of each opponent's draw step, **that player** draws an
    # additional card …" (Malignant Growth). The seat whose draw step it is,
    # frozen by `phases/draw_step.py`'s enqueue — which seat varies per firing,
    # exactly as `upkeep_each`'s does, so it cannot be re-derived at resolution
    # from the source's controller.
    "draw_step_each",
    # "At the beginning of each player's first main phase, **that player** adds
    # {G}{G}." (Eladamri's Vineyard.) The seat whose main phase it is, frozen by
    # `phases/precombat_main_phase.py`'s enqueue — it varies per firing exactly
    # as the upkeep and draw-step rows above do, so it cannot be re-derived at
    # resolution from the source's controller. `main_phase_first` stays out, for
    # `upkeep_self`'s reason: "your first main phase" has one seat and it is
    # spelled "you".
    "main_phase_first_each",
    # "Whenever an opponent casts an instant spell …, this creature deals 4
    # damage to **that player**" (Ichneumon Druid). The condition names one
    # seat — whoever cast the spell — and nothing chose it, so it is the seat
    # the cast froze rather than a target. Read as `target_player` instead, the
    # ability would ask for a choice the card never offers.
    "opponent_casts_spell",
    # "Whenever a player casts a spell, this enchantment deals 2 damage to
    # **that player**" (Spellshock). The unnarrowed spelling of the row above:
    # the same announcement, made for every seat's cast rather than an
    # opponent's, and the same seat frozen by the same fire site
    # (`_apply_spell_cast_any_triggers`, which now stamps
    # ``event_subject_player`` on both of its emits rather than only the
    # opponent-scoped one). Which seat cast varies per firing and nothing on a
    # board records it once the spell has resolved, so it cannot be re-derived
    # — and read as `target_player` instead the ability would ask for a choice
    # neither card offers, which under a duel is the caster's opponent whether
    # they cast the spell or not.
    "spell_cast",
    # "Whenever a player attacks with one or more creatures, destroy all …
    # creatures **that player** controls" (Total War). The declaration names
    # the attacking seat and the declare-attackers step freezes it; under the
    # seat-narrowed readings of this same condition ("whenever **you** attack")
    # the phrase would mean the controller, which is the same answer — so one
    # entry covers every row of the kind.
    "attackers_declared",
    # "Whenever a player plays a land, **that player** draws a card." (Horn of
    # Greed.) CR 305.1's special action names the playing seat and nothing
    # chose it; which seat it is varies per firing, and by resolution the land
    # is an ordinary permanent whose controller says nothing about who played
    # it. Frozen by the announcement in `mixins/stack/resolution.py`, beside the
    # ``seat`` key that event's own filter compares.
    "land_played",
    # "Whenever a player taps a land for mana, this enchantment deals 1 damage
    # to **that player**" (Manabarbs). The condition names the tapping seat and
    # nothing chose it. This event's trigger resolves *inline* at the
    # tap-for-mana seam in `mixins/turn_management.py` (CR 605.4a keeps its
    # triggered-mana siblings off the stack, and the damage rides the same
    # moment) — so the fire site is still holding the seat when it executes
    # the instruction, which is the freeze.
    "land_tapped_for_mana",
    # "Whenever this enchantment becomes the target of a spell, **that spell's
    # controller** loses 5 life" (Forsaken Wastes). CR 603.2's event names the
    # object that did the targeting and nothing on a board can recover its
    # controller once it has resolved or been countered, so the seat exists only
    # on the event `_announce_targeting` announces — which is what makes this a
    # row here rather than a fall-back to the ability's own controller. Without
    # it "that spell's controller" lowered to a bare recipient and the 5 life
    # came off whoever a targetless resolution defaults to, which in a duel is
    # the opponent whether they cast the spell or not.
    "self_becomes_target",
    # "At the beginning of the upkeep of enchanted <noun>'s controller, …
    # **that player** …" (the punishment Auras: Cursed Land, Feedback,
    # Maddening Wind, Mind Whip, Wanderlust, Warp Artifact, Curse Artifact).
    # The seat varies with the attachment, and the ordinary upkeep loop
    # (`phases/upkeep_step.py`) freezes whose upkeep the firing is as it
    # enqueues the trigger — after checking, through
    # `upkeep_trigger_seat_matches`, that it is the host's controller's.
    "upkeep_enchanted_controller",
    # The same clause naming the **end step** instead — "At the beginning of the
    # end step of enchanted creature's controller, this Aura deals 2 damage to
    # **that player**" (Insubordination). A separate condition kind because the
    # two are dispatched by different steps (CR 502 and CR 513), and a separate
    # row here for the same reason the kinds are separate: membership is a claim
    # about the *fire site*, and `phases/end_step.py`'s scan is the one that
    # stamps this seat — after checking, through `end_step_trigger_seat_matches`,
    # that it is the host's controller's.
    "end_step_enchanted_controller",
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


#: The payload key those fire sites stamp it under. One constant for the same
#: reason `EVENT_SUBJECT_PLAYER` is one: the fire site writes it and the handler
#: reads it, and three copies of a string is how they come apart.
EVENT_SUBJECT_OWNER = "event_subject_owner"


#: The payload spelling both a recipient and a condition subject use for that
#: seat. One constant, because the fire site writes it, the life handler reads
#: it and `evaluate_condition` reads it — three copies of a string is how they
#: come apart.
EVENT_SUBJECT_PLAYER = "event_subject_player"


#: And the seat that *controlled* what the event was about, from
#: `_EVENT_SUBJECT_CONTROLLERS` above. A constant for `EVENT_SUBJECT_PLAYER`'s
#: reason, one table over: the fire site writes it, the damage lowering and the
#: sacrifice lowering both emit it, and three handlers read it.
EVENT_SUBJECT_CONTROLLER = "event_subject_controller"


#: The seat that controlled the **damaged** permanent of a `damage_dealt`
#: event, frozen by the one damage seam (`damage_events._announce`). The other
#: end of the event from :data:`EVENT_SUBJECT_CONTROLLER`, which is the
#: damager's — Backfire wants that one and Bellowing Fiend wants this one, off
#: the same announcement.
DAMAGED_PERMANENT_CONTROLLER = "damaged_permanent_controller"


def damage_trigger_names_damaged_end(event: str | None, event_subject) -> bool:
    """Whether a printed "that creature" under *event* names the **damaged**
    permanent rather than the damager.

    A `damage_dealt` event has two objects in it and the sentence names one of
    them with a bare pronoun, so something has to decide which — and getting it
    wrong is silent and exactly backwards: Bellowing Fiend would deal its 3
    damage to its *own* controller and none to the player whose creature it
    just hit, while reporting supported.

    The card decides, and it decides in the condition. A permanent spells
    **itself** "this creature" (CR 109.2's self-reference, written out by the
    lexer), so a "that creature" behind a trigger whose damager is the source
    cannot be the damager — there is no other creature in the sentence but the
    one it damaged. Where the damager is a *described* creature instead
    ("whenever **enchanted creature** deals damage to you", Backfire;
    "whenever **a creature of the chosen color** deals damage to you", Mangara's
    Equity) the phrase names that one, which is what
    :data:`_EVENT_SUBJECT_CONTROLLERS` already says.

    Only `damage_dealt`: every other condition in that table has one object in
    its event, so there is nothing to pick between and asking would be a second
    answer to a settled question.
    """
    return (
        event == "damage_dealt"
        and getattr(event_subject, "is_source", False)
    )
