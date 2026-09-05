"""Parsing the library moves nobody looks through (CR 400).

Split out of ``effects/library.py`` at the thousand-line guard, along the line
that module's own docstring already draws: what stays there names *a pile being
looked through*, and every production here moves a pile of cards between zones
with no player seeing one of them — a library exiled whole, N cards exiled off
the top, a card put on a library, a graveyard or a hand shuffled in, a bare
shuffle. Looking and moving are the two questions that module had left once
``effects/search.py`` took the third.

The name is ``lowering/zones.py``'s, so the split **re-forms a mirror instead of
forking one**: three of the six productions here lower in that module
(``_lower_shuffle_graveyard_into_library``, ``_lower_shuffle_hand_into_library``,
``_lower_shuffle_library``), and the parse side simply had no ``zones`` family
until now — one of the asymmetries CLAUDE.md lists, closed rather than
duplicated under a new word.

The cut is where the call graph already fell apart: every name here is reached
from ``imperatives``, ``statements`` or ``subject_verb`` and from nothing left in
``library``, and nothing here calls anything there. Neither module imports the
other, which is what the layering guard requires of two families in one package.
"""


from .. import ast
from ..amounts import parse_amount
from ..references import parse_player_ref
from ..stream import TokenStream
from ..vocabulary import NUMBER_WORDS


def _parse_exile_entire_library(
    stream: TokenStream, player: "ast.PlayerRef"
) -> "ast.ExileEntireLibrary | None":
    """``exiles all cards from their library`` (Thought Lash) — the verb and
    everything after it, with the subject already read by the caller.

    Returns None with the cursor unmoved for anything else, so the ordinary
    exile productions keep their own sentences and their own errors.

    The possessive has to **agree with the subject**: "your" for the resolving
    player and "their" for anybody else. Reading either for either would let
    "that player exiles all cards from your library" through, which is two
    different libraries in one sentence and no card in Magic.
    """
    mark = stream.mark()
    if not stream.accept_word("exiles", "exile"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("all", "cards", "from"):
        stream.reset(mark)
        return None
    possessive = "your" if player.kind == "you" else "their"
    if not (stream.accept_word(possessive) and stream.accept_word("library")):
        stream.reset(mark)
        return None
    return ast.ExileEntireLibrary(player)


def _parse_exile_top_of_library(stream: TokenStream) -> ast.Statement | None:
    """``Exile the top three cards of your library.`` (Chandra, Heart of
    Fire's +1.) Returns None rather than raising when the sentence is an
    ordinary exile, so the permanent-exile production keeps its own errors.

    Every word of "of your library" is expected: "the top three cards of
    target player's library" would be someone else's cards and a different
    effect, and a production that stopped reading at the count could not tell
    them apart.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_phrase("the", "top"):
        stream.reset(mark)
        return None
    if stream.accept_word("card"):
        count: ast.Amount = ast.Fixed(1)
    else:
        count = parse_amount(stream)
        stream.expect_word("cards")
    for word in ("of", "your", "library"):
        stream.expect_word(word)
    # "…face down." (Knowledge Vault.) Optional, and consumed here rather than
    # left to a trailing-rider pass, because the two spellings are one exile
    # with a different visibility rather than two effects.
    face_down = bool(stream.accept_phrase("face", "down"))
    return ast.ExileTopOfLibrary(count, face_down)


def _parse_put_iterated_card_on_library(
    stream: TokenStream,
) -> "ast.PutIteratedCardOnLibrary | None":
    """``put the card on top of your library`` (Sylvan Library).

    "The card" is whatever the enclosing repetition is on, so this production
    reads only the *destination*; what it moves is decided by the loop around
    it, and the lowering refuses the sentence outside one.

    Refuses without consuming: every other "put …" sentence — a counter, a
    permanent, a card named by a filter — keeps the production it already had.
    """
    mark = stream.mark()
    if not stream.accept_word("put"):
        return None
    if not (stream.accept_phrase("the", "card") or stream.accept_phrase("that", "card")):
        stream.reset(mark)
        return None
    if not stream.accept_word("on"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("top", "of"):
        position = "top"
    elif stream.accept_phrase("the", "bottom", "of"):
        position = "bottom"
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("your", "library"):
        stream.reset(mark)
        return None
    return ast.PutIteratedCardOnLibrary(position=position)

# --- Shuffling a pile into a library -----------------------------------
# Moved here from ``board`` when that module crossed the thousand-line guard
# at integration — two parallel groups' additions summed past it. The
# boundary is the one this file already draws: the rest of ``board``
# destroys, sacrifices, bounces or attaches a *permanent*, and these two
# move a pile of cards into a library. They share no fragment with what
# they left.


def _parse_shuffle_graveyard_into_library(stream: TokenStream) -> ast.Statement | None:
    """``Shuffle your graveyard into your library.`` (Feldon's Cane.)

    Both possessives are read rather than assumed. A card moving *another*
    player's graveyard is a different effect, and consuming "your" without
    checking it would compile that card onto this one.
    """
    mark = stream.mark()
    # "your graveyard" is a possessive, not a player reference — `parse_player_ref`
    # reads "you" / "target player" / "each opponent" and rightly refuses it —
    # so the word is matched directly, and both occurrences are checked. A card
    # moving *another* player's graveyard is a different effect, and consuming
    # the possessive without reading it would compile that card onto this one.
    if not stream.accept_phrase(
        "shuffle", "your", "graveyard", "into", "your", "library"
    ):
        stream.reset(mark)
        return None
    return ast.ShuffleGraveyardIntoLibrary(ast.PlayerRef("you"))


def _parse_shuffle_hand_into_library(stream: TokenStream) -> ast.Statement | None:
    """``Each player shuffles the cards from their hand into their library,
    then draws that many cards.`` (Winds of Change.)

    Read here beside the graveyard shuffle for the reason that one is read
    outside the subject-verb loop: the sentence's object is a *zone*, not a set
    of objects a filter could test, so the reader that expects a noun phrase has
    nothing to take.

    The possessive has to agree with the subject, which is what makes this the
    sentence it looks like: "each player shuffles the cards from **your** hand"
    would be a different effect, and consuming the word without reading it would
    compile that card onto this one — the check `_parse_shuffle_graveyard_into_library`
    makes for the same reason.

    The draw is part of this production rather than a sentence after it: "that
    many" is the number of cards the shuffle just moved, which nothing else in
    the line knows. Parsed apart it would be a draw with no producer, and a
    producerless back-reference reads as zero.
    """
    mark = stream.mark()
    player = parse_player_ref(stream)
    if player is None:
        # "**Shuffle** a card from your hand into your library."
        # (Lat-Nam's Legacy.) The bare imperative, whose subject is the spell's
        # controller (CR 608.1) — the same implied "you" every other imperative
        # in this grammar takes, and the reason the reader above is allowed to
        # find nothing rather than refusing outright.
        if not stream.at_word("shuffle"):
            stream.reset(mark)
            return None
        player = ast.PlayerRef("you")
    if not stream.accept_word("shuffles", "shuffle"):
        stream.reset(mark)
        return None
    whose = "your" if player.kind == "you" else "their"
    # "shuffles **a card from** their hand" — a counted subset rather than the
    # whole zone, which is a different effect and not a narrowing of one: the
    # hand's owner picks which cards, and nobody else can see them to pick
    # (CR 402.1). Read before the whole-hand phrase below, and non-consuming on
    # refusal, so "the cards from" keeps the reading it has.
    count: int | None = None
    counted = stream.mark()
    if stream.accept_word("a", "an"):
        count = 1
    else:
        word = stream.peek_word()
        if word in NUMBER_WORDS:
            stream.advance()
            count = NUMBER_WORDS[word]
    if count is not None:
        if not (stream.accept_word("card", "cards") and stream.accept_word("from")):
            stream.reset(counted)
            count = None
    if count is None:
        # "shuffles **the cards from** their hand" is the current wording and
        # "shuffles their hand" the older one; they name the same cards, so the
        # phrase is optional rather than a second production.
        stream.accept_phrase("the", "cards", "from")
    # "…their hand **and graveyard** into their library." (Diminishing
    # Returns.) One shuffle over two piles, read here rather than as a second
    # sentence: CR 701.24 randomises the library once, and two statements would
    # do it twice with the hand's cards already down among the graveyard's.
    with_graveyard = False
    conjunct = stream.mark()
    if stream.accept_phrase(whose, "hand", "and", "graveyard"):
        with_graveyard = True
    else:
        stream.reset(conjunct)
        if not stream.accept_phrase(whose, "hand"):
            stream.reset(mark)
            return None
    if not stream.accept_phrase("into", whose, "library"):
        stream.reset(mark)
        return None
    then_draw = False
    probe = stream.mark()
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "draws" if whose == "their" else "draw", "that", "many", "cards"
    ):
        then_draw = True
    else:
        stream.reset(probe)
    return ast.ShuffleHandIntoLibrary(
        player, then_draw=then_draw, count=count, with_graveyard=with_graveyard,
    )


def _parse_shuffle_library(stream: TokenStream) -> ast.Statement | None:
    """``That player shuffles.`` (Prophecy's third sentence.)
    ``Shuffle your library.``

    CR 701.24 on its own — a library randomised with nothing moving into it.
    Read **after** the two zone-moving shuffles above, because both of those
    open with the same subject and the same verb and only they name the pile
    that moves: tried first, this one would take "Each player shuffles the
    cards from their hand into their library" as a bare shuffle and leave the
    rest of the sentence to fail the line.

    Non-consuming on refusal, so the sentence readers after it keep whatever
    refusal they had. The player is required — "shuffles" with no subject is a
    library nobody named, and defaulting it to the caster is how Prophecy would
    shuffle its own deck instead of the opponent's.
    """
    mark = stream.mark()
    if stream.accept_word("shuffle"):
        # The imperative spelling, whose subject is the effect's controller
        # (CR 608.2): "Shuffle your library."
        if not stream.accept_phrase("your", "library"):
            stream.reset(mark)
            return None
        return ast.ShuffleLibrary(ast.PlayerRef("you"))
    player = parse_player_ref(stream)
    if player is None or not stream.accept_word("shuffles"):
        stream.reset(mark)
        return None
    # "that player shuffles **their library**" — the same zone the bare verb
    # already means (CR 701.24a shuffles a library), so the words are optional
    # rather than a second production. Any *other* possessive is a different
    # player's deck and refuses: consuming it unread is how a shuffle lands on
    # the wrong library.
    probe = stream.mark()
    if stream.accept_word("their", "your"):
        if not stream.accept_word("library"):
            stream.reset(probe)
            stream.reset(mark)
            return None
    return ast.ShuffleLibrary(player)
