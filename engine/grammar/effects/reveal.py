"""Parsing what a card **reveals** — CR 701.20a, the public half of a look.

Split off ``effects/library.py`` at Tempest's second wave, when Sacred Guide's
reveal-until run took that module to 1,073 lines. The cut is the one that
module's own docstring drew and then CR made sharp: a **reveal** (CR 701.20a)
shows a card to *all* players, and everything left there is CR 701.20e's
**look**, which "follows the same rules as revealing a card, except that the
card is shown only to the specified player". That is why a reveal is recorded
(``Game.record_reveal``) and a look is not, and why a card's next sentence may
talk about what a reveal turned up.

The call graph had already fallen apart along that line. ``_parse_reveal_top``
and the two acceptors behind it are reached from the imperative dispatcher and
from each other and from nothing else; ``_parse_look_at_hand`` and its six
tails are reached from the look dispatcher and from each other. Neither module
imports the other.

**No lowering twin, and that is deliberate.** ``RevealTop``,
``RevealTopToHandOrBottom``, ``RevealTopOpponentChooses`` and ``RevealUntil``
all lower in ``lowering/library.py``, a few lines apart from the look-at
lowerings, because what a reveal *costs* to lower is one instruction however
elaborately its sentence is printed — the words are where the work is. That is
the asymmetry ``search`` carried until Visions and ``text_changes`` still
carries: a near-empty ``lowering/reveal.py`` would buy back the symmetry and
cost the thing symmetry is for.
"""

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..phrases import accept_a_card_at_random_from_hand
from ..references import parse_player_ref
from ..stream import TokenStream


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
    # "Reveal **cards** from the top of your library until you reveal a white
    # card. …" (Sacred Guide.) The word after the verb is the fork: this one
    # reads an unbounded run off the top and stops on a match, where everything
    # below reads a fixed number of them. Tried here, before the literal "the",
    # because that expectation is what failed the line — and non-consuming on
    # refusal, so every "Reveal the top …" keeps the reading it has.
    until = _accept_reveal_until_from_top(stream)
    if until is not None:
        return until
    # "…, then **reveal a card at random from your hand**." (Cursed Scroll.)
    # The bare imperative spelling of Wand of Ith's object phrase, which the
    # subject-verb reader takes when a player is printed in front of the verb
    # and nothing took when one is not — the line failed on "the" here, four
    # words short of a production that already existed. The fragment is
    # ``phrases``' because three families read it now.
    if accept_a_card_at_random_from_hand(stream):
        return ast.RevealRandomFromHand(ast.PlayerRef("you"))
    stream.expect_word("the")
    stream.expect_word("top")
    # "Reveal the top **three cards** of your library. Target opponent chooses
    # one of those cards. \u2026" (Thran Tome.) A counted reveal, read here because
    # the singular below expects the literal word "card" and failed the line on
    # the number \u2014 the same one-line gap ``_parse_exile_top_of_library``
    # answers this way. Non-consuming on refusal, so a counted reveal with any
    # other tail keeps whatever refusal it had.
    counted = _accept_counted_reveal_top(stream)
    if counted is not None:
        return counted
    # "Reveal the top **four cards** of your library and put all of them with
    # that name into your hand. …" (Wood Sage.) A second counted reveal, whose
    # first sentence differs from the one above only in the word after
    # "library" — so both are tried here, both non-consuming, and neither takes
    # a reading from the other.
    sorted_by_name = _accept_counted_reveal_sorting_by_name(stream)
    if sorted_by_name is not None:
        return sorted_by_name
    for word in ("card", "of"):
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


#: Where each half of a sorted reveal may be printed to go. Two closed lists
#: rather than one, because they are different questions: the match is *kept*
#: and the rest is *discarded*, and a card that put its finds on the bottom of
#: the library would be a different effect from one that put the rest there.
_SORTED_MATCH_ZONES: tuple[str, ...] = ("hand",)
_SORTED_REST_ZONES: tuple[str, ...] = ("graveyard",)


def _accept_counted_reveal_sorting_by_name(
    stream: TokenStream,
) -> "ast.RevealTopSortingByChosenName | None":
    """``<N> cards of your library and put all of them with that name into your
    hand. Put the rest into your graveyard.`` at the cursor, with "Reveal the
    top" already read — or None with the cursor where it was. (Wood Sage.)

    Both sentences, for :class:`ast.RevealTopSortingByChosenName`'s reason:
    "the rest" names exactly what the first sentence did not take, so apart the
    second moves cards out of a pile nothing recorded.

    "**that name**" is required and is what makes this a naming card rather
    than a counted mill: the name was chosen by an earlier step of the same
    ability, and the lowering demands that step. Read as the printed words
    rather than a filter, because a filter would have to describe a name the
    card never states.

    Both destinations are read and checked against a closed list, so a printing
    that sorted somewhere the handler cannot reach refuses here rather than
    lowering onto a zone nothing moves to.
    """
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 1:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("cards", "of", "your", "library"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "and", "put", "all", "of", "them", "with", "that", "name", "into",
        "your",
    ):
        stream.reset(mark)
        return None
    match_zone = stream.peek_word()
    if match_zone not in _SORTED_MATCH_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("put", "the", "rest", "into", "your"):
        stream.reset(mark)
        return None
    rest_zone = stream.peek_word()
    if rest_zone not in _SORTED_REST_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.RevealTopSortingByChosenName(
        count, match_zone=match_zone, rest_zone=rest_zone,
    )


#: What the cards a reveal-until turned over *before* the match may be printed
#: to do. A closed list, for ``effects/library._REVEAL_DESTINATIONS``'
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

    Both sentences, for :func:`_parse_reveal_top`'s reason and
    :class:`ast.RevealUntil`'s: "that card" is what the run stopped on and "all
    other cards revealed this way" is exactly what it turned over first, so
    apart they dangle referents nothing binds.

    The **rest's fate is read, not assumed**. Transmogrify shuffles its pile
    back and this one exiles it, which is the whole difference between a card
    that costs its controller a library and one that does not — and the two
    sentences up to that word are identical.

    Only the reader's own library: the destination says "your hand", so a run
    off somebody else's deck would move a card out of that library into this
    seat's hand. A card printing that is a different card, and it refuses here
    rather than lowering onto a seat the handler would guess at.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "cards", "from", "the", "top", "of", "your", "library", "until", "you",
        "reveal",
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
    # Every word of the destination, for the reason the rider one module over
    # gives about its own: a printing that put the found card somewhere else is
    # a different card and nothing before this sentence shows the difference.
    if not stream.accept_phrase("put", "that", "card", "into", "your", "hand"):
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    rest = stream.peek_word()
    if rest not in _REVEAL_UNTIL_REST:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase(
        "all", "other", "cards", "revealed", "this", "way"
    ):
        stream.reset(mark)
        return None
    return ast.RevealUntil(
        "you", filt, destination="hand", rest=_REVEAL_UNTIL_REST[rest],
    )


def _accept_counted_reveal_top(
    stream: TokenStream,
) -> "ast.RevealTopOpponentChooses | None":
    """``<N> cards of your library. Target opponent chooses one of those cards.
    Put that card into your graveyard[, then draw <N> cards].`` at the cursor,
    with "Reveal the top" already read \u2014 or None with the cursor where it was.
    (Thran Tome.)

    All three sentences, for ``_parse_reveal_top``'s reason: they describe one
    revealed pile, and "those cards" and "that card" have nothing to name
    without it. Every word is required. The chooser is read rather than assumed
    (a pick made by the wrong player is the whole card), and so is where the
    card goes \u2014 a printing that exiled it instead would be a different card
    with nothing to notice the difference.
    """
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        # The singular "Reveal the top **card**", whose word this reader is not
        # looking at. Refusing without consuming is what keeps its own refusal
        # site intact.
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 2:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("cards", "of", "your", "library"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    chooser = parse_player_ref(stream)
    if chooser is None or not stream.accept_phrase(
        "chooses", "one", "of", "those", "cards"
    ):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("put", "that", "card", "into", "your", "graveyard"):
        stream.reset(mark)
        return None
    # "\u2026, then draw two cards." The sentence behind the pick, consumed here
    # because it is inside the same printed sentence \u2014 it lowers to its own
    # instruction, so nothing is fused by reading it.
    drawn = None
    probe = stream.mark()
    if stream.accept_punct(",") and stream.accept_word("then") and stream.accept_word(
        "draw"
    ):
        drawn = parse_amount(stream)
        if not stream.accept_word("cards", "card"):
            stream.reset(mark)
            return None
    else:
        stream.reset(probe)
    return ast.RevealTopOpponentChooses(
        count, chooser, fate="graveyard", then_draw=drawn,
    )


def parse_bin_revealed_card(stream: TokenStream) -> "ast.Statement | None":
    """``Put it into <player>'s graveyard.`` (Wand of Denial.)

    Read among the "put" back-references in ``imperatives`` and, like all of
    them, refusing without consuming — the counter production behind them reads
    "it" as a counter kind and refuses with a site naming counters, which is a
    refusal that blames the wrong clause.

    Only a graveyard, because that is the only destination the record can be
    moved to without a second question: the card is still in the library the
    look turned it up in, and every other zone would want to know where in it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("put", "it", "into"):
        stream.reset(mark)
        return None
    owner = parse_player_ref(stream)
    if owner is None or not stream.accept_phrase("'s", "graveyard"):
        stream.reset(mark)
        return None
    return ast.BinRevealedCard(owner)


#: Where each half of a graveyard pick may be printed to go. Two closed lists
#: for `_SORTED_MATCH_ZONES`' reason: the chosen card and the rest go different
#: ways, and a word outside these refuses the line rather than lowering onto a
#: fate nothing carries out.
_PICKED_CARD_FATES: dict[str, str] = {"exile": "exile"}
_OTHER_CARD_FATES: dict[str, str] = {"hand": "hand", "graveyard": "graveyard"}


def parse_graveyard_top_opponent_chooses(
    stream: TokenStream, chooser: "ast.PlayerRef",
) -> "ast.GraveyardTopOpponentChooses | None":
    """``chooses one of the top <N> cards of your graveyard. Exile that card and
    put the other one into your hand.`` at the cursor, with the subject already
    read — or None with the cursor where it was. (Phyrexian Grimoire.)

    Both sentences, for :class:`ast.GraveyardTopOpponentChooses`' reason: "that
    card" is the pick and "the other one" is the rest of the same pile, and
    apart they name nothing.

    **No reveal**, and that is CR 400.2 rather than an omission: a graveyard is
    a public zone, so there is nothing to show anybody before the choice is
    made. The library version of this paragraph (Thran Tome) opens with one.

    "**your** graveyard" is required as printed: the pile is the ability's
    controller's, and a wording naming the chooser's own graveyard would be a
    different card — the opponent would be picking out of their own pile and
    the sentence behind it would put one of their cards in this seat's hand.

    Refuses without consuming, so every other "…chooses…" keeps its own reading
    and its own refusal site.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("one", "of", "the", "top"):
        stream.reset(mark)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 2:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("cards", "of", "your", "graveyard"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    verb = stream.peek_word()
    if verb not in _PICKED_CARD_FATES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("that", "card", "and", "put", "the", "other"):
        stream.reset(mark)
        return None
    # "the other **one**" / "the other **card**" — one referent, two printed
    # spellings, and neither adds anything the pile has not already said.
    if not stream.accept_word("one", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_word("into"):
        stream.reset(mark)
        return None
    stream.accept_word("your", "their")
    other = stream.peek_word()
    if other not in _OTHER_CARD_FATES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.GraveyardTopOpponentChooses(
        count, chooser,
        chosen_fate=_PICKED_CARD_FATES[verb],
        other_fate=_OTHER_CARD_FATES[other],
    )
