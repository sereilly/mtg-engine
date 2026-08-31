"""Parsing the hidden-zone flows: search, look-at, and the library's top.

The mirror of ``lowering/library.py``, which carries the same family on the
other side — "search, reveal, look-at, and exile linkage". It split off
``effects/cards.py`` when The Dark pushed that module past the 1,000-line
guard, and it reuses the lowering side's family name rather than inventing one,
so the two halves stay mirrored (CLAUDE.md: "if an ``effects/`` module ever
splits, reuse these names so the mirror re-forms instead of forking").

The cut is where the call graph already fell apart: nothing here calls anything
left in ``cards.py`` and nothing there calls anything here, so neither module
imports the other — which is what the layering guard requires of two families
in one package. Drawing, discarding, milling, scrying and the hand reveals stay
in ``cards.py``: they name a *card moving*, where everything here names a
*pile being looked through*.
"""

from __future__ import annotations

import dataclasses
from .. import ast
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..lexer import (MANA, render)
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import _accept_self_reference, _parse_card_alternatives, _parse_zone


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


def _parse_look_other_library_tail(
    stream: TokenStream, count, owner: ast.PlayerRef
) -> ast.Statement:
    """The rest of "Look at the top five cards of target player's library. You
    may then have that player shuffle that library." (Visions.)

    The shuffle sentence is read here rather than as a statement of its own
    because "that library" is the one the look just named — parsed apart it
    would have to guess a player, and guessing which library gets shuffled is
    the one mistake this card can make. The tail is optional: a card that only
    looks is this same effect without its offer, and refusing it would refuse a
    shape the node already represents.
    """
    mark = stream.mark()
    if stream.accept_punct(".") and stream.accept_phrase(
        "you", "may", "then", "have", "that", "player", "shuffle", "that", "library"
    ):
        return ast.LookAtLibraryTop(count, owner, may_shuffle=True)
    stream.reset(mark)
    # "…, **then put them back in any order**." (Natural Selection, Portent.)
    # The looker rearranges the cards they saw, which is the other handler —
    # and the optional shuffle after it is printed shorter here than Visions
    # prints it, so both spellings are read rather than one being normalized
    # into the other.
    #
    # This was a name-keyed hook on Natural Selection, and Portent prints the
    # identical sentence: `card_hooks`' entry bar is that no second card shares
    # the shape, and a second card did.
    if stream.accept_punct(",") and stream.accept_phrase(
        "then", "put", "them", "back", "in", "any", "order"
    ):
        shuffle_mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "you", "may", "have", "that", "player", "shuffle"
        ):
            return ast.LookAtLibraryTop(
                count, owner, may_shuffle=True, may_reorder=True
            )
        stream.reset(shuffle_mark)
        return ast.LookAtLibraryTop(count, owner, may_reorder=True)
    stream.reset(mark)
    return ast.LookAtLibraryTop(count, owner)


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
    # "Look at **a card at random in** target player's hand." (Urza's Bauble.)
    # Read before the count branches below, because it opens with an article
    # rather than with "the top" and would otherwise fall through to the player
    # reference and fail the line on the word "a".
    if stream.accept_phrase("a", "card", "at", "random", "in"):
        who = parse_player_ref(stream)
        if who is None:
            raise stream.error("expected the player whose hand is looked at")
        stream.expect_word("'s")
        stream.expect_word("hand")
        return ast.LookAtHand(who, random_card=True)
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
        stream.expect_word("cards")
        stream.expect_word("of")
        # Whose library, read rather than assumed to be the word "your": "the
        # top five cards of **target player's** library" (Visions) is this same
        # sentence about somebody else's deck. Everything below — the pick, the
        # bottoming, the cast-zone rider — is only ever about your own library,
        # which is why the other library's tail is read separately.
        if stream.accept_word("your"):
            owner = ast.PlayerRef("you")
        else:
            owner = parse_player_ref(stream)
            # The lexer splits "player's" into "player" + "'s"; the marker is
            # consumed here for the reason `_parse_look_at_hand`'s is — a token
            # left behind fails the line's full-token consumption.
            if owner is None or not stream.accept_word("'s"):
                raise stream.error("expected whose library is looked at")
        stream.expect_word("library")
        if owner.kind != "you":
            return _parse_look_other_library_tail(stream, count, owner)
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
        # "Exile four of them at random, **then** put the rest on top of your
        # library in any order." (Orcish Librarian.) Nothing is picked and
        # nothing reaches a hand, so it is a different statement that happens
        # to end the same way — the shared tail is read by the same words
        # below and carried out in the same place.
        if stream.at_word("exile"):
            stream.expect_word("exile")
            exile_count = parse_amount(stream)
            for word in ("of", "them", "at", "random"):
                stream.expect_word(word)
            stream.accept_punct(",")
            stream.expect_word("then")
            for word in ("put", "the", "rest", "on"):
                stream.expect_word(word)
            if not stream.accept_phrase("top", "of", "your", "library"):
                raise stream.error("expected 'top of your library'")
            for word in ("in", "any", "order"):
                stream.expect_word(word)
            return ast.LookTopExileRandom(count, exile_count)
        for word in ("put", "one", "of"):
            stream.expect_word(word)
        # "one of **them**" (Diabolic Vision) and "one of **those cards**" (See
        # the Truth) name the same pile. The pronoun was written into the
        # sequence, so the second spelling refused at the word — a card the
        # engine implements, kept out by which word it used for the cards it
        # had just looked at.
        if not (stream.accept_word("them") or stream.accept_phrase("those", "cards")):
            raise stream.error("expected 'them' or 'those cards'")
        for word in ("into", "your", "hand", "and", "the", "rest", "on"):
            stream.expect_word(word)
        # Where the rest go is the card's own statement and a real difference:
        # the bottom is out of reach, the top is the next N draws. Read rather
        # than assumed, the same rule the graveyard branch above states.
        if stream.accept_phrase("the", "bottom", "of", "your", "library"):
            rest_destination = "library_bottom"
        elif stream.accept_phrase("top", "of", "your", "library"):
            rest_destination = "library_top"
        else:
            raise stream.error("expected where the rest of the cards go")
        for word in ("in", "any", "order"):
            stream.expect_word(word)
        # See the Truth's cast-zone sentence, and only its. Optional because it
        # is a *rider* on this template rather than part of it: Diabolic Vision
        # prints the pick and stops, and demanding the sentence refused it for
        # text it does not have.
        mark = stream.mark()
        if stream.accept_punct(".") and stream.accept_phrase(
            "if", "this", "spell", "was", "cast", "from", "anywhere",
            "other", "than", "your", "hand",
        ):
            stream.accept_punct(",")
            for word in ("put", "each", "of", "those", "cards", "into", "your", "hand", "instead"):
                stream.expect_word(word)
            return ast.LookTopPickToHand(
                count,
                rest_destination=rest_destination,
                all_to_hand_if_cast_elsewhere=True,
            )
        stream.reset(mark)
        return ast.LookTopPickToHand(count, rest_destination=rest_destination)
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player whose hand is looked at")
    # The lexer splits "player's" into "player" + "'s"; the marker still has to
    # be consumed or the line fails full-token consumption.
    stream.expect_word("'s")
    stream.expect_word("hand")
    # "Look at target player's hand **and choose X cards from it. That player
    # discards those cards.**" (Mind Warp.) Duress's template with the hand
    # looked at instead of revealed, so it is that node rather than a second
    # one — and read here, from the sentence it actually opens, because the
    # choice is over the hand *this* clause opened and a statement after it
    # would be a pick from a zone nobody had looked in.
    picked = _accept_look_and_choose(stream, player)
    if picked is not None:
        return picked
    return ast.LookAtHand(player)


def _accept_look_and_choose(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.RevealHandAndChoose | None":
    """The tail of ``Look at <player>'s hand **and choose <N> cards from it.
    That player discards those cards.**`` (Mind Warp.)

    Refuses without consuming, so "Look at target player's hand." on its own
    (Glasses of Urza) keeps the reading it has. Every word of the discard
    sentence is required: a line that looks and chooses but never says what
    becomes of the cards is a card that does nothing, and dropping the sentence
    would make the two indistinguishable.
    """
    mark = stream.mark()
    if not stream.accept_phrase("and", "choose"):
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("from", "it"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # Whose discard, read as a reference rather than as the literal words
    # "that player": Leshrac's Sigil prints "**The player** discards that
    # card", which `parse_player_ref` already reads as the same back-reference
    # (it is an alias, like "they"). The referent is *required* to be that
    # back-reference — a sentence naming somebody else would be a card that
    # looks in one hand and empties another.
    discarder = parse_player_ref(stream) if stream.at_word(
        "that", "the", "they"
    ) else None
    if discarder is None or discarder.kind != "that_player":
        stream.reset(mark)
        return None
    if not stream.accept_phrase("discards", "those", "cards") and not (
        stream.accept_phrase("discards", "that", "card")
    ):
        stream.reset(mark)
        return None
    return ast.RevealHandAndChoose(
        player, ast.ObjectFilter(is_card=True), fate="discard",
        count=count, revealed=False,
    )


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
        if not stream.accept_word("them"):
            stream.expect_word("it")
        stream.accept_punct(",")
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
    * **the shuffle** — CR 701.19d ends a library search with one, so deleting
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
