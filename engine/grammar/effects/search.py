"""Searching a library (CR 701.23) — every printed shape of the tutor.

Split out of ``effects/library.py`` at the thousand-line guard, along the
boundary that module's own docstring drew when it named its contents "search,
look-at, and the library's top". The three are different questions asked of the
same hidden zone: a *look* shows a fixed number of cards off the top and the
pile is otherwise untouched, where a **search** is CR 701.23's shuffle-ending
walk of the whole library for a card the sentence describes — the caller reads a
filter, a destination, a reveal and a shuffle, and none of that vocabulary
appears anywhere else in the family.

The cut is where the call graph already fell apart: ``_parse_search_library`` is
the only name outside this module that anything reaches for, and the three
productions behind it (the other player's library, the untap rider, the counted
two-destination form) are called from here and nowhere else. Nothing left in
``library`` calls anything here, and nothing here calls anything there.

**Asymmetric, and the mirror image of the asymmetry this package usually
records.** The lowering side has no ``search`` family: ``lowering/library.py``
holds the search lowering beside the look-at lowering and is nowhere near the
cap, because a tutor lowers to one ``search_library`` instruction however
elaborately its sentence is printed. The words are where the work is. A
near-empty ``lowering/search.py`` would buy back the symmetry and cost the
thing symmetry is for.
"""



import dataclasses
from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref
from ..stream import TokenStream
from ..phrases import _parse_zone



def _parse_search_library(stream: TokenStream) -> ast.Statement:
    """``Search your library for a <object>, put that card into your hand, then
    shuffle.`` (Demonic Tutor, CR 701.23.)

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
        # "Search **target player's** library …" (Jester's Cap) — a different
        # effect, as the paragraph above says, so a different node rather than
        # a branch widening this one. Read from here and not as a production of
        # its own, so the word "search" keeps one entry point: two productions
        # racing for it would make which reading a card gets depend on their
        # order.
        return _parse_search_other_library(stream)
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
    # battlefield tapped and the other into your hand" (Cultivate), and "…for
    # **up to three** basic land cards, reveal them, put them into your hand"
    # (Land Tax). A counted search, read here so the count and the destinations
    # are parsed together — they are the same fact, one entry per find, and a
    # count read without them is a search that finds three and places one.
    if stream.accept_phrase("up", "to"):
        count = parse_amount(stream)
        if not isinstance(count, ast.Fixed) or count.value < 1:
            raise stream.error("expected how many cards the search may find")
        return _parse_counted_search(stream, graveyard, count.value)
    # "Search your library for **three cards, exile them, then shuffle**."
    # (Foresight.) A counted search whose finds are exiled rather than placed,
    # which is `SearchAndExile`'s shape with a printed ceiling — the two-zone
    # spelling above reaches the same node with "any number of". Read before
    # the singular tutor below, whose article this line does not print.
    exiled = _accept_counted_exile_search(stream, graveyard)
    if exiled is not None:
        return exiled
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    # "a card named X" is read by the noun parser, like every other restriction
    # on what may be found — `_restrictions_beyond` sees it on the filter.
    filt = parse_object_filter(stream)
    # "…**and/or** a card named Igneous Cur" (Alpine Houndmaster): a second
    # find with its own name, and the "and/or" is what makes each one optional.
    # Collected here because the names are the only thing that differs between
    # the finds — everything else about them is the phrase already read.
    alternatives: list[str] = []
    while filt.named is not None and stream.at_word("and"):
        probe = stream.mark()
        if not stream.accept_phrase("and", "or", "a") and not stream.accept_phrase(
            "and", "or", "an"
        ):
            stream.reset(probe)
            break
        try:
            second = parse_object_filter(stream)
        except GrammarError:
            stream.reset(probe)
            break
        if second.named is None or dataclasses.replace(
            second, named=filt.named
        ) != filt:
            # A second find that differs by more than its name is a different
            # sentence: the flow below gives every find the same shape, so a
            # phrase narrowing one of them differently would be dropped.
            stream.reset(probe)
            break
        if not alternatives:
            alternatives.append(filt.named)
        alternatives.append(second.named)
    stream.accept_punct(",")
    # "reveal it," / "reveal them," — recorded, not just consumed: a search that
    # prints the word shows the found cards' faces to every player (CR 701.20),
    # and the flow records that reveal so the UI can show them. The plural is
    # the two-name spelling of the same word.
    reveal = bool(stream.accept_word("reveal"))
    if reveal:
        # "reveal it" / "reveal them" / "reveal **that card**" (Merchant
        # Scroll). The same three spellings the `put` clause twelve lines below
        # already reads, because both name the same find: the referent is one
        # fact about this sentence, and a reader admitting fewer spellings here
        # than there refuses a line whose two halves agree with each other.
        if not stream.accept_word("it", "them"):
            stream.expect_word("that")
            stream.expect_word("card")
        stream.accept_punct(",")
    # "…, **then shuffle and put that card on top**." (Enlightened Tutor,
    # Mystical Tutor, Worldly Tutor.) The same search with its last two clauses
    # in the other order, and the order is the effect: the card is placed
    # **after** the shuffle, which is the whole of what these three do. Read
    # here, before the ordinary destination clause below, because "then shuffle"
    # is where the two spellings part company.
    top_mark = stream.mark()
    if stream.accept_punct(","):
        pass
    if stream.accept_word("then") and stream.accept_word("shuffle"):
        if stream.accept_word("and") and stream.accept_word("put"):
            if not stream.accept_word("it", "them"):
                stream.expect_word("that", "the")
                stream.expect_word("card")
            stream.expect_word("on")
            stream.expect_word("top")
            # "…on top **of your library**" is the same clause spelled out; the
            # zone is the one just shuffled either way, so the words are read
            # and dropped rather than left to fail the line.
            if stream.accept_word("of"):
                stream.expect_word("your")
                stream.expect_word("library")
            return ast.SearchLibrary(
                ast.PlayerRef("you"), filt, ast.Zone("library_top"), graveyard,
                tapped=(False,), named_alternatives=tuple(alternatives),
                reveal=reveal,
            )
    stream.reset(top_mark)

    # ", and put it into your hand" — the conjunction is the graveyard
    # template's punctuation, not a second effect: "put" must follow either way.
    stream.accept_word("and")
    stream.expect_word("put")
    # "put that card into your hand" / "put it into your hand" — one referent,
    # two printed spellings.
    if not stream.accept_word("it", "them"):
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
        named_alternatives=tuple(alternatives),
        untap_found_if=condition, untap_found_filter=counted,
        reveal=reveal,
    )


def _parse_search_other_library(stream: TokenStream) -> ast.Statement:
    """``Search <player>'s library for <count> cards and exile them. Then that
    player shuffles.`` (Jester's Cap.)

    ``Search <player>'s library for <count> cards. That player puts those cards
    into their hand, then shuffles.`` (Jester's Mask.)

    Three things are read rather than skipped, each for the reason the
    own-library production reads its three:

    * **whose library** — the seat the flow opens, which is not the seat that
      chooses (CR 608.2c);
    * **where the finds go** — exile and the searched player's hand are
      different effects. The sentence naming the hand is printed *after* the
      search and is still consumed here, because it is about the cards this
      search found: left to the sequence parser it would run before the prompt
      this arms had been answered, and would have nothing to move.
    * **the shuffle** — CR 701.24 ends a library search with one, so deleting
      the word refuses the line rather than claiming a search that leaves the
      library ordered.
    """
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected whose library is searched")
    # The lexer splits "player's" into "player" + "'s".
    stream.expect_word("'s")
    stream.expect_word("library")
    stream.expect_word("for")
    count = parse_amount(stream)
    if isinstance(count, ast.Fixed) and count.value < 1:
        raise stream.error("expected how many cards the search may find")
    filt = parse_object_filter(stream)
    if not filt.is_card:
        raise stream.error("a library holds cards, not permanents")
    to: ast.Zone | None = None
    if stream.accept_phrase("and", "exile", "them"):
        to = ast.Zone("exile")
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence that ends this search")
    if to is not None:
        # "**Then that player shuffles.**"
        stream.accept_word("then")
        shuffler = parse_player_ref(stream)
        if shuffler is None:
            raise stream.error("expected who shuffles after this search")
        stream.expect_word("shuffles")
        return ast.SearchPlayerLibrary(player, count, filt, to)
    # "**That player puts those cards into their hand, then shuffles.**"
    holder = parse_player_ref(stream)
    if holder is None:
        raise stream.error("expected who takes the cards this search found")
    for word in ("puts", "those", "cards", "into"):
        stream.expect_word(word)
    # "into **their** hand" — the possessive names the player this same clause
    # just named. `_parse_zone` has no reading for it (its possessives are
    # "your", "its owner's" and "its controller's"), and widening it there would
    # give every zone destination in the grammar a pronoun with no antecedent.
    stream.expect_word("their")
    stream.expect_word("hand")
    stream.accept_punct(",")
    stream.expect_word("then")
    stream.expect_word("shuffles")
    return ast.SearchPlayerLibrary(player, count, filt, ast.Zone("hand", holder))


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


def _accept_counted_exile_search(
    stream: TokenStream, graveyard: bool
) -> "ast.SearchAndExile | None":
    """``<N> cards, exile them, then shuffle`` at the cursor, or None with the
    cursor where it was.

    Only the plural-with-a-number spelling: a singular "a card" is the ordinary
    tutor below, whose destination clause this production has none of. The
    filter is parsed the same way every search parses one, so "three creature
    cards" would be the same sentence with a narrowing — and the count is a
    *ceiling*, because CR 701.23b lets a search find fewer than it names.
    """
    mark = stream.mark()
    count = parse_amount(stream)
    if not isinstance(count, ast.Fixed) or count.value < 2:
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not filt.is_card:
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("exile", "them"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    stream.accept_word("then")
    if not stream.accept_word("shuffle"):
        stream.reset(mark)
        return None
    zones = ("graveyard", "library") if graveyard else ("library",)
    return ast.SearchAndExile(filt, zones=zones, count=count.value)


def _parse_counted_search(
    stream: TokenStream, graveyard: bool, count: int
) -> ast.Statement:
    """The tail of ``Search your library for up to <N> <filter>, reveal <them>,
    <where they go>, then shuffle.`` (Cultivate, Land Tax.)

    Split from the singular production rather than branched inside it, because
    every clause after the count is *different*: "those cards" not "it", a
    plural destination clause, and an entry state per find. Sharing the code
    would mean a chain of `if counted:` through a production whose whole job is
    to read one shape.

    Two destination clauses, and which one a card prints is what the *count*
    decides. "Put **them** into your hand" sends every find to the same place,
    so the zone is read once and repeated per find. "Put **one** … and the
    other …" names a zone per find, which only a two-card search can spell —
    and both of its halves are required, because a card that places one find
    and says nothing about the second is a different effect, and defaulting the
    second to the first is how a search silently puts two lands on the
    battlefield.
    """
    filt = parse_object_filter(stream)
    stream.accept_punct(",")
    # "reveal those cards," / "reveal them," — the plural of the singular
    # production's "reveal it", recorded the same way: the finds are shown to
    # every player (CR 701.20).
    reveal = bool(stream.accept_word("reveal"))
    if reveal:
        if not stream.accept_phrase("those", "cards") and not stream.accept_word("them"):
            raise stream.error("expected 'those cards' after the plural reveal")
        stream.accept_punct(",")
    stream.expect_word("put")
    if stream.accept_word("them"):
        stream.expect_word("into", "onto")
        destination = _parse_zone(stream)
        tapped = bool(stream.accept_word("tapped"))
        stream.accept_punct(",")
        stream.accept_word("then")
        stream.expect_word("shuffle")
        return ast.SearchLibrary(
            ast.PlayerRef("you"), filt, destination, graveyard,
            extra_destinations=(destination,) * (count - 1),
            tapped=(tapped,) * count,
            up_to=True,
            reveal=reveal,
        )
    if count != 2:
        raise stream.error(
            "a search naming a destination per find can only be spelled for two"
        )
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
        reveal=reveal,
    )

