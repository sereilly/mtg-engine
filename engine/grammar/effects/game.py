"""Effects on the whole game.

Winning, drawing, losing, extra turns, ending the turn, ante, exchanging life
totals, the coin flips and the choices a sentence makes, and the Aura `enchant`
line.

Grouped because each is a sentence about the game state rather than about one
permanent's characteristics, and none of them shares vocabulary with another
family.

**Token creation left at Mirage's second wave**, when the token production grew
a board-count multiplier and this module crossed the 1,000-line guard. The cut
is CR's own: a token is an object the game *creates* (CR 111.1), where
everything here changes the state a **player** is in. It went to
``effects/tokens.py``, reusing the name ``lowering/tokens.py`` has carried since
Fallen Empires, so the mirror re-forms rather than forking.
"""

from .. import ast
from ..amounts import parse_amount
from ..errors import GrammarError
from ..nouns import parse_object_filter
from ..references import parse_player_ref
from ..stream import TokenStream
from ..durations import _parse_duration
from ..vocabulary import ALL_SUBTYPES, CARD_TYPES, NUMBER_WORDS, singular


def _parse_wins(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> wins the game`` (CR 104.2b)."""
    stream.expect_word("wins", "win")
    stream.expect_word("the")
    stream.expect_word("game")
    player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
    return ast.WinGame(player)


def _parse_game_is_a_draw(stream: TokenStream) -> ast.Statement | None:
    """``The game is a draw.`` (CR 104.4c.)

    The one game-outcome sentence with no subject, so it cannot go through
    ``_parse_subject_verb``'s noun phrase. Returns None without consuming
    anything when the line merely *starts* with "the", so every other production
    beginning that way is unaffected.
    """
    mark = stream.mark()
    if stream.accept_phrase("the", "game", "is", "a", "draw"):
        return ast.DrawGame()
    stream.reset(mark)
    return None


def _parse_coin_flip_stakes_loop(stream: TokenStream) -> ast.Statement | None:
    """``Flip a coin. If you win the flip, you gain N life and target opponent
    loses N life, and you decide whether to flip again. If you lose the flip,
    you lose N life and that opponent gains N life, and that player decides
    whether to flip again. [Double the life stakes with each flip.]``
    (Game of Chaos.)

    Read whole, for the reason Mana Clash's flip loop is: every sentence after
    the first reads a flip only the first produces, and the offer that repeats
    the paragraph is answered by whichever player the *result* names — which no
    sentence read on its own can say.

    It lives with the `game` family rather than in `paragraphs`, where the pool's
    other whole-paragraph productions sit, because that module is at the size
    guard and this paragraph's node and lowering are `ast/game.py`'s and
    `lowering/game.py`'s: putting it here re-forms the mirror instead of
    forking it, and ``_parse_flip_coin`` beside it already reads the first
    sentence on its own.

    Every fixed word is *expected* once the second sentence has been entered,
    not accepted, for that production's stated reason: each is a way the
    paragraph could mean something smaller and still parse. The four printed
    amounts must be the one quantity they are printed as — a production that let
    them differ would compile a card nobody printed — and the closing sentence
    is genuinely optional, so that reading it changes what happens rather than
    being consumed and dropped.
    """
    mark = stream.mark()
    if not stream.accept_phrase("flip", "a", "coin"):
        return None
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "win", "the", "flip"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "gain"):
        stream.reset(mark)
        return None
    stake = parse_amount(stream)
    if not stream.accept_phrase("life", "and", "target", "opponent", "loses"):
        stream.reset(mark)
        return None
    amounts = [stake, parse_amount(stream)]
    if not stream.accept_word("life"):
        raise stream.error("expected the life the opponent loses")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "and", "you", "decide", "whether", "to", "flip", "again"
    ):
        raise stream.error("expected the offer to flip again")
    stream.accept_punct(".")
    if not stream.accept_phrase("if", "you", "lose", "the", "flip"):
        raise stream.error("expected the losing half of the flip")
    stream.accept_punct(",")
    if not stream.accept_phrase("you", "lose"):
        raise stream.error("expected the life you lose")
    amounts.append(parse_amount(stream))
    if not stream.accept_phrase("life", "and", "that", "opponent", "gains"):
        raise stream.error("expected the life that opponent gains")
    amounts.append(parse_amount(stream))
    if not stream.accept_word("life"):
        raise stream.error("expected the life the opponent gains")
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "and", "that", "player", "decides", "whether", "to", "flip", "again"
    ):
        raise stream.error("expected the losing half's offer to flip again")
    stream.accept_punct(".")
    doubling = stream.accept_phrase(
        "double", "the", "life", "stakes", "with", "each", "flip"
    )
    if any(other != stake for other in amounts[1:]):
        raise stream.error("the four printed stakes must be one quantity")
    return ast.CoinFlipStakesLoop(stake, bool(doubling))


def _parse_flip_coin(stream: TokenStream) -> ast.Statement | None:
    """``Flip a coin.`` (CR 705.1.)

    Returns None without consuming anything for any other sentence starting
    "flip" — Chaos Orb's "flip it onto the battlefield from a height of at least
    one foot" is a different action, and its card hook must keep getting it.
    """
    mark = stream.mark()
    # "**You** flip a coin." (Amulet of Quoz.) CR 705.1 gives the flip a
    # flipper, and both spellings name the same one: the controller of the
    # effect, which is who ``flip_coin`` records the result for and who "if you
    # win the flip" then asks about. So the subject is a spelling, read here
    # rather than as a second production — two readers of one sentence is how
    # the two come to disagree about whose flip it is.
    stream.accept_word("you")
    if stream.accept_phrase("flip", "a", "coin"):
        return ast.FlipCoin()
    stream.reset(mark)
    return None


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


def _parse_count_objects(stream: TokenStream) -> "ast.CountObjects | None":
    """``Count the number of permanents.`` (Chaos Moon.)

    CR 107.1's number, taken once and named for the sentences behind it — see
    :class:`ast.CountObjects` for why the card prints this instead of a third
    "if", and why reading it as a sentence rather than folding it into the two
    conditions is what keeps both branches reachable.

    The noun phrase is read rather than assumed. "Permanents" is every object on
    every battlefield (CR 110.1), and a card counting something narrower is this
    same sentence with a different phrase — which is what makes the count
    payload rather than a kind.

    Refuses without consuming for anything else opening "count", and requires
    the sentence to *end* there: "count the number of permanents **and** …" is a
    sentence this has not read, and a reader that stopped early would leave the
    rest to be dropped.
    """
    mark = stream.mark()
    if not stream.accept_phrase("count", "the", "number", "of"):
        return None
    try:
        counted = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if counted.zone not in (None, "battlefield"):
        # A count out of a hand or a library is a different question with a
        # different answer, and nothing reads one back yet. Refusing keeps the
        # line's refusal rather than recording a number off the wrong zone.
        stream.reset(mark)
        return None
    if not (stream.exhausted or stream.at_punct(".", ";")):
        stream.reset(mark)
        return None
    return ast.CountObjects(counted)


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
    if stream.accept_phrase("choose", "a", "creature", "type") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        return ast.ChooseCreatureType()
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


def _parse_enchant(stream: TokenStream) -> ast.Statement:
    """``Enchant creature`` — an Aura's attachment restriction (CR 702.5).

    Not an effect: it declares what the Aura can be attached to. Parsed so the
    line is accounted for; the engine's attachment handling is driven elsewhere.
    """
    stream.expect_word("enchant")
    filt = parse_object_filter(stream, allow_bare=True)
    # "Enchant creature card in a graveyard" (Animate Dead).
    if stream.accept_word("card"):
        if stream.accept_word("in"):
            stream.accept_word("a", "an", "the")
            stream.expect_word("graveyard")
    return ast.RawEffect(f"enchant:{filt}")


def _parse_extra_turn(
    stream: TokenStream, player: "ast.PlayerRef | None" = None
) -> ast.Statement:
    """``Take an extra turn after this one.`` (Time Walk, Time Vault.)
    ``Target player takes an extra turn after this one.`` (Time Warp.)

    The count is the article or a written-out number ("Take two extra turns
    after this one.", Teferi, Master of Time) — never defaulted, so a quantity
    the amount parser cannot read fails the line instead of quietly granting
    one turn. "after this one" is required for the same reason — it is what
    says the turns are taken immediately, and a card that placed it elsewhere
    would be a different effect.

    *player* is the printed subject when the sentence has one, handed in by
    ``subject_verb`` with the cursor on the verb. Absent, the subject is the
    effect's controller (CR 109.5) — the bare imperative every other card in
    this family prints. One production either way: who takes the turn is the
    node's own field, and a second production would be the same sentence read
    twice.
    """
    stream.expect_word("take", "takes")
    if stream.accept_word("an"):
        count = 1
    else:
        amount = parse_amount(stream)
        if not isinstance(amount, ast.Fixed) or amount.value < 1:
            raise stream.error("expected a fixed number of extra turns")
        count = amount.value
    stream.expect_word("extra")
    stream.expect_word("turn", "turns")
    if not stream.accept_phrase("after", "this", "one"):
        raise stream.error("expected 'after this one'")
    return ast.ExtraTurn(player or ast.PlayerRef("you"), count)


#: The phases a printed "additional <x> phase" can name, and the engine phase
#: each one is. Held to the phases ``Game.enter_turn_phase`` can actually begin
#: by ``tests/rules/test_turn_phases.py``: a word admitted here that no driver
#: can enter would be a sentence parsed, lowered, recorded and then silently
#: not taken, which is what CR 500.8's machinery did for its whole life before
#: a card needed it. "beginning" is deliberately absent - CR 500.10's Obeka
#: adds one and nothing in this engine can run an upkeep step outside the start
#: of a turn, so the line refuses rather than pretending.
_ADDITIONAL_PHASE_WORDS = {"combat": "combat", "main": "postcombat_main"}


def parse_extra_phases(stream: TokenStream) -> ast.Statement | None:
    """``After this main phase, there is an additional combat phase followed by
    an additional main phase.`` (Relentless Assault, CR 500.8.)

    Returns None without consuming when the sentence does not open "after
    this", so every other sentence keeps its own reading; once that opener has
    matched the production is committed and every remaining token has to be one
    it knows, because a tail dropped here would be an extra phase created with
    half its printed order.

    An extra *main* phase is a postcombat one whatever it follows, and the rule
    says so about this exact card: CR 505.1a, "only the first main phase of the
    turn is a precombat main phase ... It is also true of a turn in which an
    effect has caused an additional combat phase and an additional main phase to
    be created." So the created phase must not fire "at the beginning of your
    first main phase".
    """
    if not stream.at_word("after"):
        return None
    mark = stream.mark()
    stream.advance()
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    after = _accept_phase_word(stream)
    if after is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        raise stream.error("expected ',' after the phase this sentence names")
    stream.expect_word("there")
    stream.expect_word("is")
    phases = [_expect_additional_phase(stream)]
    # "followed by an additional main phase" - the printed conjunction, and the
    # only one: "and" would leave the order unstated, and CR 500.8 makes the
    # order of a created run the whole of what it says.
    while stream.accept_phrase("followed", "by"):
        phases.append(_expect_additional_phase(stream))
    return ast.ExtraPhases(after, tuple(phases))


def _accept_phase_word(stream: TokenStream) -> str | None:
    """The phase a "this <x> phase" reference names, or None."""
    for word in _ADDITIONAL_PHASE_WORDS:
        if stream.at_word(word):
            mark = stream.mark()
            stream.advance()
            if stream.accept_word("phase"):
                return word
            stream.reset(mark)
            return None
    # "After this phase, ..." - the phase in progress, whichever it is.
    if stream.accept_word("phase"):
        return "this"
    return None


def _expect_additional_phase(stream: TokenStream) -> str:
    """``an additional <x> phase`` as the *engine* phase it creates.

    The printed word is translated here rather than at lowering because this is
    where the vocabulary is: a word with no phase behind it must fail the line,
    and the table that answers "which phase is that" is the same table that
    answers "is that a phase at all".
    """
    stream.expect_word("an")
    stream.expect_word("additional")
    word = _accept_phase_word(stream)
    if word is None or word not in _ADDITIONAL_PHASE_WORDS:
        raise stream.error("expected 'an additional <combat|main> phase'")
    return _ADDITIONAL_PHASE_WORDS[word]


def _parse_end_the_turn(stream: TokenStream) -> ast.Statement:
    """``End the turn.`` (Discontinuity.)

    Three words and every one of them required. "End the turn" is CR 724.1's
    expedited process; "end of turn" is a *duration* and "at the beginning of
    the end step" is a trigger, and both are read elsewhere. Consuming only
    "end" would let either of those reach this production and lower into a
    process that exiles the stack.
    """
    stream.expect_word("end")
    stream.expect_word("the")
    stream.expect_word("turn")
    return ast.EndTheTurn()


def _parse_ante(
    stream: TokenStream, subject: ast.PlayerRef | None = None
) -> ast.Statement | None:
    """``[<player>] ante[s] the top card of <possessive> library`` (CR 407).

    Two printed shapes, one production. Demonic Attorney prints the subject
    ("Each player antes the top card of their library"); Rebirth's offer prints
    none, because the offering player is the one the ``may`` in front of it
    named ("Each player may ante the top card of their library").

    So **who antes is the printed subject where there is one, and the possessive
    where there is not**. That is not a fallback: with no subject the only word
    naming the player is "your"/"their", and reading it is reading the card.
    "Their" back-refers exactly the way ``references.parse_player_ref`` reads
    "they" — as ``that_player`` — so the offer binds it per seat and Demonic
    Attorney's every-seat loop never sees it.

    Refuses without consuming anything else, so any other sentence opening with
    the word keeps the refusal it has today.
    """
    mark = stream.mark()
    if not stream.accept_word("antes", "ante"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("the", "top", "card", "of"):
        stream.reset(mark)
        return None
    if stream.accept_word("your"):
        possessive = ast.PlayerRef("you")
    elif stream.accept_word("their") or stream.accept_phrase("his", "or", "her"):
        possessive = ast.PlayerRef("that_player")
    else:
        stream.reset(mark)
        return None
    if not stream.accept_word("library"):
        stream.reset(mark)
        return None
    return ast.Ante(subject if subject is not None else possessive)


def _parse_exchange_life_totals(stream: TokenStream) -> ast.Statement:
    """``Exchange life totals with <player>.`` (Mirror Universe.)

    Filed with the game family rather than beside ``_parse_exchange_control``
    in ``board``: what is exchanged is a life total, and the family a
    production belongs to is the family of what it acts on. The two share only
    the printed verb, and the dispatcher branches on the word after it.

    The other party goes through ``parse_player_ref``, so "target opponent",
    "target player" and "each opponent" are read by the same noun phrase every
    other sentence about a player uses; what the handler can actually exchange
    with is the lowering's question.
    """
    stream.expect_word("exchange")
    if not stream.accept_phrase("life", "totals"):
        raise stream.error("expected 'life totals' after 'exchange'")
    if not stream.accept_word("with"):
        raise stream.error("expected 'with' after 'exchange life totals'")
    player = parse_player_ref(stream)
    if player is None:
        raise stream.error("expected the player to exchange life totals with")
    return ast.ExchangeLifeTotals(player)


def _parse_life_total_becomes(stream: TokenStream) -> ast.Statement | None:
    """``<player>'s life total becomes <N>`` / ``your life total becomes <N>``.

    CR 119.5: this is a gain or a loss of the difference, but the printed number
    is the *result*, so the sentence cannot be read as either one until the
    handler knows the current total. Its own node for that reason rather than a
    ``GainLife`` with a flag.

    Read before ``_parse_subject_verb``'s noun phrase because the subject is a
    possessive *of a player* — "that player's life total" — which the recipient
    parser reads down to the player and then chokes on. Refuses without
    consuming, so every other possessive sentence keeps its reading.
    """
    mark = stream.mark()
    if stream.accept_word("your"):
        player = ast.PlayerRef("you")
    else:
        player = parse_player_ref(stream)
        if player is None or not stream.accept_word("'s"):
            stream.reset(mark)
            return None
    if not stream.accept_phrase("life", "total"):
        stream.reset(mark)
        return None
    if not stream.accept_word("becomes", "become"):
        stream.reset(mark)
        return None
    try:
        amount = parse_amount(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.SetLifeTotal(player, amount)




#: The steps a printed "skip your next <step>" may name, mapped to the internal
#: step name ``Game.skip_next_step`` is keyed by. A table rather than a free
#: word, because a step this engine does not run would be a skip that never
#: fires and a card that reports supported.
_SKIPPABLE_STEPS: dict[str, str] = {
    "draw": "draw",
    "untap": "untap",
}

#: The **phases** a printed "skip your next <phase> phase" may name, mapped to
#: the phase name ``Game.skip_next_phase`` is keyed by (``_constants``'
#: ``_PHASE_STEPS``). A table beside the step one and not a row inside it,
#: because CR 500.11 counts the two in different buckets and the engine runs
#: them at different levels: ``_phase_steps`` spends a step skip and
#: ``next_unskipped_phase_after`` spends a phase one.
#:
#: "combat" used to sit in the table above, which was the mistake this split
#: fixes: there is no *step* called "combat" — the combat phase has five, all
#: named — so a card printing "skip your next combat step" would have compiled,
#: reported supported, recorded a skip against a step name nothing runs, and
#: skipped nothing. Unreachable in the pool (nothing prints the word "step"
#: after "combat"), which is why it never showed; the row was a claim the
#: engine could not honour rather than a live bug.
_SKIPPABLE_PHASES: dict[str, str] = {
    "combat": "combat",
}


def _parse_skip_step(stream: TokenStream, subject) -> ast.Statement:
    """``<player> skip[s] their next <step> step.`` (Ivory Gargoyle.)

    CR 500.7: a skipped step never begins, and CR 614.10 makes the skip a
    replacement effect. **Whose** step is half the sentence — a skip stored
    against the step's name alone eats whichever seat's draw step comes round
    first, which on an opponent's turn is the wrong player's — so the seat rides
    the node and the lowering carries it into the payload.

    Only "your next" today. An unbounded "skip your draw steps" is a continuous
    effect rather than a one-shot and refuses here rather than borrowing this
    one's arithmetic.

    **"Skip your next turn" is read here and lowers elsewhere.** It shares every
    word of this production's opening — one printed shape, so one production
    reads it — but CR 500.11 counts turns in a different bucket from steps
    (``Game.skip_next_turn`` against ``Game.skip_next_step``), so it returns
    :class:`~engine.grammar.ast.game.SkipTurn` and the two never share a
    handler. It also takes no trailing "step", which is what keeps the two
    apart in the token stream.
    """
    stream.expect_word("skips", "skip")
    # "…you skip your **draw step this turn**." (Elfhame Sanctuary.) The same
    # step skip with its step named by the turn it belongs to instead of as
    # "your next" — read whole (possessive, step, "step", window) or not at
    # all, so "skip your draw steps" and every other unbounded spelling keeps
    # the refusal below.
    mark = stream.mark()
    if stream.accept_word("your", "their"):
        named = _SKIPPABLE_STEPS.get(stream.peek_word() or "")
        if named is not None:
            stream.advance()
            if stream.accept_phrase("step", "this", "turn"):
                return ast.SkipStep(subject, named, this_turn=True)
    stream.reset(mark)
    if not (stream.accept_phrase("your", "next") or stream.accept_phrase("their", "next")):
        raise stream.error("expected 'your next' after 'skip'")
    word = stream.peek_word()
    if word == "turn":
        # "You skip your next turn." (Chronatog.) No "step" follows, and the
        # production still has to consume its whole line — so the advance is
        # here rather than after the shared trailing-word check below, which
        # would demand a word this sentence does not print.
        stream.advance()
        return ast.SkipTurn(subject)
    # "…skips their next **combat phase** this turn." (Moment of Silence.)
    # CR 506.1: the combat phase has five steps and is not one, so the printed
    # noun decides which counter the skip goes into — and the two are read here
    # together rather than by two productions, because every word before them is
    # shared and a second production would have to re-read all of it.
    phase = _SKIPPABLE_PHASES.get(word or "")
    if phase is not None and stream.peek_word(1) == "phase":
        stream.advance()
        stream.advance()
        # "**this turn**" — the window the card bounds the skip to. Consumed and
        # carried rather than skipped: a phase skip that outlived its turn would
        # eat the target's combat phase on their *next* turn, which is a
        # strictly larger effect than the card prints. Optional because no rule
        # requires it; a card printing the phase without it is an unbounded skip
        # and says so by carrying no window.
        this_turn = bool(stream.accept_phrase("this", "turn"))
        return ast.SkipPhase(subject, phase, this_turn=this_turn)
    step = _SKIPPABLE_STEPS.get(word or "")
    if step is None:
        raise stream.error(
            f"no skippable step or phase named {word!r} (and only a turn may "
            "be skipped without the word 'step')"
        )
    stream.advance()
    if not stream.accept_word("step"):
        raise stream.error("expected 'step' after the step's name")
    return ast.SkipStep(subject, step)


def parse_extra_land_plays(stream: TokenStream) -> "ast.ExtraLandPlays | None":
    """``You may play up to three additional lands this turn.`` (Summer Bloom.)

    CR 305.2's ceiling raised for one turn. Read as **one** production rather
    than as the ordinary "you may <action>" wrapper, because the "may" is the
    permission and not an offer: nothing is asked of anybody as the spell
    resolves, and the wrapper would put a yes/no prompt in front of a card that
    prints no decision. That is why it is tried in ``statements.py`` *ahead* of
    the "you may" branch.

    Non-consuming on every refusal. Two sentences it must leave alone sit one
    word away and both belong to ``engine/land_play_allowance.py``'s derivation
    table — "You may play **any number of** lands on each of your turns"
    (Fastbond) and "You may play an additional land **on each of your turns**" —
    and a production that consumed either would take that table's line and give
    it to nobody, since a parsed-but-unlowered line is still parsed
    (``derived.py`` is consulted only where the grammar refuses in full).
    The duration is what separates them, so the duration is required.
    """
    mark = stream.mark()
    if not stream.accept_word("you"):
        return None
    if not stream.accept_word("may"):
        stream.reset(mark)
        return None
    if not stream.accept_word("play"):
        stream.reset(mark)
        return None
    # "up to three additional lands" (Summer Bloom) and "an additional land"
    # (the shape a one-turn printing of Fastbond's sibling would take) are the
    # same clause with the count spelled differently, so the count is payload.
    # "up to" is CR 601.2c's ceiling and adds nothing here: a land drop is a
    # permission a player uses or does not, so "up to three more" and "three
    # more" grant the same thing.
    stream.accept_phrase("up", "to")
    amount = 1
    if not stream.accept_word("an", "a"):
        word = stream.peek_word()
        number = NUMBER_WORDS.get(word or "")
        if number is None:
            stream.reset(mark)
            return None
        stream.advance()
        amount = number
    if not stream.accept_word("additional"):
        stream.reset(mark)
        return None
    if not stream.accept_word("land", "lands"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind != "this_turn":
        # The derivation table's two sentences end here, in the parse, with
        # nothing consumed — see the docstring.
        stream.reset(mark)
        return None
    return ast.ExtraLandPlays(ast.PlayerRef("you"), amount, duration)
