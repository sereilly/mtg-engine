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
from ..amounts import parse_amount
from ..lexer import (MANA, render)
from ..nouns import (parse_object_filter, parse_player_ref, parse_target_spec)
from ..stream import TokenStream
from ..phrases import _parse_zone


def _parse_draw(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("draws", "draw")
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    return ast.Draw(player, count)


def _parse_discard(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("discards", "discard")
    # "Discard your hand" (Chandra, Heart of Fire) — no count to read, and
    # `whole_hand` rather than a sentinel amount so "discard all cards" (a
    # wording no card prints) stays unparsed.
    if stream.accept_phrase("your", "hand"):
        return ast.Discard(player, ast.AllOf(), whole_hand=True)
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    at_random = stream.accept_phrase("at", "random")
    return ast.Discard(player, count, at_random)


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
        return ast.AddMana(tuple(sorted(pips.items())), source_text=_clause())

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
        return ast.AddMana(((symbol, amount),), source_text=_clause())

    # "Add one mana of any color" / "Add three mana of any one color".
    stream.expect_word("mana")
    stream.expect_word("of")
    stream.accept_word("any")
    stream.accept_word("one")
    stream.expect_word("color")
    amount = count.value if isinstance(count, ast.Fixed) else 1
    return ast.AddMana((), any_color=amount, source_text=_clause())


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
    if not stream.accept_punct("."):
        raise stream.error("expected the sorting sentences after the reveal")
    if not stream.accept_word("if"):
        raise stream.error("expected \"If it's a …\" after the reveal")
    if not (stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is")):
        raise stream.error("expected \"it's\" after 'if'")
    stream.accept_word("a", "an")
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "into", "your", "hand"):
        raise stream.error("expected 'put it into your hand'")
    if not stream.accept_punct("."):
        raise stream.error("expected the 'Otherwise' sentence")
    stream.expect_word("otherwise")
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "it", "on", "the", "bottom", "of", "your", "library"):
        raise stream.error("expected 'put it on the bottom of your library'")
    return ast.RevealTopToHandOrBottom(filt)


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
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player whose hand is looked at")
    # The lexer splits "player's" into "player" + "'s"; the marker still has to
    # be consumed or the line fails full-token consumption.
    stream.expect_word("'s")
    stream.expect_word("hand")
    return ast.LookAtHand(player)


# Words that cannot be part of a card's name here because they start the next
# clause of the printed template. A name scan running past one of them would
# swallow "and/or a card named Igneous Cur" into the first name and report
# Alpine Houndmaster as a card that finds one card — so the scan stops, and the
# production then refuses the line at "put".
_SEARCHED_NAME_STOPS = ("reveal", "put", "then", "and", "or")


def _parse_searched_name(stream: TokenStream) -> str:
    """The card name in ``for a card named <name>``.

    Read token by token rather than as one word, because a legendary name
    carries the same punctuation the sentence does — "Chandra, Flame's
    Catalyst, reveal it," holds two commas and only the second ends the name. A
    comma is taken as part of the name only when a name word follows it, and
    the rendered text is compared through ``search_filters.name_key``, which
    ignores punctuation and case on both sides.
    """
    start = stream.mark()
    while not stream.exhausted:
        if stream.at_punct(".") or stream.at_word(*_SEARCHED_NAME_STOPS):
            break
        if stream.at_punct(","):
            mark = stream.mark()
            stream.advance()
            if stream.exhausted or stream.at_punct(".") or stream.at_word(*_SEARCHED_NAME_STOPS):
                stream.reset(mark)
                break
            continue
        stream.advance()
    if stream.mark() == start:
        raise stream.error("expected the name the search is for")
    return render(stream.tokens[start:stream.mark()])


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
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    filt = parse_object_filter(stream)
    # "a card named X" — the noun phrase stops at "named", so the name is read
    # here and put back on the filter, where every other restriction on what may
    # be found already lives and where `_restrictions_beyond` can see it.
    if stream.accept_word("named"):
        filt = dataclasses.replace(filt, named=_parse_searched_name(stream))
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
    return ast.SearchLibrary(ast.PlayerRef("you"), filt, destination, graveyard)


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

    def _trailing_duration() -> bool:
        nonlocal until_eot
        if stream.accept_phrase("this", "turn"):
            until_eot = True
        return True

    # "cards exiled this way" / "them" — both name the cards a step of this
    # same resolution exiled; lowering demands the producer.
    if stream.accept_phrase("cards", "exiled", "this", "way") or stream.accept_word("them"):
        _trailing_duration()
        return ast.CastPermission(
            mode=mode, what="exiled_this_way", until_end_of_turn=until_eot
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
