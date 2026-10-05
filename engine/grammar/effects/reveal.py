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
from ..amounts import parse_amount, parse_equal_to
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
    # "Reveal **a number of cards from the top of your library equal to** the
    # sacrificed creature's power. Put one into your hand and exile the rest."
    # (Eye of Yawgmoth.) The counted reveal with its count printed *behind* the
    # pile rather than in front of it — the word order "the top N cards of"
    # cannot take a computed amount. Tried here, before the literal "the", for
    # the reason the reveal-until reader above is: that expectation is what
    # failed the line, and this declines without consuming.
    counted_pick = _accept_reveal_number_from_top_pick(stream)
    if counted_pick is not None:
        return counted_pick
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
    # "Reveal the top **three cards** of your library and put one of them into
    # your hand. …" (Reviving Vapors.) The counted reveal whose pick is the
    # revealer's own. Non-consuming on refusal, like its siblings.
    picked = _accept_counted_reveal_pick_to_hand(stream)
    if picked is not None:
        return picked
    # "Reveal the top **four cards** of your library and put all of them with
    # that name into your hand. …" (Wood Sage.) A second counted reveal, whose
    # first sentence differs from the one above only in the word after
    # "library" — so both are tried here, both non-consuming, and neither takes
    # a reading from the other.
    sorted_by_name = _accept_counted_reveal_sorting_by_name(stream)
    if sorted_by_name is not None:
        return sorted_by_name
    # "Reveal the top **four cards** of your library. Put all **land cards**
    # revealed this way into your hand and the rest into your graveyard."
    # (Mulch.) The same counted reveal sorted by a printed filter instead of by
    # a chosen name — tried here beside its sibling, both non-consuming, so
    # neither takes a reading from the other.
    sorted_by_filter = _accept_counted_reveal_sorting_by_filter(stream)
    if sorted_by_filter is not None:
        return sorted_by_filter
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
#:
#: "battlefield" and "exile" joined them for Clear the Land — "puts all land
#: cards revealed this way onto the battlefield tapped, and exiles the rest" —
#: which is the first printing here that sorts a pile anywhere but a hand and a
#: graveyard. Each word is still something ``_place_sorted_reveal`` performs,
#: which is the whole point of the lists being closed.
_SORTED_MATCH_ZONES: tuple[str, ...] = ("hand", "battlefield")
_SORTED_REST_ZONES: tuple[str, ...] = ("graveyard", "exile")


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
    # "**Exile the rest.**" (Desperate Research.) The verb spelling of the one
    # rest zone that has a verb; the destination is the same closed word.
    if stream.accept_phrase("exile", "the", "rest"):
        return ast.RevealTopSortingByChosenName(
            count, match_zone=match_zone, rest_zone="exile",
        )
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


def _accept_counted_reveal_sorting_by_filter(
    stream: TokenStream,
) -> "ast.RevealTopSortingByFilter | None":
    """``<N> cards of your library. Put all <filter> revealed this way into
    your hand and the rest into your graveyard.`` at the cursor, with "Reveal
    the top" already read — or None with the cursor where it was. (Mulch.)

    The sibling of :func:`_accept_counted_reveal_sorting_by_name` one function
    up, and a separate production rather than a branch of it because the two
    sentences are punctuated differently: Wood Sage joins the sort to the reveal
    with "and" inside one sentence and Mulch ends the reveal with a full stop.
    What they share — one pile, both halves of it placed by the step that
    turned it over — is shared where it matters, in the handler.

    The predicate is a printed :class:`ObjectFilter` rather than the name an
    earlier step chose, which is the whole difference: this sentence carries
    everything it needs, so there is no record to demand and none to refuse
    for.

    Both destinations are read and checked against the same closed lists the
    named sort uses, so a printing that sorted somewhere the handler cannot
    reach refuses here rather than lowering onto a zone nothing moves to.
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
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("put", "all"):
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # A pile taken off a library is cards, never permanents (CR 400.1), so a
    # phrase describing something on the battlefield is a different sentence.
    if not filt.is_card:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "revealed", "this", "way", "into", "your",
    ):
        stream.reset(mark)
        return None
    match_zone = stream.peek_word()
    if match_zone not in _SORTED_MATCH_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("and", "the", "rest", "into", "your"):
        stream.reset(mark)
        return None
    rest_zone = stream.peek_word()
    if rest_zone not in _SORTED_REST_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.RevealTopSortingByFilter(
        count, filt, match_zone=match_zone, rest_zone=rest_zone,
    )


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


def _accept_counted_reveal_pick_to_hand(
    stream: TokenStream,
) -> "ast.Statement | None":
    """``<N> cards of your library and put one of them into your hand. You gain
    life equal to that card's mana value. Put all other cards revealed this way
    into your graveyard.`` at the cursor, with "Reveal the top" already read —
    or None with the cursor where it was. (Reviving Vapors.)

    :class:`ast.LookTopPickToHand` over a revealed pile with the rest binned,
    as Eye of Yawgmoth's reveal below is. All three sentences, because "that
    card" and "all other cards revealed this way" bind to nothing read apart.
    The life gain stays an ordinary statement behind the pick, reading a number
    the pick is told to record; it runs after the rest are binned, which nobody
    can observe — no player receives priority inside a resolution.
    """
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 2:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "cards", "of", "your", "library", "and", "put", "one", "of", "them",
        "into", "your", "hand",
    ) or not stream.accept_punct("."):
        stream.reset(mark)
        return None
    gains = stream.accept_phrase(
        "you", "gain", "life", "equal", "to", "that", "card", "'s", "mana", "value",
    )
    if gains and not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "put", "all", "other", "cards", "revealed", "this", "way", "into",
        "your", "graveyard",
    ):
        stream.reset(mark)
        return None
    pick = ast.LookTopPickToHand(
        count, rest_destination="graveyard", revealed=True,
        records_pick_mana_value=gains,
    )
    if not gains:
        return pick
    return ast.Sequence((
        pick,
        ast.GainLife(ast.PlayerRef("you"), ast.ThatMuch("its_mana_value")),
    ))


def _accept_reveal_number_from_top_pick(
    stream: TokenStream,
) -> "ast.LookTopPickToHand | None":
    """``a number of cards from the top of your library equal to <amount>. Put
    <N> [of them] into your hand and exile the rest.`` at the cursor, with
    "Reveal" already read — or None with the cursor where it was. (Eye of
    Yawgmoth.)

    The look-and-pick procedure (``LookTopPickToHand``) over a **revealed**
    pile, both sentences read here for ``_parse_reveal_top``'s reason: "one"
    and "the rest" name the pile the first sentence turned up and nothing else.
    The count is an "equal to" amount, read by the one reader every "equal to"
    goes through, so the cost-paid quantity this card prints is the same node a
    draw or a mill would get for it — which amount a pick can actually take is
    the lowering's question.

    Only the destinations Eye of Yawgmoth prints: the pick into the hand and
    the rest exiled. Any other tail declines (the line then refuses at "the"),
    because where the cards go is the card's own statement. The look family
    reads its own pick tail inline (``effects/library.py``'s Browse branch);
    the two cannot share one — the families may not import each other — and a
    third reader is the point at which the tail belongs in ``phrases``.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "a", "number", "of", "cards", "from", "the", "top", "of", "your", "library",
    ):
        return None
    count = parse_equal_to(stream)
    if count is None or not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_word("put"):
        stream.reset(mark)
        return None
    try:
        picks = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_phrase("of", "them")
    if not stream.accept_phrase("into", "your", "hand"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("and", "exile", "the", "rest"):
        stream.reset(mark)
        return None
    return ast.LookTopPickToHand(
        count, pick_count=picks, rest_destination="exile", revealed=True,
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


def accept_subject_reveals_counted_top_sorted(
    stream: TokenStream, subject: "ast.PlayerRef"
) -> "ast.RevealTopSortingByFilter | None":
    """``<player> reveals the top <N> cards of their library, puts all <filter>
    revealed this way onto the battlefield tapped, and exiles the rest`` — or
    None, unconsumed. (Clear the Land.)

    :func:`_accept_counted_reveal_sorting_by_filter` with a printed subject and
    the other punctuation: Mulch says "Reveal the top four cards of **your**
    library." and starts a new sentence for the sort, and this one runs all
    three clauses together under "each player". Both produce the **same node**,
    which is the arrangement :func:`accept_subject_reveals_top_of_library`
    already has one screen down and for the same reason — whose library is
    turned over is one question, and two nodes would be two places to answer it.

    Every clause is read and checked, none skipped:

    * **whose library** — required to be "their", the back-reference to the
      subject this production was handed. A second seat there is a sentence
      nobody prints and one this node cannot express;
    * **the destinations** — against the same two closed lists Mulch's
      production checks, so a printing that sorted somewhere the handler cannot
      reach refuses here rather than lowering onto a zone nothing moves to;
    * **"tapped"** — CR 110.5b, carried onto the node. Consumed and dropped it
      would be a strictly better card than the one printed.

    Refuses without consuming, so "each player reveals the top card of their
    library" keeps the reading and the refusal it already had.
    """
    mark = stream.mark()
    if not stream.accept_word("reveals", "reveal"):
        return None
    if not stream.accept_phrase("the", "top"):
        stream.reset(mark)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 1:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("cards", "of", "their", "library"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("puts", "all"):
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # A pile taken off a library is cards, never permanents (CR 400.1), so a
    # phrase describing something on the battlefield is a different sentence.
    if not filt.is_card:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("revealed", "this", "way", "onto", "the"):
        stream.reset(mark)
        return None
    match_zone = stream.peek_word()
    if match_zone not in _SORTED_MATCH_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    tapped = stream.accept_word("tapped")
    stream.accept_punct(",")
    if not stream.accept_word("and"):
        stream.reset(mark)
        return None
    # "and **exiles** the rest" — the verb *is* the destination here, where
    # Mulch spells it as "into your <zone>". Read off the same closed list, so
    # a card printing a verb nothing performs refuses instead of sorting the
    # remainder somewhere nobody moves it.
    rest_verb = stream.peek_word()
    rest_zone = {"exiles": "exile", "exile": "exile"}.get(rest_verb or "")
    if rest_zone not in _SORTED_REST_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("the", "rest"):
        stream.reset(mark)
        return None
    return ast.RevealTopSortingByFilter(
        count, filt, match_zone=match_zone, rest_zone=rest_zone,
        whose=subject, tapped=bool(tapped),
    )


def accept_subject_reveals_top_of_library(
    stream: TokenStream, subject: "ast.PlayerRef"
) -> "ast.RevealTop | None":
    """``<player> reveals the top card of their library`` — or None, unconsumed.

    "At the beginning of the upkeep of enchanted creature's controller, **that
    player reveals the top card of their library**." (Paroxysm.) The
    subject-verb spelling of :func:`_parse_reveal_top`'s "of target opponent's
    library", and it produces the **same node**: which library is opened is the
    only thing that differs between the two printings, and the pool prints both
    (Prophecy the imperative, Paroxysm the subject-verb). Two nodes would be two
    places for "whose deck" to be answered.

    The possessive is required to be "their", the back-reference to the subject
    this production was handed. A sentence naming a second seat there
    ("that player reveals the top card of **your** library") is a phrase nobody
    prints and one this node cannot express — it carries one player — so it
    refuses without consuming rather than opening the wrong deck.
    """
    mark = stream.mark()
    if not stream.accept_word("reveals", "reveal"):
        return None
    if not stream.accept_phrase("the", "top", "card", "of", "their", "library"):
        stream.reset(mark)
        return None
    return ast.RevealTop(subject)


def parse_reveal_any_number_from_hand(
    stream: TokenStream,
) -> "ast.RevealCardsFromHand | None":
    """``Reveal any number of <filter> cards in your hand.`` (CR 701.20a.)

    Urza's Destiny's five Seers, their five Scents, Metalworker and Rofellos's
    Gift: twelve cards, one sentence, and seven printed noun phrases between
    them. The count the sentence *behind* it spends is what the reveal records
    — see ``oracle_types.REVEALED_THIS_WAY`` — so the reveal is its own step
    and everything printed after it is an ordinary sentence reading a
    back-reference.

    Refuses **without consuming** when the words are not this template, so
    "Reveal your hand …" (Manabond) and "Reveal the top card of your library"
    (Prophecy) keep the readings and the errors they already had. The verb is
    consumed here rather than by the dispatcher for that reason.

    Three things are required rather than defaulted, and each is a different
    card if it is dropped:

    * **"any number of"**. A printed count ("reveal two cards from your hand")
      is a different offer, and one this node cannot carry.
    * **The hand, and the revealer's own**. CR 400.2 makes a hand hidden, and
      a reveal out of somebody else's is a sentence with a different actor;
      neither is printed here, so both refuse rather than being read as this.
    * **Cards**. The noun parser answers "blue permanents in your hand" the
      same way it answers "blue cards", and only the second is a card.
    """
    mark = stream.mark()
    if not stream.accept_word("reveal"):
        return None
    # "Reveal **a** creature card in your hand." (Assembly Hall.) One card
    # instead of a subset, and the same node: what happens is identical and only
    # the size of the offer differs. The article is required rather than
    # optional, so "Reveal your hand" (Manabond) and "Reveal the top card of
    # your library" (Prophecy) still decline here without consuming and keep
    # every reading and every refusal they had.
    count: int | None = None
    if stream.accept_phrase("any", "number", "of"):
        count = None
    elif stream.accept_word("a", "an"):
        count = 1
    else:
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not (
        filt.is_card
        and filt.zone == "hand"
        and filt.zone_owner is not None
        and filt.zone_owner.kind == "you"
    ):
        stream.reset(mark)
        return None
    return ast.RevealCardsFromHand(filt, count)
