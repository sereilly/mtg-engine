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

The multi-zone strip that used to sit at the bottom of this file left at
Urza's Destiny's wave 1, into ``_strips`` — a floor this module imports rather
than a family beside it, since nothing else asks. Its own docstring records the
seam; the short version is that "search a player's graveyard, hand, and library
for all cards with the same name as that spell and exile them" is not a library
search, and shared not one word of vocabulary with what stayed.

**Asymmetric, and the mirror image of the asymmetry this package usually
records** — or it was. The sentence that stood here said the lowering side has
no ``search`` family, because a tutor lowers to one ``search_library``
instruction however elaborately its sentence is printed and the words are where
the work is. ``lowering/search.py`` has existed for several sets; the mirror
re-formed on its own, which is what the naming rule is for, and the paragraph
went on describing a repo that had moved. Read a recorded seam as a lead.
"""



import dataclasses
from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import _accept_number, _parse_zone
from ._strips import _accept_strip_cards_with_chosen_name



def _accept_same_name_as_target(
    stream: TokenStream,
) -> "ast.TargetSpec | None":
    """``with the same name as target <noun phrase>`` at the cursor, as the
    target it names — or None with the cursor where it was.

    CR 201.2's name comparison against an object the sentence *chooses*, which
    is what separates it from the two spellings ``names.accept_name_comparison``
    already reads: those compare against the board ("another permanent") or
    against the event that fired ("that name"), and neither adds a target to
    the spell.

    Every word is required and the target is read by the ordinary target
    parser, so what the search may find and what the spell announces are one
    phrase. A tail this cannot read leaves the cursor untouched and the line
    refuses, which is the whole point: a dropped "same name" is a tutor for
    any card at all.
    """
    mark = stream.mark()
    if not stream.accept_phrase("with", "the", "same", "name", "as"):
        stream.reset(mark)
        return None
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if spec is None or not spec.targeted:
        stream.reset(mark)
        return None
    return spec


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
    # "Each player may search **their** library …" (Noble Benefactor, Veteran
    # Explorer, and Natural Balance's second sentence, which the whole-paragraph
    # production reads without ever reaching here). The pronoun agrees with the
    # sentence's subject, which the offer above this production has already
    # read — exactly as ``_parse_discard`` reads "discard **your** hand" and
    # "that player discards **their** hand" as one production. So the searcher
    # stays ``PlayerRef("you")``, meaning "whoever is performing this sentence",
    # and ``may``'s per-seat offer is what makes that each player in turn.
    #
    # The word is carried, not just accepted: the destination clause behind it
    # prints the *same* possessive ("put that card into **their** hand"), and a
    # reader admitting one and not the other refuses a line whose two halves
    # agree with each other.
    possessive = "their" if stream.at_word("their") else "your"
    if not stream.accept_word(possessive):
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
    #
    # "…library **and** graveyard…" (Doomsday) is the same two zones with the
    # weaker conjunction, and the difference is only in what the sentence then
    # does with them: an "and/or" search may look in either, and Doomsday looks
    # in both because it empties both. One flag either way, because what the
    # flow needs to know is which piles it may take a card out of.
    graveyard = bool(
        stream.accept_phrase("and", "or", "graveyard")
        or stream.accept_phrase("and", "graveyard")
    )
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
        return _parse_counted_search(stream, graveyard, count.value, possessive)
    # "Search your library for **any number of** Goblin cards, reveal them,
    # then shuffle and put those cards on top in any order." (Goblin
    # Recruiter.) The same counted tail with no printed ceiling — the plural
    # clauses are identical, and what differs is only that the number of finds
    # is the library's answer rather than the card's. So it reaches the counted
    # production with ``None`` for the count rather than a second reader of
    # "reveal those cards, put them …".
    if stream.accept_phrase("any", "number", "of"):
        # "Search your library for any number of land cards, **exile them, then
        # shuffle**." (Mana Severance.) The uncounted spelling of the exile
        # search below, which is why it is tried here rather than given a
        # production: `SearchAndExile.count` is already documented as "``None``
        # for 'any number'", so the only thing the two printings differ in is
        # whether a ceiling was printed. Tried first and non-consuming on
        # refusal, so Goblin Recruiter's "reveal them, then shuffle and put
        # those cards on top" keeps the counted production behind it.
        uncounted = _accept_counted_exile_search(stream, graveyard, count=None)
        if uncounted is not None:
            return uncounted
        return _parse_counted_search(stream, graveyard, None, possessive)
    # "Search your library for **three cards, exile them, then shuffle**."
    # (Foresight.) A counted search whose finds are exiled rather than placed,
    # which is `SearchAndExile`'s shape with a printed ceiling — the two-zone
    # spelling above reaches the same node with "any number of". Read before
    # the singular tutor below, whose article this line does not print.
    # "…for five cards **and exile the rest**. Put the chosen cards on top of
    # your library in any order." (Doomsday.) A counted search whose finds are
    # kept and whose *pile* is exiled, which is the other way round from the
    # exile search below — read first because both open on a number and the
    # difference is the word after the noun.
    # "Search your library for **three cards and reveal them. Target opponent
    # chooses one. Put that card into your hand and the rest into your
    # graveyard. Then shuffle.**" (Intuition.) A counted search whose finds go
    # nowhere until another seat has picked among them — read here, before the
    # two exile shapes, because all three open on a number and the difference
    # is the clause after the noun. Non-consuming on refusal, so each of them
    # keeps its own reading and its own refusal site.
    picked = _accept_search_reveal_opponent_chooses(stream, graveyard)
    if picked is not None:
        return picked
    doomsday = _accept_search_exiling_the_rest(stream, graveyard)
    if doomsday is not None:
        return doomsday
    exiled = _accept_counted_exile_search(stream, graveyard)
    if exiled is not None:
        return exiled
    if not stream.accept_word("a", "an"):
        raise stream.error("a search for more than one card has no representation")
    # "a card named X" is read by the noun parser, like every other restriction
    # on what may be found — `_restrictions_beyond` sees it on the filter.
    filt = parse_object_filter(stream)
    # "…a card **with the same name as target nontoken creature**" (Mask of the
    # Mimic). Read here rather than inside the noun parser because the phrase
    # ends in a *target*: `nouns` would have to reach into `references` for it,
    # which is the coupling the family rule exists to prevent — and this
    # production already reads a target nowhere else, so the phrase costs one
    # call.
    named_target = _accept_same_name_as_target(stream)
    if named_target is not None:
        filt = dataclasses.replace(filt, named_as_target=named_target.filter)
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
    destination = _parse_zone(stream, self_possessive=possessive)
    # "…put it onto the battlefield **tapped**" (Fabled Passage). The two-card
    # search has read this word since Cultivate; the single-find spelling had
    # nowhere to put it and so failed the line on the word after the zone. Same
    # field, one entry — how a find enters is part of where it goes.
    tapped = bool(stream.accept_word("tapped"))
    # "…, **discard a card at random**, then shuffle." (Gamble.) Read before
    # the shuffle because that is where it is printed: the shuffle is this
    # search's own last clause (CR 701.23a), so a production that stopped in
    # front of the discard would strand the words it still owes.
    discard_after, discard_at_random = _accept_search_discard_clause(stream)
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
    elif not _accept_each_searcher_shuffle(stream):
        stream.accept_punct(",")
        stream.accept_word("then")
        stream.expect_word("shuffle")
    condition, counted = _parse_search_untap_rider(stream)
    return ast.SearchLibrary(
        ast.PlayerRef("you"), filt, destination, graveyard, tapped=(tapped,),
        named_alternatives=tuple(alternatives),
        untap_found_if=condition, untap_found_filter=counted,
        reveal=reveal,
        discard_after=discard_after,
        discard_after_at_random=discard_at_random,
    )


def _accept_search_discard_clause(stream: TokenStream) -> tuple[int, bool]:
    """``, discard <N> card[s] [at random]`` — the count and whether it is
    random, or ``(0, False)`` with the cursor untouched.

    Gamble prints it between the destination and the shuffle, which is a clause
    of the search's own sentence rather than a statement behind it. Both halves
    are data: a card printing two cards, or a chosen discard, is this reader
    with a different answer rather than a second production. What it is *not*
    is a fused effect — the lowering emits an ordinary discard after the search,
    in the printed order, which is what puts the card just found inside the hand
    the random discard reaches.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    if not stream.accept_word("discard"):
        stream.reset(mark)
        return 0, False
    count = _accept_number(stream)
    if count is None:
        stream.reset(mark)
        return 0, False
    if not stream.accept_word("card", "cards"):
        stream.reset(mark)
        return 0, False
    at_random = bool(stream.accept_phrase("at", "random"))
    return count, at_random


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
    # "Search that player's **graveyard, hand, and library** for all cards with
    # the same name as the chosen card and exile them." (Lobotomy.) A search
    # across several zones and by a name nothing printed — read here, before
    # the literal "library" this production has always expected, which is the
    # word that failed the line. Non-consuming on refusal, so Jester's Cap and
    # Jester's Mask keep every reading and every refusal site they have.
    stripped = _accept_strip_cards_with_chosen_name(stream, player)
    if stripped is not None:
        return stripped
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
    elif isinstance(count, ast.Fixed) and count.value == 1 and stream.accept_phrase(
        "and", "exile", "it"
    ):
        # "Search target opponent's library for **a card** and exile **it**."
        # (Grinning Totem.) The plural clause above with one find, and the
        # pronoun is *checked against the count* rather than merely consumed:
        # "for three cards and exile it" is not a sentence any card prints, and
        # admitting it would let a three-card search claim the one-card reading
        # — the same agreement `_parse_search_untap_rider` demands of "that
        # land". The whole difference is a word, so it is a branch here and not
        # a second production.
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


def _accept_search_exiling_the_rest(
    stream: TokenStream, graveyard: bool
) -> "ast.SearchLibrary | None":
    """``<N> cards and exile the rest. Put the chosen cards on top of your
    library in any order`` at the cursor, or None with the cursor where it was.
    (Doomsday.)

    Both sentences, for the conditional-shuffle tail's reason one production
    up: the second names the cards the first found, and the search arms a
    prompt \u2014 so left to the sentence parser it would run before anybody had
    chosen, with nothing to place.

    **No shuffle, and that is the card rather than an omission.** Every other
    search here ends with one and this production would refuse a line missing
    it; this one exiles the library it searched, so there is nothing left to
    shuffle and the printed sentence says so by saying nothing.

    Both zones are required. "Exile the rest" is about the piles the search
    looked through, and a one-zone printing of it would empty a library while
    leaving a graveyard the sentence also named \u2014 so the flag is checked here
    rather than assumed, and a card printing this over one zone refuses.
    """
    if not graveyard:
        return None
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
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
    if not stream.accept_phrase("and", "exile", "the", "rest"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "put", "the", "chosen", "cards", "on", "top", "of", "your", "library",
    ):
        stream.reset(mark)
        return None
    # "in any order" is consumed and not recorded, exactly as the counted
    # search's identical clause is: the finder names the cards in the order they
    # want and that pick order *is* the answer.
    if not stream.accept_phrase("in", "any", "order"):
        stream.reset(mark)
        return None
    zone = ast.Zone("library_top")
    return ast.SearchLibrary(
        ast.PlayerRef("you"), filt, zone, graveyard,
        extra_destinations=(zone,) * (count.value - 1),
        tapped=(False,) * count.value,
        # CR 701.23b lets any search find fewer than it names, and this one has
        # to: a player with four cards left between the two zones still puts
        # what they have on top.
        up_to=True,
        exile_rest=True,
    )


def _accept_counted_exile_search(
    stream: TokenStream, graveyard: bool, *, count: int | None = -1,
) -> "ast.SearchAndExile | None":
    """``<N> cards, exile them, then shuffle`` at the cursor, or None with the
    cursor where it was.

    Only the plural-with-a-number spelling: a singular "a card" is the ordinary
    tutor below, whose destination clause this production has none of. The
    filter is parsed the same way every search parses one, so "three creature
    cards" would be the same sentence with a narrowing — and the count is a
    *ceiling*, because CR 701.23b lets a search find fewer than it names.

    *count* is the ceiling when the caller has **already read it**: "any number
    of" (Mana Severance) is the same tail with the number left to the library,
    and its words are consumed by the branch above before this is reached. The
    default sentinel means "read it here", which is every other caller — a
    plain ``None`` default could not tell "no ceiling was printed" from "nobody
    has looked yet", and those two are different sentences.
    """
    mark = stream.mark()
    if count == -1:
        parsed = parse_amount(stream)
        if not isinstance(parsed, ast.Fixed) or parsed.value < 2:
            stream.reset(mark)
            return None
        count = parsed.value
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
    zones = ("graveyard", "library") if graveyard else ("library",)
    # "…exile them **in a face-down pile, and shuffle that pile**." (Mangara's
    # Tome.) The other spelling of what happens to the finds, and the one that
    # keeps them: this pile is recorded on the exiling permanent (CR 610.3) so
    # a later linked ability can read it, where Foresight's finds are exiled
    # and never mentioned again.
    #
    # No "then shuffle" here, and that is the card rather than an omission —
    # Mangara's Tome shuffles its library in the *next* printed sentence, which
    # the ordinary shuffle production reads. Consuming a shuffle that is not
    # there would take that sentence's words away from it.
    if stream.accept_phrase("in", "a", "face-down", "pile"):
        stream.accept_punct(",")
        stream.accept_word("and")
        shuffled = bool(stream.accept_phrase("shuffle", "that", "pile"))
        return ast.SearchAndExile(
            filt, zones=zones, count=count,
            face_down_pile=True, shuffle_pile=shuffled,
        )
    stream.accept_punct(",")
    stream.accept_word("then")
    if not stream.accept_word("shuffle"):
        stream.reset(mark)
        return None
    return ast.SearchAndExile(filt, zones=zones, count=count)


def _accept_each_searcher_shuffle(stream: TokenStream) -> bool:
    """``. Then each player who searched their library this way shuffles`` at
    the cursor, or False with the cursor where it was.

    CR 701.23c ends a library search with a shuffle, and this engine performs
    it inside the search prompt — which is why the ordinary "then shuffle" is
    read and dropped rather than lowered. This is the same clause printed as a
    **following sentence**, because the search it ends was offered to a set of
    seats and the sentence has to say which of them shuffle: the ones that
    searched. Two cards print it word for word (Noble Benefactor; Natural
    Balance, whose whole paragraph has its own production), and the set it names
    is exactly the set the offer armed a prompt for — a seat that declined the
    "may" never searched and never gets one.

    Consumed here rather than left to the sentence parser for the reason the
    graveyard branch above gives about its own printed full stop: split off, it
    is a statement no production implements and the whole line refuses, and the
    shuffle it describes would be detached from the effect that performs it.
    The final full stop is left for the sequence parser, which is what ends the
    line.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return False
    if not stream.accept_phrase(
        "then", "each", "player", "who", "searched", "their", "library",
        "this", "way", "shuffles",
    ):
        stream.reset(mark)
        return False
    return True


def _parse_counted_search(
    stream: TokenStream, graveyard: bool, count: int | None,
    possessive: str = "your",
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
    # "…, **then shuffle and put those cards on top in any order**." (Goblin
    # Recruiter.) The plural of the tail the singular production reads for the
    # three Mirage tutors, and the order is the effect for the same reason: the
    # library is shuffled first and the finds placed after, so they are on top
    # rather than back in the deck. Read here, before the ordinary destination
    # clause below, because "then shuffle" is where the two spellings part.
    #
    # "in any order" is consumed and not recorded: the finder names the cards
    # in the order they want them, and that pick order *is* the answer — a
    # field saying "the player chooses" would be a second spelling of what the
    # answer already carries.
    top_mark = stream.mark()
    if stream.accept_word("then") and stream.accept_word("shuffle"):
        if stream.accept_word("and") and stream.accept_word("put"):
            if stream.accept_phrase("those", "cards") or stream.accept_word("them"):
                stream.expect_word("on")
                stream.expect_word("top")
                if stream.accept_word("of"):
                    stream.expect_word("your")
                    stream.expect_word("library")
                stream.accept_phrase("in", "any", "order")
                zone = ast.Zone("library_top")
                return ast.SearchLibrary(
                    ast.PlayerRef("you"), filt, zone, graveyard,
                    extra_destinations=() if count is None else (zone,) * (count - 1),
                    tapped=(False,) * (0 if count is None else count),
                    up_to=True, unbounded=count is None, reveal=reveal,
                )
    stream.reset(top_mark)
    stream.expect_word("put")
    # "put **them** …" / "put **those cards** …" — one referent, two printed
    # spellings, and the same pair the reveal clause above and the shuffle-then-
    # place clause between them already read. It was read here as "them" alone,
    # which is the fork this production's own docstring warns against one clause
    # up: a reader admitting fewer spellings here than there refuses a line
    # whose halves agree with each other. Defense of the Heart prints "search
    # your library for up to two creature cards, **put those cards** onto the
    # battlefield, then shuffle" and failed on the second word.
    if stream.accept_word("them") or stream.accept_phrase("those", "cards"):
        stream.expect_word("into", "onto")
        destination = _parse_zone(stream, self_possessive=possessive)
        tapped = bool(stream.accept_word("tapped"))
        if not _accept_each_searcher_shuffle(stream):
            stream.accept_punct(",")
            stream.accept_word("then")
            stream.expect_word("shuffle")
        return ast.SearchLibrary(
            ast.PlayerRef("you"), filt, destination, graveyard,
            extra_destinations=(
                () if count is None else (destination,) * (count - 1)
            ),
            tapped=(tapped,) * (0 if count is None else count),
            up_to=True,
            unbounded=count is None,
            reveal=reveal,
        )
    if count != 2:
        raise stream.error(
            "a search naming a destination per find can only be spelled for two"
        )
    stream.expect_word("one")
    stream.expect_word("into", "onto")
    first = _parse_zone(stream, self_possessive=possessive)
    first_tapped = bool(stream.accept_word("tapped"))
    if not stream.accept_phrase("and", "the", "other"):
        raise stream.error("expected 'and the other' before the second destination")
    stream.expect_word("into", "onto")
    second = _parse_zone(stream, self_possessive=possessive)
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


#: Where each half of a searched-and-revealed pile may be printed to go. Two
#: closed lists for ``effects/reveal._SORTED_MATCH_ZONES``' reason: the chosen
#: card is *kept* and the rest are *discarded*, and a card that swapped them
#: would be a different spell with nothing to notice the difference. A word
#: outside them refuses the line rather than lowering onto a fate nothing
#: carries out.
_PICKED_SEARCH_FATES: dict[str, str] = {"hand": "hand"}
_REST_SEARCH_FATES: dict[str, str] = {"graveyard": "graveyard"}


def _accept_search_reveal_opponent_chooses(
    stream: TokenStream, graveyard: bool,
) -> "ast.SearchRevealOpponentChooses | None":
    """``<N> cards and reveal them. Target opponent chooses one. Put that card
    into your hand and the rest into your graveyard. Then shuffle.`` at the
    cursor, or None with the cursor where it was. (Intuition.)

    All four sentences, interior full stops included, for
    :class:`ast.SearchRevealOpponentChooses`' reason: "one", "that card" and
    "the rest" all name the pile the first sentence found, and parsed apart
    three of them dangle a referent nothing binds. The search also **suspends**
    on its prompt, so a following statement would run before anybody had
    chosen.

    Every word is required and both destinations are read rather than assumed.
    The chooser is read as a reference (a pick made by the wrong player is the
    whole card), and the count is a plain number: CR 701.23d makes a search for
    a bare quantity a *floor*, which is what separates this from the "up to"
    spellings the counted production reads.

    One zone only. "The rest into your graveyard" is about the cards this
    search found, and a printing that also opened a graveyard would be finding
    cards there and then putting them back into it — a sentence no card prints,
    and one this refuses rather than performs.
    """
    if graveyard:
        return None
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(count, ast.Fixed) or count.value < 2:
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # A bare quantity and nothing else: CR 701.23c's "undefined quality" and
    # CR 701.23b's "stated quality" are different searches from this one, and
    # the floor below is only right for a search that names no quality at all.
    if not filt.is_card or filt != ast.ObjectFilter(is_card=True):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "reveal", "them"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    chooser = parse_player_ref(stream)
    if chooser is None or not stream.accept_phrase("chooses", "one"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("put", "that", "card", "into", "your"):
        stream.reset(mark)
        return None
    fate = stream.peek_word()
    if fate not in _PICKED_SEARCH_FATES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("and", "the", "rest", "into", "your"):
        stream.reset(mark)
        return None
    rest = stream.peek_word()
    if rest not in _REST_SEARCH_FATES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # "**Then shuffle.**" CR 701.23h ends the search with one and the engine
    # performs it inside the search prompt, so the word is read and dropped
    # exactly as the ordinary tutor's is — required, so deleting it fails the
    # line rather than quietly claiming a search that never shuffles. The final
    # full stop is left for the sequence parser, which is what ends the line.
    if not stream.accept_word("then"):
        stream.reset(mark)
        return None
    if not stream.accept_word("shuffle"):
        stream.reset(mark)
        return None
    return ast.SearchRevealOpponentChooses(
        count, chooser,
        fate=_PICKED_SEARCH_FATES[fate],
        other_fate=_REST_SEARCH_FATES[rest],
    )
