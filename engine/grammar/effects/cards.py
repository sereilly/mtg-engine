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
from ..amounts import parse_amount, parse_equal_to
from ..errors import GrammarError
from ..lexer import (MANA, render)
from ..nouns import parse_object_filter
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import _accept_self_reference, _parse_card_alternatives, _parse_zone


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


def _parse_exile_cost_sacrifices(stream: TokenStream) -> ast.Statement | None:
    """``Exile this <noun> and those <noun> cards.`` (Sword of the Ages.)

    Returns None quietly on anything else, like the two exile productions
    beside it, so an ordinary exile keeps its own refusal.

    Both halves are required. "Exile this artifact" alone is the source leaving
    the battlefield — a sentence the ordinary production already reads, and a
    different effect from this one, which reaches into a graveyard for a set the
    cost put there. Reading only the first half and stopping is what the
    ordinary production would do, so this is tried in front of it.
    """
    mark = stream.mark()
    stream.expect_word("exile")
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the source's own noun ("artifact")
    if not stream.accept_phrase("and", "those"):
        stream.reset(mark)
        return None
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()   # the sacrificed set's noun ("creature")
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    return ast.ExileCostSacrifices()


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


def _parse_put_exiled_with_source(stream: TokenStream) -> ast.Statement | None:
    """``Put all cards exiled with this artifact into their owner's hand.``
    (Knowledge Vault's ``{0}`` ability; its leaves-the-battlefield trigger says
    "exiled with **it** … into their owner's graveyard".)

    Returns None with the cursor untouched on anything else, because every
    other "put …" in the pool is counters or a card from a named zone, and this
    production has to be tried before them without being able to shadow them.

    The self-reference is required and consumed in full: "cards exiled with
    *this artifact*" is CR 610.3's linked pile, and a wording naming another
    permanent would be a different pile this cannot find.
    """
    mark = stream.mark()
    # Two printed verbs for one effect. Knowledge Vault says "**Put all cards**
    # exiled with this artifact **into** their owner's hand"; Safe Haven says
    # "**Return each card** exiled with this land **to** the battlefield under
    # its owner's control". Same linked pile (CR 610.3), same drain, same
    # handler — the difference is which zone the cards are going to and the
    # preposition English wants in front of it.
    if stream.accept_phrase("put", "all", "cards", "exiled", "with"):
        preposition = "into"
    elif stream.accept_phrase("return", "each", "card", "exiled", "with"):
        preposition = "to"
    else:
        stream.reset(mark)
        return None
    if not (stream.accept_word("it") or _accept_self_reference(stream)):
        stream.reset(mark)
        return None
    stream.expect_word(preposition)
    zone = _parse_zone(stream)
    # "…**under its owner's control**" (CR 400.3 spelled out, because a
    # battlefield has no possessive of its own to carry it). Read as the zone's
    # owner rather than dropped: the lowering *requires* an owner reference —
    # a linked pile goes to each card's own owner — so silently losing the
    # clause would refuse the line, and consuming it without recording it would
    # let a wording naming one player through.
    if zone.owner is None and zone.name == "battlefield" and (
        stream.accept_phrase("under", "its", "owner", "'s", "control")
        or stream.accept_phrase("under", "their", "owner", "'s", "control")
    ):
        zone = ast.Zone(zone.name, ast.PlayerRef("owner"))
    return ast.PutExiledWithSource(zone)


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


def _accept_hand_to_library_tail(
    stream: TokenStream, possessive: str
) -> bool:
    """``… on top of <possessive> library in any order``, consumed whole.

    Shared by the two printed spellings so they cannot come to disagree about
    the destination. Every word is required. Dropping "on top of" would let a
    sentence putting cards on the *bottom* read as this one, and dropping "in
    any order" would silently discard the ordering the card gives the player —
    the rider bug this grammar refuses by construction. The possessive is the
    caller's, because it agrees with the subject the sentence already named:
    "**your** hand … **your** library", "**their** hand … **their** library".
    """
    return bool(
        stream.accept_phrase("on", "top", "of", possessive, "library")
        and stream.accept_phrase("in", "any", "order")
    )


def _parse_put_hand_cards_on_library(
    stream: TokenStream,
) -> "ast.PutHandCardsOnLibrary | None":
    """``Put two cards from your hand on top of your library in any order.``
    (Brainstorm.)

    The bare imperative, so the player is "you" (CR 608.2: an instruction with
    no printed subject is about the spell's controller). Refuses without
    consuming, because "put" opens a counter, a permanent and three zone moves;
    every one of those keeps the production it already had.
    """
    mark = stream.mark()
    if not stream.accept_word("put"):
        return None
    count = _accept_hand_card_count(stream)
    if count is None or not stream.accept_phrase("from", "your", "hand"):
        stream.reset(mark)
        return None
    if not _accept_hand_to_library_tail(stream, "your"):
        stream.reset(mark)
        return None
    return ast.PutHandCardsOnLibrary(ast.PlayerRef("you"), count)


def _parse_player_puts_hand_cards_on_library(
    stream: TokenStream, player: ast.PlayerRef
) -> "ast.PutHandCardsOnLibrary | None":
    """``<player> chooses three cards from their hand and puts them on top of
    their library in any order.`` (Stunted Growth.)

    One sentence and one action: "chooses … and puts them" names the choice and
    the move the choice is for, which is the same prompt. Reading the halves as
    two steps would leave "them" bound to nothing.

    Refuses without consuming, so "chooses a card name…" (Petra Sphinx) and
    "chooses a creature…" (Takklemaggot) keep their own productions.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
        return None
    count = _accept_hand_card_count(stream)
    if count is None or not stream.accept_phrase("from", "their", "hand"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "puts", "them"):
        stream.reset(mark)
        return None
    if not _accept_hand_to_library_tail(stream, "their"):
        stream.reset(mark)
        return None
    return ast.PutHandCardsOnLibrary(player, count)


def _accept_hand_card_count(stream: TokenStream) -> "ast.Amount | None":
    """``two cards`` / ``a card`` — how many leave the hand.

    The noun is required and is what tells this apart from "put **a counter**"
    and "put **that card**": a bare number with nothing after it is not this
    sentence.
    """
    mark = stream.mark()
    try:
        count = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_word("cards", "card"):
        stream.reset(mark)
        return None
    return count
