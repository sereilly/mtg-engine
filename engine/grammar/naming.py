"""A **choice the board cannot show** — the bare sentence that makes one, and
the printed paragraphs that make one and check it.

A number, a colour, a creature type, a card type, a card name, a seat, a card
picked out of a hidden hand: in every case a value that exists only in a
player's head until a later sentence reads it. Two printed shapes carry one,
and both are here.

**The paragraphs** were split out of ``paragraphs`` at Prophecy's Phase 0, when
that module stood at 963 of the guard's 1,000 lines with several of the set's
groups about to land multi-sentence effects in it. Each is a paragraph for
``paragraphs``' own reason: the sentences after the first read what the first
chose, so parsed apart each would test a record nobody wrote. What makes them a
family of their own is **what** the first sentence chooses. Necromentia,
Demonic Consultation, Nebuchadnezzar, Petra Sphinx and Vexing Arcanix name a
card, and Stronghold Gambit's players each pick one face down from their hand.
The rest of each paragraph *is* the check: a search for the name, a reveal
until it turns up, a random reveal, a reveal of the top card, a reveal of the
picks.

**The bare sentences** arrived at Odyssey's Phase 0 from ``effects/game.py``,
ten lines under the guard: "Choose a number", "a color", "a creature type", "a
card type", "a card name", "one of your opponents", "a player who cast …", and
Goblin Game's hidden items. Each makes the same kind of choice and stops: the
check is a separate printed sentence that reads the record back, which is the
whole difference between the two halves of this file. ``game``'s docstring had
listed "the choices a sentence makes" as its own and the lowering side had
never agreed (next paragraph); they were the half of that module that grew,
131 of the 173 lines it gained after its previous split, where no paragraph
had been added here since this file was made; and one of them was already
written around this file from outside it — ``parse_choose_card_name`` declines
Necromentia's opening so that ``_parse_name_and_strip`` can read the paragraph.

The name is the lowering side's. ``statement_dispatch_naming.py`` lowers all
five nodes the paragraphs return and six of the eight the sentences do (the
card name lowers in ``by_node``'s table and the hidden items in
``lowering/game.py``, the two places the mirror is not exact), under a
docstring that says everything there "reads a **decision** rather than a
board", so the mirror re-forms rather than a third word arriving for one idea.
Two near misses, both checked: ``names.py`` is a different question, under
``nouns`` — the literal string a card prints after "named", which no player
chooses — and ``choices.py`` reads "Choose <something>." by probing the *next*
sentence through ``parse_statement``. Nothing here calls back into the sentence
parser, which is what keeps this module beside ``paragraphs``, below
``statements``, rather than beside ``choices``.

Two dispatchers call in, at the words each production opens on: the imperative
"choose" arm of ``imperative_verbs`` (the six bare sentences that name a value
or a seat, then Demonic Consultation, then Nebuchadnezzar, then the bare
card-name sentence, then Necromentia as the last resort — an order that arm's
own comments argue line by line) and the seat-subject arms of ``player_verbs``
("hides" for Goblin Game; under "chooses", the card-type list, Stronghold
Gambit, then Petra Sphinx's guess). Every production but the last in each arm
declines without consuming on a sentence that is not its own, which is what
lets the arms try them in order.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import expect_pt, parse_amount
from .bounds import accept_superlative
from .errors import GrammarError
from .nouns import parse_object_filter
from .readers import accept_source_reference
from .references import parse_player_ref
from .stream import TokenStream
from .vocabulary import (ALL_SUBTYPES, CARD_TYPES, COLOR_WORDS, CREATURE_TYPES,
                         SUBTYPE_INDEX, match_longest, singular)


def _parse_name_and_strip(stream: TokenStream) -> ast.Statement:
    """Necromentia's whole three-sentence effect.

    Every word is required. The zone list is what the search reaches and the
    token clause names which of those zones the count comes from — "each card
    exiled from their **hand** this way" is a strict subset of what was exiled,
    and a card counting the whole pile would make far more Zombies.

    "other than a basic land card name" is consumed and *honoured*: it is the
    one restriction on the choice, and a name it forbids has to be refused where
    the choice is made rather than dropped here.
    """
    for word in ("choose", "a", "card", "name", "other", "than", "a", "basic",
                 "land", "card", "name"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the search sentence after the choice")
    for word in ("search", "target", "opponent", "'s"):
        stream.expect_word(word)
    zones: list[str] = []
    while True:
        word = stream.peek_word()
        if word not in ("graveyard", "hand", "library"):
            break
        stream.advance()
        zones.append(word)
        if stream.accept_punct(","):
            stream.accept_word("and")
            continue
        if stream.accept_word("and"):
            continue
        break
    if len(zones) < 2:
        raise stream.error("expected the zones the search reaches")
    for word in ("for", "any", "number", "of", "cards", "with", "that", "name",
                 "and", "exile", "them"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the shuffle sentence after the search")
    for word in ("that", "player", "shuffles"):
        stream.expect_word(word)
    stream.accept_punct(",")
    for word in ("then", "creates", "a"):
        stream.expect_word(word)
    power, _, toughness, _ = expect_pt(stream)
    colors: list[str] = []
    while (word := stream.peek_word()) in COLOR_WORDS:
        colors.append(COLOR_WORDS[word])
        stream.advance()
    subtypes: list[str] = []
    while (word := stream.peek_word()) and word in CREATURE_TYPES:
        subtypes.append(word)
        stream.advance()
    for word in ("creature", "token", "for", "each", "card", "exiled", "from", "their"):
        stream.expect_word(word)
    token_zone = stream.peek_word()
    if token_zone not in ("hand", "graveyard", "library"):
        raise stream.error("expected the zone the token count comes from")
    stream.advance()
    for word in ("this", "way"):
        stream.expect_word(word)
    if not (isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)):
        raise stream.error("the token's printed power/toughness is a number")
    return ast.NameAndStrip(
        zones=tuple(zones), token_zone=token_zone,
        token_power=power.value, token_toughness=toughness.value,
        token_colors=tuple(colors), token_subtypes=tuple(subtypes),
    )


#: Where a revealed card may be printed to go. A closed list because each of
#: these is a zone the mover below actually knows how to reach; a word outside
#: it refuses the line rather than lowering onto a destination nothing moves to.
_REVEAL_DESTINATIONS: tuple[str, ...] = ("hand", "graveyard")

#: The hidden zones a "reveals N cards at random from their <zone>" clause may
#: name. A *list* rather than the word "hand" spelled into the production: the
#: randomness is only meaningful over a zone whose contents are hidden, and the
#: two of those are what this names.
_RANDOM_REVEAL_ZONES: tuple[str, ...] = ("hand", "library")


def _parse_name_then_consult(stream: TokenStream) -> "ast.Statement | None":
    """Demonic Consultation's whole four-sentence effect.

    ``Choose a card name. Exile the top <N> cards of your library, then reveal
    cards from the top of your library until you reveal a card with the chosen
    name. Put that card into your hand and exile all other cards revealed this
    way.``

    Refuses without consuming, so every other sentence opening with "choose"
    keeps the reading it has — Nebuchadnezzar's paragraph is tried after this
    one and Necromentia's after that.

    Every word is required, and the exile of the top cards especially: it is
    the whole cost of the card, and a line that dropped it would be a tutor.
    """
    mark = stream.mark()
    for word in ("choose", "a", "card", "name"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("exile", "the", "top"):
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
    for word in ("cards", "of", "your", "library"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    for word in ("then", "reveal", "cards", "from", "the", "top", "of", "your",
                 "library", "until", "you", "reveal", "a", "card", "with",
                 "the", "chosen", "name"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    for word in ("put", "that", "card", "into", "your", "hand", "and", "exile",
                 "all", "other", "cards", "revealed", "this", "way"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    return ast.NameThenConsult(count)


def _parse_name_then_random_reveal(stream: TokenStream) -> "ast.Statement | None":
    """Nebuchadnezzar's whole three-sentence effect.

    ``Choose a card name. Target opponent reveals X cards at random from their
    hand. Then that player discards all cards with that name revealed this
    way.``

    Refuses without consuming, so every other sentence opening with "choose"
    keeps the reading it has — Necromentia's naming paragraph is tried after
    this one and its first sentence differs from the fourth word on.

    "**revealed this way**" is read and is the whole reason the three sentences
    are one production: it narrows the discard to the cards the random reveal
    turned up, where a discard of "all cards with that name" would take every
    copy in the hand and make the randomness decoration.
    """
    mark = stream.mark()
    for word in ("choose", "a", "card", "name"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    who = parse_player_ref(stream)
    if who is None or who.kind != "target_opponent":
        stream.reset(mark)
        return None
    if not stream.accept_word("reveals"):
        stream.reset(mark)
        return None
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    for word in ("cards", "at", "random", "from", "their"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    zone = stream.peek_word()
    if zone not in _RANDOM_REVEAL_ZONES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    for word in ("then", "that", "player", "discards", "all", "cards", "with",
                 "that", "name", "revealed", "this", "way"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return None
    return ast.NameAndRandomReveal(who, count, zone)


def parse_reveal_chosen_hand_cards(
    stream: TokenStream, chooser: ast.PlayerRef
) -> "ast.RevealChosenHandCards | None":
    """Stronghold Gambit's three sentences, from the verb of the first.

    "Each player **chooses a card in their hand**. Then each player reveals
    their chosen card. The owner of each creature card revealed this way with
    the lowest mana value puts it onto the battlefield."

    Declines without consuming until the whole first sentence has matched, so
    every other "chooses …" keeps its arm; past it, every word is *expected*.
    The two later sentences are the effect — a production that read the pick
    and shrugged at the rest would compile a sorcery that hides a card and does
    nothing with it.

    The competing noun phrase and its superlative are read by the shared
    readers, so "each artifact card revealed this way with the greatest mana
    value" is this production with two words changed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("chooses", "a", "card", "in", "their", "hand"):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    for word in ("then", "each", "player", "reveals", "their", "chosen", "card"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the sentence the reveal decides")
    for word in ("the", "owner", "of", "each"):
        stream.expect_word(word)
    entrants = parse_object_filter(stream)
    if not entrants.is_card:
        raise stream.error("a revealed card is a card, not a permanent")
    for word in ("revealed", "this", "way"):
        stream.expect_word(word)
    if stream.accept_word("with"):
        superlative = accept_superlative(stream)
        if superlative is None:
            raise stream.error("expected the extreme the revealed cards compete on")
        entrants = dataclasses.replace(entrants, superlative=superlative)
    for word in ("puts", "it", "onto", "the", "battlefield"):
        stream.expect_word(word)
    return ast.RevealChosenHandCards(chooser, entrants)


def _parse_name_then_reveal_top(
    stream: TokenStream, who: ast.PlayerRef
) -> ast.Statement:
    """Petra Sphinx's whole three-sentence guess.

    The subject has already been read — "target player" — so this starts at the
    verb and reads to the end of the third sentence. Every word is required,
    and the two destinations are the only things that vary: "into their hand"
    on a hit and "into their graveyard" on a miss are read where they are
    printed rather than assumed, because the same guess with the miss going to
    the bottom of the library is a card this production should read too.

    "If it doesn't" is consumed rather than treated as decoration. It is the
    *complement* of the sentence before it, so nothing here has to model a
    second condition — but a line that omits it is a card whose miss does
    nothing, and dropping the words would make the two indistinguishable.
    """
    for word in ("chooses", "a", "card", "name"):
        stream.expect_word(word)
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the reveal")
    for word in ("then", "reveals", "the", "top", "card", "of", "their", "library"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the hit sentence after the reveal")
    for word in ("if", "that", "card", "has", "the", "chosen", "name"):
        stream.expect_word(word)
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the hit's destination")
    for word in ("that", "player", "puts", "it", "into", "their"):
        stream.expect_word(word)
    match_zone = stream.peek_word()
    if match_zone not in _REVEAL_DESTINATIONS:
        raise stream.error("expected the zone a matching card goes to")
    stream.advance()
    if not stream.accept_punct("."):
        raise stream.error("expected the miss sentence after the hit")
    # Two printed spellings of one complement. Petra Sphinx says "If it
    # doesn't", Vexing Arcanix says "Otherwise" — the same branch, so the same
    # reading rather than a second production. Both are consumed rather than
    # skipped, for the reason the docstring gives: a line omitting the miss
    # sentence is a card whose miss does nothing.
    if stream.accept_word("otherwise"):
        subject_words = ("they",)
    else:
        for word in ("if", "it", "doesn't"):
            stream.expect_word(word)
        subject_words = ("the", "player")
    if not stream.accept_punct(","):
        raise stream.error("expected the comma before the miss's destination")
    for word in subject_words:
        stream.expect_word(word)
    # Singular "they" takes the plural verb, so the two spellings of this
    # sentence differ by one letter: "the player **puts**" and "they **put**".
    if not stream.accept_word("puts", "put"):
        raise stream.error("expected the verb that moves the revealed card")
    for word in ("it", "into", "their"):
        stream.expect_word(word)
    miss_zone = stream.peek_word()
    if miss_zone not in _REVEAL_DESTINATIONS:
        raise stream.error("expected the zone a non-matching card goes to")
    stream.advance()
    # "…**and this artifact deals 2 damage to them**." (Vexing Arcanix.) The
    # rest of the miss branch, read here because "them" is the player this
    # paragraph has been about throughout — a sentence of its own would have no
    # antecedent and no way to know the guess missed.
    miss_damage = 0
    mark_damage = stream.mark()
    if stream.accept_word("and"):
        if accept_source_reference(stream) and stream.accept_word("deals"):
            amount = stream.peek()
            if amount is None or not str(amount.text).isdigit():
                raise stream.error("expected how much damage the miss deals")
            stream.advance()
            miss_damage = int(amount.text)
            for word in ("damage", "to", "them"):
                stream.expect_word(word)
        else:
            stream.reset(mark_damage)
    return ast.NameThenRevealTop(who, match_zone, miss_zone, miss_damage)


# The bare sentences. Each makes one choice and stops; a different printed
# sentence reads the record back. Moved whole from ``effects/game.py`` at
# Odyssey's Phase 0, in the order they stood there.


def _parse_choose_number(stream: TokenStream) -> ast.Statement | None:
    """``Choose a number between 0 and 7.`` (Shapeshifter.)

    Returns None without consuming anything for any other "choose" sentence, so
    the naming and modal productions beside it keep the ones they own. Both
    bounds must be printed numbers: a range with a word in it would be a
    different sentence, and reading only the first would silently halve the card.

    ``Choose a number greater than 0 and a color.`` (Scrying Glass.) Two
    printed variations on the same sentence, and both are read here rather than
    in productions of their own.

    The **bound** is one word where "between" is three, and it has no ceiling:
    "greater than 0" is CR 107.1's whole range from 1 upward, which the node
    carries as a None maximum. Read as a floor rather than folded into a
    "between" with an invented ceiling, because an invented ceiling is an
    answer the card would have accepted and the prompt would refuse.

    The **trailing conjunct** is an elision: "and a color" is "and choose a
    color" with the verb left out, so the general sentence joiner cannot read
    it — it looks for a statement after the "and" and finds a noun phrase. The
    verb is this production's, so supplying it is this production's job, and
    what comes back is the ordinary :class:`ast.Conjunction` of the two choices
    the joiner would have built. Both remain separate statements: they are
    answered separately, recorded separately and read back separately, and a
    fused node would be a kind whose only card is this one.

    Read only after a number bound, never as a way into the colour on its own:
    "choose a color" alone is ``_parse_choose_color``'s sentence below and must
    stay so, or the two productions compete for the same tokens.
    """
    mark = stream.mark()
    bounds: tuple[int, int | None] | None = None
    if stream.accept_phrase("choose", "a", "number", "between"):
        low = parse_amount(stream)
        if isinstance(low, ast.Fixed) and stream.accept_word("and"):
            high = parse_amount(stream)
            if isinstance(high, ast.Fixed) and low.value <= high.value:
                bounds = (low.value, high.value)
    elif stream.accept_phrase("choose", "a", "number", "greater", "than"):
        floor = parse_amount(stream)
        if isinstance(floor, ast.Fixed):
            # "Greater than 0" is strict (CR 107.1), so the smallest legal
            # answer is one above the printed number — the floor the prompt
            # offers and the resolver enforces.
            bounds = (floor.value + 1, None)
    elif stream.accept_phrase("choose", "a", "number") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        # "Choose a number." (Void.) No bound printed at all, which CR 107.1
        # reads as any whole number from zero up: the floor is the rule's and
        # the missing ceiling is the card's own answer.
        bounds = (0, None)
    if bounds is None:
        stream.reset(mark)
        return None
    chosen: ast.Statement = ast.ChooseNumber(bounds[0], bounds[1])
    conjunct = stream.mark()
    if stream.accept_phrase("and", "a", "color"):
        return ast.Conjunction((chosen, ast.ChooseColor()))
    stream.reset(conjunct)
    return chosen


def parse_hides_items(
    stream: TokenStream, chooser: "ast.PlayerRef"
) -> "ast.SecretlyChooseNumbers | None":
    """``<each player> hides at least one item, then all players reveal them
    simultaneously.`` The subject has been read, so this starts at the verb.
    (Goblin Game.)

    One production for the comma-joined pair, because neither half is a
    sentence about the game on its own: hiding with no reveal is a number
    nobody ever reads, and "all players reveal them" names a set only the
    first half makes. Together they are one event — a number per seat, secret
    until every seat has one — so they are one node.

    Every word is required. The floor must be a printed number ("at least
    **one**"), the reveal must be **simultaneous** — the word is the whole of
    the secrecy, and a sentence without it describes numbers named in turn,
    each in sight of the last — and the revealing set must be the hiding one:
    "all players" behind any subject but "each player" is two different sets
    of seats and a record half of whose entries nobody made.

    Refuses without consuming for anything that is not this shape.
    """
    mark = stream.mark()
    if not (
        chooser.kind == "each_player"
        and stream.accept_word("hides", "hide")
        and stream.accept_phrase("at", "least")
    ):
        stream.reset(mark)
        return None
    floor = parse_amount(stream)
    if not (
        isinstance(floor, ast.Fixed)
        and floor.value >= 0
        and stream.accept_word("item", "items")
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not (
        stream.accept_phrase(
            "then", "all", "players", "reveal", "them", "simultaneously"
        )
        and (stream.exhausted or stream.at_punct(".", ";"))
    ):
        stream.reset(mark)
        return None
    return ast.SecretlyChooseNumbers(chooser, floor.value)  # parse_hides_items


def parse_choose_card_name(stream: TokenStream) -> "ast.Statement | None":
    """``Choose a card name.`` (Foreshadow.)

    Beside :func:`_parse_choose_color` and refusing the same way: None with the
    cursor untouched for every other "choose" sentence, so the naming, modal and
    player productions keep the ones they own.

    ``Choose a creature card name.`` (Wood Sage.)

    Exactly four words and nothing after them but the punctuation that ends a
    clause — or five, with a card type in front of "card". Foreshadow prints
    ", **then** target opponent mills a card" behind it, which is the sentence
    loop's join and not this production's business.

    The type is read from the shared catalog rather than spelled here, so a
    card printing "artifact card name" needs no code; and it is *carried*
    rather than consumed, because a narrowing dropped at the parse is a prompt
    that offers more than the card allows — the quiet failure this repo names
    as an ability working more often than it should.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        stream.reset(mark)
        return None
    if not stream.accept_word("a", "an"):
        stream.reset(mark)
        return None
    card_type = None
    if (word := stream.peek_word()) in CARD_TYPES and word != "card":
        card_type = word
        stream.advance()
    if stream.accept_phrase("card", "name"):
        # "…**other than a basic land card name**." (Desperate Research.) The
        # second printed bound on CR 202.1's freedom, read whole or not at all.
        no_basics = stream.accept_phrase(
            "other", "than", "a", "basic", "land", "card", "name",
        )
        # …and never when the sentence behind it is Necromentia's "Search
        # target opponent's graveyard, hand, and library …": that card opens
        # with these same eleven words and reads two more sentences as one
        # paragraph (`naming._parse_name_and_strip`, the last resort behind
        # this production), so taking the first sentence here strands the rest
        # — the hazard `imperative_verbs` records beside the call.
        strips = no_basics and stream.at_punct(".") and stream.peek_word(1) == "search"
        if not strips and (stream.exhausted or stream.at_punct(".", ",")):
            return ast.ChooseCardName(
                card_type=card_type, other_than_basic_land=no_basics,
            )
    stream.reset(mark)
    return None


def _parse_choose_color(stream: TokenStream) -> ast.Statement | None:
    """``Choose a color.`` (Chromatic Armor's activated ability.)

    Beside :func:`_parse_choose_number` and refusing the same way: None with the
    cursor untouched for every other "choose" sentence, so the naming, modal and
    player productions keep the ones they own.

    Exactly three words and nothing after them. "Choose a color **and**…" and
    "choose a color of your choice" are sentences this has not read, and a
    reader that stopped at "color" would leave the rest to be dropped.

    **Or three words and a noun phrase**: "Choose a color **of a permanent you
    control**." (Meteor Crater.) The phrase narrows which colours may be named
    to the ones those permanents have, so it is read whole — by the noun
    reader, into ``among`` — or the sentence is not this one.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "color"):
        if stream.exhausted or stream.at_punct(".", ","):
            return ast.ChooseColor()
        if stream.accept_phrase("of", "a"):
            try:
                among = parse_object_filter(stream)
            except GrammarError:
                among = None
            if among is not None and (
                stream.exhausted or stream.at_punct(".", ",")
            ):
                return ast.ChooseColor(among=among)
    stream.reset(mark)
    return None


def _parse_choose_creature_type(stream: TokenStream) -> ast.Statement | None:
    """``Choose a creature type.`` (Outbreak.)

    :func:`_parse_choose_color`'s sentence one characteristic over, refusing the
    same way and for its reason: exactly four words and nothing after them but
    the punctuation that ends a clause, None with the cursor untouched for every
    other "choose" sentence.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "creature", "type"):
        if stream.exhausted or stream.at_punct(".", ","):
            return ast.ChooseCreatureType()
        # "Choose a creature type **other than Wall**." (Unnatural Selection.)
        # The one narrowing of the catalog a card prints, read against the
        # vocabulary (CR 205.3m) so a multiword type is one word here, and
        # carried on the node: an exclusion read and dropped is a choice the
        # card forbids, made anyway.
        if stream.accept_phrase("other", "than"):
            matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
            if matched is not None and matched[0] in CREATURE_TYPES:
                stream.advance(matched[1])
                if stream.exhausted or stream.at_punct(".", ","):
                    return ast.ChooseCreatureType(excluded=(matched[0],))
    stream.reset(mark)
    return None


def _parse_choose_opponent(stream: TokenStream) -> "ast.ChooseOpponent | None":
    """``Choose one of your opponents.`` (Goblin Festival.)

    Beside :func:`_parse_choose_color` and refusing the same way: None with the
    cursor untouched, so every other "choose" sentence keeps the reading it
    owns.

    The whole phrase and nothing after it, for that production's reason exactly:
    "choose an opponent **and a color**" is a sentence this has not read, and a
    reader that stopped at "opponents" would leave the rest to be dropped.

    "**One of your** opponents" rather than a bare "an opponent": the latter is
    a noun phrase the control-gift lowering already reads *inside* its own
    sentence (Rainbow Vale's "An opponent gains control of this land"), and one
    production reading both positions would make the two spellings compete for
    the same tokens.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "one", "of", "your", "opponents") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        return ast.ChooseOpponent()
    stream.reset(mark)
    return None


def parse_choose_card_type(
    stream: TokenStream, chooser: "ast.PlayerRef | None" = None
) -> "ast.ChooseCardType | None":
    """``chooses artifact, creature, land, or non-Aura enchantment``
    (Teferi's Realm) — the verb and its object list, without the subject.

    A printed *list* of card types, read as a list rather than assumed to be all
    of them: the card offers four, and "instant" is not among them because no
    permanent is one. A card offering a different three needs no code here.

    One option may name a subtype to exclude ("**non-Aura** enchantment"), which
    is one adjective and not a general noun phrase — a full filter here would be
    a second noun parser, and what the sentence is doing is naming an option a
    player picks by its printed words.

    ``Choose a card type.`` (Blood Oath) is the same sentence with the list left
    off, and it is the *unbounded* offer — CR 205.2a's card types, every one of
    them, which is what the card's own reminder text spells out. Read here
    rather than as a production of its own because what it produces is the same
    node with the same meaning: the difference is only whether the card printed
    the options or the rules supply them, and two productions would be two
    answers to "who may be chosen". The catalog comes from
    ``vocabulary.CARD_TYPES`` — data refreshed by ``fetch_vocabulary.py``, never
    a list spelled out here — and is sorted so the offer, the prompt and the
    deterministic default are the same order on every run.

    Non-consuming on refusal, because the ``chooses`` dispatcher hands every
    sentence it cannot finish to the readers below it and one that had eaten a
    word would replace their refusals with its own.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    if stream.accept_phrase("a", "card", "type"):
        # The whole phrase and nothing after it, exactly as the printed list
        # below requires: "choose a card type **and a color**" is a sentence
        # this has not read, and stopping at "type" would leave the rest to be
        # dropped.
        if stream.exhausted or stream.at_punct(".", ","):
            return ast.ChooseCardType(tuple(sorted(CARD_TYPES)), chooser)
        stream.reset(mark)
        return None
    options: list[str] = []
    while True:
        probe = stream.mark()
        prefix = ""
        # "non-Aura enchantment" lexes as one hyphenated word plus the noun,
        # the same shape "phased-out" takes one family over.
        word = stream.peek_word() or ""
        if word.startswith("non-"):
            excluded = word[4:]
            if not excluded or excluded not in ALL_SUBTYPES:
                stream.reset(mark)
                return None
            stream.advance()
            prefix = f"non-{excluded} "
        noun = stream.peek_word()
        if noun is None or singular(noun) not in CARD_TYPES:
            stream.reset(probe)
            break
        stream.advance()
        options.append(prefix + singular(noun))
        if stream.accept_punct(","):
            stream.accept_word("or")
            continue
        if stream.accept_word("or"):
            continue
        break
    # Two is the floor: "chooses a creature" is a different sentence entirely
    # (a permanent, not a type), and a one-item "list" would let this production
    # claim it.
    if len(options) < 2 or not (stream.exhausted or stream.at_punct(".", ",")):
        stream.reset(mark)
        return None
    return ast.ChooseCardType(tuple(options), chooser)


def _parse_choose_player_who_cast(stream: TokenStream) -> "ast.Statement | None":
    """``Choose a player who cast one or more sorcery spells this turn.``
    (Backdraft.)

    Returns None without consuming anything for any other "choose" sentence,
    exactly as the number and hand-pick productions beside it do, so the naming
    productions behind them keep their readings.

    The type and the minimum are both read off the words. "One or more" is the
    ordinary way Magic prints "at least one" and a card printing "two or more"
    is the same sentence with one number changed — so it is a quantity, not a
    phrase to match. The type must be a real card type: "a player who cast one
    or more **spells**" is a wider set, and reading it as this one would offer a
    choice the card never allowed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("choose", "a", "player", "who", "cast"):
        stream.reset(mark)
        return None
    minimum = parse_amount(stream)
    if not (isinstance(minimum, ast.Fixed) and stream.accept_phrase("or", "more")):
        stream.reset(mark)
        return None
    card_type = stream.peek_word()
    if card_type is None or singular(card_type) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("spells", "this", "turn"):
        stream.reset(mark)
        return None
    return ast.ChoosePlayerWhoCast(singular(card_type), minimum.value)
