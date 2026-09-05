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
from ..phrases import _parse_duration
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
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "number", "between"):
        low = parse_amount(stream)
        if isinstance(low, ast.Fixed) and stream.accept_word("and"):
            high = parse_amount(stream)
            if isinstance(high, ast.Fixed) and low.value <= high.value:
                return ast.ChooseNumber(low.value, high.value)
    stream.reset(mark)
    return None


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

    Exactly four words and nothing after them but the punctuation that ends a
    clause. Foreshadow prints ", **then** target opponent mills a card" behind
    it, which is the sentence loop's join and not this production's business.
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "card", "name") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        return ast.ChooseCardName()
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
    """
    mark = stream.mark()
    if stream.accept_phrase("choose", "a", "color") and (
        stream.exhausted or stream.at_punct(".", ",")
    ):
        return ast.ChooseColor()
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

    Non-consuming on refusal, because the ``chooses`` dispatcher hands every
    sentence it cannot finish to the readers below it and one that had eaten a
    word would replace their refusals with its own.
    """
    mark = stream.mark()
    if not stream.accept_word("chooses", "choose"):
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


def _parse_extra_turn(stream: TokenStream) -> ast.Statement:
    """``Take an extra turn after this one.`` (Time Walk, Time Vault.)

    The count is the article or a written-out number ("Take two extra turns
    after this one.", Teferi, Master of Time) — never defaulted, so a quantity
    the amount parser cannot read fails the line instead of quietly granting
    one turn. "after this one" is required for the same reason — it is what
    says the turns are taken immediately, and a card that placed it elsewhere
    would be a different effect.
    """
    stream.expect_word("take")
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
    return ast.ExtraTurn(ast.PlayerRef("you"), count)


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
    "combat": "combat",
}


def _parse_skip_step(stream: TokenStream, subject) -> ast.Statement:
    """``<player> skip[s] their next <step> step.`` (Ivory Gargoyle.)

    CR 500.7: a skipped step never begins, and CR 614.10 makes the skip a
    replacement effect. **Whose** step is half the sentence — a skip stored
    against the step's name alone eats whichever seat's draw step comes round
    first, which on an opponent's turn is the wrong player's — so the seat rides
    the node and the lowering carries it into the payload.

    Only "your next" today. "Skip your next turn" is a different rule (CR
    500.11's turn counter) with its own handler, and an unbounded "skip your
    draw steps" is a continuous effect rather than a one-shot; both refuse here
    rather than borrowing this one's arithmetic.
    """
    stream.expect_word("skips", "skip")
    if not (stream.accept_phrase("your", "next") or stream.accept_phrase("their", "next")):
        raise stream.error("expected 'your next' after 'skip'")
    word = stream.peek_word()
    step = _SKIPPABLE_STEPS.get(word or "")
    if step is None:
        raise stream.error(f"no skippable step named {word!r}")
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


def parse_cant_play_lands(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.CantPlayLands | None":
    """``… can't play lands this turn.`` (Solfatara.) The verb only — the
    subject has already been read by the caller.

    CR 305.1's permission withdrawn from one seat for one turn, and the mirror
    of :func:`parse_extra_land_plays`. Non-consuming on refusal, because the
    ``can't`` dispatcher hands every other sentence on to the combat production
    and a consumed word there would replace its refusal with one naming a verb
    the line never printed.

    The duration is required for the same reason as above: "Players can't play
    lands" (Worms of the Earth) is a permanent's static ability read by
    ``engine/land_play_allowance.py``, and it prints no duration at all.
    """
    if not isinstance(subject, ast.PlayerRef):
        return None
    mark = stream.mark()
    if not stream.accept_phrase("play", "lands"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind != "this_turn":
        stream.reset(mark)
        return None
    return ast.CantPlayLands(subject, duration)
