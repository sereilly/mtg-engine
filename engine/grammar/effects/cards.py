"""Cards moving: drawing, discarding, milling, searching, and mana.

Draw / discard / mill share a shape — a player reference and a count — and are
one-liners for that reason. Library search carries the filter that decides what
may be found, and the mana productions read both "add {G}" and the
"that player adds" spelling a land's tapped-for-mana trigger uses.

Mana is here rather than in its own module because adding mana is what a card
*does* with a card or a permanent, and the payment fragment it shares with
"unless they pay" lives in `phrases` where both can reach it.
"""

from .. import ast
from ..amounts import parse_amount
from ..lexer import (MANA, render)
from ..nouns import (parse_object_filter, parse_player_ref)
from ..stream import TokenStream
from ..phrases import _parse_zone


def _parse_draw(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("draws", "draw")
    count = parse_amount(stream)
    stream.expect_word("card", "cards")
    return ast.Draw(player, count)


def _parse_discard(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    stream.expect_word("discards", "discard")
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

    # "Add one mana of any color" / "Add three mana of any one color".
    count = parse_amount(stream)
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
    """
    stream.expect_word("search")
    if not stream.accept_word("your"):
        raise stream.error("only searching your own library has a search flow")
    stream.expect_word("library")
    stream.expect_word("for")
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    # "reveal it," — honoured rather than dropped: the search flow's log names
    # the found card publicly ("searched library and put X into hand"), which
    # is what revealing one card means to this engine.
    if stream.accept_word("reveal"):
        stream.expect_word("it")
        stream.accept_punct(",")
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
    stream.accept_punct(",")
    stream.accept_word("then")
    stream.expect_word("shuffle")
    return ast.SearchLibrary(ast.PlayerRef("you"), filt, destination)
