"""The **run** — "Reveal cards from the top of your library until you reveal
a <filter>": CR 701.20a's reveal repeated until a card passes a test.

A floor under ``effects/reveal.py``, pre-split out of it between the two waves
of Invasion, when that module sat ten lines under the thousand-line guard with
seven parallel groups about to open. A floor rather than a family for
``_other_libraries``' reason one family over: ``reveal`` is the only module
that asks. It could not be a family in any case — the printed verb keeps one
entry point, ``_parse_reveal_top``, which has already read "Reveal" by the time
this is tried, and a family may not be called from another one.

**The seam is the first thing that entry point decides**, and its own comment
had drawn it before the cut was made: "the word after the verb is the fork:
this one reads an unbounded run off the top and stops on a match, where
everything below reads a fixed number of them." Every other branch of that
function reveals a number of cards the sentence prints — one at random from a
hand, the top card, the top N, a number equal to something — and where it
reads on, says what becomes of that pile: a pick, a sort, somebody's choice. A
run has no size. What it prints instead is a stopping test, and the test is
also what divides its two fates: the card the run stopped on, and everything it
turned over on the way there.

So it is one node (:class:`ast.RevealUntil`), one lowering
(``lowering/reveal._lower_reveal_until``) and one instruction kind
(``reveal_until_match``), where the fixed piles need a node per procedure.

The call graph agreed. ``_accept_reveal_until_from_top`` is the only name
``reveal`` reaches for; the two readers behind it and the table are called from
it and from nowhere else, and nothing here calls anything left behind. The
imports divided with them: this reads the noun parser and the token stream,
and ``amounts``, ``references`` and ``phrases`` are read by what stayed alone.

It is a half that grows, and it is not the only one — the sorted reveals and
the counted picks left behind have grown as much, which is why the cut was
chosen on the line above rather than on a growth rate. This block was one
production and 75 lines when ``reveal`` left ``library`` at Tempest and is
three and 207 now: Exodus added the battlefield destination, the "their" possessive and the
restated offer (Oath of Druids, Avenging Druid), Mercadian Masques a fourth
spelling of the remainder (Foster), and Invasion's first wave the remainder
shuffled back (Thicket Elemental). A new printing has so far meant a new word
in one of three positions — whose library, where the match goes, what becomes
of the rest — and each of the three is read in exactly one place below.

**Not every run is read here.** Transmogrify's and Polymorph's is a rider on
the sentence in front of it: "that creature's controller reveals cards from
the top of their library until …" names a seat only the exile step recorded,
so ``pronouns._parse_that_controller_reveals_rider`` reads it and builds the
same node with a different ``whose``. The two share the node and no reader —
that one is handed the steps already parsed, which nothing in ``effects/`` is.

No mirror name to reuse. The lowering is one function in ``lowering/reveal.py``
and the node sits in ``ast/library.py``, neither of which has split along this
line; the name is the one the node, the lowering and the instruction kind
already share.
"""

from .. import ast
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..stream import TokenStream


#: What the cards a reveal-until turned over *before* the match may be printed
#: to do. A closed list, for ``naming._REVEAL_DESTINATIONS``'
#: reason: each of these is something ``reveal_until_match`` actually performs,
#: and a word outside it refuses the line rather than lowering onto a fate
#: nobody carries out.
_REVEAL_UNTIL_REST: dict[str, str] = {
    "exile": "exile",
    "graveyard": "graveyard",
}

def _accept_reveal_until_from_top(
    stream: TokenStream,
) -> "ast.RevealUntil | None":
    """``cards from the top of your library until you reveal a <filter>. Put
    that card into your hand and exile all other cards revealed this way.`` at
    the cursor, with "Reveal" already read — or None with the cursor where it
    was. (Sacred Guide.)

    ``…until they reveal a creature card. If the first player does, that player
    puts that card onto the battlefield and all other cards revealed this way
    into their graveyard.`` (Oath of Druids; Avenging Druid prints the same
    procedure with "you"/"your" and its own verb before the rest.)

    Both sentences, for :func:`_parse_reveal_top`'s reason and
    :class:`ast.RevealUntil`'s: "that card" is what the run stopped on and "all
    other cards revealed this way" is exactly what it turned over first, so
    apart they dangle referents nothing binds.

    **Three things are read rather than assumed, and each is a different
    card.** The destination — a hand or the battlefield. The rest's fate —
    Transmogrify shuffles its pile back, Sacred Guide exiles it and these two
    bin it, which is the whole difference between a card that costs its
    controller a library and one that does not. And the **possessive**, which
    agrees with the sentence's subject: "your"/"you" where the performer is the
    resolving player and "their"/"they" where an enclosing offer named somebody
    else (``effects/search`` reads its own the same way, and for the same
    reason — a "may" parses its action as a bare imperative with no subject in
    it). Both spellings mean "whoever is performing this sentence", which is
    what ``whose="you"`` says to the handler, and the pronoun has to agree at
    every one of its printed positions or the line refuses.

    Only the reader's own library, whichever pronoun says so: a run off
    somebody else's deck would move a card out of that library into this seat's
    hand, and a card printing that is a different card.
    """
    mark = stream.mark()
    possessive = "their" if stream.peek_word(5) == "their" else "your"
    pronoun = "they" if possessive == "their" else "you"
    if not stream.accept_phrase(
        "cards", "from", "the", "top", "of", possessive, "library", "until",
        pronoun, "reveal",
    ):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not filt.is_card:
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # "**If you do,** put that card onto the battlefield…" (Avenging Druid);
    # "**If the first player does,** that player puts…" (Oath of Druids). The
    # offer above this production is what the clause points back at — the run
    # only happens if the seat took it, and the whole procedure is one node
    # inside that offer — so the words are a restatement and are consumed.
    # Optional: Sacred Guide and Hermit Druid print no offer and no clause.
    _accept_did_clause(stream)
    # "…**that player** puts that card…" — the subject the offer named, in the
    # third person because the sentence names it rather than addressing it.
    # Consumed here so the destination clause below is one production either
    # way; it is the same seat the pronoun above already agreed with.
    if possessive == "their":
        stream.accept_phrase("that", "player")
    if not stream.accept_word("put", "puts"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("that", "card"):
        stream.reset(mark)
        return None
    # Every word of the destination, for the reason the rider one module over
    # gives about its own: a printing that put the found card somewhere else is
    # a different card and nothing before this sentence shows the difference.
    if stream.accept_word("into"):
        if not stream.accept_phrase(possessive, "hand"):
            stream.reset(mark)
            return None
        destination = "hand"
    elif stream.accept_phrase("onto", "the", "battlefield"):
        destination = "battlefield"
    else:
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    rest = _accept_reveal_until_rest(stream, possessive)
    if rest is None:
        stream.reset(mark)
        return None
    return ast.RevealUntil("you", filt, destination=destination, rest=rest)


def _accept_did_clause(stream: TokenStream) -> bool:
    """``If you do,`` / ``If the first player does,`` — the offer restated.

    Consumed rather than lowered because the offer it points back at is the one
    this production already sits inside: nothing happens unless the seat took
    it, so the clause repeats a condition the ``may`` above already enforces.
    Every word of both spellings is required — a conditional naming some *other*
    fact would be a card this production is not.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    if not (
        stream.accept_phrase("you", "do")
        or stream.accept_phrase("the", "first", "player", "does")
        or stream.accept_phrase("that", "player", "does")
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    return True


def _accept_reveal_until_rest(
    stream: TokenStream, possessive: str,
) -> "str | None":
    """Where the cards turned over before the match go, or None.

    **Three printed word orders for one clause**, read here rather than in
    three productions because every word in front of them is identical and a
    production that differed only in a tail would be this sentence written
    three times. Sacred Guide puts a verb in front of the pile ("and *exile*
    all other cards revealed this way"); Hermit Druid and Oath of Druids elide
    it and name a destination instead ("and all other cards revealed this way
    *into your graveyard*") — the same "put" the clause before it already
    carries, distributed across both objects; Avenging Druid prints that verb
    again ("and *put* all other cards revealed this way into your graveyard").
    """
    mark = stream.mark()
    # "…and **shuffle all other cards revealed this way into your library**."
    # (Thicket Elemental.) The fate Transmogrify prints as "then shuffles the
    # rest into their library", on this production's own sentence -- so it
    # reaches the handler branch that card already uses, and the pile is put
    # back and shuffled once (CR 701.24) rather than binned. A verb of its own
    # rather than a row of ``_REVEAL_UNTIL_REST``, because that table maps a
    # *zone word* and the zone here is the library the cards came from: only
    # the verb says they are shuffled in rather than put back in order. Every
    # word required, the possessive agreeing with the sentence's subject as it
    # does at every other position.
    if stream.accept_word("shuffle"):
        if stream.accept_phrase(
            "all", "other", "cards", "revealed", "this", "way", "into",
            possessive, "library",
        ):
            return "shuffle_into_library"
        stream.reset(mark)
        return None
    # Avenging Druid's repeated verb. Read before the pile so the two elided
    # spellings below are one branch.
    stream.accept_word("put")
    # "…and **the rest** into your graveyard." (Foster.) A fourth printed
    # spelling of the same pile — what the run turned over before it stopped —
    # and read here beside the other three for this function's stated reason:
    # every word in front of it is identical, and a production differing only
    # in a tail would be one sentence written four times.
    rest_mark = stream.mark()
    if stream.accept_phrase("the", "rest"):
        if stream.accept_word("into"):
            stream.accept_word(possessive)
            rest_zone = stream.peek_word()
            if rest_zone in _REVEAL_UNTIL_REST:
                stream.advance()
                return _REVEAL_UNTIL_REST[rest_zone]
        stream.reset(rest_mark)
    if stream.accept_phrase("all", "other", "cards", "revealed", "this", "way"):
        if not stream.accept_word("into"):
            stream.reset(mark)
            return None
        # "into **your** graveyard" has the possessive and "into exile" does
        # not; it is the same seat either way, since the run reads this seat's
        # own library.
        stream.accept_word(possessive)
        rest_zone = stream.peek_word()
        if rest_zone not in _REVEAL_UNTIL_REST:
            stream.reset(mark)
            return None
        stream.advance()
        return _REVEAL_UNTIL_REST[rest_zone]
    stream.reset(mark)
    rest = stream.peek_word()
    if rest not in _REVEAL_UNTIL_REST:
        return None
    stream.advance()
    if not stream.accept_phrase(
        "all", "other", "cards", "revealed", "this", "way"
    ):
        stream.reset(mark)
        return None
    return _REVEAL_UNTIL_REST[rest]
