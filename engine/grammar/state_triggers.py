"""CR 603.8's state triggers — the condition that is a *state*, not an event.

Split out of ``triggers`` the third time that module reached the thousand-line
guard, and the third time along a line the family already had: it started in
``parser``, shed its phrase-to-event data to ``trigger_tables`` and its
named-subject readings to ``trigger_subjects``, and this is what was left that
is not an event at all.

The boundary is the CR's own. Every other production next door reads a clause
naming something that **happens** — a creature attacks, a land is tapped, a
spell is cast — and fires once per occurrence. CR 603.8 is a condition that is
simply *true*: the ability triggers whenever the game state matches and does
not trigger again until the state stops matching. Nothing in the two readings
is shared, which is why this module imports no word table from up there and
``triggers`` reaches down for one name.

Below ``triggers`` in the layer order for that reason, and above nothing but
the readers a fragment production needs.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .lexer import NUMBER, SELF
from .phrases import parse_subject_filter_at
from .readers import accept_source_reference
from .stream import TokenStream
from .vocabulary import KEYWORD_ABILITIES, NUMBER_WORDS


def _parse_state_trigger_event(
    stream: TokenStream, word: str
) -> ast.TriggerEvent | None:
    """``there are <state>`` — CR 603.8's state triggers, under either word.

    "**When** there are four or more page counters on this artifact"
    (Mazemind Tome); "**Whenever** there are four or more tide counters on this
    creature" (Homarid, Tidal Influence). CR 603.1 makes the two words one kind
    of ability — they differ in how often it triggers while it exists, never in
    what triggers it — and for a state trigger not even in that: CR 603.8 says
    it triggers whenever the game state matches, whichever word is printed. So
    the reading is one production asked with the word the line carried, rather
    than a copy per branch, which is how one spelling ends up read and the
    other refusing.

    Read here as well as in `engine/oracle.py`'s table because both front ends
    see the whole line, and a condition only one of them reads leaves the other
    refusing the effect behind it.

    Marked, because both readings behind "there are" can refuse: the block used
    to consume the two words and fall through with the cursor past them, so
    every later branch was offered a line missing its opening. That was
    invisible while one production followed the phrase and is what kept Mana
    Vortex's reading below from being reached at all.
    """
    # "When **this creature's power is 7 or greater**, sacrifice it."
    # (Phyrexian Devourer.) CR 603.8 read off a characteristic rather than off a
    # census, and here rather than in a branch of its own because the *word* is
    # the only thing this family shares — the caller passes it in, so both
    # printings are one production.
    #
    # The threshold is consumed and dropped, exactly as the counter branch below
    # drops its own: `engine/oracle.py`'s table is the front end that supplies
    # the condition (and its payload) to the dispatcher, and this one supplies
    # the effect. A number carried here would be a second copy of it.
    # "When **a player doesn't pay this enchantment's cumulative upkeep**, …"
    # (Thought Lash.) Read on this front end as well as in `engine/oracle.py`'s
    # table, for the reason stated above: both see the whole line, and a
    # condition only one of them reads leaves the other refusing the effect.
    # "When **a player has no cards in hand**, …" (Veiled Crocodile.) CR 603.8
    # asked of a hand rather than of a board, and read on this front end for
    # the reason every branch below it is: both front ends see the whole line,
    # and a condition only one of them reads leaves the other refusing the
    # effect behind it. The seat is not narrowed — the card says "a player",
    # which is every seat — so the phrase carries no payload and
    # ``engine/oracle.py``'s row is the one that names the kind.
    if stream.accept_phrase("a", "player", "has", "no", "cards", "in", "hand"):
        return ast.TriggerEvent("player_has_no_cards_in_hand", word)

    # "When **you have 10 or less life**, …" (Opal Avenger.) "When **an
    # opponent has 10 or less life**, …" (Lurking Jackals.) CR 603.8 read
    # off a life total, and read on this front end for the reason the branch
    # above it is: both front ends see the whole line, and a condition only
    # one of them reads leaves the other refusing the effect behind it.
    #
    # The threshold **and the seat** are both consumed and dropped, exactly
    # as the power branch below drops its own: `engine/oracle.py`'s table is
    # the front end that supplies the condition and its payload to the
    # dispatcher, and a copy of either carried here would be free to
    # disagree with it. Both spellings of the number are accepted because
    # the lexer gives a printed digit its own token kind, and "10" is the
    # only spelling either card printing this uses.
    life_mark = stream.mark()
    if stream.accept_phrase("you", "have") or stream.accept_phrase(
        "an", "opponent", "has"
    ):
        if stream.at_kind(NUMBER) or stream.peek_word() in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase("or", "less", "life"):
                return ast.TriggerEvent("life_at_most", word)
    stream.reset(life_mark)

    unpaid_mark = stream.mark()
    if stream.accept_phrase("a", "player", "doesn't", "pay", "this"):
        stream.accept_word(
            "artifact", "creature", "enchantment", "permanent", "land",
        )
        if stream.accept_phrase("'s", "cumulative", "upkeep"):
            return ast.TriggerEvent("cumulative_upkeep_unpaid", word)
    stream.reset(unpaid_mark)

    power_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase("'s", "power", "is"):
        # Both spellings of the threshold. The lexer gives a printed digit its
        # own token kind, so a word-table test alone reads "four" and refuses
        # "7" — which is the only spelling the one card printing this sentence
        # uses.
        if stream.at_kind(NUMBER) or stream.peek_word() in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase("or", "greater"):
                return ast.TriggerEvent("source_power_at_least", word)
    stream.reset(power_mark)

    # "When **this creature has flying**, sacrifice it." (Floodgate.) The
    # keyword twin of the power threshold above, in the same family and read
    # here for the same reason: both front ends see the whole line, and a
    # condition only one of them reads leaves the other refusing the effect.
    #
    # The keyword is consumed and dropped, exactly as the threshold above is:
    # `engine/oracle.py`'s table is the front end that supplies the condition
    # and its payload to the dispatcher, and a copy carried here would be free
    # to disagree with it. It is *checked* against the vocabulary rather than
    # skipped, so "has three heads" refuses the line instead of claiming it.
    # "When **this enchantment has no +1/+1 counters on it**, sacrifice it."
    # (Afiya Grove.) The empty-store state, read here for the reason the
    # keyword branch below it states: both front ends see the whole line, and a
    # condition only one of them reads leaves the other refusing the effect.
    #
    # Above the keyword branch, whose vocabulary test would refuse "no" and
    # rewind — the same order `engine/oracle.py`'s table takes for the same
    # pair, so the two front ends read the sentence the same way round.
    #
    # The counter kind is consumed and dropped: `engine/oracle.py`'s table
    # supplies the payload the sweep dispatches on, and a copy carried here
    # would be free to disagree with it.
    empty_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase("has", "no"):
        if stream.peek() is not None:
            stream.advance()
            if stream.accept_word("counters", "counter") and stream.accept_phrase(
                "on", "it"
            ):
                return ast.TriggerEvent("source_has_no_counters", word)
    stream.reset(empty_mark)

    keyword_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_word("has"):
        word_token = stream.peek_word()
        if word_token and word_token in KEYWORD_ABILITIES:
            stream.advance()
            return ast.TriggerEvent("source_has_keyword", word)
    stream.reset(keyword_mark)

    state_mark = stream.mark()
    if stream.accept_phrase("there", "are"):
        # "When there are **no lands on the battlefield**, sacrifice this
        # enchantment." (Mana Vortex.) "When there are **no creatures on the
        # battlefield**, …" (Drop of Honey.) CR 603.8 again, asked about every
        # battlefield rather than about the source's controller — a different
        # set and so a different kind, since a Mana Vortex whose controller has
        # run out of lands stays while an opponent has one.
        #
        # The noun is carried rather than dropped, which is the opposite of
        # what the threshold and the keyword above do — and the difference is
        # that this one is a **subject**. `engine/oracle.py`'s row reads it as
        # an `absent_subjects` group and `_resolve_subject_groups` turns it into
        # the payload the dispatcher tests, so a phrase only one front end read
        # would be a card whose two halves watch different sets. That equality
        # is asserted (`test_a_narrowed_trigger_reads_the_same_subject_on_both
        # _sides`), which is what makes it cheaper to read the noun here than
        # to argue that dropping it is safe.
        absent_mark = stream.mark()
        if stream.accept_word("no"):
            # Plural, because "no" counts: the card prints "no **lands**", never
            # "no a land", so the counted-position quantifier is the one to
            # admit — the same reading `controls_no_matching` takes of the same
            # word one production up.
            described = parse_subject_filter_at(stream, plural=True)
            # The noun parser reads "on the battlefield" itself, as CR 403.1's
            # shared zone — and here that is the *kind*, not a narrowing: this
            # condition asks about every battlefield and its name says so. So
            # the scope is required (a card printing "when there are no
            # creatures" alone is a different sentence and refuses) and then
            # stripped, which is also what keeps the phrase this front end
            # carries identical to the one `engine/oracle.py`'s row reads out of
            # its `absent_subjects` group.
            if described is not None and described.on_the_battlefield:
                return ast.TriggerEvent(
                    "no_permanents_anywhere", word,
                    subject=dataclasses.replace(described, on_the_battlefield=False),
                )
        stream.reset(absent_mark)
        count = stream.peek_word()
        if count in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase("or", "more"):
                kind = stream.peek_word()
                if kind:
                    stream.advance()
                    if stream.accept_word("counters") and stream.accept_word("on"):
                        if stream.at_kind(SELF) or stream.at_word("this"):
                            stream.advance()
                            stream.accept_word(
                                "artifact", "creature", "enchantment",
                                "permanent", "land",
                            )
                            return ast.TriggerEvent(
                                "counters_reach_threshold", word,
                            )
    stream.reset(state_mark)
    return None
