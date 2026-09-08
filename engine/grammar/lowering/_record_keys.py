"""The names an earlier step of *this same resolution* records under.

Split out of `_events` at Tempest's Phase 0, when that module sat twelve lines
from the thousand-line guard as a floor eight lowering families read — the
shared-module case SET_PLAYBOOK.md says to pre-split rather than brief, since
no one group crosses it alone.

The line is one both neighbouring docstrings had already written, each about
the other. `_events` is titled

    "What a back-reference in a *triggered* ability names. … It is whatever the
    firing event froze (CR 603.10), because by the time the trigger resolves the
    creature is in a graveyard, the blocker has left combat, or the upkeep has
    moved on. … every value here is keyed by **trigger-condition kind**"

and `_records` beside it states the other half outright:

    "what a step **records** is keyed by *instruction kind*, where `_events`'
    tables are keyed by *trigger-condition kind* and `categories`' by which
    migration family a kind belongs to. Three tables, three keys, three
    questions"

Nothing here is keyed by a trigger-condition kind and nothing here is about a
firing event. Every name below is the *spelling* of a scratchpad key one step of
a resolution writes and a later sentence of the same effect reads back
(CR 608.2) — the very strings ``_records._PRODUCES`` writes, which is why nearly
every comment already ends by saying so. They accumulated in `_events` because
the module that decides **where** a back-reference reads from is the natural
place to keep both answers; keeping the two answers together is not the same as
keeping the two vocabularies together, and it is the vocabulary that grows.

**And it is the half that grows with the pool**, which is the playbook's
tiebreak. A trigger-condition table gains a row when a set prints an event the
engine already fires; a record key is minted whenever any step learns to leave
something behind for the sentence after it, which is most rounds — twenty-two
keys and sets here against nine event tables next door.

A **floor under a floor**, exactly as `_filters` is to `_common`: `_events`
imports every name and re-exports it, so the twenty-odd families reading
``CHOSEN_PLAYER`` or ``_RECORDED_PERMANENTS`` are untouched and nothing imports
this module directly. It reads ``oracle_types`` and ``tokens`` and no grammar
sibling at all, which is what makes it a floor rather than a second half — in
particular it does **not** read `_records`, so the module that writes these keys
and the module that names them cannot form a cycle.
"""

from __future__ import annotations

from ...oracle_types import (BASE_PT_SET_PERMANENTS,
                             CONTROL_EXCHANGED_PERMANENTS,
                             COUNTERS_PLACED_THIS_WAY,
                             COUNTERS_REMOVED, HAND_CARDS_TO_LIBRARY,
                             PER_OBJECT_SEAT_RECORDS, SEARCHED_PERMANENTS)
from ...oracle_types import (
    REMOVED_FROM_COMBAT_PERMANENTS as _REMOVED_FROM_COMBAT_PERMANENTS,
)
from ...tokens import CREATED_TOKEN_RESULT_KEY, CREATED_TOKENS_RESULT_KEY
# The two records a *death* freezes that are also produced quantities. `_deaths`
# is the floor beside this one that owns what a death leaves behind, and it
# reads nothing here, so the two sit side by side rather than one inside the
# other — the arrangement `_events` had with it before this split.
from ._deaths import (_EVENT_SUBJECT_POWER_RECORD,
                      _EVENT_SUBJECT_TOUGHNESS_RECORD)


#: The scratchpad key a token maker writes the created token's ``permanent_id``
#: under. Imported rather than spelled again: ``engine/tokens.py`` is the one
#: home for it, because the handler that writes it lives on the other side of
#: the pipeline from the lowering that gates the phrase on it.
CREATED_TOKEN = CREATED_TOKEN_RESULT_KEY

#: Its plural (Waylay). Imported rather than spelled again for the reason
#: above, and named here beside it so a lowering choosing between the two
#: reads them from one place.
CREATED_TOKENS = CREATED_TOKENS_RESULT_KEY

#: What "**exiled this way**" names (Martyr's Cry): the `produced` marker a
#: sweep that exiles stamps, and the scratchpad key it records the objects
#: under. Imported rather than spelled again for ``CREATED_TOKEN``'s reason —
#: the sweep handler writes them and this lowering gates on them, so the two
#: sides live on opposite ends of the pipeline and a second copy would rot.


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

#: "**Choose a source you control** and flip a coin. … the next time **that
#: source** would deal damage this turn…" (Desperate Gambit.) The permanent an
#: untargeted CR 609.7 source choice picked, written by the same
#: ``choose_permanent`` step the key above is written by and read by the two
#: damage clauses behind it.
#:
#: A key of its own rather than that one, and the distance between their names
#: is the reason: ``attach_host`` is what a sentence about *attaching* reads,
#: and one record under one name would let a card that chose a permanent for one
#: purpose satisfy a producer gate written for the other. Two questions, two
#: records — the same rule the pair above it keeps.
CHOSEN_DAMAGE_SOURCE = "chosen_damage_source"
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
    # How many cards a hand exile this effect performed actually took (Scroll
    # Rack), which is what "put **that many** cards from the top of your
    # library into your hand" reads. Its own key beside ``exiled_cards``
    # because a list is not a quantity: this set is what a *bare* back-reference
    # resolves against, and admitting the list would let "that much" name a
    # pile.
    "exiled_count",
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

#: "X target attacking creatures become blocked. Choking Vines deals 1 damage to
#: **each of those creatures**." The becomes-blocked step records which
#: creatures it chose, for the reason the tap and untap pair do: the sentence
#: behind it names them and nothing else in the resolution can say which they
#: were. The mirror image of ``_UNBLOCKABLE_PERMANENTS`` one entry up, which is
#: why it sits beside it (CR 509.1h is the one rule both sentences are about).
_BLOCKED_PERMANENTS = "blocked_permanents"

#: "Target creature you cast this turn has base power and toughness 0/1 until
#: your next upkeep. At the beginning of your next upkeep, put a +1/+1 counter
#: on **that creature**." (Cycle of Life.) The rewrite records which permanent
#: it chose, for the tap and untap pair's reason exactly: the sentence behind it
#: names that creature and chooses nothing itself — and here the reader is a
#: *delayed* ability a whole turn later (CR 603.7c), so a board read at that
#: moment could not tell the chosen creature from any other 0/1.
#: Re-exported from ``oracle_types`` under this module's private spelling, the
#: way ``_COUNTERS_PLACED_THIS_WAY`` below is: one string, two ends of the
#: pipeline, and a second spelling is what makes a producer gate vacuous while
#: the handler reads an empty record.
_BASE_PT_SET_PERMANENTS = BASE_PT_SET_PERMANENTS

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

#: "You and that opponent each gain control of all creatures the other controls
#: until end of turn. **Those creatures** gain haste until end of turn."
#: (Reins of Power.) Every permanent the mutual control change moved, in both
#: directions, under one key — because the sentence behind it names all of them
#: and the board cannot be asked again: by then the two sets have swapped, so
#: "creatures you control" is the opponent's old board and "creatures that
#: opponent controls" is yours, and neither phrase names what the card means.
#:
#: **Ids, not permanents.** The channel takes either (``recorded_permanent_ids``
#: reads an id off an object), and ids are what every reader wants here: the
#: grant behind this looks each one up again through ``permanent_by_id``, which
#: answers None for a permanent that has left — the CR 400.7 answer a live
#: object would hide.
#:
#: Imported from ``oracle_types`` rather than defined here — one string, two
#: ends of the pipeline — and **rebound to itself on purpose**, which is the
#: one line in this file that looks like a mistake and is not. Its two siblings
#: above rename as they re-export (``_BASE_PT_SET_PERMANENTS`` from
#: ``BASE_PT_SET_PERMANENTS``); this key keeps its own spelling, so there is
#: nothing for the assignment to change and its whole job is to give this
#: paragraph something to be attached to. Deleting it costs the documentation
#: and buys nothing: the name is already bound by the import at the top, and
#: ``_records`` imports it from here either way.


#: "Remove target attacking creature you control from combat **and untap it**."
#: (Reconnaissance.) The permanent the removal chose, recorded because the step
#: behind it names it with a bare pronoun and there is nothing else to read: the
#: removal is not a tap or an untap, so none of the records above it holds the
#: object, and reading the *board* at that point cannot tell the creature the
#: ability targeted from any other creature that is no longer attacking.
#:
#: The other printing of this sentence (Disharmony, Imprison) has the pronoun in
#: front rather than behind and reads one of those records instead — which is
#: why this is a record the removal *writes* rather than a second reading of one
#: it takes.
#: Imported from ``oracle_types`` rather than defined here, exactly as
#: ``COUNTERS_PLACED_THIS_WAY`` above is and for the same reason: the handler
#: that writes it and the lowering that gates on it are at opposite ends of the
#: pipeline, so the string lives in the module neither imports from.
REMOVED_FROM_COMBAT_PERMANENTS = _REMOVED_FROM_COMBAT_PERMANENTS


_RECORDED_PERMANENTS: frozenset[str] = frozenset({
    _TAPPED_PERMANENTS, _UNTAPPED_PERMANENTS, _UNBLOCKABLE_PERMANENTS,
    REMOVED_FROM_COMBAT_PERMANENTS,
    _BLOCKED_PERMANENTS,
    _PERMANENTS_GIVEN_COUNTERS, _REANIMATED_PERMANENTS,
    _BASE_PT_SET_PERMANENTS,
    PUT_FROM_HAND_PERMANENTS,
    CONTROL_EXCHANGED_PERMANENTS,
    # What a search put onto the battlefield (Zirilan of the Claw). The
    # reanimation's twin one zone over, and a member of this set for that
    # entry's reason: "that creature" behind either step names the permanent
    # the step created, and a reader that knew only one of them would refuse
    # the other for no reason a card could see.
    SEARCHED_PERMANENTS,
    # The permanent a ``choose_permanent`` prompt was answered with (Echo
    # Chamber: "An opponent chooses target creature they control. Create a
    # token that's a copy of **that creature**."). The same entry's reason
    # again, and the omission was only ever invisible because no card had yet
    # printed a sentence *behind* such a pick that named it as an object —
    # Takklemaggot's does, and reads the key by name through the attach
    # channel rather than through this set.
    CHOSEN_PERMANENT,
})

#: The subset of :data:`_RECORDED_PERMANENTS` whose producer *made* the
#: permanent — it was a card in a graveyard (Necromancy), a hand (Flash) or a
#: library (Zirilan of the Claw) when the ability was announced, so nothing on
#: the stack or the board pointed at it and it did not exist until that step ran.
#:
#: Its own set beside the wider one because it answers a question the wider one
#: cannot: a back-reference *behind such a step* cannot mean the ability's
#: target, since the target was a card and the words name a permanent (CR 400.7
#: makes them different objects). Every other member of `_RECORDED_PERMANENTS`
#: records permanents the effect merely *acted on* — a tap, an unblockable
#: grant, a counter — where the target and the record are the same object and a
#: reader may take either.
_PERMANENTS_MADE_BY_THIS_EFFECT: frozenset[str] = frozenset({
    _REANIMATED_PERMANENTS, PUT_FROM_HAND_PERMANENTS, SEARCHED_PERMANENTS,
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
