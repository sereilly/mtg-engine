"""Parsing the hidden-zone flows: search, look-at, and the library's top.

The mirror of ``lowering/library.py``, which carries the same family on the
other side — "search, reveal, look-at, and exile linkage". It split off
``effects/cards.py`` when The Dark pushed that module past the 1,000-line
guard, and it reuses the lowering side's family name rather than inventing one,
so the two halves stay mirrored (CLAUDE.md: "if an ``effects/`` module ever
splits, reuse these names so the mirror re-forms instead of forking").

The cut is where the call graph already fell apart: nothing here calls anything
left in ``cards.py`` and nothing there calls anything here, so neither module
imports the other — which is what the layering guard requires of two families
in one package. Drawing, discarding, milling, scrying and the hand reveals stay
in ``cards.py``: they name a *card moving*, where everything here names a
*pile being looked through*.
"""


from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref
from ..stream import TokenStream
from ..phrases import _parse_card_alternatives
from ..vocabulary import NUMBER_WORDS


def _parse_reveal_top(stream: TokenStream) -> ast.Statement:
    """``Reveal the top card of your library. If it's a <filter>, put it into
    your hand. Otherwise, put it on the bottom of your library.`` (Garruk,
    Savage Herald.)

    ``Reveal the top card of target opponent's library.`` (Prophecy.)

    One production for the whole three-sentence template, interior full stops
    included: the sentences all describe one revealed card, so parsed apart
    two of them dangle a referent nothing binds. Every word of both
    destinations is required — hand-or-bottom is the effect, and a wording
    that sorted elsewhere would be a different card wearing this one's head.

    **Whose** library is read rather than spelled, because the seat is the one
    thing about a reveal that cannot be inferred: it was the literal word
    "your", so Prophecy failed on the word after "of" — and admitting the
    phrase without recording it would have opened the caster's own library
    while the card named an opponent's.
    """
    stream.expect_word("reveal")
    for word in ("the", "top", "card", "of"):
        stream.expect_word(word)
    if stream.accept_word("your"):
        player = ast.PlayerRef("you")
    else:
        # "…of **target opponent's** library" (Prophecy). The lexer splits the
        # possessive into its own token, as it does everywhere a player owns a
        # zone.
        player = parse_player_ref(stream)
        if player is None:
            raise stream.error("expected whose library is revealed from")
        stream.expect_word("'s")
    stream.expect_word("library")
    # "Scry 3, then reveal the top card of your library. If it's a creature or
    # land card, draw a card." (Track Down.) The reveal is the whole sentence
    # and what follows it is an ordinary conditional, so the bare node is
    # returned and the sentence loop reads the rest. Tried by *falling back*
    # rather than by looking ahead: Garruk's three-sentence template is checked
    # first and keeps every word it requires, so a line that matches it is
    # unaffected, and a line that does not gets a node instead of a refusal.
    mark = stream.mark()
    if not stream.accept_punct("."):
        return ast.RevealTop(player)
    # The hand-or-bottom template is about the reader's **own** library: both of
    # its destinations say "your", and reaching it from another seat's library
    # would move a card out of that deck into this one's hand. A reveal of
    # somebody else's top card gets the bare node and whatever ordinary
    # sentences follow it, which is Prophecy's shape.
    if player.kind != "you":
        stream.reset(mark)
        return ast.RevealTop(player)
    if not stream.accept_word("if"):
        stream.reset(mark)
        return ast.RevealTop(player)
    if not (stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is")):
        stream.reset(mark)
        return ast.RevealTop(player)
    stream.accept_word("a", "an")
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "into", "your", "hand"):
        # The conditional is somebody else's ("…, draw a card"). Hand the whole
        # thing back and let the sentence loop read it as the two statements it
        # is.
        stream.reset(mark)
        return ast.RevealTop(player)
    if not stream.accept_punct("."):
        raise stream.error("expected the 'Otherwise' sentence")
    stream.expect_word("otherwise")
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "on", "the", "bottom", "of", "your", "library"):
        raise stream.error("expected 'put it on the bottom of your library'")
    return ast.RevealTopToHandOrBottom(filt)


def _parse_look_pick_tail(
    stream: TokenStream, count, *, already_split: bool = False
) -> ast.Statement:
    """"You may reveal a <filter> card from among them and put it into your
    hand. Put the rest on the bottom of your library in a random order."

    Both sentences, because they describe one looked-at pile: "them" is what the
    look turned up and "the rest" is exactly what is left after the pick. Every
    word of the second is required — "in a random order" is a stated shuffle and
    "in any order" leaves the cards as they lay, and a card that said one while
    the engine did the other would differ only in a place no test looks.
    """
    if not already_split and not stream.accept_punct("."):
        raise stream.error("expected the reveal sentence after the look")
    for word in ("you", "may", "reveal"):
        stream.expect_word(word)
    # The same reader the discard *cost* uses for "a land card or Shrine card":
    # one phrase, one filter vocabulary, and a restriction the card matcher
    # cannot answer refuses here exactly as it does there.
    filters = _parse_card_alternatives(stream)
    if filters is None:
        raise stream.error("the pick cannot test this restriction on a card")
    for word in ("from", "among", "them", "and", "put", "it", "into", "your", "hand"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the sorting sentence after the reveal")
    for word in (
        "put", "the", "rest", "on", "the", "bottom", "of", "your", "library",
        "in", "a", "random", "order",
    ):
        stream.expect_word(word)
    return ast.LookTopPickToHand(
        count, filters=filters, optional=True, rest_order="random",
    )


def parse_player_looks_at_own_library_top(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.Statement | None":
    """``<player> looks at the top N cards of their library, puts one of them
    back on top of their library, then exiles the rest.`` (Ashnod's Cylix.)

    The look-and-pick template with its looker printed, which is the whole of
    what is new: every other card in the family looks at its own controller's
    library, so the seat was never a field and "your library" was a literal.
    Here the pile, the pick and the exile all belong to the *named* player, and
    the possessive says so three times ("their … their … the rest" of theirs) —
    so one seat answers all three and a card that split them would be a
    different node.

    Declines without consuming when the sentence is not this one, so
    "Look at target player's hand" and Visions' "look at the top five cards of
    target player's library" keep their own readings and their own refusals.

    Both halves of the destination are required rather than defaulted, for
    ``rest_destination``'s standing reason: keeping a card on top is not
    drawing it, and exiling the rest is not bottoming them. A card printing
    either differently is a different card.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    probe = stream.mark()
    if not stream.accept_word("looks", "look"):
        return None
    if not stream.accept_phrase("at", "the", "top"):
        stream.reset(probe)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(probe)
        return None
    if not stream.accept_phrase("cards", "of", "their", "library"):
        stream.reset(probe)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "puts", "one", "of", "them", "back", "on", "top", "of", "their", "library",
    ):
        stream.reset(probe)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("then", "exiles", "the", "rest"):
        stream.reset(probe)
        return None
    return ast.LookTopPickToHand(
        count,
        pick_destination="library_top",
        rest_destination="exile",
        looker=subject,
    )


def _parse_look_other_library_tail(
    stream: TokenStream, count, owner: ast.PlayerRef
) -> ast.Statement:
    """The rest of "Look at the top five cards of target player's library. You
    may then have that player shuffle that library." (Visions.)

    The shuffle sentence is read here rather than as a statement of its own
    because "that library" is the one the look just named — parsed apart it
    would have to guess a player, and guessing which library gets shuffled is
    the one mistake this card can make. The tail is optional: a card that only
    looks is this same effect without its offer, and refusing it would refuse a
    shape the node already represents.
    """
    mark = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "you", "may", "then", "have", "that", "player", "shuffle", "that", "library"
    ):
        return ast.LookAtLibraryTop(count, owner, may_shuffle=True)
    stream.reset(mark)
    # "…, **then put them back in any order**." (Natural Selection, Portent.)
    # The looker rearranges the cards they saw, which is the other handler —
    # and the optional shuffle after it is printed shorter here than Visions
    # prints it, so both spellings are read rather than one being normalized
    # into the other.
    #
    # This was a name-keyed hook on Natural Selection, and Portent prints the
    # identical sentence: `card_hooks`' entry bar is that no second card shares
    # the shape, and a second card did.
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "put", "them", "back", "in", "any", "order"
    ):
        shuffle_mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "you", "may", "have", "that", "player", "shuffle"
        ):
            return ast.LookAtLibraryTop(
                count, owner, may_shuffle=True, may_reorder=True
            )
        stream.reset(shuffle_mark)
        return ast.LookAtLibraryTop(count, owner, may_reorder=True)
    stream.reset(mark)
    return ast.LookAtLibraryTop(count, owner)


def _parse_look_at_hand(stream: TokenStream) -> ast.Statement:
    """``Look at <player>'s hand.`` (Glasses of Urza.)

    Both the possessive marker and the zone noun are expected rather than
    skipped. "Look at" heads a family of information effects that differ only in
    their object — the top card of a library, the cards in a hand, a face-down
    creature — so consuming the object is what keeps this production from
    claiming the others.
    """
    stream.expect_word("look")
    stream.expect_word("at")
    # "Look at **a card at random in** target player's hand." (Urza's Bauble.)
    # Read before the count branches below, because it opens with an article
    # rather than with "the top" and would otherwise fall through to the player
    # reference and fail the line on the word "a".
    if stream.accept_phrase("a", "card", "at", "random", "in"):
        who = parse_player_ref(stream)
        if who is None:
            raise stream.error("expected the player whose hand is looked at")
        stream.expect_word("'s")
        stream.expect_word("hand")
        return ast.LookAtHand(who, random_card=True)
    # "Look at the top three cards of your library. Put one of those cards
    # into your hand and the rest on the bottom of your library in any order.
    # If this spell was cast from anywhere other than your hand, put each of
    # those cards into your hand instead." (See the Truth.) One production for
    # the whole three-sentence template, interior full stops included — the
    # sentences share one looked-at set, and the cast-zone conditional is the
    # card's whole reason to exist, so a wording without it must keep refusing
    # rather than quietly becoming the plain pick.
    # "Look at **that many** cards from the top of your library." (Garruk's
    # Harbinger.) The count is the firing event's number, and the word order is
    # the other one this template prints — "cards from the top of" rather than
    # "the top … cards of".
    if stream.accept_phrase("that", "many"):
        for word in ("cards", "from", "the", "top", "of", "your", "library"):
            stream.expect_word(word)
        return _parse_look_pick_tail(stream, ast.ThatMuch(None))
    if stream.accept_phrase("the", "top"):
        count = parse_amount(stream)
        stream.expect_word("cards")
        stream.expect_word("of")
        # Whose library, read rather than assumed to be the word "your": "the
        # top five cards of **target player's** library" (Visions) is this same
        # sentence about somebody else's deck. Everything below — the pick, the
        # bottoming, the cast-zone rider — is only ever about your own library,
        # which is why the other library's tail is read separately.
        if stream.accept_word("your"):
            owner = ast.PlayerRef("you")
        else:
            owner = parse_player_ref(stream)
            # The lexer splits "player's" into "player" + "'s"; the marker is
            # consumed here for the reason `_parse_look_at_hand`'s is — a token
            # left behind fails the line's full-token consumption.
            if owner is None or not stream.accept_word("'s"):
                raise stream.error("expected whose library is looked at")
        stream.expect_word("library")
        if owner.kind != "you":
            return _parse_look_other_library_tail(stream, count, owner)
        # The sentence break, printed either way. See the Truth and Diabolic
        # Vision start a new sentence; Browse runs the whole ability on as one
        # ("…of your library, put one of them into your hand, and exile the
        # rest."). The punctuation is all that differs, and a card is not a
        # different card for printing a comma.
        if not (stream.accept_punct(".") or stream.accept_punct(",")):
            raise stream.error("expected the sorting sentence after the look")
        # Garruk's Harbinger's optional, filtered pick shares this position with
        # See the Truth's compulsory one; reading the second sentence is what
        # decides which card this is.
        if stream.at_word("you"):
            return _parse_look_pick_tail(stream, count, already_split=True)
        # "Put one of **them** into your hand and the other into your
        # graveyard." (Waker of Waves.) A compulsory, unfiltered pick like See
        # the Truth's, differing only in where the rest go — which is a
        # difference the sentence states and this production requires, because
        # a card that bottomed them instead is a different card.
        mark = stream.mark()
        if stream.accept_phrase(
            "put", "one", "of", "them", "into", "your", "hand",
            "and", "the", "other", "into", "your", "graveyard",
        ):
            return ast.LookTopPickToHand(count, rest_destination="graveyard")
        stream.reset(mark)
        # "Exile four of them at random, **then** put the rest on top of your
        # library in any order." (Orcish Librarian.) Nothing is picked and
        # nothing reaches a hand, so it is a different statement that happens
        # to end the same way — the shared tail is read by the same words
        # below and carried out in the same place.
        if stream.at_word("exile"):
            stream.expect_word("exile")
            exile_count = parse_amount(stream)
            for word in ("of", "them", "at", "random"):
                stream.expect_word(word)
            stream.accept_punct(",")
            stream.expect_word("then")
            for word in ("put", "the", "rest", "on"):
                stream.expect_word(word)
            if not stream.accept_phrase("top", "of", "your", "library"):
                raise stream.error("expected 'top of your library'")
            for word in ("in", "any", "order"):
                stream.expect_word(word)
            return ast.LookTopExileRandom(count, exile_count)
        for word in ("put", "one", "of"):
            stream.expect_word(word)
        # "one of **them**" (Diabolic Vision) and "one of **those cards**" (See
        # the Truth) name the same pile. The pronoun was written into the
        # sequence, so the second spelling refused at the word — a card the
        # engine implements, kept out by which word it used for the cards it
        # had just looked at.
        if not (stream.accept_word("them") or stream.accept_phrase("those", "cards")):
            raise stream.error("expected 'them' or 'those cards'")
        for word in ("into", "your", "hand"):
            stream.expect_word(word)
        # "…, and **exile** the rest." (Browse.) The third destination, beside
        # the graveyard branch above and the two library ends below, and read
        # for their reason: where the unchosen cards go is the card's own
        # statement. Exiling them is what makes Browse a repeatable engine that
        # eats its own library rather than a re-orderer.
        exiled_rest = stream.mark()
        stream.accept_punct(",")
        if stream.accept_phrase("and", "exile", "the", "rest"):
            return ast.LookTopPickToHand(count, rest_destination="exile")
        stream.reset(exiled_rest)
        for word in ("and", "the", "rest", "on"):
            stream.expect_word(word)
        # Where the rest go is the card's own statement and a real difference:
        # the bottom is out of reach, the top is the next N draws. Read rather
        # than assumed, the same rule the graveyard branch above states.
        if stream.accept_phrase("the", "bottom", "of", "your", "library"):
            rest_destination = "library_bottom"
        elif stream.accept_phrase("top", "of", "your", "library"):
            rest_destination = "library_top"
        else:
            raise stream.error("expected where the rest of the cards go")
        for word in ("in", "any", "order"):
            stream.expect_word(word)
        # See the Truth's cast-zone sentence, and only its. Optional because it
        # is a *rider* on this template rather than part of it: Diabolic Vision
        # prints the pick and stops, and demanding the sentence refused it for
        # text it does not have.
        mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "if", "this", "spell", "was", "cast", "from", "anywhere",
            "other", "than", "your", "hand",
        ):
            stream.accept_punct(",")
            for word in ("put", "each", "of", "those", "cards", "into", "your", "hand", "instead"):
                stream.expect_word(word)
            return ast.LookTopPickToHand(
                count,
                rest_destination=rest_destination,
                all_to_hand_if_cast_elsewhere=True,
            )
        stream.reset(mark)
        return ast.LookTopPickToHand(count, rest_destination=rest_destination)
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player whose hand is looked at")
    # The lexer splits "player's" into "player" + "'s"; the marker still has to
    # be consumed or the line fails full-token consumption.
    stream.expect_word("'s")
    stream.expect_word("hand")
    # "Look at target player's hand **and choose X cards from it. That player
    # discards those cards.**" (Mind Warp.) Duress's template with the hand
    # looked at instead of revealed, so it is that node rather than a second
    # one — and read here, from the sentence it actually opens, because the
    # choice is over the hand *this* clause opened and a statement after it
    # would be a pick from a zone nobody had looked in.
    picked = _accept_look_and_choose(stream, player)
    if picked is not None:
        return picked
    return ast.LookAtHand(player)


def _accept_look_and_choose(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.RevealHandAndChoose | None":
    """The tail of ``Look at <player>'s hand **and choose <N> cards from it.
    That player discards those cards.**`` (Mind Warp.)

    Refuses without consuming, so "Look at target player's hand." on its own
    (Glasses of Urza) keeps the reading it has. Every word of the discard
    sentence is required: a line that looks and chooses but never says what
    becomes of the cards is a card that does nothing, and dropping the sentence
    would make the two indistinguishable.
    """
    mark = stream.mark()
    if not stream.accept_phrase("and", "choose"):
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("from", "it"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # Whose discard, read as a reference rather than as the literal words
    # "that player": Leshrac's Sigil prints "**The player** discards that
    # card", which `parse_player_ref` already reads as the same back-reference
    # (it is an alias, like "they"). The referent is *required* to be that
    # back-reference — a sentence naming somebody else would be a card that
    # looks in one hand and empties another.
    discarder = parse_player_ref(stream) if stream.at_word(
        "that", "the", "they"
    ) else None
    if discarder is None or discarder.kind != "that_player":
        stream.reset(mark)
        return None
    if not stream.accept_phrase("discards", "those", "cards") and not (
        stream.accept_phrase("discards", "that", "card")
    ):
        stream.reset(mark)
        return None
    return ast.RevealHandAndChoose(
        player, ast.ObjectFilter(is_card=True), fate="discard",
        count=count, revealed=False,
    )



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

    CR 701.16 on its own — a library randomised with nothing moving into it.
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
    # already means (CR 701.16a shuffles a library), so the words are optional
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
