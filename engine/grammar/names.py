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
_NAME_STOPS = ("reveal", "put", "then", "and", "or", "in", "get", "gets", "has", "have")


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
            if stream.exhausted or stream.at_punct(".") or stream.at_word(*_NAME_STOPS):
                stream.reset(mark)
                break
            continue
        stream.advance()
    if stream.mark() == start:
        raise stream.error("expected the name the search is for")
    return render(stream.tokens[start:stream.mark()])


__all__ = ["parse_card_name"]
