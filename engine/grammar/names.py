"""What a printed card **name** is, read off the token stream.

Its own module rather than a tail of `nouns.py` for the reason that file's
split from `references.py` records: a name is not a description of a set of
objects, it is a literal string, and the scan that reads one shares nothing
with the vocabulary that reads a type line — no card types, no subtypes, no
postmodifiers. It sits below `nouns` because the noun phrase's ``named``
restriction calls it, and nothing here calls back.

`nouns.py` reached 997 of the guard's 1,000 lines before this split; the round
that added the cross-axis class union pushed it past. The lines that left are
the ones that were never about a noun phrase.
"""

from __future__ import annotations

from .lexer import render
from .stream import TokenStream


# Words that cannot be part of a card's name here because they start the next
# clause of the printed template. A name scan running past one of them would
# swallow "and/or a card named Igneous Cur" into the first name and report
# Alpine Houndmaster as a card that finds one card — so the scan stops, and the
# production then refuses the line at "put".
#
# The verbs are stops because a *subject* can carry a name too: "Creatures you
# control named Kobolds of Kher Keep get +2/+2" (Rohgahh of Kher Keep) ends the
# name where the sentence's verb begins, and without the stop the scan swallowed
# "get +2/+2" and the statement parser found no verb at all. No card in the pool
# has any of these words in its name (checked against every set file), so the
# stop can only end a scan the verb was never part of.
#
# "you" is the same stop one clause later: "permanents named Sheltered Valley
# **you control**" ends the name where the *postmodifier* begins, and without
# the stop the scan swallowed the seat — leaving a filter asking for a card
# literally named "Sheltered Valley you control" (which matches nothing) with
# ``controller`` never set (so the restriction was dropped as well). Both halves
# silent, and both wrong in the direction of a wider sweep. No shipped card is
# affected only because the pool's one instance of the phrase sits inside
# reminder text (Master of the Hunt's banding parenthetical, which the lexer
# drops); Sheltered Valley is the first card to print it as rules text.
_NAME_STOPS = (
    "reveal", "put", "then", "and", "or", "in", "get", "gets", "has", "have",
    "you",
)

# The same stops, but only *after a comma*. A comma inside a name is the one a
# legendary title carries ("Chandra, Flame's Catalyst"), and no card in this
# pool follows one with an article — checked against every set file, and it is
# not a coincidence: a Magic title's second half is an apposition ("Adeliz, the
# Cinder Wind"), never an indefinite noun phrase.
#
# What follows one *outside* a name is the next item of a printed list:
# "Sacrifice a creature named Feral Shadow**, a creature named
# Breathstealer**, and this creature" (Urborg Panther). Without the stop the
# scan ran to the next "and" and produced a filter asking for a card literally
# named "Feral Shadow, a creature named Breathstealer" — which matches nothing,
# so the cost was admitted and could never be paid. "the" is deliberately not
# here: it is exactly the word a legendary apposition does begin with.
_AFTER_COMMA_STOPS = ("a", "an", "another", "this")


def parse_card_name(stream: TokenStream) -> str:
    """The card name after ``named``, wherever a noun phrase carries one.

    Read token by token rather than as one word, because a legendary name
    carries the same punctuation the sentence does — "Chandra, Flame's
    Catalyst, reveal it," holds two commas and only the second ends the name. A
    comma is taken as part of the name only when a name word follows it, and
    the rendered text is compared through ``search_filters.name_key``, which
    ignores punctuation and case on both sides.
    """
    start = stream.mark()
    while not stream.exhausted:
        if stream.at_punct(".") or stream.at_word(*_NAME_STOPS):
            break
        if stream.at_punct(","):
            mark = stream.mark()
            stream.advance()
            if (
                stream.exhausted
                or stream.at_punct(".")
                or stream.at_word(*_NAME_STOPS)
                or stream.at_word(*_AFTER_COMMA_STOPS)
            ):
                stream.reset(mark)
                break
            continue
        stream.advance()
    if stream.mark() == start:
        raise stream.error("expected the name the search is for")
    return render(stream.tokens[start:stream.mark()])


#: The words a *bare* name scan stops before. Each opens the clause that follows
#: a name in the one template that prints one — a duration, a conjunct, or the
#: word ending a replacement. No card in the pool has any of them in its name
#: (checked against every set file), so a stop can only end a scan the name was
#: never part of.
_BARE_NAME_STOPS = ("this", "until", "during", "and", "or", "instead")

#: The words a bare name may not *begin* with. Each one opens a printed **noun
#: phrase** — a description of a set of objects — and a phrase the vocabulary
#: could not read must refuse the line rather than be taken for a literal
#: string: a name matching no card is a shield that never fires, silent and in
#: nobody's favour. Refusing leaves the wording in the backlog, which is where
#: an unread noun phrase belongs.
_NOT_A_NAME = (
    "a", "an", "the", "each", "all", "any", "every", "another", "other",
    "target", "this", "that", "those", "these", "its", "your", "their",
    "one", "two", "three", "no", "up", "attacking", "blocking", "tapped",
    "untapped", "unblocked", "enchanted", "equipped",
)


def accept_source_card_name(stream: TokenStream) -> str | None:
    """A card's printed name standing on its own, or None with the cursor unmoved.

    "…that would be dealt to this creature **by Torrent of Lava** this turn."
    (the ability Torrent of Lava grants each creature while it is on the stack.)
    The name is a literal string rather than a description of a set, which is
    this module's subject — and it is read *last*, after every noun-phrase
    reader has refused, because those readers are what tell a printed phrase
    from a printed name.

    Two guards keep it from swallowing a phrase nobody read: it refuses
    outright when the first word opens a noun phrase (:data:`_NOT_A_NAME`), and
    it stops before the words that open the next clause
    (:data:`_BARE_NAME_STOPS`). Both fail towards a refusal, so an unread phrase
    stays unread rather than becoming a name that matches nothing.
    """
    mark = stream.mark()
    first = stream.peek_word()
    if first is None or first in _NOT_A_NAME or first in _NAME_STOPS:
        return None
    while not stream.exhausted:
        if (
            stream.at_punct(".")
            or stream.at_punct(",")
            or stream.at_word(*_BARE_NAME_STOPS)
            or stream.at_word(*_NAME_STOPS)
            or stream.peek_word() is None
        ):
            break
        stream.advance()
    if stream.mark() == mark:
        return None
    return render(stream.tokens[mark:stream.mark()])


__all__ = ["accept_source_card_name", "parse_card_name"]


def accept_original_expansion(stream: TokenStream) -> str | None:
    """``a name originally printed in the <Set> expansion`` -- the *set code*
    the printed expansion name resolves to, or None with the cursor unmoved.

    A set name is a literal string read off the stream, which is this module's
    subject: it shares no vocabulary with the filter parser above, so the scan
    that reads one lives here beside the card-name scan for the same reason.

    Two readers ask it -- the noun phrase's postmodifier ("all nontoken
    permanents **with** a name originally printed in the Homelands expansion",
    Apocalypse Chime) and the passive sacrifice production ("Each nontoken
    permanent with a name originally printed in the Antiquities expansion is
    sacrificed by its controller", Golgothian Sylex). One reader, because two
    scans of one printed phrase are two spellings free to disagree about where
    the set name ends (idiom 36).

    The name is resolved through ``card_loader.set_code_for_expansion_name`` --
    the manifest already holds both the name and the code, so the mapping is a
    projection of the registry rather than a second table. A name the manifest
    does not know refuses without consuming, which is the right answer: the
    effect would otherwise sweep whichever set the caller guessed.
    """
    from ..card_loader import set_code_for_expansion_name

    mark = stream.mark()
    if not stream.accept_phrase(
        "a", "name", "originally", "printed", "in", "the"
    ):
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_word("expansion"):
        word = stream.peek_word()
        if word is None:
            stream.reset(mark)
            return None
        words.append(word)
        stream.advance()
    if not words or not stream.accept_word("expansion"):
        stream.reset(mark)
        return None
    set_code = set_code_for_expansion_name(" ".join(words))
    if set_code is None:
        stream.reset(mark)
        return None
    return set_code
