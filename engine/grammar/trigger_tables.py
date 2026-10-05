"""Which printed phrase names which trigger event — the tables, not the reading.

Split out of ``triggers`` at the thousand-line guard, a cap neither parallel
branch crossed alone: one added "a player attacks with", the other the
"creature **or spell**" damage union, and the sum went over. The boundary is
the one the module already had in its own shape — a couple of hundred lines of
phrase-to-event data followed by the productions that walk a stream against it.

Pure data, no imports from the reading side, which is what makes this a layer
below ``triggers`` rather than a second half of it. ``engine/oracle.py`` keeps
its own pattern table for the same events and the two are held equal by
``tests/engine/test_trigger_tables.py`` — that guard is why the file is named
what it is.
"""

from __future__ import annotations
from . import ast


#: The permanent nouns a card uses to name **itself** — "this creature", "this
#: artifact", … — shared by ``accept_event_phrase``'s SELF substitution and by
#: the generated table below. Moved above ``_WHENEVER_EVENTS`` when that table
#: grew a row set built from it; it was always pure data and its position in
#: the file was incidental.
#:
#: **"aura" is one of them**, and its absence was the whole of six Urza's
#: Saga cards. A card names itself by whatever noun it likes (CR 109.5), and
#: the two sibling tables that answer the same question -- ``readers._SELF_NOUNS``
#: and ``delay_openers._SELF_TYPE_WORDS``, whose comment already claims to be
#: "the same set ``triggers.py`` reads after 'this'" -- both carried the word
#: while this one did not. "When **this Aura** is put into a graveyard from the
#: battlefield" therefore fell past the long-dies loop to the *subject-led*
#: death reader, which named a different event (``permanent_dies``, watching
#: every permanent that matches a filter) than ``engine/oracle.py`` did -- and
#: the engine dispatches on that one.
_DAMAGER_NOUNS = (
    "creature", "artifact", "enchantment", "land", "aura", "permanent",
)

#: "Whenever this <permanent> becomes the target of a spell [or ability]
#: [an opponent controls | you control]" — Warden of the Woods, and Forsaken
#: Wastes, which prints the narrowest of them ("this enchantment", "a spell",
#: nobody's in particular).
#:
#: Generated rather than written out. Three axes — which noun the card uses for
#: itself, which class of object did the targeting, and whose it was — multiply
#: to forty-five spellings of **one** condition, and a hand-written list of
#: forty-five is forty-four chances to leave one out; the narrowings themselves
#: are payload on ``engine/oracle.py``'s row and are dispatched from there.
#:
#: Ordered longest-first on every axis, which is this table's own rule: matched
#: the other way round "a spell" would claim a line that said "a spell or
#: ability" and strand the rest of it.
_BECOMES_TARGET_OBJECTS: tuple[tuple[str, ...], ...] = (
    ("a", "spell", "or", "ability"),
    # "…becomes the target of **an Aura spell**" (Fugitive Druid). A narrower
    # class than "a spell", and an *axis entry* rather than a fourth condition
    # for the reason this table is generated at all: the three axes multiply,
    # so a card printing this phrase about an artifact, or about a spell an
    # opponent controls, is already read. The filter in `engine/events.py` is
    # what enforces it — dropped, the Druid would draw a card for any spell at
    # all.
    ("an", "aura", "spell"),
    ("a", "spell"),
    ("an", "ability"),
)

_BECOMES_TARGET_CONTROLLERS: tuple[tuple[str, ...], ...] = (
    ("an", "opponent", "controls"),
    ("you", "control"),
    (),
)

#: The subjects the condition is printed about, longest first on this axis too.
#:
#: "**You or a permanent you control**" (Rayne, Academy Chancellor) is the one
#: that is not a self-reference: it spans a *player* and a set of permanents at
#: once, which is a third dispatch scope for this event rather than a third
#: spelling of the first — `engine/events.py` is where the three are told apart,
#: and `engine/oracle.py`'s marker group is what tells them.
#:
#: It joins the axes rather than getting a production of its own because that is
#: what the axes are for: the card printing this subject about "a spell an
#: opponent controls" is already read, and so is the one nobody has printed yet.
_BECOMES_TARGET_SUBJECTS: tuple[tuple[str, ...], ...] = (
    ("you", "or", "a", "permanent", "you", "control"),
    *(("this", noun) for noun in _DAMAGER_NOUNS),
)

_BECOMES_TARGET_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (
        "self_becomes_target",
        subject + ("becomes", "the", "target", "of") + obj + controller,
    )
    for subject in _BECOMES_TARGET_SUBJECTS
    for obj in _BECOMES_TARGET_OBJECTS
    for controller in _BECOMES_TARGET_CONTROLLERS
)


_WHENEVER_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_dies", ("a", "land", "is", "put", "into", "a", "graveyard", "from", "the", "battlefield")),
    # "Whenever **another card** is put into a graveyard **from anywhere**."
    # (Planar Void.) A card rather than a permanent, out of no named zone and
    # into anybody's pile — so nothing on a battlefield is watched, and the
    # subject-led death reader below could not name it either. Carried here as
    # well as in ``engine/oracle.py``'s table for the reason this file's
    # docstring gives: a condition only one front end reads leaves the other
    # refusing the effect behind it, and the engine dispatches on the compiler's.
    ("card_put_into_graveyard",
     ("another", "card", "is", "put", "into", "a", "graveyard", "from",
      "anywhere")),
    # Longest first: the explicit-self spelling (Basri's Lieutenant) names the
    # same set as the bare one below it — see the oracle table's note.
    ("creature_you_control_dies",
     ("this", "creature", "or", "another", "creature", "you", "control", "dies")),
    ("creature_you_control_dies", ("a", "creature", "you", "control", "dies")),
    ("creature_opponent_controls_dies",
     ("a", "creature", "an", "opponent", "controls", "dies")),
    # Longer phrases first: this list is matched in order, so a prefix entry
    # would claim the shorter reading and strand the rest of the clause.
    ("creature_dealt_damage_by_self_dies",
     ("a", "creature", "dealt", "damage", "by", "this", "creature", "this", "turn", "dies")),
    # The attached spelling of the row above (Vampiric Embrace), and its own
    # kind for the reason `engine/oracle.py`'s twin row states: the fire site
    # reaches the observer by a different route. Both attachment words, because
    # CR 301.5f makes them one rule.
    ("creature_dealt_damage_by_attached_dies",
     ("a", "creature", "dealt", "damage", "by", "enchanted", "creature",
      "this", "turn", "dies")),
    ("creature_dealt_damage_by_attached_dies",
     ("a", "creature", "dealt", "damage", "by", "equipped", "creature",
      "this", "turn", "dies")),
    ("creature_dies", ("a", "creature", "dies")),
    # "Whenever you discard a card" (Necropotence) and "whenever an opponent
    # discards a card" (Megrim). One event, two printed seats — the narrowing
    # is payload on ``engine/oracle.py``'s row and is dispatched from the
    # discard seam, exactly as ``land_played``'s and ``draws_card``'s are.
    ("discards_card", ("you", "discard", "a", "card")),
    ("discards_card", ("an", "opponent", "discards", "a", "card")),
    # "Whenever a spell or ability an opponent controls causes you to discard a
    # card" (Spiritual Focus). Carried here as well as in `engine/oracle.py`'s
    # table for this file's standing reason: a condition only one front end
    # reads leaves the other refusing the effect behind it, and the engine
    # dispatches on the compiler's. Its "when" printing (Psychic Purge) is read
    # by `triggers.py`'s own passive block, which this word never reaches.
    ("discarded_by_opponent_effect",
     ("a", "spell", "or", "ability", "an", "opponent", "controls", "causes",
      "you", "to", "discard", "a", "card")),
    # "Whenever **equipped** creature dies" (Malefic Scythe) / "When
    # **enchanted** creature dies" (Creature Bond). One condition for both
    # words: an Equipment and an Aura attach the same way here, and the trigger
    # is about the permanent this one is attached to either way. Both spellings
    # are listed because both are printed, and neither is a wording of the other
    # in a way this table could derive.
    ("attached_creature_dies", ("equipped", "creature", "dies")),
    ("attached_creature_dies", ("enchanted", "creature", "dies")),
    # "When enchanted creature leaves the battlefield, …" (Funeral March). The
    # row above widened from a death (CR 704.5g) to CR 603.6c's whole event, so
    # a host exiled, bounced or tucked fires it as well as one that died. Both
    # printed words for the row above's reason, and both spellings of
    # "attached" for the same one.
    ("attached_creature_leaves_battlefield",
     ("equipped", "creature", "leaves", "the", "battlefield")),
    ("attached_creature_leaves_battlefield",
     ("enchanted", "creature", "leaves", "the", "battlefield")),
    # "…becomes the target of a spell or ability an opponent controls" (Warden
    # of the Woods) and its forty-four siblings, generated above. Longest first
    # on every axis, as everywhere in this table: the narrowed wording has the
    # unnarrowed one as a strict prefix, so matching that first would strand
    # "an opponent controls" — and *both* front ends would then name a
    # condition that fires on the controller's own spells too.
    *_BECOMES_TARGET_EVENTS,
    ("creature_attacks_or_blocks", ("this", "creature", "attacks", "or", "blocks")),
    # "attacks and isn't blocked" (Merchant Ship) — before the bare "attacks"
    # it is a prefix of, so the longer condition matches first.
    ("attacks_unblocked", ("this", "creature", "attacks", "and", "isn't", "blocked")),
    # "attacks **alone**" (Reckless Ogre; CR 506.5) — before the bare "attacks"
    # it is a prefix of, for this table's standing reason. One kind with the
    # bare row, because it is one event: which declarations announce it is a
    # narrowing `engine/oracle.py`'s condition table carries as payload and the
    # declare-attackers step reads, and this side has no dispatcher to tell.
    # Listed all the same, because a word left unclaimed here refuses the whole
    # line and the effect behind it goes with it.
    ("creature_attacks", ("this", "creature", "attacks", "alone")),
    ("creature_attacks", ("this", "creature", "attacks")),
    # The bare joined sentence (Spitting Slug), above both halves it is a
    # strict prefix of: matching "this creature blocks" first would leave
    # "or becomes blocked" unconsumed and fail the line. The filtered table
    # below carries the narrowed printing, which ends in "by".
    ("creature_blocks_or_blocked_by",
     ("this", "creature", "blocks", "or", "becomes", "blocked")),
    ("creature_blocks", ("this", "creature", "blocks")),
    ("creature_becomes_blocked", ("this", "creature", "becomes", "blocked")),
    # "…is dealt **combat** damage" (Wall of Essence, Wall of Souls). One kind
    # with the bare row below, because the narrowing is payload on the
    # compiler's side (`damage_combat` in engine/oracle.py) and this table has
    # only to agree about *which event* the words name — the arrangement the
    # upkeep and draw-step rows already use.
    ("creature_dealt_damage",
     ("this", "creature", "is", "dealt", "combat", "damage")),
    ("creature_dealt_damage", ("this", "creature", "is", "dealt", "damage")),
    ("permanent_becomes_untapped", ("this", "creature", "becomes", "untapped")),
    ("permanent_becomes_untapped", ("this", "artifact", "becomes", "untapped")),
    ("permanent_becomes_untapped", ("this", "permanent", "becomes", "untapped")),
    # CR 702.26's two events (Teferi's Imp, Warping Wurm). One row per printed
    # noun, exactly as the untap rows above: the noun is not payload here, it
    # is the self-reference, and every spelling a Mirage card prints is listed.
    # The joined event (Ertai's Familiar), above both halves it is a strict
    # prefix of — matching the bare "phases out" first would leave "or leaves
    # the battlefield" unconsumed and refuse the line, which is the same
    # longest-first rule every pair in this table follows.
    ("phases_out_or_leaves_battlefield",
     ("this", "creature", "phases", "out", "or", "leaves", "the", "battlefield")),
    ("phases_out_or_leaves_battlefield",
     ("this", "permanent", "phases", "out", "or", "leaves", "the", "battlefield")),
    ("phases_out", ("this", "creature", "phases", "out")),
    ("phases_out", ("this", "artifact", "phases", "out")),
    ("phases_out", ("this", "permanent", "phases", "out")),
    ("phases_in", ("this", "creature", "phases", "in")),
    ("phases_in", ("this", "artifact", "phases", "in")),
    ("phases_in", ("this", "permanent", "phases", "in")),
    ("land_tapped_for_mana", ("a", "player", "taps", "a", "land", "for", "mana")),
    # "Whenever a player chooses one or more targets" (Psychic Battle). The
    # whole phrase is the event — "one or more" is CR 115.6's wording for "the
    # object is targeted" and carries no number to read.
    ("player_chooses_targets",
     ("a", "player", "chooses", "one", "or", "more", "targets")),
    ("spell_cast", ("a", "player", "casts", "a", "spell")),
    # "Whenever a player **kicks** a spell" (Saproling Infestation). The cast
    # event under CR 702.33d's narrowing; `engine/oracle.py`'s pattern table
    # carries the marker the dispatcher reads, exactly as it carries every
    # other cast narrowing this table's bare phrases cannot.
    ("spell_cast", ("a", "player", "kicks", "a", "spell")),
    # Longest first: the bare phrase below is a strict prefix of this one, so
    # matching it first would leave "from anywhere other than their hand"
    # unaccounted and fail the line.
    ("opponent_attackers_declared",
     ("an", "opponent", "attacks", "with", "creatures")),
    ("opponent_casts_nth_spell_each_turn",
     ("an", "opponent", "casts", "their", "second", "spell", "each", "turn")),
    ("opponent_casts_spell",
     ("an", "opponent", "casts", "a", "spell", "from", "anywhere", "other",
      "than", "their", "hand")),
    # "…that targets you or a creature you control" (Reparations). The clause
    # narrows what the *dispatcher* admits rather than what the sentence means,
    # so the parse side carries the words and `engine/oracle.py`'s table carries
    # the marker the cast filter reads. Above the bare row for this table's
    # standing reason: the shorter phrase is a prefix, and matching it would
    # strand the rest of the condition and fail the line.
    ("opponent_casts_spell",
     ("an", "opponent", "casts", "a", "spell", "that", "targets", "you", "or",
      "a", "creature", "you", "control")),
    ("opponent_casts_spell", ("an", "opponent", "casts", "a", "spell")),
    ("enchantment_cast", ("you", "cast", "an", "enchantment", "spell")),
    ("you_cast_spell", ("you", "cast", "a", "spell")),
    # "Whenever a spell **you've cast** is countered" (Multani's Presence).
    # CR 701.6a's cancel, watched from the battlefield — the passive voice of an
    # event no card in this pool had ever watched, and a different question from
    # the three cast rows above it: what is announced is the *countering*, which
    # happens long after the cast and to an object that is already leaving the
    # stack. CR 603.10e is why the tense is safe to read at all — an ability
    # that triggers when a spell is countered looks back in time.
    #
    # The seat rides the announcement (``events._SEAT_SCOPED_EVENTS``) rather
    # than the phrase, so "you've" is part of the condition's identity here and
    # is not re-tested by the reader: the spell's caster is what the event
    # carries, and the watching permanent's controller is CR 109.5's "you".
    ("your_spell_countered",
     ("a", "spell", "you've", "cast", "is", "countered")),
    # "…**you play a card**" (Juju Bubble). Listed on both front ends because
    # the card prints it and a line only one of them reads is a card the other
    # refuses -- the same reason the two draw spellings are both here.
    ("you_play_card", ("you", "play", "a", "card")),
    # Ankh of Mishra's, which has its own fire site. The bare creature and
    # artifact entries that used to sit beside it are gone: they had no
    # dispatcher and no card, and the subject-led production below reads the
    # same words as `matching_permanent_enters`, which does fire.
    ("land_enters", ("a", "land", "enters")),
    # "Whenever an opponent **plays** a land" (Dirtcowl Wurm) — CR 305.1's
    # special action, not the entry above it, and not a cast. Both seat
    # spellings are listed for `draws_card`'s reason below: which seat played is
    # the event's, the printed word is the condition's narrowing, and a line
    # only one front end reads is a card the other refuses.
    # "When an opponent plays a **nonbasic** land" (Hidden Herd) — the same
    # event with a supertype narrowing the other front end carries as payload
    # (``engine/oracle.py``'s ``played_land_supertype`` group), exactly as
    # ``other_land`` below is. Above the bare phrase, which is its strict
    # prefix and would strand the word.
    ("land_played", ("an", "opponent", "plays", "a", "nonbasic", "land")),
    ("land_played", ("an", "opponent", "plays", "a", "land")),
    # "Whenever **a player** plays a land" (Horn of Greed) — the unnarrowed
    # spelling of the same event. The seat is payload on ``engine/oracle.py``'s
    # row; here it is one more phrase for one kind.
    ("land_played", ("a", "player", "plays", "a", "land")),
    # "When you play **another** land, sacrifice this land." (City of
    # Traitors.) The same event with the printed exclusion as the trigger's own
    # narrowing, which the *other* front end carries as payload
    # (``engine/oracle.py``'s ``other_land`` group, compared against the played
    # permanent's id by ``engine/events._land_played_filter``) — this table has
    # only to agree about which event the words name, the arrangement the seat
    # rows above already use. Above the bare phrase it is not a prefix of, so
    # the order is documentation here rather than precedence.
    ("land_played", ("you", "play", "another", "land")),
    ("land_played", ("you", "play", "a", "land")),
    # "…your second card each turn" (Mystic Skyfish, Jolrael) — a different
    # article, so no prefix collision with the bare draw event above.
    ("draws_second_card", ("you", "draw", "your", "second", "card", "each", "turn")),
    ("draws_card", ("you", "draw", "a", "card")),
    # The same event asked of another seat (Underworld Dreams). One kind, as in
    # engine/oracle.py's table: which seat drew is the event's, and the
    # condition payload the regex there captures is what the event filter
    # narrows on. Both spellings are listed here because both are printed, and
    # a line only one front end reads is a card refused by the other.
    ("draws_card", ("an", "opponent", "draws", "a", "card")),
    # "When **the chosen player draws a card with the chosen name**, …" (Booby
    # Trap.) The third spelling of the same event, and here for the reason the
    # second is: a line only one front end reads is a card the other refuses.
    # Both narrowings are the condition's — the seat and the card name were
    # chosen as the artifact entered (CR 614.1c), and `engine/events.py` tests
    # them against the permanent's own record. This table carries no payload, so
    # what it buys is the *effect* half: without the phrase the grammar refuses
    # the line and the trigger compiles with no instruction behind it.
    ("draws_card",
     ("the", "chosen", "player", "draws", "a", "card", "with", "the",
      "chosen", "name")),
    # "Whenever you gain life …" (Vito). No amount in the phrase: how much was
    # gained is the event's, and a "that much" in the effect reads it out of the
    # trigger's captured context rather than out of these words.
    ("you_gain_life", ("you", "gain", "life")),
    # "Whenever you lose life …" (Oath of Lim-Dûl). Bare for the same reason:
    # how much was lost is the event's, and "for each 1 life you lost" reads it
    # out of the trigger's captured context rather than out of these words.
    ("you_lose_life", ("you", "lose", "life")),
    # "Whenever you sacrifice a permanent …" (Havoc Jester). Announced from
    # ``Game.sacrifice_permanent``, the one place CR 701.21a happens. Bare, like
    # the life gain above: what was sacrificed is the event's, and no card in
    # the pool narrows it — a "…sacrifice a creature" entry would go above this
    # one, and does not collide with it.
    ("you_sacrifice_permanent", ("you", "sacrifice", "a", "permanent")),
)

# Events whose subject is an object *filter* the trigger carries, keyed by the
# fixed words printed in front of it. The mirror of the `_subject`-group
# patterns in engine/oracle.py's table: one printed phrase, read by the same
# noun parser on both sides of the pipeline, and held equal by
# `test_a_narrowed_trigger_reads_the_same_subject_on_both_sides`.


_FILTERED_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    # The Basilisk cycle's event, and Abomination's and Aisling Leprechaun's:
    # one printed sentence joining the two halves of a block, whose noun phrase
    # narrows **both** of them. First, because "this creature blocks" below is a
    # strict prefix — matching that would read "or becomes blocked by …" as the
    # blocked creature's noun phrase.
    (("this", "creature", "blocks", "or", "becomes", "blocked", "by"),
     "creature_blocks_or_blocked_by"),
    # The same joined event watched by an Aura rather than by the creature
    # itself (Infinite Authority). One kind, because it is one event: whose
    # ability is watching is the narrowing, and `engine/oracle.py`'s table is
    # what records it (`combatant_attached`) for the two combat dispatchers.
    # What this side has to read is the *pair* noun phrase, which is the
    # subject both halves are narrowed by — so it is a row of this table and
    # not of `trigger_subjects.py`, whose four productions read no phrase at
    # all.
    (("enchanted", "creature", "blocks", "or", "becomes", "blocked", "by"),
     "creature_blocks_or_blocked_by"),
    (("this", "creature", "blocks"), "creature_blocks"),
    (("this", "creature", "becomes", "blocked", "by"), "creature_becomes_blocked"),
    # "Whenever you activate a loyalty ability of **a Chandra planeswalker**"
    # (Keral Keep Disciples) — the same pair the oracle regex table carries, so
    # the two front ends turn one printed phrase into one filter.
    (("you", "activate", "a", "loyalty", "ability", "of"),
     "you_activate_loyalty_ability"),
)

# The same, for events whose subject comes *first* — "a creature you control
# with deathtouch **attacks**". The verb behind the noun phrase names the event,
# so the phrase is read speculatively and these decide whether it was one.
# Longest first, per the ordering rule the whenever table follows.


# The **board-wide** halves of a block, keyed by the words between the two noun
# phrases. "Whenever **a creature** becomes blocked by **a creature with lesser
# power**" / "…**a creature** blocks **a creature with lesser power**"
# (No Quarter).
#
# Its own table rather than rows of `_SUBJECT_LED_EVENTS` below, because these
# rows have a *second* noun phrase after the verb and that table's loop has no
# way to consume one — the same reason "a player puts <noun> onto the
# battlefield" is a production in `triggers.py` rather than a row here.
# "Becomes blocked by" is first: "blocks" is not a prefix of it, but the
# specific-before-generic rule is what keeps that true when either is edited.
#
# The kinds are the `matching_` ones, not `creature_blocks` /
# `creature_becomes_blocked`: those two are announced by a scan over the
# combatant's own card and its attachments, and a permanent watching the whole
# board is reached by the event bus instead (`engine/events.py`), exactly as
# `matching_creature_attacks` sits beside `creature_attacks`.


_BOARD_WIDE_BLOCK_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("becomes", "blocked", "by"), "matching_creature_becomes_blocked"),
    (("blocks",), "matching_creature_blocks"),
)


#: The same two events with **no partner phrase** — "Whenever a creature blocks,
#: …" (Heat of Battle), "Whenever a Sliver becomes blocked, …" (Spined Sliver).
#:
#: Its own table rather than a third column on the one above, because a row here
#: means a different *announcement* rather than a different word: CR 509.3c/
#: 509.3d fire a bare condition once for the creature the event is about however
#: many creatures are on the other side, where a narrowed one fires once per
#: creature its phrase admits. The fire site makes both announcements and
#: ``events._board_wide_block_filter`` keeps a trigger on exactly one.
#:
#: Read **after** the table above, because each phrase here is a strict prefix
#: of the matching row there — the same specific-before-generic order
#: ``engine/oracle.py``'s rows keep, and for the same reason: read first, the
#: partner phrase is left on the stream and the line fails full consumption.
_BARE_BOARD_WIDE_BLOCK_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("becomes", "blocked"), "matching_creature_becomes_blocked"),
    (("blocks",), "matching_creature_blocks"),
)


_SUBJECT_LED_EVENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("attacks",), "matching_creature_attacks"),
    (("enters", "the", "battlefield"), "matching_permanent_enters"),
    (("enters",), "matching_permanent_enters"),
    # "Whenever **a nontoken creature** leaves the battlefield, …" (Dual
    # Nature). CR 603.6c's event about a permanent the source is neither nor
    # attached to, so the subject leads and the phrase is the narrowing — the
    # entry rows' shape, read in `engine/oracle.py`'s table under the same kind.
    (("leaves", "the", "battlefield"), "matching_permanent_leaves_battlefield"),
    # "Whenever **a creature** is dealt damage, destroy it." (Death Pits of
    # Rath.) The same event Fungusaur's "whenever **this** creature is dealt
    # damage" names and Binding Agony's "whenever **enchanted** creature is
    # dealt damage" names, watched by a permanent that is neither the damaged
    # creature nor attached to it — so the subject leads and the phrase is the
    # narrowing, which is exactly this table's shape.
    (("is", "dealt", "damage"), "creature_dealt_damage"),
    # "Whenever **a creature with shadow** dies" (Dauthi Ghoul). CR 700.4 makes
    # this the long spelling read a few lines up in `_parse_matched_event`
    # ("…is put into a graveyard from the battlefield"), so it is the same kind
    # and reaches the same fire site. Last, because the table is tried in order
    # and a one-word verb is the most permissive entry in it.
    (("dies",), "permanent_dies"),
)


_AT_EVENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("upkeep_self", ("the", "beginning", "of", "your", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "player", "'s", "upkeep")),
    ("upkeep_each", ("the", "beginning", "of", "each", "upkeep")),
    # "each **opponent's** upkeep" (Psychic Allergy). The same kind, because the
    # narrowing is payload on the compiler's side (see `upkeep_scope` in
    # engine/oracle.py) and this table only has to agree about *which event* the
    # words name — idiom 1's rule that a condition narrowed on one side only is
    # a card firing on the wrong event.
    ("upkeep_each", ("the", "beginning", "of", "each", "opponent", "'s", "upkeep")),
    # An Aura firing on the upkeep — or the end step — of whoever controls what
    # it enchants (Feedback, Wanderlust, Warp Artifact, Aggression) is
    # `trigger_subjects._parse_attached_step_event`, tried before this table.
    # It left because the event needs a **subject**: the phrase names the
    # permanent the source is attached to, and a bare pronoun in the effect
    # behind it is a back-reference to that permanent rather than to the Aura.
    # A table row cannot carry one.
    ("upkeep_chosen", ("the", "beginning", "of", "the", "chosen", "player", "'s", "upkeep")),
    # "Your draw step" beside "each player's", the same pair as the upkeep two
    # above and for the same reason: the scope is what the dispatcher reads, and
    # a narrowing present on one side of the pipeline and absent on the other
    # compiles the card supported and fires it on the wrong event (round 7).
    ("draw_step_self", ("the", "beginning", "of", "your", "draw", "step")),
    ("draw_step_each", ("the", "beginning", "of", "each", "player", "'s", "draw", "step")),
    # "each **opponent's** draw step" (Malignant Growth). The same kind, for the
    # reason the upkeep row one screen up gives: the narrowing is payload on the
    # compiler's side (`draw_step_scope` in engine/oracle.py) and this table has
    # only to agree about *which event* the words name.
    ("draw_step_each", ("the", "beginning", "of", "each", "opponent", "'s", "draw", "step")),
    # CR 505.1a — the precombat main phase, the only one that is "first". Both
    # printed spellings; the M21 Shrines say "first" and modern templating says
    # "precombat". The oracle regex table carries the same pair, because a
    # condition narrowed on one side of the pipeline and not the other compiles
    # the card supported and fires it on the wrong event (round 7).
    ("main_phase_first", ("the", "beginning", "of", "your", "first", "main", "phase")),
    ("main_phase_first", ("the", "beginning", "of", "your", "precombat", "main", "phase")),
    # "each player's" beside "your", the same pair as the upkeep and draw-step
    # rows above and for their reason: the scope is what the dispatcher reads,
    # and a narrowing present on one side of the pipeline and absent on the
    # other compiles the card supported and fires it on the wrong event.
    ("main_phase_first_each",
     ("the", "beginning", "of", "each", "player", "'s", "first", "main", "phase")),
    ("main_phase_first_each",
     ("the", "beginning", "of", "each", "player", "'s", "precombat", "main", "phase")),
    ("main_phase_first_each",
     ("the", "beginning", "of", "each", "opponent", "'s", "first", "main", "phase")),
    # "each of your main phases" (Carpet of Flowers) — CR 505.1's *both* main
    # phases, on the controller's own turn. Its own kind for the reason the two
    # rows above are two: the dispatcher is what reads the difference, and a
    # scope present on one side of the pipeline and absent on the other compiles
    # the card supported and fires it on the wrong event (round 7).
    ("main_phase_each_yours",
     ("the", "beginning", "of", "each", "of", "your", "main", "phases")),
    # "Your" is a scope narrowing and so a separate kind, the same pair the
    # oracle regex table carries: a condition narrowed on one side of the
    # pipeline and not the other compiles the card supported and fires it on the
    # wrong event (round 7).
    ("end_step_self", ("the", "beginning", "of", "your", "end", "step")),
    ("end_step", ("the", "beginning", "of", "the", "end", "step")),
    ("end_step", ("the", "beginning", "of", "each", "end", "step")),
    # "each **player's** end step" (Monsoon) — the same set, because CR 513.1
    # gives every turn one end step; a spelling, not a scope. The oracle regex
    # table carries the same alternative, for the reason stated above it.
    ("end_step", ("the", "beginning", "of", "each", "player", "'s", "end", "step")),
    # The narrowed form precedes its own prefix, per the rule above.
    ("combat_your_turn", ("the", "beginning", "of", "combat", "on", "your", "turn")),
    # "…on **each opponent's** turn" (Fight or Flight) — the same step's other
    # narrowing, for the reason engine/oracle.py's table states beside it.
    ("combat_opponent_turn",
     ("the", "beginning", "of", "combat", "on", "each", "opponent", "'s", "turn")),
    # "…of **each** combat" (Goblin Flotilla) — one event, two spellings, for
    # the reason engine/oracle.py's table states beside the same pair.
    ("combat", ("the", "beginning", "of", "each", "combat")),
    ("combat", ("the", "beginning", "of", "combat")),
    # "At end of combat, …" (The Wretched) — CR 511.1. Read here as well as in
    # engine/oracle.py's table, because both front ends see the whole line and
    # a condition only one of them reads leaves the other refusing the effect
    # behind it.
    ("end_of_combat", ("end", "of", "combat")),
)



# ---------------------------------------------------------------------------
#
# Fragment productions over the word tables above: they read the clause
# between the trigger word and the comma, and nothing about a whole line.
# They lived in parser.py until the counters-put-on production pushed that
# module past the thousand-line guard, which is the guard working as
# documented — the family that should absorb this work is the one whose
# tables the productions already read.


_CAST_TYPE_FILTERS: dict[str, "ast.ObjectFilter"] = {
    "noncreature": ast.ObjectFilter(excluded_types=("creature",)),
    "nonartifact": ast.ObjectFilter(excluded_types=("artifact",)),
    "creature": ast.ObjectFilter(card_types=("creature",)),
    "artifact": ast.ObjectFilter(card_types=("artifact",)),
    "instant": ast.ObjectFilter(card_types=("instant",)),
    "sorcery": ast.ObjectFilter(card_types=("sorcery",)),
}

#: The printed type *unions* the same narrowing may name, longest first. A
#: union is not a filter this table can hold as one word, and the event filter
#: has to test "any of these" rather than "this one" — so it is its own table
#: and its own key, and the filter reads them apart.


_CAST_TYPE_UNIONS: tuple[tuple[tuple[str, ...], "ast.ObjectFilter"], ...] = (
    (("instant", "or", "sorcery"),
     ast.ObjectFilter(card_types=("instant", "sorcery"))),
)


# The printed recipients of a damage event, longest first: "a player or
# planeswalker" has "a player" as a strict prefix, and matching the shorter one
# would leave the union's second half stranded — the ordering rule this whole
# file follows.


_DAMAGE_RECIPIENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("a", "player", "or", "planeswalker"), "a player or planeswalker"),
    (("a", "player"), "a player"),
    (("an", "opponent"), "an opponent"),
    (("a", "planeswalker"), "a planeswalker"),
    # "…deals combat damage to **defending player**" (Electryte). The seat the
    # attack was declared against (CR 506.2), which is a relation to the
    # *combat* rather than to the ability's controller — so it is a row here
    # beside "an opponent" and a test of its own in `events.py`, not a spelling
    # of one of the four above. Printed with no article, which is why the tuple
    # is two words.
    (("defending", "player"), "defending player"),
    (("you",), "you"),
)


#: What `_accept_ordinal_exclusion` returns when the clause is there but says
#: something this engine would have to guess at. A sentinel rather than None,
#: because None already means "no such clause was printed" and the two must not
#: collapse: one is a card with no exclusion, the other is a card whose
#: exclusion nothing would enforce.
