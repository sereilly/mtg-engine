"""``accept_event_phrase`` — a trigger table's word run, matched against a line.

A floor rather than a family. :mod:`trigger_matched` walks the ``whenever``
tables against a stream and :mod:`triggers` walks the ``when`` ones, and both
owe a pre-Sixth-Edition card's self-naming spelling the same reading — so the
substitution lives under both rather than in either, which is the shape
``phrases`` has under the effect families and ``_common`` has under the
lowerings.

Split out of ``triggers`` at Mercadian Masques' Phase 0, when the ``whenever``
half of that module left for :mod:`trigger_matched` and this was the one thing
the two halves still shared. Above :mod:`trigger_tables`, because it consumes
the nouns that table defines and that module's own docstring makes it pure
data; below both callers, because neither owns it.
"""

from __future__ import annotations

from .lexer import SELF
from .stream import TokenStream
from .trigger_tables import _DAMAGER_NOUNS


def accept_event_phrase(stream: TokenStream, phrase: tuple[str, ...]) -> bool:
    """Consume *phrase*, reading a SELF token wherever it spells "this <noun>".

    The tables in this file write the source out the modern way — "this
    creature attacks", "a creature dealt damage by this creature this turn
    dies" — and a pre-Sixth-Edition card says its own name instead, which the
    lexer collapses to one SELF token. Those are the same two words, so a plain
    word-run match reads only one of the two spellings: Axelrod Gunnarson's
    death trigger and Nicol Bolas's damage trigger are Sengir Vampire's and
    Hypnotic Specter's conditions printed the old way, and both front ends
    refused them while the productions that ask ``at_kind(SELF)`` by hand read
    theirs. So the substitution is made here, once, for every entry in every
    table rather than by spelling a second row per card.

    All-or-nothing, like ``accept_phrase``: a partial match leaves the stream
    where it was, because a production that consumed half a phrase would strand
    the rest of the line and break full-token consumption.
    """
    mark = stream.mark()
    index = 0
    while index < len(phrase):
        if (
            phrase[index] == "this"
            and index + 1 < len(phrase)
            and phrase[index + 1] in _DAMAGER_NOUNS
            and stream.at_kind(SELF)
        ):
            stream.advance()
            index += 2
            continue
        if not stream.accept_phrase(phrase[index]):
            stream.reset(mark)
            return False
        index += 1
    return True

