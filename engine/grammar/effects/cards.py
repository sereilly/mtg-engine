"""Cards moving: drawing, discarding, milling, searching, and mana.

Draw / discard / mill share a shape — a player reference and a count — and are
one-liners for that reason. Library search carries the filter that decides what
may be found, and the mana productions read both "add {G}" and the
"that player adds" spelling a land's tapped-for-mana trigger uses.

Mana is here rather than in its own module because adding mana is what a card
*does* with a card or a permanent, and the payment fragment it shares with
"unless they pay" lives in `phrases` where both can reach it.
"""

import dataclasses

from .. import ast
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..lexer import (MANA, render)
from ..nouns import (parse_object_filter, parse_player_ref, parse_target_spec)
from ..stream import TokenStream
from ..phrases import _parse_card_alternatives, _parse_zone


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
    count = parse_amount(stream)
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
        if not (isinstance(count, ast.Fixed) and count.value == 1):
            raise stream.error("a per-each draw multiplies one card")
        return ast.Draw(player, multiplier)
    return ast.Draw(player, count)


def _parse_draw_multiplier(stream: TokenStream) -> "ast.Amount | None":
    """``for each color among <objects>`` after a draw, or None.

    One aggregate today, and the words are what name it — the same way the
    where-clause tells "the number of" from "the greatest power among". A "for
    each <objects>" with no aggregate word is a plain count and is *not* claimed
    here: the ordinary noun-phrase reading of it belongs to whatever production
    already handles a per-each, and adding a second reader is how the two come
    to disagree.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each", "color", "among"):
        stream.reset(mark)
        return None
    try:
        return ast.ColorsAmong(parse_object_filter(stream))
    except GrammarError:
        stream.reset(mark)
        return None


def _parse_mana_multiplier(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``for each <objects>`` after a mana clause (Leafkin Avenger).

    A multiplier over the whole clause, read where the pips are so the two stay
    one statement: parsed apart, the count would be a sentence nothing performs
    and the mana would come out flat. Both pip spellings ask this, because
    "Add {G} for each …" and "Add two {G} for each …" differ only in how the
    symbols were written.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        return parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None


def _parse_discard(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("discards", "discard")
    # "Discard your hand" (Chandra, Heart of Fire) — no count to read, and
    # `whole_hand` rather than a sentinel amount so "discard all cards" (a
    # wording no card prints) stays unparsed.
    if stream.accept_phrase("your", "hand"):
        return ast.Discard(player, ast.AllOf(), whole_hand=True)
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
    return ast.Mill(player, count)


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


def _parse_add_mana(stream: TokenStream) -> ast.Statement:
    """``Add {G}`` / ``Add {C}{C}{C}`` / ``Add one mana of any color``."""
    start = stream.mark()
    stream.expect_word("add")

    def _clause() -> str:
        return render(stream.tokens[start:stream.pos])

    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
        # "{B} or {R}" — a dual land's choice, not two mana.
        if stream.at_word("or"):
            mark = stream.mark()
            stream.advance()
            if not stream.at_kind(MANA):
                stream.reset(mark)
                break
    if pips:
        return ast.AddMana(
            tuple(sorted(pips.items())),
            source_text=_clause(),
            per_each=_parse_mana_multiplier(stream),
        )

    count = parse_amount(stream)
    # "Add six {R}." (Chandra, Heart of Fire's −9) — a counted single symbol,
    # the same pips as "{R}{R}{R}{R}{R}{R}" spelled with a number word.
    if stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        amount = count.value if isinstance(count, ast.Fixed) else 0
        if amount <= 0:
            raise stream.error("expected a fixed number of mana symbols")
        return ast.AddMana(
            ((symbol, amount),),
            source_text=_clause(),
            per_each=_parse_mana_multiplier(stream),
        )

    # "Add one mana of any color" / "Add three mana of any one color".
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.accept_word("any")
    stream.accept_word("one")
    stream.expect_word("color")
    # "Add **X** mana of any one color" (Sanctum of Fruitful Harvest). The count
    # travels as the amount it was parsed as — it used to be forced to an int
    # here and a variable one refused, which was right while the handler read the
    # clause *text* and could only recognize the literal "one mana of any color".
    # The handler takes a number now, so any amount the enclosing sentence can
    # define is one it can add.
    return ast.AddMana((), any_color=count, source_text=_clause())


def _parse_player_adds_mana(
    stream: TokenStream, recipient: ast.PlayerRef
) -> ast.AddManaForTappedLand:
    """``<player> adds an additional {R}`` / ``<player> adds one mana of any type
    that land produced`` — the effect half of a triggered mana ability on a land
    being tapped (Gauntlet of Might, Mana Flare).

    Distinct from :func:`_parse_add_mana`, whose bare "Add {G}" always means the
    ability's own controller. Here the subject is a *player reference* bound by
    the trigger, so the mana can land in someone else's pool, and "any type that
    land produced" names a quantity no pip list can express.
    """
    stream.expect_word("adds", "add")
    additional = bool(stream.accept_phrase("an", "additional"))

    pips: dict[str, int] = {}
    while stream.at_kind(MANA):
        token = stream.next()
        symbol = token.text.strip("{}")
        if symbol.isdigit() or symbol in ("T", "Q", "X"):
            raise stream.error(f"unsupported mana symbol {token.text!r}")
        pips[symbol] = pips.get(symbol, 0) + 1
    if pips:
        return ast.AddManaForTappedLand(
            recipient, pips=tuple(sorted(pips.items())), additional=additional
        )

    # "one mana of any type that land produced". Every word is read: "any type
    # **that land** produced" is what ties the mana to the land the trigger
    # names, and a production that skipped the tail would read the same as an
    # unrestricted "one mana of any type" — a strictly larger effect.
    count = parse_amount(stream)
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.expect_word("any")
    stream.expect_word("type")
    if not stream.accept_phrase("that", "land", "produced"):
        raise stream.error("expected 'that land produced'")
    amount = count.value if isinstance(count, ast.Fixed) else 0
    if amount <= 0:
        raise stream.error("expected a fixed amount of mana")
    return ast.AddManaForTappedLand(
        recipient, of_type_produced=amount, additional=additional
    )


def _parse_reveal_top(stream: TokenStream) -> ast.Statement:
    """``Reveal the top card of your library. If it's a <filter>, put it into
    your hand. Otherwise, put it on the bottom of your library.`` (Garruk,
    Savage Herald.)

    One production for the whole three-sentence template, interior full stops
    included: the sentences all describe one revealed card, so parsed apart
    two of them dangle a referent nothing binds. Every word of both
    destinations is required — hand-or-bottom is the effect, and a wording
    that sorted elsewhere would be a different card wearing this one's head.
    """
    stream.expect_word("reveal")
    for word in ("the", "top", "card", "of", "your", "library"):
        stream.expect_word(word)
    # "Scry 3, then reveal the top card of your library. If it's a creature or
    # land card, draw a card." (Track Down.) The reveal is the whole sentence
    # and what follows it is an ordinary conditional, so the bare node is
    # returned and the sentence loop reads the rest. Tried by *falling back*
    # rather than by looking ahead: Garruk's three-sentence template is checked
    # first and keeps every word it requires, so a line that matches it is
    # unaffected, and a line that does not gets a node instead of a refusal.
    mark = stream.mark()
    if not stream.accept_punct("."):
        return ast.RevealTop()
    if not stream.accept_word("if"):
        stream.reset(mark)
        return ast.RevealTop()
    if not (stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is")):
        stream.reset(mark)
        return ast.RevealTop()
    stream.accept_word("a", "an")
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "into", "your", "hand"):
        # The conditional is somebody else's ("…, draw a card"). Hand the whole
        # thing back and let the sentence loop read it as the two statements it
        # is.
        stream.reset(mark)
        return ast.RevealTop()
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
        for word in ("cards", "of", "your", "library"):
            stream.expect_word(word)
        if not stream.accept_punct("."):
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
        for word in (
            "put", "one", "of", "those", "cards", "into", "your", "hand",
            "and", "the", "rest", "on", "the", "bottom", "of", "your",
            "library", "in", "any", "order",
        ):
            stream.expect_word(word)
        if not stream.accept_punct("."):
            raise stream.error("expected the cast-zone sentence after the sort")
        for word in (
            "if", "this", "spell", "was", "cast", "from", "anywhere",
            "other", "than", "your", "hand",
        ):
            stream.expect_word(word)
        stream.accept_punct(",")
        for word in ("put", "each", "of", "those", "cards", "into", "your", "hand", "instead"):
            stream.expect_word(word)
        return ast.LookTopPickToHand(count, all_to_hand_if_cast_elsewhere=True)
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player whose hand is looked at")
    # The lexer splits "player's" into "player" + "'s"; the marker still has to
    # be consumed or the line fails full-token consumption.
    stream.expect_word("'s")
    stream.expect_word("hand")
    return ast.LookAtHand(player)


def _parse_search_library(stream: TokenStream) -> ast.Statement:
    """``Search your library for a <object>, put that card into your hand, then
    shuffle.`` (Demonic Tutor, CR 701.19.)

    Three parts are read rather than skipped, because each one names a
    different effect:

    * **whose library** — the engine's search flow only ever opens the
      searcher's own library, so "search target player's library" is a
      different card, not a wording of this one;
    * **where the found card goes** — onto the battlefield or on top of the
      library are other effects entirely, and the destination is parsed as an
      ordinary zone so lowering can compare it against the one the flow
      implements;
    * **the shuffle** — ``confirm_search_library`` shuffles as it moves the
      card, so it is part of this effect rather than a step of its own. It is
      required, so deleting the word makes the line fail to parse instead of
      quietly claiming a search that never shuffles.

    Singular by construction: the article is *expected* rather than a general
    quantity being parsed. :class:`ast.SearchLibrary` has no count field and
    the confirm flow moves exactly one card, so "search your library for two
    cards" must fail here rather than silently find one.

    The two-zone spelling ("search your library and/or graveyard … If you
    search your library this way, shuffle.") is the same effect with a second
    zone and a shuffle conditional on which one was searched, so it is branches
    of this production rather than a second one: the destination, the reveal
    and the name are read the same way in both.
    """
    stream.expect_word("search")
    if not stream.accept_word("your"):
        raise stream.error("only searching your own library has a search flow")
    # "Search your graveyard and library for any number of <filter> cards,
    # exile them, then shuffle." (Chandra, Heart of Fire's −9.) A different
    # effect, not a wording of the tutor below: any number rather than one,
    # exile rather than the hand, and both zones always. Branching on the
    # first zone word keeps the two shapes from claiming each other.
    if stream.accept_word("graveyard"):
        stream.expect_word("and")
        stream.expect_word("library")
        stream.expect_word("for")
        if not stream.accept_phrase("any", "number", "of"):
            raise stream.error("a two-zone search finds any number of cards")
        filt = parse_object_filter(stream)
        stream.accept_punct(",")
        if not stream.accept_phrase("exile", "them"):
            raise stream.error("expected 'exile them' after the searched cards")
        stream.accept_punct(",")
        stream.accept_word("then")
        stream.expect_word("shuffle")
        return ast.SearchAndExile(filt)
    stream.expect_word("library")
    # "and/or graveyard" — a second zone, read here so lowering can arm the
    # search over both. The lexer splits "and/or" into two words.
    graveyard = bool(stream.accept_phrase("and", "or", "graveyard"))
    stream.expect_word("for")
    # "…for **up to two** basic land cards, reveal those cards, put one onto the
    # battlefield tapped and the other into your hand" (Cultivate). A counted
    # search, read here so the count and the destinations are parsed together —
    # they are the same fact, one entry per find.
    if stream.accept_phrase("up", "to", "two"):
        return _parse_two_card_search(stream, graveyard)
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    # "a card named X" is read by the noun parser, like every other restriction
    # on what may be found — `_restrictions_beyond` sees it on the filter.
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    # "reveal it," — honoured rather than dropped: the search flow's log names
    # the found card publicly ("searched library and put X into hand"), which
    # is what revealing one card means to this engine.
    if stream.accept_word("reveal"):
        stream.expect_word("it")
        stream.accept_punct(",")
    # ", and put it into your hand" — the conjunction is the graveyard
    # template's punctuation, not a second effect: "put" must follow either way.
    stream.accept_word("and")
    stream.expect_word("put")
    # "put that card into your hand" / "put it into your hand" — one referent,
    # two printed spellings.
    if not stream.accept_word("it"):
        stream.expect_word("that")
        stream.expect_word("card")
    # "into your hand" / "onto the battlefield" — both prepositions are read so
    # the destination reaches lowering, which refuses the ones no flow
    # implements *by name*. Refusing here instead would report the card as an
    # unparsed search rather than an unimplemented destination.
    stream.expect_word("into", "onto")
    destination = _parse_zone(stream)
    # "…put it onto the battlefield **tapped**" (Fabled Passage). The two-card
    # search has read this word since Cultivate; the single-find spelling had
    # nowhere to put it and so failed the line on the word after the zone. Same
    # field, one entry — how a find enters is part of where it goes.
    tapped = bool(stream.accept_word("tapped"))
    if graveyard:
        # "…into your hand. If you search your library this way, shuffle."
        # A printed sentence break, but not a second effect: the shuffle is the
        # tail of *this* search, conditional only because the graveyard half
        # shuffles nothing. Consuming it here — interior full stop and all —
        # keeps it attached to the effect that performs it; left to the
        # sequence parser it would be a statement no production implements and
        # the whole line would refuse. The final full stop is deliberately left
        # for the sequence parser, which is what ends the line.
        if not stream.accept_punct("."):
            raise stream.error("expected the conditional shuffle sentence")
        if not stream.accept_phrase("if", "you", "search", "your", "library", "this", "way"):
            raise stream.error("expected 'If you search your library this way'")
        stream.accept_punct(",")
        stream.expect_word("shuffle")
    else:
        stream.accept_punct(",")
        stream.accept_word("then")
        stream.expect_word("shuffle")
    condition, counted = _parse_search_untap_rider(stream)
    return ast.SearchLibrary(
        ast.PlayerRef("you"), filt, destination, graveyard, tapped=(tapped,),
        untap_found_if=condition, untap_found_filter=counted,
    )


def _parse_search_untap_rider(stream: TokenStream):
    """``Then if you control <n> or more <objects>, untap that <noun>.``
    (Fabled Passage.) Returns (comparison, counted filter), or (None, None).

    Read as a rider on the search rather than as the next sentence, because
    "that land" is the card the search just found: the search arms a prompt and
    resolves when the player answers it, so a following statement would run with
    nothing chosen yet. Consuming the interior full stop here is the same move
    the conditional-shuffle tail above makes, for the same reason.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None, None
    if not stream.accept_phrase("then", "if", "you", "control"):
        stream.reset(mark)
        return None, None
    amount = parse_amount(stream)
    if not isinstance(amount, ast.Fixed) or not stream.accept_phrase("or", "more"):
        stream.reset(mark)
        return None, None
    try:
        counted = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None, None
    stream.accept_punct(",")
    if not stream.accept_word("untap"):
        stream.reset(mark)
        return None, None
    # "untap **that land**" — the referent is the found card, and the noun has
    # to agree with what was searched for. Read and required rather than
    # skipped: a card saying "untap that creature" after a land search is a
    # different sentence, and consuming the words without checking them is how a
    # rider gets silently repointed.
    if not stream.accept_word("that"):
        stream.reset(mark)
        return None, None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None, None
    stream.advance()
    return ast.Comparison("ge", amount), counted


def _parse_two_card_search(stream: TokenStream, graveyard: bool) -> ast.Statement:
    """The tail of ``Search your library for up to two <filter>, reveal those
    cards, put one <zone> and the other <zone>, then shuffle.`` (Cultivate.)

    Split from the singular production rather than branched inside it, because
    every clause after the count is *different*: "those cards" not "it", two
    destinations joined by "and the other", and an entry state on the first.
    Sharing the code would mean a chain of `if two:` through a production whose
    whole job is to read one shape.

    Both destinations are required. A card that puts one somewhere and says
    nothing about the second find is a different effect, and defaulting the
    second to the first is how a search silently puts two lands on the
    battlefield.
    """
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    # "reveal those cards," — the plural of the singular production's "reveal
    # it", and honoured the same way: the search log names what was found.
    if stream.accept_word("reveal"):
        if not stream.accept_phrase("those", "cards"):
            raise stream.error("expected 'those cards' after the plural reveal")
        stream.accept_punct(",")
    stream.expect_word("put")
    stream.expect_word("one")
    stream.expect_word("into", "onto")
    first = _parse_zone(stream)
    first_tapped = bool(stream.accept_word("tapped"))
    if not stream.accept_phrase("and", "the", "other"):
        raise stream.error("expected 'and the other' before the second destination")
    stream.expect_word("into", "onto")
    second = _parse_zone(stream)
    second_tapped = bool(stream.accept_word("tapped"))
    stream.accept_punct(",")
    stream.accept_word("then")
    stream.expect_word("shuffle")
    return ast.SearchLibrary(
        ast.PlayerRef("you"), filt, first, graveyard,
        extra_destinations=(second,),
        tapped=(first_tapped, second_tapped),
        up_to=True,
    )


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


def _parse_exile_graveyard(stream: TokenStream) -> ast.Statement | None:
    """``Exile target player's graveyard.`` (Tormod's Crypt.)

    Returns None quietly on anything else, so the ordinary permanent exile keeps
    its own errors. The possessive and the zone noun are both expected: "exile
    target player" is not a sentence, and consuming the player and stopping
    would leave a production that exiles whatever the next reader assumes.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    player = parse_player_ref(stream)
    if (
        isinstance(player, ast.PlayerRef)
        and player.kind in ("target_player", "target_opponent")
        and stream.accept_word("'s")
        and stream.accept_word("graveyard")
    ):
        return ast.ExileGraveyard(player)
    stream.reset(mark)
    return None


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
    return ast.ExileTopOfLibrary(count)


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
    if stream.at_word("until"):
        if not stream.accept_phrase("until", "end", "of", "turn"):
            return None
        stream.accept_punct(",")
        until_eot = True
    if not stream.accept_phrase("you", "may"):
        stream.reset(mark)
        return None
    if stream.accept_word("play"):
        mode = "play"
    elif stream.accept_word("cast"):
        mode = "cast"
    else:
        stream.reset(mark)
        return None

    regrant = False

    def _trailing_duration() -> bool:
        nonlocal until_eot, regrant
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
    ):
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="exiled_this_way", until_end_of_turn=until_eot,
            until_source_grants_again=regrant,
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
        )
    # "target red instant or sorcery card from your graveyard" — the noun
    # parser reads the zone and its owner onto the filter, and lowering
    # refuses any zone the cast path cannot open.
    spec = parse_target_spec(stream)
    if spec is not None and spec.quantifier == "target":
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="target_card", target=spec, until_end_of_turn=until_eot
        )
    stream.reset(mark)
    return None
