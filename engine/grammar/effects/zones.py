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
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..phrases import accept_graveyard_position
from ..references import parse_player_ref, parse_recipient
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


def _parse_exile_graveyard_position(stream: TokenStream) -> ast.Statement | None:
    """``Exile the bottom card of target player's graveyard.`` (Phyrexian
    Furnace.) Returns None with the cursor unmoved for anything else.

    The graveyard twin of :func:`_parse_exile_top_of_library` directly above,
    and here for its reason: CR 404.1/404.2 name these cards by *position*, so the
    recipient parser refuses the phrase and would fail the sentence with a
    misleading error. The phrase itself is read by the one production three
    families share (``phrases.accept_graveyard_position``), so the effect and
    the cost printing the same words cannot disagree about which card they
    name.
    """
    mark = stream.mark()
    if not stream.accept_word("exile"):
        stream.reset(mark)
        return None
    position = accept_graveyard_position(stream)
    if position is None:
        stream.reset(mark)
        return None
    return ast.ExileGraveyardPosition(position)


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
    # "**Target player shuffles** up to three target cards from their graveyard
    # into their library." (Gaea's Blessing.) The same move with its subject
    # printed in front of it and the cards *chosen* rather than described, so it
    # is a branch of this production rather than a second one — the verb is the
    # same word in another inflection, and two productions racing for it would
    # make which reading a card gets depend on their order. Tried first because
    # it is the only branch that opens on a player reference.
    chosen = _accept_player_shuffles(stream)
    if chosen is not None:
        return chosen
    # "your graveyard" is a possessive, not a player reference — `parse_player_ref`
    # reads "you" / "target player" / "each opponent" and rightly refuses it —
    # so the word is matched directly, and both occurrences are checked. A card
    # moving *another* player's graveyard is a different effect, and consuming
    # the possessive without reading it would compile that card onto this one.
    if not stream.accept_word("shuffle"):
        stream.reset(mark)
        return None
    # "Shuffle **it** into **its owner's** library." (Alabaster Dragon.) One
    # object rather than a pile, read here because the word after the verb is
    # what tells the two apart and this is the production the verb reaches.
    # Non-consuming on refusal, so the two pile readings below keep theirs.
    source = stream.mark()
    if stream.accept_word("it"):
        if stream.accept_phrase("into", "its", "owner", "'s", "library"):
            return ast.ShuffleSourceIntoLibrary(ast.PlayerRef("owner"))
        stream.reset(mark)
        return None
    stream.reset(source)
    # "Shuffle **all creature cards from** your graveyard into your library."
    # (Barishi.) The same move over a named subset, so it is this node with a
    # filter rather than a second one — see ``ShuffleGraveyardIntoLibrary.cards``.
    # ``parse_object_filter`` is the one reader of a printed noun phrase, and a
    # phrase it cannot express refuses here rather than shuffling back a wider
    # set than the card names.
    if stream.accept_word("all"):
        try:
            cards = parse_object_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        # The source zone is part of the noun phrase, not a clause after it:
        # ``parse_object_filter`` reads "from your graveyard" onto the filter,
        # so it is *checked* here rather than consumed again. Anybody else's
        # graveyard is a different effect, for the reason the whole-zone
        # reading below states.
        if not (
            cards.is_card
            and cards.zone == "graveyard"
            and cards.zone_owner is not None
        ):
            stream.reset(mark)
            return None
        # "Shuffle all creature cards from **target player's** graveyard into
        # **that player's** library." (Repopulate.) Barishi's sentence with a
        # chosen seat instead of the caster, so it is a branch of this reading
        # rather than a second production — what differs is whose two zones the
        # cards move between, and the pronoun in the destination is what says
        # they are the *same* player's. Both possessives are read for the
        # reason the "your" pair is: a card pairing one player's graveyard with
        # another's library would be a different card, and consuming the words
        # unread would compile it onto this one.
        if cards.zone_owner.kind == "target_player":
            if not stream.accept_phrase(
                "into", "that", "player", "'s", "library"
            ):
                stream.reset(mark)
                return None
            return ast.ShuffleGraveyardIntoLibrary(
                ast.PlayerRef("target_player"), cards=cards
            )
        if not (
            cards.zone_owner.kind == "you"
            and stream.accept_phrase("into", "your", "library")
        ):
            stream.reset(mark)
            return None
        return ast.ShuffleGraveyardIntoLibrary(ast.PlayerRef("you"), cards=cards)
    # "Shuffle **target nontoken permanent you control** into its owner's
    # library." (Rishadan Pawnshop.) The "it" branch above with the object
    # chosen instead of named, so it is a branch of this production rather than
    # one of its own: the verb and the destination are the same words, and two
    # productions racing for "shuffle" would make which reading a card gets
    # depend on their order.
    #
    # Read **last**, after every pile reading, and non-consuming on refusal:
    # ``parse_recipient`` reads a great many phrases, and one asked first would
    # take "your graveyard" for a noun phrase and strand the destination. The
    # trailing possessive is required for the "it" branch's reason — a card
    # printing "your library" would be a different card the moment a permanent
    # changed hands.
    chosen_mark = stream.mark()
    try:
        chosen_one = parse_recipient(stream)
    except GrammarError:
        chosen_one = None
    if chosen_one is not None and stream.accept_phrase(
        "into", "its", "owner", "'s", "library"
    ):
        return ast.ShuffleTargetIntoLibrary(chosen_one, ast.PlayerRef("owner"))
    stream.reset(chosen_mark)
    if not stream.accept_phrase("your", "graveyard", "into", "your", "library"):
        stream.reset(mark)
        return None
    return ast.ShuffleGraveyardIntoLibrary(ast.PlayerRef("you"))


def _accept_player_shuffles(
    stream: TokenStream,
) -> "ast.ShuffleGraveyardIntoLibrary | None":
    """``<player> shuffles <their graveyard | up to <N> target cards from their
    graveyard> into their library`` at the cursor, or None with the cursor where
    it was. (Thran Foundry; Gaea's Blessing.)

    Barishi's ``cards`` filter one step further: there the moving subset is
    *described* and nobody chooses, here it is **targeted** and the controller
    picks the slots (CR 601.2c). One node either way, because what changes is
    which cards move and not what happens to them — CR 701.24a still shuffles
    the whole library once, and the destination is still the pile's own owner's.

    Every possessive is read rather than assumed, for the whole-zone reading's
    reason: "their graveyard … their library" both name the player this
    sentence has already named, and a card pairing one player's graveyard with
    another's library would be a different card that consuming the words unread
    would compile onto this one.

    Refuses without consuming, so "That player shuffles." keeps its own
    production and its own refusal site.
    """
    mark = stream.mark()
    player = parse_player_ref(stream)
    if player is None or not stream.accept_word("shuffles"):
        stream.reset(mark)
        return None
    # "Target player shuffles **their graveyard** into their library." (Thran
    # Foundry.) Feldon's Cane's whole-zone move with its subject printed in
    # front of it, which is the same relationship Gaea's Blessing below has to
    # Barishi — so it is a branch here rather than a production of its own, and
    # tried first because "their graveyard" and "up to" are different words in
    # the same slot. Both possessives are read for the reason every other
    # reading in this file reads its own: a card pairing one player's graveyard
    # with another's library is a different card, and consuming the words unread
    # would compile it onto this one.
    if stream.accept_phrase(
        "their", "graveyard", "into", "their", "library",
    ):
        return ast.ShuffleGraveyardIntoLibrary(player)
    if not stream.accept_phrase("up", "to"):
        stream.reset(mark)
        return None
    count = parse_amount(stream)
    if not isinstance(count, ast.Fixed) or count.value < 1:
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # The source zone rides the noun phrase — ``parse_object_filter`` reads
    # "from their graveyard" onto the filter — so it is *checked* here rather
    # than consumed again, exactly as the "all …" branch above checks its own.
    if not (
        filt.is_card
        and filt.zone == "graveyard"
        and filt.zone_owner is not None
        and filt.zone_owner.kind == "owner"
        and stream.accept_phrase("into", "their", "library")
    ):
        stream.reset(mark)
        return None
    return ast.ShuffleGraveyardIntoLibrary(
        player,
        chosen=ast.TargetSpec(
            "up_to", filt, count=count.value, targeted=True,
        ),
    )


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
    any_number = False
    counted = stream.mark()
    # "shuffles **any number of** cards from their hand" (Credit Voucher). The
    # counted branch below with the number left to the player, read here rather
    # than as a production of its own because everything after the quantifier is
    # the identical clause — and read *before* the article, whose "a" would
    # otherwise never be reached by these words but whose ordering is what keeps
    # the two quantifiers from racing if one ever prints "any one".
    if stream.accept_phrase("any", "number", "of"):
        if stream.accept_word("cards", "card") and stream.accept_word("from"):
            any_number = True
        else:
            stream.reset(counted)
    if any_number:
        pass
    elif stream.accept_word("a", "an"):
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
    if count is None and not any_number:
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
    then_draw_count: int | None = None
    probe = stream.mark()
    drew = "draws" if whose == "their" else "draw"
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", drew, "that", "many", "cards"
    ):
        then_draw = True
    else:
        # "…into their library, **then draws seven cards**." (Time Spiral.) The
        # same trailing draw with a printed number, read here rather than as the
        # sentence after it for the reason "that many" is: CR 701.24a shuffles
        # the library and the draw comes off the shuffled one, so a statement
        # parsed apart would be a second sentence about the same step. The
        # number is *not* what moved — an empty hand still draws seven — which
        # is why it travels as its own field.
        stream.reset(probe)
        counted = stream.mark()
        if stream.accept_punct(",") and stream.accept_phrase("then", drew):
            word = stream.peek_word()
            printed = NUMBER_WORDS.get(word) if word else None
            if printed is not None:
                stream.advance()
                if stream.accept_word("cards", "card"):
                    then_draw_count = printed
                else:
                    stream.reset(counted)
            else:
                stream.reset(counted)
        else:
            stream.reset(counted)
    return ast.ShuffleHandIntoLibrary(
        player, then_draw=then_draw, then_draw_count=then_draw_count,
        count=count, any_number=any_number, with_graveyard=with_graveyard,
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


def parse_put_library_top_into_hand(
    stream: TokenStream,
) -> "ast.PutLibraryTopIntoHand | None":
    """``Put <amount> cards from the top of your library into your hand.``
    (Scroll Rack.)

    Not a draw and deliberately not spelled as one — see
    :class:`ast.PutLibraryTopIntoHand`. Every word after the count is required:
    "from the top of your library" is where the cards come from and "into your
    hand" is where they go, and a production that shrugged at either would be
    reading a sentence this card does not print.

    Refuses without consuming, so every other "Put …" keeps its own reading and
    the counter production behind them all keeps its own refusal site.
    """
    mark = stream.mark()
    if not stream.accept_word("put"):
        stream.reset(mark)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "from", "the", "top", "of", "your", "library", "into", "your", "hand",
    ):
        stream.reset(mark)
        return None
    return ast.PutLibraryTopIntoHand(count)
