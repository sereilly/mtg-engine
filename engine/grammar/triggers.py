"""Trigger events — the condition half of a triggered ability line.

The word tables a printed trigger clause is matched against, and the fragment
productions that read one. A production here reads the clause between the
trigger word and the comma and knows nothing about a whole line.

**This family has moved twice, and both moves are the size guard working as
documented.** It started in ``parser.py`` and left when the counters-put-on
production pushed that module past a thousand lines; it lived in ``phrases.py``
until Antiquities' trigger work — a cast-type narrowing, a general
put-into-a-graveyard event, and a compound tap-or-activate event — pushed
*that* module past the same line. The guard's instruction is to split along the
family the new work belongs to rather than raise the number, and by then the
trigger tables and their readers were plainly one family: every table in here
is read only by the productions in here.

Sits between ``phrases`` and ``effects`` in the parse layer order: it reads
``phrases``' subject-filter reader and nothing above. (That list read
"durations, numbers, subject filters" when it was written. The number reader is
:mod:`trigger_matched`'s import now, and the durations are a module of their
own, ``durations``, which nothing here reads.)

**And it has now moved a third time, in place.** The ``whenever`` clause
readers are :mod:`trigger_matched` as of Mercadian Masques' Phase 0 and the
shared word-run matcher is :mod:`trigger_phrases`; what is left here is
:func:`_parse_trigger_event`, the dispatch over the three printed trigger
words, plus the ``when``- and ``at``-specific readers it puts in front of the
shared tables.
"""

from __future__ import annotations

from . import ast
from .lexer import SELF
from .phrases import parse_subject_filter_at
from .stream import TokenStream
from .state_triggers import _parse_state_trigger_event
from .trigger_subjects import (
    _parse_attached_event,
    _parse_attached_step_event,
    _parse_named_subject_tap_event,
)
from .trigger_matched import _parse_matched_event
from .trigger_phrases import accept_event_phrase
from .trigger_tables import _AT_EVENTS, _DAMAGER_NOUNS


def _parse_trigger_event(stream: TokenStream) -> ast.TriggerEvent | None:
    if stream.accept_word("whenever"):
        return _parse_matched_event(stream, "whenever")
    if stream.accept_word("at"):
        attached_step = _parse_attached_step_event(stream, "at")
        if attached_step is not None:
            return attached_step
        for kind, phrase in _AT_EVENTS:
            if stream.accept_phrase(*phrase):
                return ast.TriggerEvent(kind, "at")
        return None
    if stream.accept_word("when"):
        # "…dies **during combat**" (Mongrel Pack). Read before the bare
        # spelling it extends, for this file's standing ordering rule: matched
        # there, the two extra words are left on the stream and the line fails
        # full-token consumption — which is the *safe* half of the failure. The
        # unsafe half is on the regex side, where an unanchored bare row reads
        # them as nothing at all.
        #
        # The narrowing itself is `engine/oracle.py`'s payload and the death
        # fire site's to enforce; what is owed here is reading the same
        # sentence, so a line one front end claims is not a card the other
        # refuses.
        if accept_event_phrase(stream, ("this", "creature", "dies", "during", "combat")):
            return ast.TriggerEvent("dies", "when")
        if accept_event_phrase(stream, ("this", "creature", "dies")):
            return ast.TriggerEvent("dies", "when")
        # CR 700.4: "dies" *means* "is put into a graveyard from the
        # battlefield", so Brood of Cockroaches' long spelling is the same
        # event and not a second one. "Your" graveyard is not a narrowing
        # either — CR 404.1 sends a permanent to its owner's graveyard, and the
        # subject here is the ability's own source, so the possessive can only
        # ever be its controller's on a card that is also its owner's.
        #
        # Read before the state-trigger reader below for the same reason every
        # long phrase in this file is read before a short one: nothing else
        # opens on these words, and a production that got there first would
        # strand the tail.
        #
        # The permanent noun and the article are both read rather than fixed.
        # Lich prints "**this enchantment** … into **a** graveyard", and with
        # neither spelling here the subject-led death production below claimed
        # it as `permanent_dies` — a *different* fire site, watching every
        # permanent that matches a filter rather than this one's own death.
        # CR 404.1 sends a permanent to its owner's graveyard, so "a" and
        # "your" name one pile for a card its controller owns.
        for noun in _DAMAGER_NOUNS:
            for article in ("your", "a"):
                if accept_event_phrase(stream, (
                    "this", noun, "is", "put", "into", article, "graveyard",
                    "from", "the", "battlefield",
                )):
                    return ast.TriggerEvent("dies", "when")
        state = _parse_state_trigger_event(stream, "when")
        if state is not None:
            return state
        # "**When** enchanted land becomes tapped, destroy it" (Blight). The
        # same event as the whenever spelling — one printed word apart — so it
        # is the same production, asked with the word this branch read.
        named_tap = _parse_named_subject_tap_event(stream, "when")
        if named_tap is not None:
            return named_tap
        # "**When** enchanted creature is dealt damage, destroy it." (Mortal
        # Wound.) Blight's argument one production over, and the asymmetry it
        # closes was invisible from either side alone: `engine/oracle.py`'s
        # table reads this condition under **both** printed words — it falls
        # back to the whenever table for any "when" line — while this front end
        # read it under one. So the condition parsed, the *effect* behind it
        # did not, and the card compiled with a trigger whose clause had no
        # instruction. CR 603.1 makes the two words one kind of ability; how
        # often it triggers while it exists is not something a fire site reads.
        attached = _parse_attached_event(stream, "when")
        if attached is not None:
            return attached
        # "When you remove the last intervention counter from this enchantment"
        # (Divine Intervention). Read here as well as in `engine/oracle.py`'s
        # table for the reason stated above the threshold trigger: both front
        # ends see the whole line, and a condition only one of them reads leaves
        # the other refusing the effect behind it.
        mark_removal = stream.mark()
        if stream.accept_phrase("you", "remove", "the", "last"):
            kind = stream.peek_word()
            if kind:
                stream.advance()
                if stream.accept_word("counter") and stream.accept_word("from"):
                    if stream.at_kind(SELF) or stream.at_word("this"):
                        stream.advance()
                        stream.accept_word(
                            "artifact", "aura", "creature", "enchantment",
                            "permanent", "land",
                        )
                        return ast.TriggerEvent("last_counter_removed", "when")
        stream.reset(mark_removal)
        # "When the last ore counter **is removed** from this Aura" (Orcish
        # Mine). The passive voice of the branch above and the same event: a
        # counter removal is one event whoever performed it (CR 122.1), and the
        # sweep that announces it reads the record every removal path writes.
        # Read on this front end as well as in `engine/oracle.py`'s table, for
        # the reason the active voice is: a condition only one of them reads
        # leaves the other refusing the effect behind it.
        mark_passive = stream.mark()
        if stream.accept_phrase("the", "last"):
            kind = stream.peek_word()
            if kind:
                stream.advance()
                if stream.accept_word("counter") and stream.accept_phrase(
                    "is", "removed", "from"
                ):
                    if stream.at_kind(SELF) or stream.at_word("this"):
                        stream.advance()
                        stream.accept_word(
                            "artifact", "aura", "creature", "enchantment",
                            "permanent", "land",
                        )
                        return ast.TriggerEvent("last_counter_removed", "when")
        stream.reset(mark_passive)
        # "When a spell or ability an opponent controls causes you to discard
        # this card" (Psychic Purge). Read on both front ends, same reason.
        if stream.accept_phrase(
            "a", "spell", "or", "ability", "an", "opponent", "controls",
            "causes", "you", "to", "discard", "this", "card",
        ):
            return ast.TriggerEvent("discarded_by_opponent_effect", "when")
        # "When **you cast this spell**" (Mana Vortex) — CR 603.6d, an ability
        # that triggers on its own object being cast. Read on this front end
        # too, for the reason every condition above it is: a condition only one
        # of them sees leaves the other refusing the effect behind it.
        if stream.accept_phrase("you", "cast", "this", "spell"):
            return ast.TriggerEvent("self_cast", "when")
        # "When **this card is put into your graveyard from your library**"
        # (Gaea's Blessing). CR 113.6k: a trigger condition that cannot trigger
        # from the battlefield functions in every zone it can trigger from, and
        # this one names a move a permanent cannot make — so it watches the
        # card wherever it is. Read on this front end too, for the reason every
        # condition around it is: a condition only one of them sees leaves the
        # other refusing the effect behind it.
        if stream.accept_phrase(
            "this", "card", "is", "put", "into", "your", "graveyard",
            "from", "your", "library",
        ):
            return ast.TriggerEvent(
                "self_put_into_graveyard_from_library", "when"
            )
        # "When **a card is put into your graveyard from anywhere**" (Energy
        # Field). The row above with any card for its object and every zone for
        # its source — a permanent watching its controller's graveyard rather
        # than a card watching itself. Read on this front end too, for the
        # reason every condition around it is: a condition only one of them
        # sees leaves the other refusing the effect behind it.
        if stream.accept_phrase(
            "a", "card", "is", "put", "into", "your", "graveyard",
            "from", "anywhere",
        ):
            return ast.TriggerEvent("card_put_into_graveyard", "when")
        # "When **this creature is put into a graveyard from anywhere**"
        # (Serra Avatar). CR 113.6k again, one zone wider: "from anywhere" is
        # every zone the card can be in, so it is watched off the card and not
        # off a battlefield — and it is deliberately *not* the death reading,
        # since CR 700.4 makes dying "from the battlefield" and an Avatar milled
        # or discarded never dies. Read on this front end for the reason the
        # library row above it is.
        #
        # The noun is read rather than fixed: a card names itself by whatever
        # word it likes (CR 109.5), and "card" belongs beside the permanent
        # nouns because a sentence about a move out of any zone is a sentence
        # about a card.
        for noun in (*_DAMAGER_NOUNS, "card"):
            if accept_event_phrase(stream, (
                "this", noun, "is", "put", "into", "a", "graveyard",
                "from", "anywhere",
            )):
                return ast.TriggerEvent(
                    "self_put_into_graveyard_from_anywhere", "when"
                )
        # "When you control **no Islands** / **no Forests**, sacrifice this
        # creature." (Sea Serpent, Island Fish Jasconius; Gorilla Pack in Ice
        # Age.) The negative twin of `controls_matching_permanent` below, and
        # the noun is payload for the same reason it is there: this was a
        # ``no_islands`` kind with the land type welded into the name, so a card
        # printing any other type was a card the engine could not read.
        mark_none = stream.mark()
        if stream.accept_phrase("you", "control", "no"):
            # Plural, because "no" counts: the card prints "no **Islands**",
            # never "no an Island", so the counted-position quantifier is the
            # one to admit.
            described = parse_subject_filter_at(stream, plural=True)
            if described is not None:
                return ast.TriggerEvent(
                    "controls_no_matching", "when", subject=described
                )
        stream.reset(mark_none)
        # "When you control **a Dwarf**" (Goblins of the Flarg). The positive
        # state trigger (CR 603.8), read on this front end too because a
        # condition only one of them sees is a card whose halves watch
        # different sets — the narrowing has to be the same phrase on both.
        # "When **an opponent** controls a creature with power 4 or greater"
        # (Hidden Predators) is the same condition asked of another seat, and
        # the seat is payload on ``engine/oracle.py``'s row rather than a kind
        # of its own; this side has only to read the words. Both spellings in
        # one branch, so a card printing either gets the same noun parser.
        mark_controls = stream.mark()
        if stream.accept_phrase("you", "control") or stream.accept_phrase(
            "an", "opponent", "controls"
        ):
            controlled = parse_subject_filter_at(stream)
            if controlled is not None:
                return ast.TriggerEvent(
                    "controls_matching_permanent", "when", subject=controlled
                )
            stream.reset(mark_controls)
        # "When **the token** leaves the battlefield, …" (Dance of Many). The
        # CR 603.6c event asked about the token this permanent created rather
        # than about the permanent itself — read on this front end too, because
        # a narrowing only one of them sees is a card whose two halves watch
        # different objects (the pipeline's oldest failure mode).
        if stream.accept_phrase("the", "token", "leaves", "the", "battlefield"):
            return ast.TriggerEvent("created_token_leaves_battlefield", "when")
        # "**When you lose control of this artifact**, …" (Gustha's Scepter).
        # CR 603.10d's event, read on this front end too for the reason the
        # token row above states: a condition only one of them sees is a card
        # whose two halves watch different things. The permanent noun is
        # consumed as a word rather than matched against a spelling, so an
        # enchantment or a creature printing the same sentence needs no branch —
        # and "it" is the same reference one pronoun shorter.
        mark_control = stream.mark()
        if stream.accept_phrase("you", "lose", "control", "of"):
            if stream.accept_word("it"):
                return ast.TriggerEvent("lose_control_of_source", "when")
            if stream.accept_word("this", "the") and not (
                stream.exhausted or stream.at_punct(",", ".")
            ):
                stream.advance()
                return ast.TriggerEvent("lose_control_of_source", "when")
        stream.reset(mark_control)
        mark = stream.mark()
        if stream.at_kind(SELF) or stream.at_word("this"):
            stream.advance()
            if not stream.at_kind(SELF):
                stream.accept_word("creature", "artifact", "enchantment", "land", "aura")
            if stream.accept_word("enters"):
                stream.accept_phrase("the", "battlefield")
                # "When this creature **enters or dies**, …" (Goblin Marshal,
                # Hunting Moa). CR 603.1's one ability with two trigger events,
                # and the engine's standing answer to that shape is one
                # condition kind read at both fire sites — the arrangement
                # `creature_attacks_or_blocks` and
                # `phases_out_or_leaves_battlefield` already have, and the
                # reason this is not two abilities: an ability is one object,
                # and splitting it would make a card that counts its own
                # triggers count two.
                #
                # Read **after** the entry phrase rather than as a phrase of its
                # own, because "enters" is its strict prefix: a table row for
                # the joined event placed under the bare one would never be
                # reached, and placed over it would have to re-spell every
                # permanent noun the branch above consumes as a word.
                if stream.accept_phrase("or", "dies"):
                    return ast.TriggerEvent("enters_or_dies", "when")
                return ast.TriggerEvent("enters_battlefield", "when")
            if stream.accept_word("leaves"):
                stream.accept_phrase("the", "battlefield")
                return ast.TriggerEvent("leaves_battlefield", "when")
        stream.reset(mark)
        # "**When** this creature blocks" (Elder Land Wurm), "**when** this
        # creature attacks or blocks" (Time Elemental) — events the "whenever"
        # branch already reads, printed with the one-shot word. CR 603.1 makes
        # the two words one kind of ability; the difference is how often it
        # triggers while it exists, not what triggers it, and every fire site in
        # this engine reads the kind rather than the word.
        #
        # So the **whole** reader is asked here rather than a hand-written
        # subset of it. It used to be the phrase table alone, which is one
        # subset smaller than the last one this line held ("blocks", which was
        # why Elder Land Wurm's condition read and Time Elemental's did not) —
        # and every clause that carries a *noun phrase* was still out of reach:
        # a narrowed cast, a subject-led entry, a quantified tap. Timid Drake
        # ("When another creature enters") and Straw Golem ("When an opponent
        # casts a creature spell") are the two Weatherlight cards that name it,
        # and `engine/oracle.py`'s regex table reads both words for either — so
        # the disagreement was never about the condition, only about which
        # cards have one.
        return _parse_matched_event(stream, "when")
    return None
