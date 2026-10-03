"""Printed paragraphs that turn on a **choice the board cannot show** — a card
name, or a card picked out of a hidden hand.

Split out of ``paragraphs`` at Prophecy's Phase 0, when that module stood at
963 of the guard's 1,000 lines with several of the set's groups about to land
multi-sentence effects in it. Every production here is a paragraph for
``paragraphs``' own reason: the sentences after the first read what the first
chose, so parsed apart each would test a record nobody wrote. What makes them a
family of their own is **what** the first sentence chooses. Necromentia,
Demonic Consultation, Nebuchadnezzar, Petra Sphinx and Vexing Arcanix name a
card, and Stronghold Gambit's players each pick one face down from their hand —
in every case a value that exists only in a player's head until a later
sentence checks it. The rest of each paragraph *is* that check: a search for
the name, a reveal until it turns up, a random reveal, a reveal of the top
card, a reveal of the picks.

The name is the lowering side's. ``statement_dispatch_naming.py`` lowers all
five nodes these productions return, under a docstring that says everything
there "reads a **decision** rather than a board", so the mirror re-forms rather
than a third word arriving for one idea. Two near misses, both checked:
``names.py`` is a different question, under ``nouns`` — the literal string a
card prints after "named", which no player chooses — and ``choices.py`` reads
"Choose <something>." by probing the *next* sentence through
``parse_statement``. Nothing here calls back into the sentence parser, which is
what keeps this module beside ``paragraphs``, below ``statements``, rather than
beside ``choices``.

Two dispatchers call in, at the words each paragraph opens on: the imperative
"choose" arm of ``imperative_verbs`` (Demonic Consultation, then
Nebuchadnezzar, then — after the bare naming sentence ``effects/game`` reads —
Necromentia as the last resort) and the seat-subject "chooses" arm of
``player_verbs`` (Stronghold Gambit, then Petra Sphinx's guess). Every
production but the last in each arm declines without consuming on a paragraph
that is not its own, which is what lets the arms try them in order.
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
from .vocabulary import COLOR_WORDS, CREATURE_TYPES


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
