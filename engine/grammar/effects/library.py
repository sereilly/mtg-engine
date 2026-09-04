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
from ..phrases import _parse_card_alternatives, _parse_mana_payment
from ..vocabulary import CARD_TYPES


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


def _parse_look_top_offer_pick_tail(
    stream: TokenStream, count: "ast.Amount"
) -> "ast.May | None":
    """``You may sacrifice this <type> and pay <cost>. If you do, put one of
    those cards into your hand. If you don't, put one of those cards on the
    bottom of your library.`` (Preferred Selection.)

    Three sentences read where the look is, for :func:`_parse_reveal_top`'s
    reason: they describe **one** looked-at pile, and "those cards" in the last
    two names exactly what the first sentence turned up. Parsed apart, the two
    branches would each look at the top two cards again.

    Both branches pick one of the same cards and only the destination differs,
    so the whole thing is an ordinary :class:`ast.May` — the offer, its cost,
    the accept branch and the decline branch all reach machinery that already
    exists, and ``looked_at_top`` is what carries the first sentence through to
    the prompt that asks the question. The unchosen card goes back on top in
    both branches, which is where it already was: the card moves nothing it
    does not name.

    Declines without consuming, so Garruk's Harbinger's "you may **reveal** …"
    keeps its own reading and its own refusal site — both tails open on "you".
    """
    mark = stream.mark()
    if not stream.accept_phrase("you", "may", "sacrifice"):
        return None
    # "**this enchantment**" — the source, with its printed type carried into
    # the filter rather than dropped: the noun names the source's own type, and
    # a filter that said only "the source" would accept a wording naming a
    # permanent this card is not. Read in place rather than through
    # ``_accept_self_reference``, which consumes the noun and hands nothing
    # back; the card naming itself has no printed type here at all, so that
    # spelling is left to refuse.
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    noun = stream.peek_word()
    if noun not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("and", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None:
        stream.reset(mark)
        return None
    # Every word of both branches, and the sentence break between them. A
    # missing "if you don't" half would be a card that looked at two cards, was
    # offered a price and then did nothing for declining it — which is a
    # different card, and a strictly better one.
    for words in (
        (".", "if", "you", "do", ","),
        ("put", "one", "of", "those", "cards", "into", "your", "hand"),
        (".", "if", "you", "don't", ","),
        ("put", "one", "of", "those", "cards", "on", "the", "bottom", "of",
         "your", "library"),
    ):
        for word in words:
            if word == ".":
                if not stream.accept_punct("."):
                    stream.reset(mark)
                    return None
            elif word == ",":
                stream.accept_punct(",")
            elif not stream.accept_word(word):
                stream.reset(mark)
                return None
    return ast.May(
        actor=ast.PlayerRef("you"),
        cost=cost,
        action=ast.Sacrifice(
            ast.PlayerRef("you"),
            ast.TargetSpec(
                quantifier="this",
                filter=ast.ObjectFilter(card_types=(noun,), is_source=True),
            ),
        ),
        then=ast.LookTopPickToHand(count, rest_destination="library_top"),
        otherwise=ast.LookTopPickToHand(
            count, pick_destination="library_bottom",
            rest_destination="library_top",
        ),
        looked_at_top=count,
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


def parse_player_separates_your_library_top(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.Statement | None":
    """Phyrexian Portal, all three of its sentences.

    ``<player> looks at the top N cards of your library and separates them into
    two face-down piles. Exile one of those piles. Search the other pile for a
    card, put it into your hand, then shuffle the rest of that pile into your
    library.``

    Declines without consuming on anything else, so
    :func:`parse_player_looks_at_own_library_top` beside it keeps Ashnod's
    Cylix - the two open on the same four words and differ at the possessive,
    which is the whole point of the card: somebody else is looking through
    *your* deck.

    Every word of all three sentences is required. "Face-down" is the reason
    the second decision is a decision (CR 406.3); "the other pile" is what the
    second sentence left; and where the unsearched remainder goes is the
    difference between this and a tutor that exiles nine cards.
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
    if not stream.accept_phrase("cards", "of", "your", "library"):
        stream.reset(probe)
        return None
    if not stream.accept_phrase(
        "and", "separates", "them", "into", "two", "face-down", "piles"
    ):
        stream.reset(probe)
        return None
    if not stream.accept_punct("."):
        raise stream.error("expected the exile sentence after the split")
    for word in ("exile", "one", "of", "those", "piles"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the search sentence after the exile")
    for word in ("search", "the", "other", "pile", "for", "a", "card"):
        stream.expect_word(word)
    stream.accept_punct(",")
    for word in ("put", "it", "into", "your", "hand"):
        stream.expect_word(word)
    stream.accept_punct(",")
    stream.expect_word("then")
    for word in ("shuffle", "the", "rest", "of", "that", "pile", "into",
                 "your", "library"):
        stream.expect_word(word)
    return ast.SeparateLibraryTopIntoPiles(count, subject)


def parse_look_top_cycle_tail(
    stream: TokenStream, count
) -> "ast.Statement | None":
    """The rest of Lim-Dul's Vault, from the full stop after its first
    sentence. Declines without consuming on anything else, so every other look
    at your own library's top keeps its sorting sentence and its refusal.

    Read as one production over three sentences for :func:`_parse_look_pick_tail`'s
    reason: they describe one pile, and parsed apart "those cards" and "the last
    cards you looked at this way" dangle referents nothing binds.

    The second count is read and required to match the first. A wording that
    looked at five and then at three would be a different loop, and quietly
    reusing the first number is how a card comes to do something it does not
    say.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    if not stream.accept_phrase("as", "many", "times", "as", "you", "choose"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "may", "pay"):
        stream.reset(mark)
        return None
    life_cost = parse_amount(stream)
    for word in ("life", ",", "put", "those", "cards", "on", "the", "bottom",
                 "of", "your", "library", "in", "any", "order"):
        if word == ",":
            stream.accept_punct(",")
            continue
        stream.expect_word(word)
    stream.accept_punct(",")
    stream.expect_word("then")
    for word in ("look", "at", "the", "top"):
        stream.expect_word(word)
    again = parse_amount(stream)
    if again != count:
        raise stream.error("the repeated look reads the same number of cards")
    for word in ("cards", "of", "your", "library"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the shuffle sentence after the loop")
    stream.expect_word("then")
    for word in ("shuffle", "and", "put", "the", "last", "cards", "you",
                 "looked", "at", "this", "way", "on", "top", "in", "any",
                 "order"):
        stream.expect_word(word)
    return ast.LookTopCycleForLife(count, life_cost)


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
    # "**You may put that card on the bottom of that player's library.**"
    # (Coral Fighters.) The other offer this template prints, and the other
    # direction: Visions offers a shuffle, which the looker takes when the top
    # is bad, and this offers the one card itself.
    #
    # "That player" is read as the very player the look named rather than as a
    # fresh reference — parsed apart it would have to guess a seat, which is
    # this production's whole reason for reading the tail at all.
    bottomed = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "you", "may", "put", "that", "card", "on", "the", "bottom", "of",
        "that", "player", "'s", "library",
    ):
        return ast.LookAtLibraryTop(count, owner, may_bottom=True)
    stream.reset(bottomed)
    # "**Exile one of those cards and put the rest back on top of that player's
    # library in any order.**" (Sealed Fate.) The look-and-pick template over
    # somebody else's pile: the cards are the opponent's and every decision
    # about them is the caster's, which is the one thing ``looker`` cannot say
    # (there the seat answers both questions at once). So it produces the pick
    # node with ``pile_owner`` set rather than a second node — the procedure is
    # the same one, over a library that is not the chooser's.
    #
    # Every word of both destinations, for this family's standing reason: where
    # the taken card goes and where the rest go are the whole of what separates
    # these cards, and a wording that sorted them elsewhere would be a
    # different card wearing this one's head.
    exiled = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "exile", "one", "of", "those", "cards", "and", "put", "the", "rest",
        "back", "on", "top", "of", "that", "player", "'s", "library",
        "in", "any", "order",
    ):
        return ast.LookTopPickToHand(
            count,
            pick_destination="exile",
            rest_destination="library_top",
            pile_owner=owner,
        )
    stream.reset(exiled)
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
        # "Look at the top **card**" (Coral Fighters), beside "the top N
        # **cards**". The singular prints no number at all, so a reader that
        # went straight to `parse_amount` refused the line at the noun — the
        # same one-line gap `_parse_exile_top_of_library` already answers this
        # way two productions down.
        if stream.accept_word("card"):
            count: ast.Amount = ast.Fixed(1)
        else:
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
        # Lim-Dul's Vault: the look is the *first* of three sentences and the
        # two behind it bind its pile. Tried before the sorting sentence below,
        # and declining without consuming, so every card in that family keeps
        # its own reading and its own refusal site.
        cycled = parse_look_top_cycle_tail(stream, count)
        if cycled is not None:
            return cycled
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
            # Preferred Selection's offer opens on the same word as Garruk's
            # Harbinger's reveal, so it is tried first and declines without
            # consuming — leaving that card's own refusal site intact.
            offered = _parse_look_top_offer_pick_tail(stream, count)
            if offered is not None:
                return offered
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
        stream.expect_word("put")
        # "Put **two** of them into your hand" (Ancestral Memories). The count
        # was the literal word "one", so the only card in the pool that takes
        # more than one failed on the number it printed. Read rather than
        # defaulted: a card taking one where it says two is a strictly smaller
        # card, and nothing downstream could notice.
        picks = parse_amount(stream)
        stream.expect_word("of")
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
            return ast.LookTopPickToHand(
                count, pick_count=picks, rest_destination="exile"
            )
        stream.reset(exiled_rest)
        # "…and the rest **into your graveyard**." (Ancestral Memories.) The
        # graveyard spelled as a destination for the whole remainder, where
        # Waker of Waves prints the same fate for a named single card ("the
        # other"). The preposition differs from the two library ends below —
        # "into" a graveyard, "on" a library — so it is read here rather than
        # as a fourth alternative under the shared "on".
        graveyard_rest = stream.mark()
        if stream.accept_phrase("and", "the", "rest", "into", "your", "graveyard"):
            return ast.LookTopPickToHand(
                count, pick_count=picks, rest_destination="graveyard"
            )
        stream.reset(graveyard_rest)
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
                pick_count=picks,
                rest_destination=rest_destination,
                all_to_hand_if_cast_elsewhere=True,
            )
        stream.reset(mark)
        return ast.LookTopPickToHand(
            count, pick_count=picks, rest_destination=rest_destination
        )
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

    ``…**and choose a card from it. Put that card on top of that player's
    library.**`` (Painful Memories.) The same template with the other printed
    ending, which is a field on the node rather than a second production: what
    the family varies is what becomes of the chosen card, and the choice, the
    reveal and the picker are identical either way.

    Refuses without consuming, so "Look at target player's hand." on its own
    (Glasses of Urza) keeps the reading it has. Every word of the last sentence
    is required in both endings: a line that looks and chooses but never says
    what becomes of the cards is a card that does nothing, and dropping the
    sentence would make the two indistinguishable.
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
    # "**Put that card on top of that player's library.**" (Painful Memories.)
    # The other printed ending, read before the discard because it opens on the
    # verb rather than on a player reference. The possessive is required to be
    # the same back-reference the discard's subject is: a sentence naming
    # somebody else would look in one hand and stack another player's library.
    tuck = stream.mark()
    if stream.accept_phrase("put", "that", "card", "on", "top", "of"):
        owner = parse_player_ref(stream) if stream.at_word("that", "the") else None
        if (
            owner is not None
            and owner.kind == "that_player"
            and stream.accept_word("'s")
            and stream.accept_word("library")
        ):
            return ast.RevealHandAndChoose(
                player, ast.ObjectFilter(is_card=True), fate="library_top",
                count=count, revealed=False,
            )
        stream.reset(tuck)
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
