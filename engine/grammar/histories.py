"""What a noun phrase relates to that no board can answer: a **record**.

"creature **that attacked this turn**", "creature **that was dealt damage this
turn**", "creatures **that blocked or were blocked by it this turn**",
"creature **you cast this turn**", "Plains **that weren't chosen this way by any
player**". Every reading here is answered from something the game wrote down as
it happened — an attack declaration, a block pairing, a damage ledger, the seat
that cast a permanent, the picks a resolution has already made — and from
nothing a matcher could see by looking at the object it is handed.

That is a fourth relation, and `postmodifiers`' own docstring names three: "A
postmodifier names a **relation**: to the controller, to another object the
sentence names, to a zone." The controller half left for `seat_relations` at
Weatherlight's Phase 0 and the zone half for `zones` before it; a history is
none of the three, because the object it relates to may have left the
battlefield and the relation may have ended two steps ago. Which is why every
clause here has to print "this turn" and the live combat relations left behind
("it's blocking", "attacking you") must not — the two are told apart by the
window, not by the verb, and Jabari's Influence prints both tenses of one
sentence to prove it.

`seat_relations` named this family on its way out — "what stays behind asks the
others — combat relations, zones, **records**, nested phrases" — and `records`
is the one word that could not be reused: `grammar/records.py` is already the
parse-side mirror of `lowering/_records.py` and reads a *quantity* off an event,
so taking it here would fork a name inside one package rather than re-form a
mirror across two.

Split off `postmodifiers.py` at Tempest's Phase 0, under SET_PLAYBOOK.md's rule
that a module two groups will both reach is pre-split before the fan-out rather
than at integration: that file stood three lines under the thousand-line guard
with two wave-3 groups about to open on it — one on a comparison between the two
creatures of a combat pair, one on "not named <name>" — so neither group could
be given it to own and neither would have crossed it alone.

**Two functions, because the chain has two runs.** Six clauses open on their own
words and are read near the head of the loop; eight more are arms of one
`that …` relative clause and are read from inside it, after the four arms of
that clause which are not histories. Order inside each is the order the loop
always tried them in, and it is load-bearing: several of these phrases are
prefixes of others ("that didn't attack" of "that didn't attack this turn",
"blocked" of "blocked or were blocked by", "was dealt damage" against "has been
dealt damage"), so a branch tried early enough takes the words its neighbour
needs.

Both functions return True when a branch consumed its phrase — the caller's loop
continues, as its own ``continue`` did — and False when none did, which is the
contract `accept_zone_scope` already has one branch further down the same loop
and `statement_dispatch_naming` has one package over. A floor rather than a
family, the same shape `seat_relations` is: `postmodifiers` reads this and it
reads nothing back.

**Three record clauses stayed behind, because a single branch is not a run.**
"Tapped this turn to pay for its abilities" (Vodalian War Machine), "that
attacked you this turn" (Jabari's Influence) and "tokens created with this
creature" (Tetravus) each sit alone between live-board readings whose prefixes
they share — Jabari's Influence's own comment is the instruction to keep it
beside its present-tense twin — so moving one would cost a call site to save
five lines and would put a prefix pair in two files.
"""

from __future__ import annotations

from .readers import accept_source_reference
from .stream import TokenStream
from .vocabulary import CARD_TYPES, singular as _singular


def accept_history_relation(stream: TokenStream, d) -> bool:
    """Read one record-keyed postmodifier onto *d*.

    True when a branch consumed its phrase — the caller's loop continues — and
    False having consumed nothing. There is no probe to restore: every branch
    here is a single ``accept_phrase``, which takes its whole run or none of it.
    """
    # "all untapped creatures **that didn't attack this turn**, **except
    # for creatures that couldn't attack**" (Season of the Witch). Two
    # narrowings of one noun phrase, both about the same combat: the first
    # is the set the sweep takes, the second is the exemption the card
    # prints. Read here rather than as a sentence-level exception clause
    # because they narrow the *subject* — the sweep destroys exactly what
    # the noun phrase names, and an exemption read anywhere else would have
    # to be re-applied by every verb.
    if stream.accept_phrase("that", "didn't", "attack", "this", "turn"):
        d.attacked_this_turn = False
        return True
    # "…creatures that player controls **that didn't attack**" (Total War).
    # The same narrowing with the two words the card does not print, and
    # the same record answers it: `attacked_this_turn` is stamped at the
    # declaration, so "didn't attack" asked during the combat it fired in
    # names exactly the creatures left at home. Read *after* the longer
    # spelling above, which it is a strict prefix of.
    if stream.accept_phrase("that", "didn't", "attack"):
        d.attacked_this_turn = False
        return True
    if stream.accept_phrase("that", "attacked", "this", "turn"):
        d.attacked_this_turn = True
        return True
    # "destroy each creature **that blocked or was blocked this turn**"
    # (Heat Stroke). CR 509.1a's relation with *neither* end named — the
    # sentence asks whether the creature was on either side of a block,
    # not which creature it was paired with — so it is a narrowing of
    # the noun phrase like the attack records above it rather than one
    # of the `blocking_*` relations further down, every one of which
    # needs a second object to be about.
    #
    # "This turn", not this combat: the card fires at end of combat and
    # a turn may hold two of them, so the window is the pair records the
    # declare-blockers step keeps and the cleanup step sweeps.
    if stream.accept_phrase(
        "that", "blocked", "or", "was", "blocked", "this", "turn"
    ):
        d.blocked_or_was_blocked_this_turn = True
        return True
    # "…destroy it and all creatures **it blocked this turn**." (Defiant
    # Vanguard.) Glyph of Doom's "that were blocked by that creature this
    # turn" in the active voice with the relative pronoun left out, and the
    # same record answers it: the pair the declare-blockers step wrote on the
    # *candidate* (``blocked_by_blocker_ids_this_turn``), which survives the
    # blocker leaving — the ordinary way this card is played, since combat
    # damage usually kills it before the end of combat it names.
    #
    # It sets Glyph of Doom's field rather than a field of its own because
    # "it" here is the object the delayed ability is *about*: the field's
    # name is what tells ``delayed.delay_binds_an_object`` to bind one, and
    # its lowering refuses outside a delayed event that bound one. Every word
    # is required — "this turn" for the clause beside it's reason, and "it"
    # because a clause naming some other blocker is a different set.
    if stream.accept_phrase("it", "blocked", "this", "turn"):
        d.blocked_by_bound_object = True
        return True
    # "target creature **you cast this turn**" (Cycle of Life). A narrowing
    # of the noun phrase like the combat records above it, off a different
    # record: CR 701.5a's cast, stamped as the permanent entered. Not "you
    # control" and not "that entered this turn" — a creature you cast and
    # then gave away is still one you cast, and a reanimated one never was.
    if stream.accept_phrase("you", "cast", "this", "turn"):
        d.cast_by_you_this_turn = True
        return True
    # "Creatures **played by your opponents** enter tapped." (Uphill Battle.)
    # The record above with the seat turned around and the window dropped —
    # and the word is "played", not "control": CR's glossary entry for Play
    # makes it "cast that card as a spell", so a creature an opponent
    # *reanimated* was never played and this static does not tap it. Reading
    # the phrase as a controller clause would be a static that binds a
    # strictly larger set than the card prints, which is exactly the shape
    # every enter-tapped comment in this engine warns about.
    #
    # No "this turn" half, deliberately: the phrase names how the permanent
    # arrived, and the stamp is written at that arrival and never rewritten —
    # a creature an opponent cast three turns ago is still one they played.
    if stream.accept_phrase("played", "by", "your", "opponents"):
        d.played_by = "opponent"
        return True
    # "destroy all Plains **that weren't chosen this way by any player**"
    # (Raiding Party). A narrowing of the noun phrase rather than an
    # exception clause on the verb, for the reason Season of the Witch's
    # pair above is: the sweep destroys exactly what the phrase names, and
    # an exclusion read anywhere else would have to be re-applied by every
    # verb that could carry it.
    #
    # "By any player" is the whole of what makes it one narrowing: the
    # choices were made by several seats over several iterations, and the
    # words ask about all of the answers at once — which is why the record
    # behind it accumulates instead of holding the last seat's pick.
    if stream.accept_phrase(
        "that", "weren't", "chosen", "this", "way", "by", "any", "player"
    ):
        d.not_chosen_this_way = True
        return True
    return False


def accept_relative_clause_history(stream: TokenStream, d, parse_filter) -> bool:
    """Read one history arm of a ``that …`` relative clause onto *d*.

    The caller has consumed the "that" and tried the four arms of that clause
    which are not histories; this is the rest of the same chain, so it is an
    ``if``/``elif`` run and an arm that opens and then fails takes no later one
    — it falls to the end, exactly as it fell to the caller's
    ``stream.reset(probe)`` before the split.

    True when an arm consumed its phrase, False with the cursor back where it
    entered; the caller then restores its own "that" and breaks.

    *parse_filter* is ``nouns.parse_object_filter``, handed down rather than
    imported for the reason ``postmodifiers`` takes it that way — two of these
    arms name the blocker with a whole noun phrase, and that parser is two
    layers up.
    """
    start = stream.mark()
    # "…all creature cards in your graveyard **that were put there from the
    # battlefield this turn**" (No Rest for the Wicked). A history about a card
    # in a pile rather than about a permanent on a board: "there" is the zone
    # the noun phrase has already named, and "from the battlefield" is how it
    # got there — neither readable off the card, both written down as the move
    # happened.
    #
    # First in the run, and it can shadow nothing: no other arm opens on "were
    # put", and this one requires the whole phrase before it sets anything.
    if stream.accept_phrase(
        "were", "put", "there", "from", "the", "battlefield", "this", "turn",
    ):
        d.put_there_from_battlefield_this_turn = True
        return True
    # "…that **were blocked by that creature this turn**" (Glyph of
    # Doom). "That creature" is the object the sentence's delayed
    # ability was bound to, and "this turn" is what makes the record
    # outlive the combat the block happened in — both required, for the
    # reason the damage clause below requires its own.
    if stream.accept_phrase("were", "blocked", "by", "that"):
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in CARD_TYPES:
            stream.advance()
            if stream.accept_phrase("this", "turn"):
                d.blocked_by_bound_object = True
                return True
    # "…that **blocked or were blocked by it this turn**" (Venomous
    # Breath). The two-way reading of the clause directly above: the
    # bound object stood on one side of a block and the sentence names
    # whichever creatures stood on the other, whichever side that was.
    # Its own field, not a widening of the one-way one — the set is
    # strictly larger, and a lowering written for "were blocked by"
    # answering this phrase would destroy creatures the card does not
    # name.
    #
    # "It" and "that creature" are one referent here and both are
    # admitted: this is the `that …` postmodifier run, whose subject is
    # the sentence's own object, so neither spelling can be read as the
    # ability's source. The present-participle relation
    # (`in_combat_with_source`, "blocking or blocked by it") is a
    # different production reached by a different first word, which is
    # what keeps the two "it"s apart.
    elif stream.accept_phrase("blocked", "or", "were", "blocked", "by"):
        # Named apart from the entry mark above rather than `probe`, which is
        # what it was called in `postmodifiers` — where it **rebound** that
        # loop's own `probe`, so this arm opening and then failing left the
        # loop's fall-through resetting to here instead of to the "that" it
        # had marked. No card in the pool prints these six words without the
        # tail that satisfies them (Venomous Breath is the only one), so the
        # differential across the split is empty; the shadow is gone rather
        # than carried, because a refusal restoring less than it consumed is
        # not a behaviour worth preserving across a file boundary.
        bound_probe = stream.mark()
        named_bound = stream.accept_word("it")
        if not named_bound and stream.accept_word("that"):
            noun = stream.peek_word()
            if noun is not None and _singular(noun) in CARD_TYPES:
                stream.advance()
                named_bound = True
        if named_bound and stream.accept_phrase("this", "turn"):
            d.in_combat_with_bound_object = True
            return True
        stream.reset(bound_probe)
    # "…that were blocked by **target Wall** this turn" (Glyph of
    # Reincarnation). The same history against the *spell's own target*
    # instead of a bound object, so the blocker's own noun phrase is
    # read and travels with the relation — the lowering hoists it into
    # the instruction's `targets` description, which is what makes the
    # picker offer Walls. "This turn" is required here for the reason it
    # is required above: the record is kept per turn, and a clause
    # naming some other window is a different sentence.
    elif stream.accept_phrase("were", "blocked", "by", "target"):
        blocker = parse_filter(stream)
        if stream.accept_phrase("this", "turn"):
            d.blocked_by_target_object = blocker
            return True
    # "…that **target Wall blocked this turn**" (Glyph of Delusion). The
    # same relation as the passive clause directly above, printed with
    # the blocker as the sentence's subject rather than its agent — so
    # it sets the same field, and everything downstream (the lowering's
    # hoist, the role picker, the block record the handler reads) is
    # written once for both voices. Spelling it as its own field would
    # have been two names for one fact, and the second would need its
    # own reader everywhere the first already has one.
    elif stream.accept_word("target"):
        blocker = parse_filter(stream)
        if stream.accept_phrase("blocked", "this", "turn"):
            d.blocked_by_target_object = blocker
            return True
    # "…all creatures **that blocked this creature this turn**"
    # (Joven's Ferrets). The active voice of the passive clause above,
    # with the ability's own source as the referent — so it sets its
    # own field rather than either of theirs: which object the block
    # record is read against decides which permanent the sweep names,
    # and one field meaning either would leave the matcher guessing.
    #
    # Read *after* "blocked or were blocked by", whose first word this
    # is: tried first it would take the word and strand the "or".
    # "This turn" is required for that clause's reason — the record is
    # kept per turn, and a clause naming another window is a different
    # sentence.
    elif stream.at_word("blocked"):
        blocked_probe = stream.mark()
        stream.advance()
        if accept_source_reference(stream) and stream.accept_phrase(
            "this", "turn"
        ):
            d.blocked_source_this_turn = True
            return True
        stream.reset(blocked_probe)
# "…**that dealt damage to it this turn**" (Brine Hag). A history
# relative to the ability's source, answered from the damage record
# the victim carries rather than from the object's characteristics
# — so it is a flag the one lowering written for it reads, and every
# other one refuses (see ``ObjectFilter``). "This turn" is required:
# without it the sentence says something the record cannot answer.
    elif stream.accept_phrase("dealt", "damage", "to"):
        if accept_source_reference(stream) and stream.accept_phrase(
            "this", "turn"
        ):
            d.dealt_damage_to_source_this_turn = True
            return True
    # "…that **has been dealt damage this turn**" (Giant Shark). The
    # passive voice with no agent, which is the whole difference from
    # the clause above: that one asks who dealt it, this one only that
    # some damage was. Both halves required — a clause naming another
    # window is a different sentence, and the record is kept per turn.
    elif stream.accept_phrase("has", "been", "dealt", "damage"):
        if stream.accept_phrase("this", "turn"):
            d.was_dealt_damage_this_turn = True
            return True
    # "…that **was dealt damage this turn**" (Fatal Blow). The same
    # agentless passive one branch up in the simple past — one printed
    # fact in two English tenses, so it sets the same field rather than
    # earning one of its own: a second field would be a second answer to
    # "was this creature damaged", and the two would drift the moment a
    # matcher was taught only one of them.
    #
    # A branch rather than a word bolted onto the phrase above, because
    # the two spellings share no token: "has been dealt" and "was dealt"
    # differ in length as well as in words, and `accept_phrase` matches a
    # fixed run. The plural "were" is deliberately absent — the pool
    # prints it only in Suffocation's cast restriction, which is a fact about
    # a *player* and is read by `engine/cast_restrictions.py`, so
    # admitting it here would be a reading nothing tests.
    elif stream.accept_phrase("was", "dealt", "damage"):
        if stream.accept_phrase("this", "turn"):
            d.was_dealt_damage_this_turn = True
            return True
    stream.reset(start)
    return False
