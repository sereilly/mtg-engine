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

The **scratchpad key names** left at Tempest's Phase 0, for the half of that
same sentence this module had stopped keeping: a key one step of a resolution
writes and a later sentence reads back (CR 608.2) is keyed by nothing and is
not about a firing event at all. They are `_record_keys.py` now, re-exported
from here so no family's import moved, and `_records` next door already said
the line — "three tables, three keys, three questions".
"""

from __future__ import annotations

from ...exiled_records import (EXILE_RECORD_KEY,
                               EXILED_SPELL_CONTROLLER_KEY)

from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER,  # noqa: F401
                             LAST_TARGET_CONTROLLER,
                             EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS)
from .. import ast
from ..errors import LoweringError
from ._deaths import (DEAD_CHARACTERISTIC_EVENTS, DEAD_CHARACTERISTIC_RECORDS,
                      _EVENT_SUBJECT_POWER_RECORD,
                      _EVENT_SUBJECT_TOUGHNESS_RECORD)
# The scratchpad key *names*, split out at Tempest's Phase 0 along the line both
# this docstring and `_records`' already drew: nothing over there is keyed by a
# trigger-condition kind. Re-exported under the names this module used, so every
# family that reads one is untouched — `_common` and `_filters` have the same
# arrangement, and for the same reason.
from ._record_keys import (CHOSEN_CAST_DAMAGE,  # noqa: F401
                           CHOSEN_DAMAGE_SOURCE, CHOSEN_PERMANENT,
                           CHOSEN_PLAYER, COUNTED_NUMBER, CREATED_TOKEN,
                           DAMAGE_RECIPIENT, EXTRA_TURN_GRANTED,
                           LOOP_BOUND_OBJECT, LOOP_BOUND_PLAYER,
                           OTHER_CHOSEN_PERMANENT, PUT_FROM_HAND_PERMANENTS,
                           SWEPT_CONTROLLER_SEATS,
                           _COUNTERS_PLACED_THIS_WAY, _DAMAGED_PERMANENTS,
                           _PERMANENTS_MADE_BY_THIS_EFFECT,
                           _PRODUCED_QUANTITIES, _REANIMATED_PERMANENTS,
                           _RECORDED_PERMANENTS, _SPELL_POSSESSIVE_RECORDS,
                           _TAPPED_PERMANENTS, _UNTAPPED_PERMANENTS)

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
    # "Whenever a Djinn or Efreet enters, **destroy it**." (Suleiman's Legacy.)
    # The entering permanent, stamped by the one entry transition
    # (`_put_permanent_onto_battlefield`) — every path onto a battlefield goes
    # through it, so the announcement and the freeze are one place.
    "matching_permanent_enters",
    # "Whenever a creature attacks you, **it** loses flanking until end of
    # turn" / "…this enchantment deals 1 damage to **it**" (Barbed Foliage).
    # The declared attacker, stamped by `_fire_matching_creature_attacks_triggers`
    # for the same reason `become_tapped` stamps its subject: the announcement
    # is game-wide and per object, and by resolution the creature may have been
    # removed from combat or destroyed.
    "matching_creature_attacks",
    # "Whenever a creature of the chosen color deals damage to you …, this
    # enchantment deals that much damage to **that creature**." (Mangara's
    # Equity.) CR 120.4b's event, whose one seam (`damage_events._announce`)
    # freezes the damager's id — the object the words name, which is the *other*
    # end of the event from the permanent it damaged.
    "damage_dealt",
    # "Whenever a creature is dealt damage, **destroy it**." (Death Pits of
    # Rath.) The *damaged* creature, which is what the subject of this event is
    # — the row above is the other way round, and the two are the two ends of
    # one damage event (`_EVENT_SUBJECT_CONTROLLERS` says the same thing about
    # the seats). Frozen by `_fire_dealt_damage_triggers`, which stamps the id
    # while the creature is still on a battlefield: this trigger resolves off
    # the stack (CR 603.3) and lethal damage puts it in a graveyard before then,
    # where CR 400.7 makes it a new object.
    "creature_dealt_damage",
    # "Whenever a Sliver becomes blocked, **that Sliver** gets +1/+1 until end
    # of turn for each creature blocking it." (Spined Sliver.) The creature
    # that became blocked — the attacker, which is the half this board-wide
    # event is announced *about*; its partner is the blocker, and
    # `ROLE_NAMES_BLOCK_PARTNER` below is where a printed role word reaches
    # that one instead.
    #
    # Both of the kind's fire sites stamp the id
    # (`declare_blockers_step._fire_board_wide_block_triggers` for CR 509.3d's
    # narrowed reading, `_announce_bare_board_wide_blocks` for CR 509.3c's bare
    # one), which is what this table is a claim about — and the *source*-scoped
    # scan one screen up announces `creature_becomes_blocked`, a different kind
    # that is not here.
    #
    # Not `_BLOCK_PAIR_EVENTS`, deliberately: under that set "that creature"
    # names the *other* half of the pair, and `binds_block_pair` additionally
    # requires the printed narrowing that makes a bare firing name one creature.
    # A bare "becomes blocked" has several blockers and one attacker, so the
    # attacker is exactly the referent a bare firing can answer for.
    "matching_creature_becomes_blocked",
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


# What a bare "that much" names when the effect is a *triggered ability*: the
# quantity the firing event carried, frozen into the trigger's context by the
# fire site. Keyed by trigger-condition kind, and deliberately a table rather
# than a rule — an event either carries a number or it does not, and a kind
# absent here refuses the back-reference instead of reading a zero out of an
# empty context.
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


#: The **toughness** twin of the table above, keyed by trigger kind the same way.
#:
#: A second table rather than more rows in that one, and ``amounts.py`` already
#: wrote down why: every row of ``_EVENT_QUANTITIES`` names a *power*, so a
#: toughness read through it would silently be handed one. Two characteristics
#: of one object are two numbers, and a reader given the wrong one is wrong on
#: every card whose P and T differ — which is most of them.
#:
#: Membership is a claim about a fire site, exactly as it is next door: the
#: entry transition (``_put_permanent_onto_battlefield``) freezes
#: ``entering_toughness`` beside the power it already froze, on every entry,
#: because the cost is one integer and the alternative is a fire site that has
#: to know which cards care.
_EVENT_TOUGHNESS_QUANTITIES: dict[str, str] = {
    # "Whenever a creature you control enters, you gain life equal to **its
    # toughness**." (Angelic Chorus.)
    "matching_permanent_enters": "entering_toughness",
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
        # "…**its controller** loses life equal to **its power** and you gain
        # life equal to **its toughness**." (Death Watch.) "It" is the dead
        # permanent, so no step of this effect produced the number — the fire
        # site froze it. Read here, where a back-reference's home is already
        # decided, so the two halves of one sentence cannot answer differently.
        record = DEAD_CHARACTERISTIC_RECORDS.get(amount.source)
        if record is not None and event in DEAD_CHARACTERISTIC_EVENTS:
            return {"amount_from_trigger": record}
        # "Whenever a creature you control enters, you gain life equal to **its
        # toughness**." (Angelic Chorus.) The same phrase under an event that is
        # not a death: no step of this effect produced the number and no
        # graveyard holds it, so it is the entry's own frozen toughness — read
        # off its own table for the reason that table exists, one screen up.
        if amount.source == _EVENT_SUBJECT_TOUGHNESS_RECORD:
            toughness = _EVENT_TOUGHNESS_QUANTITIES.get(event or "")
            if toughness is not None:
                return {"amount_from_trigger": toughness}
        raise LoweringError(
            f"back-reference to {amount.source!r} with no producer in this effect",
            node=amount,
        )
    # A step of **this** effect that produced a number is read before the
    # trigger's own, because it is the nearer antecedent: "that player discards
    # all the cards in their hand, then draws **that many** cards" (Shocker) is
    # one sentence about the discard, under a trigger whose event also carries a
    # number (the damage dealt). Read the other way round, Shocker draws cards
    # equal to its power — a card that plays, compiles and is wrong, with
    # nothing in this repo able to see it.
    #
    # Only when the effect produced **exactly one**: two candidate numbers is a
    # sentence with two readings, and picking one of them is the guess this
    # whole function exists to refuse.
    within = tuple(sorted(produced & _PRODUCED_QUANTITIES))
    if len(within) == 1:
        return {"amount_from": within[0]}
    key = _EVENT_QUANTITIES.get(event or "")
    if key is not None:
        return {"amount_from_trigger": key}
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


#: For each printed combat role, the events under which that role names the
#: **partner** — the other half of the pair the firing is about, which
#: ``handlers/_common.block_pair_permanents`` resolves.
#:
#: The mirror of ``rebinding._ROLE_EVENT_SUBJECTS``, which says when a role names
#: the event's *own* subject; between them they are the two objects a block event
#: has, and an event appears in at most one of the two per role. "Whenever a
#: creature becomes blocked by …" is announced about the attacker, so under it
#: "the blocking creature" is the partner; "whenever a creature blocks …" is
#: announced about the blocker, so under it "the attacking creature" is.
#:
#: Only the board-wide kinds are here. Under the source-scoped ones the partner
#: is still what ``block_pair_permanents`` returns, but the *combatant* is the
#: ability's own source and the pool spells the partner "that creature" — the
#: reading the four lowerings gated on :func:`binds_block_pair` already have. A
#: role word admitted there as well would be a second spelling of one referent.
ROLE_NAMES_BLOCK_PARTNER: dict[str, frozenset[str]] = {
    "blocking": frozenset({"matching_creature_becomes_blocked"}),
    "attacking": frozenset({"matching_creature_blocks"}),
}


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


def names_attached_permanent(
    subject, event: str | None, event_subject=None
) -> bool:
    """Whether *subject* names the permanent the ability's source is attached to.

    One reader for both spellings — "it"/"enchanted <noun>", which the noun
    parser already marks, and the repeated "that <noun>" above — so a lowering
    that learns one gets the other and the two cannot come to disagree about
    which permanent an Aura's sentence is talking about.

    *event_subject* is the firing trigger's own printed subject, and it answers
    the case the event set above cannot. :data:`ATTACHED_SUBJECT_EVENTS` holds
    the conditions that are *only ever* printed about an attached permanent, so
    the kind alone settles them; "becomes the target of a spell or ability" is
    not one — the same kind is printed about "this creature" (Warden of the
    Woods) and about "enchanted creature" (Spinal Graft), and adding it to that
    set would make the Warden's "that creature" name a permanent it is not
    attached to. The condition's own subject is what tells the two apart, and
    it is already threaded through every lowering that could need it.

    The noun must be the one the condition named, for the reason the "that"
    test above is bare: "that creature" is a back-reference and "that creature
    you control" is a phrase that chose for itself.
    """
    from ._common import _is_enchanted

    if _is_enchanted(subject):
        return True
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier == "that"
        and not subject.targeted
    ):
        return False
    if event in ATTACHED_SUBJECT_EVENTS:
        return True
    return (
        getattr(event_subject, "is_enchanted", False)
        and tuple(getattr(event_subject, "card_types", ())) == subject.filter.card_types
        and not set(subject.filter.to_payload()) - {"type_filter"}
    )


def chooser_payload(statement, event: str | None, what: str) -> dict[str, object]:
    """Who names the value a "choose a <thing>" sentence produces.

    Here rather than in the dispatcher that calls it, and that is the point of
    the move: the answer is a fact about the **event** — which seat, if any, the
    firing froze — and this module is where that fact already lives
    (``_EVENT_SUBJECT_PLAYERS``, ``EVENT_SUBJECT_PLAYER``). A dispatcher arm
    re-deriving it was the dispatch layer holding a second copy of an events
    fact, and the two would drift the first time a trigger kind joined that set.

    Shared by the colour choice (Chromatic Armor, Hall of Gemstone) and the card
    type (Teferi's Realm), because the question is the same one and the two arms
    were the same twenty lines with a noun changed. *what* is that noun, for the
    refusal message.

    Empty is CR 601.2b's default — the ability's controller, which the handler
    reads off the source — and is the payload every printing before Hall of
    Gemstone produced, so nothing already compiled moves.

    "That player" is the seat the firing event froze (CR 603.10), and it refuses
    under an event that froze none: the prompt would otherwise go to whoever the
    resolution happened to be holding, which is the refusal every other reading
    of those two words in this package makes.
    """
    chooser = statement.chooser
    if chooser is None:
        return {}
    if chooser.kind != "that_player":
        raise LoweringError(
            f"no {what} choice is made by {chooser.kind!r}", node=statement
        )
    if event not in _EVENT_SUBJECT_PLAYERS:
        raise LoweringError(
            f"no event named {event!r} freezes the seat \"that player\" names",
            node=statement,
        )
    return {"chooser": EVENT_SUBJECT_PLAYER}


#: What ``handlers/stack.exile_target_spell`` writes to the resolution
#: scratchpad: the :class:`~engine.exiled_records.ExiledRecord` for the spell it
#: moved to exile, and the seat that spell's controller was. Imported from
#: ``engine/exiled_records.py`` rather than spelled again, because that module
#: is where the *reader* lives and it imports nothing from the engine — so the
#: handler layer and this package can both name the key without either importing
#: the other, which is the second-copy failure every key here exists to avoid.
EXILED_SPELL_RECORD = EXILE_RECORD_KEY
EXILED_SPELL_CONTROLLER = EXILED_SPELL_CONTROLLER_KEY
