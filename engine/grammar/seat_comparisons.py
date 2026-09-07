"""``who controls more creatures than they do`` — a seat picked out by a
**comparison against another seat**.

The board-state twin of ``records.accept_player_deed``, which reads the same
grammatical shape — a relative clause narrowing *which seats* a sentence is
about — off an event record instead. Its own module rather than another
production in that one because the two differ in the property that decides
what may enforce them: a deed is a record only a resolution holds, and a
comparison is a count anybody can take while CR 601.2c is choosing targets. So
this clause is the one the **picker** answers, and `records` is not where a
question about a board belongs.

Two printed frames over one reading, which is what makes this a table rather
than ten cards:

* the verb frame — "who **controls** more creatures than they do" (Oath of
  Druids), "who **has** more life than they do" (Oath of Mages), "who **has**
  at least two fewer creature cards in their graveyard than you do" (Keeper of
  the Dead);
* the possessive frame — "**whose graveyard has** fewer creature cards in it
  than their graveyard does" (Oath of Ghouls), which names the same set with
  the zone hoisted in front of the noun.

Every quantity is a printed noun phrase read by the caller's own filter parser
and counted by ``handlers/_common.evaluate_count``, so a card printed about
artifacts or about a library is this clause with one word changed. Life is the
one exception and it is named rather than described: a life total is not a pile
to scan.

*parse_filter* is handed down rather than imported, exactly as
``accept_player_deed`` takes it — this module sits below `nouns` in the parse
layering, and the inversion keeps the clause readable from `choices` and from
`player_verbs` without either of them being reached from here.

Above `records`, which it reads for the printed threshold ("at least **two**
more"), and below `nouns`.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .errors import GrammarError
from .records import accept_printed_number
from .stream import TokenStream

#: The quantity that is **named** rather than described, and the only one.
#:
#: `handlers/_common.evaluate_count` answers it under ``board_count`` for the
#: reason that node's own docstring gives: a life total is not a set of objects
#: in a zone, so no noun phrase describes it and no filter counts it. A closed
#: table so that a printing naming some other bare quantity refuses the line
#: rather than lowering onto a count of nothing.
_NAMED_QUANTITIES: frozenset[str] = frozenset({"life"})

#: The seats a comparison may be *against*, as the ``PlayerRef`` kind each
#: printed word names.
#:
#: "than **you** do" is the seat activating the ability; "than **they** do" is
#: the seat the sentence in front of this one named — under the Oaths' trigger
#: that is the player whose upkeep it is, which the fire site froze. Both are
#: the seat doing the choosing, and the two words are kept apart anyway: a
#: printing that compared against somebody else would be read here as one of
#: these two and silently answered against the chooser, which is the failure
#: this whole family exists to refuse.
_REFERENCE_SEATS: dict[str, str] = {
    "you": "you",
    "they": "that_player",
}

#: Zone words the possessive frame may hoist in front of its noun — "**whose
#: graveyard** has fewer creature cards in it".
#:
#: Held to the zones ``lowering/_amounts._COUNTABLE_ZONES`` will actually count,
#: minus the battlefield, which nobody's possessive names (a battlefield is
#: shared, CR 403.1). A word outside this refuses rather than being hoisted onto
#: a pile the counter cannot read.
_POSSESSIVE_ZONES: frozenset[str] = frozenset({"graveyard", "hand", "library"})


def _accept_margin(stream: TokenStream) -> int | None:
    """``at least two`` in front of "more"/"fewer", or None (which is one).

    "…who has **at least two** fewer creature cards in their graveyard than you
    do" (Keeper of the Dead). A printed number rather than part of the phrase,
    for :class:`ast.BoardCount`'s stated reason: spelling the threshold into
    the words makes every other threshold a non-match.

    Non-consuming on refusal, so a plain "more" is read by the caller
    immediately after.
    """
    mark = stream.mark()
    if not stream.accept_phrase("at", "least"):
        return None
    count = accept_printed_number(stream)
    if count is None or count < 1:
        stream.reset(mark)
        return None
    return count


def _accept_direction(stream: TokenStream) -> tuple[bool, int] | None:
    """``[at least N] more|fewer`` — the direction and the threshold, or None."""
    mark = stream.mark()
    margin = _accept_margin(stream)
    if stream.accept_word("more"):
        return True, margin or 1
    if stream.accept_word("fewer"):
        return False, margin or 1
    stream.reset(mark)
    return None


def _accept_reference(stream: TokenStream) -> str | None:
    """``than you do`` / ``than they do`` — the seat compared against, or None.

    The verb is required and read in both spellings the printed frames use
    ("do" after a player, "does" after a possessive), because the words after
    it are the end of the clause: a reader that stopped at the pronoun would
    leave "do" for the caller and turn a full match into an unconsumed tail.
    """
    mark = stream.mark()
    if not stream.accept_word("than"):
        return None
    word = stream.peek_word()
    kind = _REFERENCE_SEATS.get(word or "")
    if kind is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("do", "does"):
        stream.reset(mark)
        return None
    return kind


def _accept_possessive_reference(stream: TokenStream, zone: str) -> str | None:
    """``than their graveyard does`` — the possessive frame's tail, or None.

    The zone is repeated in the printed sentence and has to *match* the one
    hoisted in front, because a card comparing a graveyard against a hand would
    be a different card and nothing else in the sentence shows the difference.
    """
    mark = stream.mark()
    if not stream.accept_word("than"):
        return None
    if not stream.accept_word("their"):
        stream.reset(mark)
        return None
    if not stream.accept_word(zone):
        stream.reset(mark)
        return None
    if not stream.accept_word("does", "do"):
        stream.reset(mark)
        return None
    # "than **their** graveyard does" hangs off the same antecedent "they" does
    # in the verb frame — the seat this sentence already named — so it is that
    # reference and not a third one.
    return "that_player"


def _accept_quantity(
    stream: TokenStream, parse_filter, *, zone: str | None = None,
) -> "ast.ObjectFilter | str | None":
    """The counted quantity: a printed noun phrase, or the one named one.

    *zone* is set by the possessive frame, where the pile is printed in front
    of the noun ("whose **graveyard** has fewer creature cards **in it**")
    rather than behind it. The filter parser reads a zone off a postmodifier and
    has none to read there, so the hoisted word is written onto the phrase here
    — one clause with the zone in either printed position, rather than two
    productions that would differ only in word order.
    """
    if zone is None and stream.peek_word() in _NAMED_QUANTITIES:
        named = stream.peek_word()
        stream.advance()
        return named
    mark = stream.mark()
    try:
        filt = parse_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if zone is None:
        return filt
    # "…fewer creature cards **in it**" — the pronoun points back at the pile
    # the possessive already named, so the words carry no zone of their own and
    # the hoisted one is written on. Required: without them the sentence would
    # be counting cards in some zone nobody named.
    if not stream.accept_phrase("in", "it"):
        stream.reset(mark)
        return None
    if filt.zone != "battlefield" or filt.zone_owner is not None:
        # The noun phrase named a pile of its own and the possessive named
        # another. Two zones in one clause are two different sets, so the
        # sentence refuses rather than one of them winning.
        stream.reset(mark)
        return None
    return dataclasses.replace(filt, zone=zone, is_card=True)


def accept_player_comparison(
    stream: TokenStream, parse_filter,
) -> "ast.PlayerComparison | None":
    """``who <compares> [and is their opponent]`` at the cursor, or None.

    Non-consuming on refusal, so a caller that does not find the clause still
    owes the rest of its line to full-token consumption — which is what makes a
    comparison no reader can carry fail the line rather than widen the sentence
    to every player.

    **Every word is required and nothing is defaulted.** The verb, the
    direction, the threshold, the reference seat and its own verb are each a
    difference between two different sets of players, so a reader that let any
    of them be absent would let the word be deleted with no change to the parse.
    """
    mark = stream.mark()
    if stream.accept_word("who"):
        comparison = _accept_verb_frame(stream, parse_filter)
    elif stream.accept_word("whose"):
        comparison = _accept_possessive_frame(stream, parse_filter)
    else:
        return None
    if comparison is None:
        stream.reset(mark)
        return None
    # "…**and is their opponent**" (the Oaths). CR 102.2's relation, conjoined
    # to the clause above it and hanging on the same antecedent — so it rides
    # the same node and is answered against the same reference seat. Optional:
    # the Keepers print "target **opponent**" instead, where the word is in the
    # noun and the reference is the activator.
    mark_opponent = stream.mark()
    if stream.accept_phrase("and", "is", "their", "opponent"):
        return dataclasses.replace(comparison, is_opponent=True)
    stream.reset(mark_opponent)
    return comparison


def _accept_verb_frame(
    stream: TokenStream, parse_filter,
) -> "ast.PlayerComparison | None":
    """``controls more creatures than they do`` — with "who" already read.

    Two verbs, read as one production because the direction, the noun phrase
    and the reference behind them are identical: "controls" names what is on a
    battlefield and "has" names everything else a player holds, and which of
    them a card prints follows from its noun rather than from what it does.
    """
    if not stream.accept_word("controls", "has"):
        return None
    direction = _accept_direction(stream)
    if direction is None:
        return None
    more, margin = direction
    quantity = _accept_quantity(stream, parse_filter)
    if quantity is None:
        return None
    reference = _accept_reference(stream)
    if reference is None:
        return None
    return ast.PlayerComparison(
        quantity=quantity, more=more, margin=margin, than=reference,
    )


def _accept_possessive_frame(
    stream: TokenStream, parse_filter,
) -> "ast.PlayerComparison | None":
    """``graveyard has fewer creature cards in it than their graveyard does``
    — with "whose" already read. (Oath of Ghouls.)
    """
    zone = stream.peek_word()
    if zone not in _POSSESSIVE_ZONES:
        return None
    stream.advance()
    if not stream.accept_word("has"):
        return None
    direction = _accept_direction(stream)
    if direction is None:
        return None
    more, margin = direction
    quantity = _accept_quantity(stream, parse_filter, zone=zone)
    if quantity is None:
        return None
    reference = _accept_possessive_reference(stream, zone)
    if reference is None:
        return None
    return ast.PlayerComparison(
        quantity=quantity, more=more, margin=margin, than=reference,
    )
