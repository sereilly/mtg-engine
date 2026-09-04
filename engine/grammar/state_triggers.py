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

from . import ast
from .lexer import NUMBER, SELF
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
        # enchantment." (Mana Vortex.) CR 603.8 again, asked about every
        # battlefield rather than about the source's controller — a different
        # set and so a different kind, since a Mana Vortex whose controller has
        # run out of lands stays while an opponent has one.
        if stream.accept_phrase("no", "lands", "on", "the", "battlefield"):
            return ast.TriggerEvent("no_lands_anywhere", word)
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
