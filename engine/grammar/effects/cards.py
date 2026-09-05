"""Cards moving: drawing, discarding, milling, searching, revealing.

Draw / discard / mill share a shape — a player reference and a count — and are
one-liners for that reason. Library search carries the filter that decides what
may be found.

Mana used to be here, on the grounds that adding mana is what a card *does*
with a card or a permanent. It is `effects/mana.py` now: a template about what
a land *produces* rather than about a card moving pushed this module past the
thousand-line guard, and the lowering side had already split the same family
off for the same reason. The name is `lowering/mana.py`'s, so the mirror
re-forms instead of forking.
"""


from .. import ast
from ..amounts import accept_fraction_head, accept_rounding, parse_amount, parse_equal_to
from ..records import accept_as_many_as

from ..amounts import accept_counters_on_source
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import _parse_duration, _parse_mana_payment
from ..readers import accept_source_reference


def _parse_draw(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("draws", "draw")
    # "draw cards **equal to** the number of …" (Frantic Inventory) puts the
    # noun in front of the count, where every other draw puts it behind. Read
    # first, and reset if the words turn out to be the ordinary "draw cards" of
    # a phrase like "draw two cards" — there is no number to have skipped,
    # because "cards" cannot start one.
    mark = stream.mark()
    if stream.accept_word("cards"):
        counted = parse_equal_to(stream)
        if counted is not None:
            return ast.Draw(player, counted)
        stream.reset(mark)
    # "…then draws **as many cards as they discarded this way**" (Forget). The
    # comparative spelling puts the noun *inside* the quantity, which is why it
    # is read here with the noun handed to it rather than by `parse_amount`
    # below — that one is called where the noun has not been reached yet, and
    # returns before it.
    as_many = accept_as_many_as(stream, ("card", "cards"), player)
    if as_many is not None:
        return ast.Draw(player, as_many)
    # "Each player may draw **up to** two cards." (Truce.) Read before the
    # amount and recorded rather than consumed, exactly as `_parse_discard`
    # below reads the same two words: a ceiling read as an exact count is a
    # card that forces a draw its controller was offered the choice of
    # declining — and on this card the declining is the whole point.
    up_to = bool(stream.accept_phrase("up", "to"))
    count = parse_amount(stream)
    # "draw two **additional** cards" (Sylvan Library). The word says the draw
    # is on top of one the turn already provides; it names no second effect and
    # changes no number, so it is consumed rather than recorded. Recording it
    # would invite a reader to treat "additional" as a modifier on the draw,
    # which is what it is *not* — the draw step's own card is a turn-based
    # action this ability neither performs nor replaces (CR 504.1).
    stream.accept_word("additional")
    stream.expect_word("card", "cards")
    # "draw a card **for each color among permanents you control**" (Chromatic
    # Orrery) — a multiplier over the count just read, in the trailing position
    # where "equal to" sits in front. Read here rather than as a wrapper around
    # the whole statement: a "for each" after a draw multiplies the cards, and
    # a production claiming it at statement level would take it away from the
    # mana clause and the counter placement that print it too.
    multiplier = _parse_draw_multiplier(stream)
    if multiplier is not None:
        # Only the plain "a card" spelling composes: "draw two cards for each …"
        # is a product this AST has no node for, and reading it as the
        # multiplier alone would halve the card's effect.
        if not (isinstance(count, ast.Fixed) and count.value == 1) or up_to:
            raise stream.error("a per-each draw multiplies one card")
        return ast.Draw(player, multiplier)
    return ast.Draw(player, count, up_to=up_to)


def _parse_draw_multiplier(stream: TokenStream) -> "ast.Amount | None":
    """``for each color among <objects>`` / ``for each <word> counter on <the
    source>`` after a draw, or None.

    Two quantities, and the words are what name each — the same way the
    where-clause tells "the number of" from "the greatest power among". A "for
    each <objects>" with neither an aggregate word nor a counter is a plain
    count and is *not* claimed here: the ordinary noun-phrase reading of it
    belongs to whatever production already handles a per-each, and adding a
    second reader is how the two come to disagree.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None
    # "…draws an additional card **for each growth counter on this
    # enchantment**." (Malignant Growth.) A count of the ability's own source
    # rather than of a set of objects, read through the same
    # `accept_counters_on_source` both spellings of "the number of <word>
    # counters on <the source>" already go through — so the counter word is
    # payload the whole way down and a card printing any other kind needs
    # nothing here.
    #
    # Before the colour aggregate below because the two cannot collide (a
    # counter word is not "color among"), and first because it is the reading
    # a bare word takes: the aggregate spells itself out.
    counters = accept_counters_on_source(stream)
    if counters is not None:
        return counters
    if not stream.accept_phrase("color", "among"):
        stream.reset(mark)
        return None
    try:
        return ast.ColorsAmong(parse_object_filter(stream))
    except GrammarError:
        stream.reset(mark)
        return None


def _parse_discard(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("discards", "discard")
    # "Discard your hand" (Chandra, Heart of Fire) — no count to read, and
    # `whole_hand` rather than a sentinel amount so "discard all cards" (a
    # wording no card prints) stays unparsed.
    # The possessive agrees with whoever is discarding — "discard **your**
    # hand" (Chandra, Heart of Fire), "that player discards **their** hand"
    # (Nicol Bolas) — so both spellings are one production. Which player it is
    # was read before this function was called; the pronoun only repeats them.
    if stream.accept_phrase("your", "hand") or stream.accept_phrase("their", "hand"):
        return ast.Discard(player, ast.AllOf(), whole_hand=True)
    # "discards **a third of the cards in their hand**" (Pox). The fraction's
    # noun is this production's own, so the head is read here and the quantity
    # built from the zone rather than handed to `parse_amount` — the same
    # arrangement `_parse_loses` makes for "half their life", and for its
    # reason: a quantity parser that swallowed "the cards in their hand" would
    # leave this production without the noun every other printing of the verb
    # ends on.
    fraction_mark = stream.mark()
    divisor = accept_fraction_head(stream)
    if divisor is not None and stream.accept_word("the"):
        if stream.accept_word("cards") and stream.accept_word("in"):
            if stream.accept_word("their", "your", "his"):
                stream.accept_phrase("or", "her")
                if stream.accept_word("hand"):
                    return ast.Discard(
                        player,
                        ast.Half(
                            ast.CountOf(
                                ast.ObjectFilter(
                                    is_card=True, zone="hand",
                                    zone_owner=ast.PlayerRef("target"),
                                )
                            ),
                            accept_rounding(stream),
                            divisor,
                        ),
                    )
    stream.reset(fraction_mark)
    # "Discard **up to** two cards" (Kinetic Augur). Read before the amount, and
    # recorded rather than consumed: a ceiling read as an exact count is a card
    # that forces its controller to pitch two cards they were offered the choice
    # of keeping.
    up_to = bool(stream.accept_phrase("up", "to"))
    count = parse_amount(stream)
    # "Discard a **creature** card" (Crypt Lurker). The noun parser reads the
    # whole phrase including its "card", so it is tried before the bare
    # template and reset when the phrase is just "card(s)". What the narrowing
    # may say is lowering's question, not this one: parsing it here and refusing
    # it there is how an unreadable phrase becomes a card reported unsupported
    # rather than a discard that quietly takes anything.
    # "Draw two cards, then discard one **of them**." (Krovikan Sorcerer.) The
    # cards the previous step drew, named by a pronoun rather than described —
    # so it is read before the noun-phrase branch below, which would refuse
    # "them" and take the whole line with it.
    if stream.accept_phrase("of", "them"):
        return ast.Discard(player, count, up_to=up_to, of_drawn=True)
    narrowed = None
    mark = stream.mark()
    try:
        candidate = parse_object_filter(stream)
    except GrammarError:
        candidate = None
    if candidate is not None and candidate.is_card and candidate != ast.ObjectFilter(is_card=True):
        narrowed = candidate
    else:
        stream.reset(mark)
        stream.expect_word("card", "cards")
    at_random = stream.accept_phrase("at", "random")
    return ast.Discard(player, count, at_random, up_to=up_to, filter=narrowed)


def _parse_mill(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    """``<player> mills <n> cards`` (CR 701.13a).

    The count is an ordinary amount rather than a digit, because the printed
    template spells small numbers out ("mills two cards") and Magic reprints it
    with every number there is.
    """
    stream.expect_word("mills", "mill")
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    repeated = _parse_mill_repeat_tail(stream, player, count)
    if repeated is not None:
        return repeated
    return ast.Mill(player, count)


def _parse_mill_repeat_tail(
    stream: TokenStream, player: ast.PlayerRef, count: "ast.Amount"
) -> "ast.Statement | None":
    """``, then repeats this process until <noun> or <n> cards have been put
    into their graveyard this way, whichever comes first`` (Helm of Obedience).

    Declines without consuming on anything else, so every ordinary mill keeps
    its own reading and its own refusal site.

    The mill in front of it must be **one** card. The whole point of the
    sentence is that the loop is asked after every single card, so a wording
    milling two at a time would step past its own stopping card - and that
    refuses loudly rather than being read as this loop.

    Every word of both stopping conditions is required, and "whichever comes
    first" is consumed and dropped because it states what two stopping
    conditions on one loop already mean. A card printing only one of them is a
    different loop, and this would rather refuse it than guess which half was
    meant.
    """
    mark = stream.mark()
    if not stream.accept_punct(","):
        return None
    if not stream.accept_word("then"):
        stream.reset(mark)
        return None
    if not stream.accept_word("repeats", "repeat"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "process", "until"):
        stream.reset(mark)
        return None
    if not (isinstance(count, ast.Fixed) and count.value == 1):
        raise stream.error("a repeated mill mills one card at a time")
    stream.accept_word("a", "an")
    filter_mark = stream.mark()
    try:
        stop_filter = parse_object_filter(stream)
    except GrammarError:
        stream.reset(filter_mark)
        raise stream.error("expected what the repeated mill stops on")
    if not stop_filter.is_card or not stop_filter.card_types:
        # The loop watches what is *put into a graveyard*, so the only thing it
        # can be told to stop on is a printed card type. A phrase the record
        # cannot answer refuses here rather than being dropped where it is
        # tested, which would be a loop that never stopped early.
        raise stream.error("a repeated mill stops on a printed card type")
    stream.expect_word("or")
    limit = parse_amount(stream)
    for word in (
        "cards", "have", "been", "put", "into", "their", "graveyard",
        "this", "way",
    ):
        stream.expect_word(word)
    stream.accept_punct(",")
    for word in ("whichever", "comes", "first"):
        stream.expect_word(word)
    return ast.MillUntil(player, stop_filter, limit)


def _parse_scry(stream: TokenStream) -> ast.Statement:
    """``Scry N`` (CR 701.22a).

    Unlike draw / discard / mill there is no trailing noun — the printed
    template is "Scry 3", never "scry 3 cards" — so the amount is the whole
    tail. An ``Amount`` rather than a digit because "Scry X" is printable and
    the amount parser already reads spelled-out numbers.
    """
    stream.expect_word("scry")
    count = parse_amount(stream)
    return ast.Scry(count)


def _parse_reveal_hand(
    stream: TokenStream, player: ast.PlayerRef
) -> ast.Statement | None:
    """``<player> reveals their hand [and <does something with it>]`` (CR 701.16).

    Amnesia ("…and discards all nonland cards") and Rag Man ("…and discards a
    creature card at random"). Two steps rather than one fused node, because
    that is what the sentence is: the reveal makes the hand public and the
    discard then happens out of it, and a card printing some other act after the
    reveal reuses this production instead of adding a second one.

    The conjunction is read here rather than left to the sentence loop because
    the sentence loop splits on full stops, not on "and" — and the second half
    prints no subject, so a reader that got it on its own would fail on
    "discards" with no player in front of it.

    Returns None without consuming when the words are not a hand reveal, so
    "reveals the top card of their library" keeps its own reading. Declining is
    what a production owes a phrase it cannot read: "reveals the top card of
    their library" and "reveals a card at random from their hand" are different
    effects over different zones, and a reader that took the verb and shrugged
    at its object would claim them and reveal the wrong pile.
    """
    mark = stream.mark()
    stream.expect_word("reveals", "reveal")
    # "…reveals **a card at random from their hand**." (Wand of Ith.) A
    # different act over the same zone: one card, chosen by nobody, and the
    # sentences behind it ask what it is. Read here because this is where the
    # verb is dispatched and because the two readings must not overlap — the
    # hand reveal below makes every card public and leaves no "it".
    random_from_hand = _parse_random_card_from_hand(stream, player)
    if random_from_hand is not None:
        return random_from_hand
    if not (
        (stream.accept_word("their") or stream.accept_word("your"))
        and stream.accept_word("hand")
    ):
        stream.reset(mark)
        return None
    if not stream.accept_word("and"):
        return ast.RevealHand(player)
    if stream.peek_word() in ("discards", "discard"):
        # The same player throughout: "and discards" has no subject of its own,
        # so handing the discard production anyone else would aim it at a seat
        # the sentence never named.
        return ast.Sequence((ast.RevealHand(player), _parse_discard(stream, player)))
    stream.reset(mark)
    return None


def _parse_play_with_hand_revealed(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.PlayWithHandRevealed | None":
    """``<player> play with their hand revealed <duration>`` (Stromgald Spy).

    CR 701.20a's reveal with a duration on it, and the duration is required:
    without one the sentence is Revelation's *static* ("Players play with their
    hands revealed"), which ``engine/revealed_hands.py`` claims off the printed
    line and this production must not take away from it. A production that
    parsed the line and left the lowering to raise would do exactly that —
    parsed-but-unlowered is still parsed, and the derivation tables are reached
    only where the grammar refuses in full.

    Refuses without consuming, so "plays" keeps every other reading it has.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    mark = stream.mark()
    if not stream.accept_word("play", "plays"):
        return None
    if not stream.accept_phrase("with", "their", "hand", "revealed"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind is None:
        stream.reset(mark)
        return None
    return ast.PlayWithHandRevealed(subject, duration)


def _parse_reveal_hand_and_choose(stream: TokenStream) -> ast.Statement | None:
    """``<player> reveals their hand. You choose a <filter> card from it.
    That player discards that card.`` (Duress.)

    Read whole, interior full stops included, because the three sentences share
    one revealed hand: split apart, the choice would be over a zone nobody
    revealed. Returns None quietly when the words are not this template, so an
    ordinary "reveals" keeps its own error.

    Every fixed word is expected. "You choose" is the *caster* choosing from
    someone else's hidden zone, which is the whole novelty here — a production
    that skipped it could not tell this from the victim choosing, and those are
    different cards.
    """
    mark = stream.mark()
    player = parse_player_ref(stream)
    if player is None or player.kind not in ("target_player", "target_opponent"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("reveals", "their", "hand"):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("you", "choose"):
        stream.reset(mark)
        return None
    chosen = parse_target_spec(stream)
    if chosen is None or chosen.quantifier != "a" or not chosen.filter.is_card:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("from", "it"):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    if stream.accept_phrase("that", "player", "discards", "that", "card"):
        return ast.RevealHandAndChoose(player, chosen.filter, fate="discard")
    # "Exile that card until this creature leaves the battlefield." (Kitesail
    # Freebooter.) The *whole* ending is expected, the duration included: a bare
    # "exile that card" is a permanent exile and a different card, and letting
    # the clause be absent would let it be deleted with no change to the parse.
    if stream.accept_phrase(
        "exile", "that", "card", "until", "this", "creature", "leaves",
        "the", "battlefield",
    ):
        return ast.RevealHandAndChoose(
            player, chosen.filter, fate="exile_until_source_leaves"
        )
    stream.reset(mark)
    return None
def parse_put_milled_card_onto_battlefield(
    stream: TokenStream,
) -> ast.Statement | None:
    """``Put one of them onto the battlefield under your control.`` (Helm of
    Obedience.)

    Declines without consuming on anything else, because "put" opens a dozen
    unrelated sentences and every one of them has a better refusal site than
    this production's.

    "Under your control" is required rather than defaulted: a card put onto the
    battlefield goes under its owner's control unless the effect says otherwise
    (CR 110.2a), and this one says otherwise about an **opponent's** card - so
    a wording without the clause would be a different effect that handed the
    creature back.
    """
    mark = stream.mark()
    if not stream.accept_phrase("put", "one", "of", "them", "onto"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("the", "battlefield", "under", "your", "control"):
        stream.reset(mark)
        return None
    return ast.PutMilledCardOntoBattlefield()


def _parse_cast_permission(stream: TokenStream) -> ast.Statement | None:
    """A sentence granting permission to cast or play from a zone the rules
    alone would not allow (CR 601.3) — see :class:`ast.CastPermission` for the
    printed forms. Returns None quietly on anything else, so "you may pay …"
    and the causative "you may have …" keep their own readings.

    The duration is read in both printed positions — a leading "Until end of
    turn," and a trailing "this turn" — because the two spellings scope the
    permission identically (CR 514.2 ends both at cleanup).
    """
    mark = stream.mark()
    until_eot = False
    next_upkeep = False
    if stream.at_word("until"):
        # Through the shared duration table, so the phrase this sentence may
        # open with is the same set of phrases every other effect reads — a
        # second literal here is how one family comes to accept a wording
        # another refuses. A kind the permission cannot *end* refuses the line
        # rather than being read as the nearest one it can.
        leading = _parse_duration(stream)
        if leading.kind == "until_end_of_turn":
            until_eot = True
        elif leading.kind == "until_your_next_upkeep":
            next_upkeep = True
        else:
            stream.reset(mark)
            return None
        stream.accept_punct(",")
    if not stream.accept_phrase("you", "may"):
        stream.reset(mark)
        return None
    if stream.accept_word("play"):
        mode = "play"
    elif stream.accept_word("cast"):
        mode = "cast"
    elif stream.accept_phrase("look", "at"):
        # "You may **look at** it for as long as it remains exiled." (Gustha's
        # Scepter.) The same CR 611.2a permission sentence about a different
        # verb: a card in exile face down is hidden from every player (CR
        # 406.3), so the permission to read one is an effect rather than a
        # courtesy. "at" is consumed here because the verb is two words; the
        # referent and the duration below are shared with the cast readings.
        mode = "look"
    else:
        stream.reset(mark)
        return None

    regrant = False
    while_exiled = False

    def _trailing_duration() -> bool:
        nonlocal until_eot, regrant, while_exiled
        # "…**for as long as it remains exiled**." (Ice Cauldron.) A duration
        # stated as a zone rather than as a moment in the turn, which is why it
        # is not in the shared duration table: that table is read by every
        # effect family and none of the others can end on where a card is.
        if stream.accept_phrase(
            "for", "as", "long", "as", "it", "remains", "exiled"
        ):
            while_exiled = True
            return True
        if stream.accept_phrase("this", "turn"):
            until_eot = True
        # "until you exile another card with this <permanent type>" (Furious
        # Rise). The noun is whatever the card is printed as, so it is consumed
        # as a word rather than matched against one spelling — an Artifact
        # printing the same sentence needs no second branch. Every token is
        # consumed or the phrase is not this one, because a half-read duration
        # would leave "with this enchantment" as unaccounted text and fail the
        # whole line.
        elif stream.accept_phrase("until", "you", "exile", "another", "card"):
            if not stream.accept_phrase("with", "this"):
                raise stream.error("expected 'with this <permanent>'")
            if stream.exhausted or stream.at_punct(".", ";"):
                raise stream.error("expected the permanent this sentence is on")
            stream.advance()
            regrant = True
        return True

    # "cards exiled this way" / "them" — both name the cards a step of this
    # same resolution exiled; lowering demands the producer.
    # "cards exiled this way" / "them" / "that card" — all name the cards a step
    # of this same resolution exiled; lowering demands the producer. The
    # singular is the same set with one member in it (Furious Rise exiles the
    # top card, so "that card" is the whole of what was exiled), which is why it
    # is a spelling here rather than a second ``what``.
    if (
        stream.accept_phrase("cards", "exiled", "this", "way")
        or stream.accept_word("them")
        or stream.accept_phrase("that", "card")
        # The bare pronoun, and only under "look at": a *cast* permission
        # naming "it" would claim any "you may cast it …" sentence in the pool,
        # where this verb has exactly one referent — the card the sentence
        # before it exiled.
        or (mode == "look" and stream.accept_word("it"))
    ):
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="exiled_this_way", until_end_of_turn=until_eot,
            until_source_grants_again=regrant,
            until_your_next_upkeep=next_upkeep,
            while_exiled=while_exiled,
        )
    # "spells from your hand without paying their mana costs" — a cost waiver.
    # The waiver clause is required: a bare "you may cast spells from your
    # hand" states the rules default and no card prints it.
    if stream.accept_phrase("spells", "from", "your", "hand"):
        if not stream.accept_phrase("without", "paying", "their", "mana", "costs"):
            stream.reset(mark)
            return None
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="spells_from_hand",
            until_end_of_turn=until_eot, free=True,
            until_your_next_upkeep=next_upkeep,
        )
    # "target red instant or sorcery card from your graveyard" — the noun
    # parser reads the zone and its owner onto the filter, and lowering
    # refuses any zone the cast path cannot open.
    spec = parse_target_spec(stream)
    if spec is not None and spec.quantifier == "target":
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="target_card", target=spec, until_end_of_turn=until_eot,
            until_your_next_upkeep=next_upkeep,
        )
    stream.reset(mark)
    return None


def _parse_choose_cards_in_hand(stream: TokenStream) -> "ast.ChooseCardsInHand | None":
    """``choose two cards in your hand drawn this turn`` (Sylvan Library).

    Refuses without consuming, so every other sentence opening with "choose"
    keeps the reading it already had.

    The noun phrase goes through the shared object parser, which is what makes
    "choose two **creature** cards in your hand" the same production; only the
    zone is required, because a pick out of anywhere else is a different
    sentence with different hidden-information rules (CR 400.2).
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        return None
    try:
        count = parse_amount(stream)
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not (filt.is_card and filt.zone == "hand"):
        stream.reset(mark)
        return None
    # "…**drawn this turn**". A provenance rather than a characteristic — see
    # ``ast.ChooseCardsInHand`` — so it rides the node, not the filter.
    drawn = bool(stream.accept_phrase("drawn", "this", "turn"))
    return ast.ChooseCardsInHand(count=count, filter=filt, drawn_this_turn=drawn)


def _parse_random_card_from_hand(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.RevealRandomFromHand | None":
    """``a card at random from their hand`` — the object of "reveals" for the
    random spelling (Wand of Ith).

    Split out of :func:`_parse_reveal_hand` rather than nested in it, because
    the two are different effects sharing one verb: this one names a single
    card nobody chose and leaves a record the sentences behind it read, and the
    hand reveal names every card and leaves none.
    """
    mark = stream.mark()
    if (
        stream.accept_phrase("a", "card", "at", "random", "from")
        and (stream.accept_word("their") or stream.accept_word("your"))
        and stream.accept_word("hand")
    ):
        return ast.RevealRandomFromHand(player)
    stream.reset(mark)
    return None


def _parse_discard_revealed_unless_pay_life(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.DiscardRevealedUnlessPayLife | None":
    """``<player> discards it unless they pay 1 life.``
    ``<player> discards it unless they pay life equal to its mana value.``
    (Wand of Ith.)

    "It" is the card the sentence in front of this one revealed, so the discard
    chooses nothing — which is what separates this from the ordinary discard
    the same verb otherwise reads, and why it is tried first.

    The payment is refused rather than skipped when it is neither of the two
    printed shapes: a cost nobody is charged is the discard happening
    unconditionally, which is the card without its clause.
    """
    mark = stream.mark()
    stream.expect_word("discards", "discard")
    if not (
        stream.accept_word("it")
        and stream.accept_word("unless")
        and stream.accept_word("they", "he", "she")
        and stream.accept_word("pay", "pays")
    ):
        stream.reset(mark)
        return None
    # "…pay **life equal to its mana value**": a number nothing knows until the
    # card is revealed, so it travels as the flag the handler resolves rather
    # than as an amount this parser could have counted.
    if stream.accept_phrase("life", "equal", "to", "its", "mana", "value"):
        return ast.DiscardRevealedUnlessPayLife(player, mana_value_of_revealed=True)
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("life"):
        stream.reset(mark)
        return None
    return ast.DiscardRevealedUnlessPayLife(player, amount=amount)


def _parse_for_each_revealed_discard(
    stream: TokenStream,
) -> "ast.DiscardRevealedMatchingUnlessPayLife | None":
    """``For each <filter> card revealed this way, <player> discards that card
    unless they pay <N> life.`` (Sirocco.)

    One production for the whole sentence rather than a general loop, for the
    reason :class:`ast.DiscardRevealedUnlessPayLife` is fused: the offer and its
    penalty are one prompt, and here they are one prompt *per card* out of a set
    the handler already holds. A ``ForEach`` around the singular node would have
    to bind "that card" for every turn of the loop, which nothing else in the
    pool asks for and which the offer's suspension would have to be resumable
    through.

    Every word is required and the whole thing refuses without consuming. The
    "this way" window is what makes the set the cards the *sentence in front*
    revealed rather than every card in a hand, and a production that dropped it
    would discard a hand the spell never showed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not (
        filt.is_card
        and stream.accept_phrase("revealed", "this", "way")
        and stream.accept_punct(",")
    ):
        stream.reset(mark)
        return None
    player = parse_player_ref(stream)
    if player is None:
        stream.reset(mark)
        return None
    if not stream.accept_word("discards", "discard"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_phrase("that", "card")
        and stream.accept_word("unless")
        and stream.accept_word("they", "he", "she")
        and stream.accept_word("pay", "pays")
    ):
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("life"):
        stream.reset(mark)
        return None
    return ast.DiscardRevealedMatchingUnlessPayLife(player, filt, amount)


def _parse_repeated_graveyard_pick(
    stream: TokenStream, who: ast.PlayerRef
) -> "ast.RepeatedGraveyardPick | None":
    """Forgotten Lore's whole four-sentence effect. The subject has already
    been read, so this starts at the verb.

    Refuses without consuming, so "chooses a card name…" (Petra Sphinx) and
    "chooses a creature…" (Takklemaggot) keep their own productions.

    Every word is required, the exclusion clause included: without it the loop
    would let one card be chosen forever, which is a different card — and the
    self-reference at the end of it is the lexer's SELF token, because the
    sentence names the spell by name.
    """
    mark = stream.mark()
    if not stream.accept_phrase("chooses", "a", "card", "in", "your", "graveyard"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("you", "may", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("if", "you", "do"):
        stream.reset(mark)
        return None
    # The comma is a token of its own to the lexer, so it is consumed on its
    # own rather than as a word inside the phrase.
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "repeat", "this", "process", "except", "that", "opponent", "can't",
        "choose", "a", "card", "already", "chosen", "for",
    ):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "then", "put", "the", "last", "chosen", "card", "into", "your", "hand"
    ):
        stream.reset(mark)
        return None
    return ast.RepeatedGraveyardPick(who, cost)
