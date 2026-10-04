"""The multi-zone strip by name — "search a player's graveyard, hand, and
library for all cards with the same name as X and exile them".

A floor split out of ``effects/search.py`` at Urza's Destiny's wave 1, when
that module sat 28 lines from the thousand-line guard with five cards' worth of
new reading to land here and nowhere else. A floor rather than a family,
precedented by ``lowering/_recipients`` and for its stated reason: one module
asks, and this exists because that family crossed the guard.

**That one module is ``_other_libraries``, and it always was one function.**
This is tried from inside the production that reads ``Search <player>'s`` and
hands down the player — never from the tutor — so when that production left
``search`` at the Phase 0 before Invasion, the import went with it. A floor
under a floor; nothing reads back.

**And the seam is a real one, which is what makes it a floor and not a
convenience.** Everything in ``search`` and ``_other_libraries`` is CR 701.23's
library walk — whose library, what may be found, where the find goes, and the
shuffle that ends it. This is not a library search at all. It opens three zones
of three different kinds (an open zone, its owner's hidden hand, and a
library), it finds by a name nothing printed rather than by a described card,
it exiles everything it finds rather than moving one card somewhere, and it
shuffles only the library because that is the only one of the three CR 701.24
says to. With the tutor it shares the printed word "Search" and nothing else.
With its caller it shares the opener that names the player and the closing
"and exile them. Then that player shuffles", each side reading its own copy —
this sentence said "no vocabulary whatsoever" until the caller was measured
apart from the tutor. ``_STRIPPED_ZONES`` below is the file's only zone table
and neither module reads it.

The name it compares against is always a **record** — something an earlier step
of the same resolution wrote down — and never a literal the card prints, which
is what keeps this out of ``nouns``: :class:`ast.ObjectFilter.named` holds a
string, and no string can stand for "whatever that spell was called".
"""


from .. import ast
from ..references import parse_player_ref
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES, singular


#: The zones a strip-by-name may open, in the order CR 400.1 lists them and the
#: cards print them. A closed list because each is a pile the handler actually
#: walks — a word outside it refuses the line rather than lowering onto a zone
#: nothing reaches.
_STRIPPED_ZONES: tuple[str, ...] = ("graveyard", "hand", "library")

#: The nouns "…with the same name as that **<noun>**" may name. Every card type
#: (CR 300.1), plus the two words that describe an object without being one:
#: "permanent" for something on the battlefield and "spell" for something on the
#: stack (CR 111.1 — a spell is a card, not a card type).
#:
#: Read and required rather than skipped, exactly as ``names.accept_name_
#: comparison`` reads its own copy of this phrase: the noun is what tells the
#: lowering which *record* the sentence is about — "that spell" is a stack
#: object a counter chose and "that creature" is a permanent an exile chose —
#: and a word consumed unread would let either sentence take the other's
#: reading and search for a name nobody wrote down.
_STRIPPED_NAME_SUBJECTS: frozenset[str] = frozenset(CARD_TYPES) | {
    "permanent", "spell",
}


def _accept_strip_cards_with_chosen_name(
    stream: TokenStream, player: "ast.PlayerRef",
) -> "ast.StripCardsWithChosenName | None":
    """``graveyard, hand, and library for all cards with the same name as <the
    chosen card | that <noun>> and exile them. Then that player shuffles.`` at
    the cursor, with ``Search <player>'s`` already read — or None with the
    cursor where it was. (Lobotomy; Eradicate, Scour, Splinter, Sowing Salt and
    Quash.)

    Both sentences, for :class:`ast.StripCardsWithChosenName`' reason: CR 701.24
    ends a library search with the shuffle, and the seat it names is the one
    this search opened.

    Two or more zones are required. One zone is the ordinary counted search in
    ``_other_libraries``, whose whole tail this production has none of, and
    admitting a single zone here would take those cards away from it.

    **Two spellings of one thing, which is why they are branches and not two
    productions.** "the same name as **the chosen card**" (Lobotomy) and "the
    same name as **that creature**" (Eradicate) both read as the printed words
    rather than as a filter: the name is not on this card at all — an earlier
    step of the same spell recorded it — and a filter would have to describe a
    literal the sentence never states. What differs is only *which* earlier step
    wrote it down, and that is the lowering's question, not this one's. The
    lowering demands the step either way.
    """
    mark = stream.mark()
    zones: list[str] = []
    while True:
        word = stream.peek_word()
        if word not in _STRIPPED_ZONES:
            break
        stream.advance()
        zones.append(word)
        if stream.accept_punct(","):
            stream.accept_word("and")
            continue
        if stream.accept_word("and"):
            continue
        break
    if len(zones) < 2:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "for", "all", "cards", "with", "the", "same", "name", "as",
    ):
        stream.reset(mark)
        return None
    name_of = _accept_named_object(stream)
    if name_of is False:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "exile", "them"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    stream.accept_word("then")
    shuffler = parse_player_ref(stream)
    if shuffler is None or shuffler.kind != "that_player":
        # "Then **that player** shuffles" names the seat this search opened. A
        # sentence naming anybody else would shuffle a library nothing looked
        # through, which is a different card.
        stream.reset(mark)
        return None
    if not stream.accept_word("shuffles"):
        stream.reset(mark)
        return None
    return ast.StripCardsWithChosenName(
        player, tuple(zones), name_of=name_of or None,
    )


def _accept_named_object(stream: TokenStream) -> "str | bool | None":
    """Which recorded object the name is compared against, with
    ``…with the same name as`` already read.

    Returns None for Lobotomy's "the chosen card", the printed noun for
    "that <noun>", and ``False`` — the one value neither of those can be — for
    a tail this cannot read. The three-valued return is what keeps the caller
    from having to tell "no noun" apart from "the noun was absent", which is
    the distinction a bare None would lose.

    Non-consuming on refusal is the caller's job, not this one's: it resets to
    a mark taken before the zone list, which is further back than anything here
    could restore to.
    """
    if stream.accept_phrase("the", "chosen", "card"):
        return None
    if not stream.accept_word("that"):
        return False
    noun = singular(stream.peek_word() or "")
    if not noun or noun not in _STRIPPED_NAME_SUBJECTS:
        return False
    stream.advance()
    return noun
