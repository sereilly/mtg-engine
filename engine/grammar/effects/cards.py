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


import dataclasses

from .. import ast
from ..amounts import accept_fraction_head, accept_rounding, parse_amount, parse_equal_to
from ..records import (accept_as_many_as, parse_for_each_revealed_this_way,
                       parse_for_each_sacrificed_this_way)

from ..amounts import accept_counters_on_source
from ..errors import GrammarError
from ..distinct import accept_one_of_each, parse_counted_objects
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..durations import _parse_duration
from ..phrases import (accept_a_card_at_random_from_hand,
                       _parse_mana_payment)
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
    # "Draw a card **for each permanent sacrificed this way**." (Reprocess.)
    # A count off what the sentence in front of this one took, which no reading
    # of the board can answer: "any number" prints no count and the permanents
    # are gone by now (CR 400.7). Read through the one production that owns the
    # phrase, and *before* "for each" is consumed, so the clause is claimed or
    # refused whole.
    #
    # First, because the plain noun-phrase reading below would consume the noun
    # and leave "sacrificed this way" as unconsumed text — the phrase claimed
    # for a count of the whole battlefield, which is a strictly larger number
    # than the card prints.
    sacrificed = parse_for_each_sacrificed_this_way(stream, parse_object_filter)
    if sacrificed is not None:
        return sacrificed
    # "Target opponent reveals their hand. You draw a card **for each Mountain
    # and red card in it**." (Baleful Stare.) The same clause one record over —
    # the cards a hand reveal in front of this sentence showed — through the
    # reader the damage sentence already asks (Blood Oath), and first for the
    # reason above: the plain reading would count a battlefield.
    revealed = parse_for_each_revealed_this_way(stream, parse_object_filter)
    if revealed is not None:
        return revealed
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
    if stream.accept_phrase("color", "among"):
        try:
            return ast.ColorsAmong(parse_object_filter(stream))
        except GrammarError:
            stream.reset(mark)
            return None
    # "Each player draws a card **for each creature card in their graveyard**."
    # (Nature's Resurgence.) A plain count of a set, which is the same quantity
    # "draw cards **equal to** the number of …" puts in front of the noun
    # — so it produces the `CountOf` that spelling already produces and travels
    # the one count spec every computed number in this engine travels on.
    #
    # The docstring above said this reading belonged "to whatever production
    # already handles a per-each". For a draw there is no such production: the
    # statement ends here, so an unclaimed "for each" was unconsumed text and
    # the card was refused. Claiming it is therefore not a second reader of one
    # phrase — it is the only one.
    #
    # "…that died this turn" / "…that died this way" are histories rather than
    # sets and belong to `phrases._parse_for_each`; a relative clause left
    # behind here would be unconsumed text with the count already claimed, so
    # the whole clause is handed back, exactly as `_parse_per_each_objects`
    # hands it back one module over.
    try:
        counted = parse_counted_objects(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if stream.at_word("that"):
        stream.reset(mark)
        return None
    return ast.CountOf(counted)


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
    # "…that player discards **all the cards in their hand**, then draws that
    # many cards." (Shocker.) The long spelling of the two words above — every
    # card goes and nobody chooses — so it is a branch here rather than a
    # counted discard of "all", which is the *narrowed* sweep further down and
    # arms no prompt for a hand it has already emptied. The possessive agrees
    # with the sentence's subject, exactly as the short spelling's does.
    long_hand = stream.mark()
    if stream.accept_word("all") and stream.accept_phrase("the", "cards", "in"):
        if stream.accept_word("their", "your") and stream.accept_word("hand"):
            return ast.Discard(player, ast.AllOf(), whole_hand=True)
    stream.reset(long_hand)
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
    # "Then that player discards **another** card at random …" (Flay.) One
    # more card, written as a comparison with the discard the sentence in front
    # already made — the reading `_parse_gets` gives Sabertooth Cobra's
    # "another poison counter". Not a narrowing: the first card has left the
    # hand, so every card still in it is "another" one.
    count = (
        ast.Fixed(1) if not up_to and stream.accept_word("another")
        else parse_amount(stream)
    )
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
    """``<player> mills <n> cards`` (CR 701.17a).

    The count is an ordinary amount rather than a digit, because the printed
    template spells small numbers out ("mills two cards") and Magic reprints it
    with every number there is.
    """
    stream.expect_word("mills", "mill")
    # "mills **cards equal to** the sacrificed creature's power" (Altar of
    # Dementia) puts the noun in front of the count, where every other mill
    # puts it behind — the same two spellings ``_parse_draw`` above reads, and
    # read the same way: first, and reset if the words turn out to be an
    # ordinary "mills two cards", because "cards" cannot start a number so
    # nothing has been skipped.
    equal_mark = stream.mark()
    if stream.accept_word("cards"):
        counted = parse_equal_to(stream)
        if counted is not None:
            return ast.Mill(player, counted)
        stream.reset(equal_mark)
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
    """``<player> reveals their hand [and <does something with it>]`` (CR 701.20).

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
    # "…reveals their hand**, chooses one card of each color from it, then
    # discards all other nonland cards**." (Noxious Vapors.) The third act this
    # reader carries, joined by a comma where the two below are joined by
    # "and" — and the same subject throughout, for the discard's reason.
    kept = _accept_keep_then_discard_rest(stream, player)
    if kept is not None:
        return ast.Sequence((ast.RevealHand(player), kept))
    before_and = stream.mark()
    if not stream.accept_word("and"):
        return ast.RevealHand(player)
    if stream.peek_word() in ("discards", "discard"):
        # The same player throughout: "and discards" has no subject of its own,
        # so handing the discard production anyone else would aim it at a seat
        # the sentence never named.
        return ast.Sequence((ast.RevealHand(player), _parse_discard(stream, player)))
    # "…reveal your hand **and put all land cards from it onto the
    # battlefield**." (Manabond.) The second act this production's own
    # docstring promised: a card printing something other than a discard after
    # the reveal reuses this reader rather than adding a second one, and the
    # subject is carried the way the discard's is.
    emptied = _accept_put_revealed_hand_cards(stream, player)
    if emptied is not None:
        return ast.Sequence((ast.RevealHand(player), emptied))
    # "…that player reveals their hand **and Darigaaz deals damage to the
    # player** equal to …" (Darigaaz, the Igniter.) What follows the "and" has a
    # subject of its own, so it is not a second act of this player's and not
    # this production's to read: the reveal is whole, and the conjunction is
    # handed back to the sentence joiner, which already reads "<clause> and
    # <clause>". Declining the whole reveal here — what this did — left a
    # sentence the joiner reads perfectly well refused at its first verb.
    stream.reset(before_and)
    return ast.RevealHand(player)


def _accept_keep_then_discard_rest(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.KeepChosenDiscardRest | None":
    """``, chooses one <card> of each <characteristic> from it, then discards
    all other <cards>`` — or None with nothing consumed. (Noxious Vapors.)

    One reader and one node for both verbs, because "all **other**" is a
    complement of the choice in front of it (see the node). Every word is
    required: "from it" is what says the picks come out of the revealed hand,
    and "all other" is what says the discard spares them — a reader that let
    either be absent would discard the cards the sentence kept.

    Only the abbreviated keep is read. "Chooses a creature card and an
    artifact card from it, then discards all other cards" is the same node
    with a printed list, and no card prints it; when one does, the list goes
    where ``effects/board._accept_keep_slots`` reads Cataclysm's.
    """
    mark = stream.mark()
    if not (
        stream.accept_punct(",")
        and stream.accept_word("chooses", "choose")
        and stream.accept_word("one")
    ):
        stream.reset(mark)
        return None
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    keeps = accept_one_of_each(stream, described, keeps=True)
    if not keeps or not described.is_card or not stream.accept_phrase("from", "it"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_punct(",")
        and stream.accept_word("then")
        and stream.accept_word("discards", "discard")
        and stream.accept_phrase("all", "other")
    ):
        stream.reset(mark)
        return None
    try:
        rest = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not rest.is_card:
        stream.reset(mark)
        return None
    return ast.KeepChosenDiscardRest(player, keeps, rest)


def _accept_put_revealed_hand_cards(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.PutOntoBattlefield | None":
    """``put all <card phrase> from it onto the battlefield`` at the cursor —
    or None with the cursor where it was. (Manabond.)

    **"It" is the hand this same sentence has just revealed**, which is why the
    phrase is read here and not by the shared noun parser: that parser reads a
    zone from a zone *noun* ("from your hand"), and teaching it the pronoun
    would hand the word to every line in the game that prints it. Duress'
    three-sentence template makes the same binding for the same reason ("you
    choose a … card **from it**"), and the two are the only readings of the
    word this package has.

    The noun phrase is data, so a card printing "all creature cards from it" is
    the same production; the count is not, because "all" is the whole
    difference between emptying a hand and picking out of it. Anything else
    rewinds whole — a tail half-read here would leave the reveal claiming a
    sentence it does not carry out.
    """
    mark = stream.mark()
    if not stream.accept_word("put", "puts"):
        return None
    try:
        moved = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if (
        not isinstance(moved, ast.TargetSpec)
        or moved.quantifier != "all"
        or not moved.filter.is_card
        # A phrase that named its own zone is not this sentence: "from it" is
        # the binding, and a spec arriving with a zone already on it would be
        # two answers to one question. The *owner* is what says so — the noun
        # parser leaves ``zone`` at its "battlefield" default for a phrase that
        # printed none, and only a printed "from <somebody>'s <pile>" fills the
        # possessive in.
        or moved.filter.zone_owner is not None
        or moved.filter.zone not in (None, "battlefield")
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("from", "it", "onto", "the", "battlefield"):
        stream.reset(mark)
        return None
    return ast.PutOntoBattlefield(
        dataclasses.replace(
            moved,
            filter=dataclasses.replace(
                moved.filter, zone="hand", zone_owner=player,
            ),
        ),
    )


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
    # "…reveals their hand**, then** you choose a card…" (Lobotomy) is the same
    # two sentences with the weaker join. English writes one clause either way
    # and the referent is identical — "it" is the hand this sentence revealed —
    # so it is two accepted tokens here rather than a second production, which
    # would race this one for the word "reveals".
    #
    # "…reveals their hand **and** you choose a card of that color from it."
    # (Addle.) The third join, and the same clause again.
    if not stream.accept_punct("."):
        if stream.accept_punct(","):
            stream.accept_word("then")
        else:
            stream.accept_word("and")
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
    # Marked before the full stop, because the ending may not be this
    # production's — see the fall-through below.
    tail = stream.mark()
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
    # "You choose an instant or sorcery card from it **and exile that card**."
    # (Psychic Theft.) A plain exile; what becomes of the card is the next
    # sentences' business, which read the `exiled_cards` record it leaves.
    if stream.accept_phrase("and", "exile", "that", "card"):
        return ast.RevealHandAndChoose(player, chosen.filter, fate="exile")
    # **No ending at all** (Lobotomy): the sentence stops at "from it" and what
    # the pick was *for* is the next printed sentence, which reads the name this
    # one recorded. So the production stops too, and the sequence parser reads
    # the rest — which is the decomposition this family's own docstring asks
    # for ("the lowering carries the bounds of the choice and nothing else").
    #
    # Read last, so both endings above keep every word they require: a card
    # printing one of them cannot fall through to this and leave its own last
    # sentence to a production that has no reading for it.
    #
    # The full stop is **handed back**: the sentence loop in ``parser.py``
    # requires the cursor to be sitting on it after every statement, so a
    # production that consumed one and then stopped fails the line at
    # "unconsumed text" — which is what this did until the mark above.
    #
    # Unconditional, and safe because of how much is already matched: a
    # targeted player, "reveals their hand", the join, "you choose", a card
    # noun phrase and "from it" is a sentence nothing else in the pool prints —
    # Rag Man and Amnesia stop at the reveal and fail this production on "you",
    # and Mind Warp opens on "look at".
    stream.reset(tail)
    return ast.RevealHandAndChoose(player, chosen.filter, fate="name")


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
    """``<player> reveals a card at random from their hand`` (Wand of Ith).

    Split out of :func:`_parse_reveal_hand` rather than nested in it, because
    the two are different effects sharing one verb: this one names a single
    card nobody chose and leaves a record the sentences behind it read, and the
    hand reveal names every card and leaves none.
    """
    if accept_a_card_at_random_from_hand(stream):
        return ast.RevealRandomFromHand(player)
    return None


def parse_exile_random_card_from_hand(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.ExileRandomFromHand | None":
    """``<player> exiles a card at random from their hand`` (Elkin Lair).

    The verb is consumed here rather than by the caller, so a refusal leaves the
    stream where it found it — "that player exiles all cards from their library"
    is read by the production beside this one and must keep its own words.
    """
    mark = stream.mark()
    stream.expect_word("exiles", "exile")
    if accept_a_card_at_random_from_hand(stream):
        return ast.ExileRandomFromHand(player)
    stream.reset(mark)
    return None


def parse_player_exiles_cards_from_hand(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.ExileCardsFromHand | None":
    """``<player> exiles <N> cards from their hand`` (Mind Swords: "Each player
    exiles two cards from their hand.")

    The random exile above with the player choosing, so it is tried after that
    one — "a card **at random**" is the narrower reading and must keep its
    words — and after the pile reader, whose "all cards from their hand"
    (Memory Jar) is no count at all. The noun phrase goes through the shared object parser, which is what
    makes "two **nonland** cards" the same production; the zone is required,
    and the hand must be the subject's own ("their" under a seat subject, "your"
    under "you"), because a pick out of somebody else's hand is a different
    sentence with different hidden-information rules (CR 400.2).

    Refuses without consuming, so "that player exiles all cards from their
    library" and the graveyard sweep beside it keep their own readers.
    """
    mark = stream.mark()
    stream.expect_word("exiles", "exile")
    try:
        count = parse_amount(stream)
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    owner = filt.zone_owner
    if not (
        # A printed number: "**all** cards from their hand" is a pile, which
        # ``_parse_player_exiles_pile`` reads with its own handler.
        isinstance(count, ast.Fixed)
        and filt.is_card
        and filt.zone == "hand"
        and owner is not None
        and (owner.kind == "owner" or owner.kind == player.kind == "you")
    ):
        stream.reset(mark)
        return None
    return ast.ExileCardsFromHand(player, count, filt)


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
