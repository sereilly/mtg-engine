"""What a permanent *is*: P/T, keywords, colour, printed text, counters.

The `gets`/`gains`/`loses`/`has` family (CR 613 layers 6 and 7), base-P/T
setting, colour changes, the printed-text swaps of Sleight of Mind and Magical
Hack, and +1/+1-style counters including the "for each creature that died"
repetition.

Counters are here rather than with the board because what a counter does is
change a characteristic; where it sits is incidental.
"""

from .. import ast
from ..amounts import accept_counters_on_source, accept_fraction_head, accept_life_gain_cap, accept_rounding, expect_pt, parse_amount, parse_equal_to
from ..records import _parse_for_each_this_way

from ..errors import GrammarError
from ..lexer import PT, PUNCT, QUOTE, SELF, tokenize
from ..nouns import parse_object_filter
from ..references import parse_recipient, parse_target_spec
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, COLOR_WORDS, IMPLEMENTED_KEYWORDS,
                          LAND_TYPES, SUBTYPE_INDEX,
                          TYPE_LINE_SUPERTYPES, match_longest,
                          singular as _singular_type)

from ..phrases import (_expect_counter_kind, _parse_can_attack_as_though,
                       _parse_duration, _parse_for_each, _parse_keywords,
                       _parse_per_each_objects, parse_keyword_list)
from ..where_x import parse_where_x_definition


def _parse_gets(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gets +N/+N [duration][, where X is the number of …]``."""
    stream.expect_word("gets", "get")
    # "That player gets a poison counter." (Pit Scorpion.) A counter on a
    # *player* (CR 122.1) shares its verb with the P/T pump, and the subject
    # settles which sentence this is: a player has no power or toughness for a
    # P/T reading to change. The kind is read as printed and judged at
    # lowering, so "gets an energy counter" fails naming the missing store
    # rather than failing to parse.
    if isinstance(subject, ast.PlayerRef):
        count = parse_amount(stream)
        token = _expect_counter_kind(stream, " for a player to get")
        if token.kind == PT:
            raise stream.error("a player cannot get a power/toughness counter")
        stream.expect_word("counter", "counters")
        return ast.PlayerGetsCounters(subject, token.text, count)
    power, power_negative, toughness, toughness_negative = expect_pt(stream)
    duration = _parse_duration(stream)

    # "gets -X/-X until end of turn, where X is the number of cards in your
    # graveyard" (Liliana, Waker of the Dead). The clause *defines* the X the
    # P/T token used, so it is recorded on the pump rather than consumed and
    # dropped — an undefined X would otherwise silently read as the cast cost's.
    # "…for each creature tapped this way" (Siege Striker). Read before the
    # where-clause because both are trailing modifiers and this one is not a
    # definition of X — it multiplies the printed P/T by a number only the
    # sentence in front of it can supply.
    per_each_tapped = False
    tapped_mark = stream.mark()
    if stream.accept_phrase("for", "each", "creature", "tapped", "this", "way"):
        per_each_tapped = True
    else:
        stream.reset(tapped_mark)

    # "gets +2/+2 **for each Aura attached to it**" (Rabid Wombat). Read after
    # the back-reference above, which shares its first two words and is not a
    # count of anything on the board.
    per_each, per_each_beyond_first = (
        _parse_per_each_objects(stream) if not per_each_tapped else (None, False)
    )

    # The same clause the statement level reads, through the same parser
    # (`phrases.parse_where_x_definition`). It used to be a second copy here,
    # accepting "the greatest power among" where the other accepted "that died
    # under your control" — so which definitions a card could use depended on
    # which sentence it printed them in.
    x_definition = parse_where_x_definition(stream)

    pump = ast.Pump(
        subject, power, toughness, duration, power_negative, toughness_negative,
        x_definition=x_definition, per_each_tapped_this_way=per_each_tapped,
        per_each=per_each, per_each_beyond_first=per_each_beyond_first,
    )

    # "gets +3/+3 and gains flying until end of turn" / "get +1/+1 and have
    # mountainwalk" — the same conjunction in the two persons the templating
    # uses. Accepting only "gains" would leave the lordly form ("Other Goblins
    # get +1/+1 and have mountainwalk") stranding "have mountainwalk", which
    # fails full consumption and takes the whole line down.
    # "…gets +4/-4 until end of turn **and can attack this turn as though it
    # didn't have defender**" (Wall of Wonder). Read here rather than left to
    # the sentence loop, which joins a tail with no printed subject only when
    # the carried one is a *player*: a creature carried into "gains"/"wins"
    # would read a sentence nobody printed, so the loop refuses it and the
    # clause would be unconsumed text that takes the whole line down.
    mark_permission = stream.mark()
    if stream.accept_word("and"):
        permission = _parse_can_attack_as_though(stream, subject)
        if permission is not None:
            return ast.Conjunction((pump, permission))
    stream.reset(mark_permission)

    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gains", "gain", "has", "have"):
        stream.advance()
        # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift) —
        # read here as well as in the bare `gains` production, because the pump
        # conjunction is where the card actually prints it.
        choose_one = bool(stream.accept_phrase("your", "choice", "of"))
        keywords, disjunctive = parse_keyword_list(stream)
        choose_one = choose_one or disjunctive
        keyword_duration = _parse_duration(stream)
        if choose_one and len(keywords) < 2:
            raise stream.error("a choice of keywords needs more than one")
        if duration.kind is None and keyword_duration.kind is not None:
            pump = ast.Pump(
                subject, power, toughness, keyword_duration,
                power_negative, toughness_negative,
            )
        return ast.Conjunction((
            pump,
            ast.GainKeyword(subject, keywords, keyword_duration, choose_one=choose_one),
        ))
    stream.reset(mark)
    return pump


def _parse_gains(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> gains <keywords|life|control of …> [duration]``."""
    stream.expect_word("gains", "gain")

    # "**Target opponent** gains control of this creature …" (Chaos Lord.) The
    # same control change ``effects/control_changes._parse_gain_control``
    # reads, printed with its seat in front of the verb instead of implied —
    # so it is read here, where the subject has already been consumed, and
    # handed to the same node.
    #
    # Only a *player* may gain control of something, so the branch is gated on
    # the subject rather than on the words: "this creature gains control" is
    # not a sentence, and letting the words alone decide would build a node
    # whose gainer is a permanent.
    #
    # No duration is read. CR 611.2b makes an untimed control change one that
    # lasts indefinitely, which is what this printing is; a card printing a
    # duration behind this spelling would leave it unconsumed and fail the line
    # loudly rather than being silently given the wrong lifetime.
    if isinstance(subject, ast.PlayerRef):
        control_mark = stream.mark()
        if stream.accept_phrase("control", "of"):
            try:
                what = parse_target_spec(stream)
            except GrammarError:
                what = None
            if what is not None:
                return ast.GainControl(what, "indefinite", gained_by=subject)
        stream.reset(control_mark)

    # "you gain 3 life" / "you gain life equal to the damage dealt"
    mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            # "…, but not more life than the player's life total before the
            # damage was dealt, …" (Drain Life, Soul Burn). Read here rather
            # than folded as a rider by the sentence layer because it is not a
            # separate effect: it is part of how much life this gain is, and a
            # rider that failed to attach would leave the gain uncapped —
            # strictly better than the printed card.
            return ast.GainLife(player, amount, capped_by=accept_life_gain_cap(stream))
    else:
        try:
            amount = parse_amount(stream)
            if stream.accept_word("life"):
                player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
                # "…for each creature you control with flying" (Aven
                # Gagglemaster) — recorded rather than consumed-and-dropped,
                # mirroring the loses-life multiplier.
                #
                # The *history* clause is read first: "for each creature that
                # died this turn" (Canopy Stalker) counts exactly the creatures
                # the battlefield no longer holds, and the board reading of the
                # same words counts the opposite set. The noun parser consumes
                # "creature" and stops, so without this the trailing words were
                # unconsumed and the line failed loudly — which was right, and
                # is why the ordering matters rather than the fallback.
                per_each: object | None = _parse_for_each(stream)
                # "…you gain 1 life **for each card exiled this way**."
                # (Rysorian Badger.) A *count* an earlier step of this same
                # effect recorded, not a set the board holds — so it replaces
                # the gain's number instead of multiplying it, exactly as the
                # counter placement one family over treats the same clause.
                #
                # Read after the history clause above, which declines without
                # consuming, and only over a printed 1: "gain 2 life for each"
                # is a multiplication `ThatMuch` cannot carry, and reading the
                # clause while dropping the printed count would gain one life
                # where the card says two.
                if per_each is None:
                    counted = _parse_for_each_this_way(stream)
                    if counted is not None:
                        if not (isinstance(amount, ast.Fixed) and amount.value == 1):
                            raise stream.error(
                                "life gained per recorded unit is gained one "
                                "at a time"
                            )
                        return ast.GainLife(player, counted)
                if per_each is None:
                    for_each_mark = stream.mark()
                    if stream.accept_phrase("for", "each"):
                        # "…**for each credit counter on this creature**"
                        # (Icatian Moneychanger). A count of the source's own
                        # counters rather than a set of objects, so it is read
                        # by the one production that reads that phrase
                        # (`accept_counters_on_source`) and before the noun
                        # parser, which refuses a counter word as an unknown
                        # noun and would take the whole line down with it.
                        per_each = accept_counters_on_source(stream)
                        if per_each is None:
                            try:
                                per_each = parse_object_filter(stream)
                            except GrammarError:
                                stream.reset(for_each_mark)
                return ast.GainLife(player, amount, per_each=per_each)
        except GrammarError:
            pass
        stream.reset(mark)

    # "…gains "Remove a matrix counter from this creature: Regenerate this
    # creature."" (Life Matrix.) CR 113.3: what a card grants in quotes is a
    # whole printed ability, not a keyword — so it is read out as text and the
    # compiler makes the ability, exactly as it does for the emblem shape one
    # module up. Checked before the keyword list because a quote is not a word:
    # `_parse_keywords` would refuse it and take the whole line down with it.
    if stream.at_kind(QUOTE):
        abilities, self_name = _parse_quoted_abilities(stream)
        return ast.GainAbilityText(
            subject, abilities, _parse_duration(stream), self_name=self_name
        )

    # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift), and
    # "gains banding, first strike, **or** trample" (Nature's Blessing) — the
    # same card with the four words the older printing does not spell out.
    # CR 608.2d: a choice an effect offers that was not made as the spell was
    # cast is announced while the effect is applied. So the alternatives are
    # marked *here*, where the connective is still in the stream: by the time a
    # lowering sees the list, "and" and "or" have become the same tuple.
    choose_one = bool(stream.accept_phrase("your", "choice", "of"))
    keywords, disjunctive = parse_keyword_list(stream)
    choose_one = choose_one or disjunctive
    duration = _parse_duration(stream)
    if choose_one and len(keywords) < 2:
        raise stream.error("a choice of keywords needs more than one")
    grant = ast.GainKeyword(subject, keywords, duration, choose_one=choose_one)

    # "…gains haste **and** "{0}: Untap this creature. Activate only once.""
    # (Touch of Vitae.) One "gains" over two kinds of thing, which CR 113.3
    # keeps apart: a word the layer system holds and a whole printed ability
    # the compiler has to read. Two nodes, joined here, because every consumer
    # below reads one or the other and a fused node would be a third thing.
    #
    # A duration printed after the quote governs both halves, the way the
    # keyword-and-pump join below reads a trailing one — and the leading
    # spelling this card prints is distributed over the conjunction by the
    # sentence layer.
    quoted_mark = stream.mark()
    if stream.accept_word("and") and stream.at_kind(QUOTE):
        abilities, self_name = _parse_quoted_abilities(stream)
        text_duration = _parse_duration(stream)
        if duration.kind is None and text_duration.kind is not None:
            grant = ast.GainKeyword(
                subject, keywords, text_duration, choose_one=choose_one
            )
        elif text_duration.kind is None:
            text_duration = duration
        return ast.Conjunction((
            grant,
            ast.GainAbilityText(
                subject, abilities, text_duration, self_name=self_name
            ),
        ))
    stream.reset(quoted_mark)

    mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("gets", "get"):
        pump = _parse_gets(stream, subject)
        # Berserk: "gains trample and gets +X/+0 until end of turn" — the shared
        # duration sits at the end and applies to both halves.
        if isinstance(pump, ast.Pump) and duration.kind is None and pump.duration.kind:
            grant = ast.GainKeyword(subject, keywords, pump.duration)
        return ast.Conjunction((grant, pump))
    stream.reset(mark)
    return grant


def _parse_quoted_abilities(stream: TokenStream) -> tuple[tuple[str, ...], str | None]:
    """The quoted abilities a grant hands over, ``"A" [and "B"]``, as printed,
    and the name the quoted text calls itself by.

    The second half is what Johan needs and Life Matrix does not. Life Matrix
    grants "Remove a matrix counter from **this creature**: …", which reads the
    same on whatever permanent ends up holding it; Johan grants "**Johan** can't
    attack", and that sentence is only an ability at all on a card called Johan.
    The lexer has already answered which words those are — it collapsed them
    into a SELF token when it was given the granting card's name — so the name
    is read back off that token rather than plumbed down from the compiler as a
    second opinion about what the card is called.

    Recovered from the *source line* through the tokens' own offsets rather than
    rebuilt from the tokens, because the payload is text the compiler will read
    again: rebuilding it would lose the card's spacing and punctuation, and the
    compiler would then be reading a sentence the card did not print.

    The slice is checked against the tokens it came from before it is trusted.
    A line whose offsets do not line up (reminder text cut out ahead of the
    quote is the way that happens) yields a slice of the wrong words, and a
    wrong sentence that happens to compile is a granted ability nobody printed
    — so the mismatch raises here instead.
    """
    abilities: list[str] = []
    self_name: str | None = None
    while True:
        if stream.accept_kind(QUOTE) is None:
            break
        start = stream.mark()
        while not stream.exhausted and not stream.at_kind(QUOTE):
            stream.next()
        end = stream.mark()
        if stream.accept_kind(QUOTE) is None:
            raise stream.error("unterminated granted ability")
        if end == start:
            raise stream.error("an empty granted ability")
        text = stream.text_between(start, end)
        if _token_shape(tokenize(text).tokens) != _token_shape(stream.tokens[start:end]):
            raise stream.error("granted ability text could not be read as printed")
        abilities.append(text)
        for token in stream.tokens[start:end]:
            if token.kind == SELF:
                self_name = self_name or token.text
        mark = stream.mark()
        # "gains "A" and "B"" (Glyph of Delusion) — two whole abilities, not a
        # conjunction inside one. The "and" is only this list's when a second
        # quote follows it; anything else belongs to the sentence around us.
        if stream.accept_word("and") and stream.at_kind(QUOTE):
            continue
        stream.reset(mark)
        break
    if not abilities:
        raise stream.error("a quoted grant needs an ability in quotes")
    return tuple(abilities), self_name


def _token_shape(tokens) -> tuple[str, ...]:
    """*tokens* as bare words, with trailing sentence punctuation dropped.

    Bare words rather than (kind, text) pairs because the two lexings are not
    given the same context: the granting card's name makes a self-reference one
    SELF token, and re-lexing the slice on its own makes it words. Both spell
    the same thing, which is what this comparison is asking.
    """
    kept = list(tokens)
    while kept and kept[-1].kind == PUNCT:
        kept.pop()
    return tuple(token.text.lower() for token in kept)


def _parse_loses(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> loses <the game|keywords|life>``."""
    stream.expect_word("loses", "lose")
    mark = stream.mark()
    # "loses the game" (CR 104.3e) before the life reading: "the" is not an
    # amount, so the amount branch below rejects it anyway, but checking here
    # keeps the two spellings of "lose" visibly separate.
    if stream.accept_phrase("the", "game"):
        player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
        return ast.LoseGame(player)
    stream.reset(mark)
    # "loses **half their life**" (Peer into the Abyss). Read here rather than in
    # `parse_amount`, because the trailing "life" is the *production's* word
    # everywhere else ("loses 3 life") and here it belongs to the quantity —
    # "half their life" is one amount, not a half followed by a life keyword. A
    # quantity parser that consumed it would leave every other printing of this
    # verb without its noun.
    half_mark = stream.mark()
    # "half" and "a third of" are one printed idea with two spellings, so the
    # head is read by one function (`accept_fraction_head`) and the denominator
    # rides the node. Pox's "loses a third of their life" is this branch with a
    # 3 in it.
    divisor = accept_fraction_head(stream)
    if divisor is not None and stream.accept_word("their", "your", "his"):
        stream.accept_phrase("or", "her")
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(
                player,
                ast.Half(
                    ast.BoardCount("their_life"), accept_rounding(stream), divisor
                ),
            )
    stream.reset(half_mark)
    try:
        amount = parse_amount(stream)
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            # "loses 2 life for each creature card in their graveyard"
            # (Liliana, Death Mage) — a multiplier over a count of objects,
            # recorded rather than consumed-and-dropped.
            per_each: ast.ObjectFilter | None = None
            for_each_mark = stream.mark()
            if stream.accept_phrase("for", "each"):
                try:
                    per_each = parse_object_filter(stream)
                except GrammarError:
                    stream.reset(for_each_mark)
            return ast.LoseLife(player, amount, per_each=per_each)
    except GrammarError:
        pass
    stream.reset(mark)
    # "Target player loses **all poison counters**." (Leeches.) The same removal
    # ``effects/counters.py`` reads as "remove all poison counters from target
    # player", in the word order this card prints — one node, so what a counter
    # removal *is* has one answer however the sentence is arranged and the
    # lowering behind it does not have to learn a second shape.
    #
    # Read after the life branch, which has already refused on the missing word
    # "life", and before the keyword list, which fails the whole line on
    # "poison" — which is exactly how Leeches refused. Non-consuming, so every
    # other "loses …" keeps the reading it has: "loses all abilities" gets as
    # far as the head noun and backtracks on the missing word "counter".
    counter_mark = stream.mark()
    try:
        count = parse_amount(stream)
        kind = _expect_counter_kind(stream, " for a subject to lose")
        if kind.kind == PT and isinstance(subject, ast.PlayerRef):
            raise stream.error("a player cannot lose a power/toughness counter")
        stream.expect_word("counter", "counters")
        return ast.RemoveCounter(subject, kind.text, count)
    except GrammarError:
        stream.reset(counter_mark)
    keywords = _parse_keywords(stream)
    duration = _parse_duration(stream)
    return ast.LoseKeyword(subject, keywords, duration)


def _parse_has(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has <keywords>`` / ``<subject> has base power …``.

    "Has" is the third person of "gains" — "Enchanted creature has flying" and
    "Target creature gains flying until end of turn" grant the same thing and
    differ only in duration, so they share :class:`ast.GainKeyword` rather than
    getting a node apiece. What separates them is exactly what lowering acts on:
    a granted keyword with no duration is a continuous effect (CR 613) and is
    refused there, while one with a duration has a handler.

    "Base power" is checked first and delegated, because it is the one reading
    of "has" that is not a keyword grant. Falling through to the keyword list
    instead would make "has base power and toughness 3/3" fail on "base" — which
    is not a keyword — and take the whole line down with it.
    """
    mark = stream.mark()
    stream.expect_word("has", "have")
    if stream.at_word("base"):
        stream.reset(mark)
        return _parse_has_base_pt(stream, subject)
    keywords, disjunctive = parse_keyword_list(stream)
    duration = _parse_duration(stream)
    return ast.GainKeyword(subject, keywords, duration, choose_one=disjunctive)


def _parse_has_base_pt(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> has base power [and toughness] N[/N] [duration]``."""
    stream.expect_word("has", "have")
    stream.expect_word("base")
    stream.expect_word("power")

    if stream.accept_phrase("and", "toughness"):
        token = stream.peek()
        if token is not None and token.kind == PT:
            power, _, toughness, _ = expect_pt(stream)
        else:
            power = parse_amount(stream)
            toughness = parse_amount(stream)
        duration = _parse_duration(stream)
        return ast.SetBasePT(subject, power, toughness, duration)

    power = parse_amount(stream)
    duration = _parse_duration(stream)
    return ast.SetBasePT(subject, power, None, duration)


def _parse_double(stream: TokenStream) -> ast.DoublePower:
    """``Double the power of <subject> until end of turn.`` (Unleash Fury.)

    Only power: doubling toughness, life or mana are separate effects with
    separate handlers, and consuming the noun without checking it is how one
    card's production quietly claims another's.
    """
    stream.expect_word("double")
    stream.expect_word("the")
    if not stream.accept_word("power"):
        raise stream.error("only doubling power has a handler")
    stream.expect_word("of")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something whose power to double")
    return ast.DoublePower(subject, _parse_duration(stream))


def _parse_switch_pt(stream: TokenStream) -> ast.SwitchPT:
    """``Switch <subject>'s power and toughness [duration].`` (Transmutation.)

    The two nouns are checked rather than skipped, and the order is the printed
    one: "switch" opens other sentences in the wider card pool (switching a
    creature's *colour* words, switching life totals), and a production that
    consumed the possessive and shrugged at whatever followed would claim them
    and do the wrong thing. What it cannot read it refuses, and the line keeps
    the refusal it has today.
    """
    stream.expect_word("switch")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something whose power and toughness to switch")
    stream.expect_word("'s")
    stream.expect_word("power")
    stream.expect_word("and")
    stream.expect_word("toughness")
    return ast.SwitchPT(subject, _parse_duration(stream))


def _parse_change_base_pt(stream: TokenStream) -> ast.ChangeBasePT | None:
    """``Change <subject>'s base [power and] toughness to <value> [duration].``

    CR 613.4b, the Legends rewrite template — Sentinel, Wall of Tombstones,
    Halfdane, Brine Hag. Returns None without consuming when the sentence is
    not this shape, so "Change the text of …" keeps falling through to
    :func:`_parse_change_text`.

    Two printed subject positions, one node: the possessive ("change this
    creature's base toughness…", "change Halfdane's base power and toughness…"
    — the lexer has already collapsed the self-name to SELF plus its
    possessive marker) and the of-phrase ("change the base power and toughness
    of all creatures that dealt damage to it this turn…").

    Three printed value shapes: a P/T pair ("to 0/2"), a quantity with an
    addend ("to 1 plus the number of …", "to 1 plus the power of target …"),
    and both stats of one chosen creature ("to the power and toughness of
    target creature…"). Each is recorded whole — an addend or a referent
    consumed and dropped would be the dropped-rider class this grammar exists
    to refuse.
    """
    mark = stream.mark()
    stream.expect_word("change")
    both = False
    from_pt_of: ast.Recipient | None = None
    if stream.at_word("the"):
        stream.advance()
        if not stream.accept_word("base"):
            # "Change the text of …" — not this production's sentence.
            stream.reset(mark)
            return None
        stream.expect_word("power")
        stream.expect_word("and")
        stream.expect_word("toughness")
        stream.expect_word("of")
        both = True
        subject = parse_recipient(stream)
    else:
        subject = parse_recipient(stream)
        if subject is None or not stream.accept_word("'s"):
            stream.reset(mark)
            return None
        if not stream.accept_word("base"):
            stream.reset(mark)
            return None
        if stream.accept_phrase("power", "and", "toughness"):
            both = True
        elif not stream.accept_word("toughness"):
            raise stream.error("expected 'power and toughness' or 'toughness'")
    if subject is None:
        raise stream.error("expected whose base power/toughness to change")
    stream.expect_word("to")

    power: ast.Amount | None = None
    toughness: ast.Amount | None = None
    token = stream.peek()
    if token is not None and token.kind == PT:
        pt_power, power_negative, pt_toughness, toughness_negative = expect_pt(stream)
        if power_negative or toughness_negative:
            raise stream.error("a base P/T is a value, not a modification")
        if both:
            power, toughness = pt_power, pt_toughness
        else:
            raise stream.error("a toughness-only change takes one number")
    elif stream.accept_phrase("the", "power", "and", "toughness", "of"):
        # Halfdane: both stats read off one chosen creature at resolution.
        if not both:
            raise stream.error("both stats must be named to copy both stats")
        from_pt_of = parse_recipient(stream)
        if from_pt_of is None:
            raise stream.error("expected whose power and toughness to copy")
    else:
        amount: ast.Amount = parse_amount(stream)
        if stream.accept_word("plus"):
            addend_mark = stream.mark()
            if stream.accept_phrase("the", "power", "of"):
                # "1 plus the power of target creature …" (Sentinel). The
                # quantity itself carries the sentence's target.
                referent = parse_recipient(stream)
                if not isinstance(referent, ast.TargetSpec):
                    raise stream.error("expected whose power to add")
                amount = ast.Plus(amount, ast.PowerOfSubject(referent))
            elif stream.accept_phrase("the", "number", "of"):
                # "1 plus the number of creature cards in your graveyard"
                # (Wall of Tombstones).
                amount = ast.Plus(amount, ast.CountOf(parse_object_filter(stream)))
            else:
                stream.reset(addend_mark)
                raise stream.error("expected a count or a power after 'plus'")
        if both:
            raise stream.error(
                "one quantity cannot set both base power and base toughness"
            )
        toughness = amount

    duration = _parse_duration(stream)
    return ast.ChangeBasePT(
        subject, power, toughness, from_pt_of=from_pt_of, duration=duration
    )


# Vocabularies a printed text change can swap, one literal phrase per mode
# (CR 612.1). Closed on purpose: `mark_text_modified` substitutes exactly these
# two, and a card naming a third — a creature type, a card name — is a text
# change the engine does not perform. Listing the phrases keeps that card
# failing here instead of reaching the handler as a mode it will ignore.
_TEXT_CHANGE_MODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_type", ("basic", "land", "type")),
    ("color_word", ("color", "word")),
)


def _parse_change_text(stream: TokenStream) -> ast.ChangeText:
    """``Change the text of <subject> by replacing all instances of one <what>
    with another.`` (Magical Hack, Sleight of Mind.)

    One production for the pair: they are the same sentence with one word
    changed, which is what makes the swapped vocabulary payload rather than part
    of the effect's name. Every word between the subject and the mode is
    required — "all instances of **one**" is what says a single word is
    replaced everywhere, and a card replacing something else, or only the first
    instance, would be a different effect wearing this one's sentence.
    """
    stream.expect_word("change")
    stream.expect_word("the")
    stream.expect_word("text")
    stream.expect_word("of")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to change the text of")
    if not stream.accept_phrase("by", "replacing", "all", "instances", "of", "one"):
        raise stream.error("expected 'by replacing all instances of one'")
    for mode, phrase in _TEXT_CHANGE_MODES:
        if stream.accept_phrase(*phrase):
            if not stream.accept_phrase("with", "another"):
                raise stream.error("expected 'with another'")
            return ast.ChangeText(subject, mode)
    raise stream.error("no text substitution replaces this")


def _parse_becomes(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """"<subject> becomes <colour>" or "<subject> becomes a P/T <types> creature
    …". One production, because the word is the same and what follows it is what
    tells the two apart — a colour word, or a P/T.

    The colour form is a *replacement* and the creature form is an *addition*,
    which is the whole reason they are different nodes; both are the sentence's
    entire effect, so a word after "becomes" that starts neither must fail
    rather than be skipped.
    """
    # "…**become** a 3/3 Sphinx creature" is the same verb after the "you may
    # have" wrapper has taken its subject; English changes the inflection and
    # the card does not change what it does.
    stream.expect_word("becomes", "become")
    # "…becomes **the color of your choice**" (Alchor's Tomb). CR 609.3 makes
    # the choice part of the resolution, so the sentence names no colour and the
    # node carries the sentinel instead. Read before the colour-word branch,
    # which would see "the" and refuse — and read here rather than as a separate
    # production, because it is the same verb with the same duration tail.
    # "…becomes **the color or colors of your choice**" (Dream Coat). Read
    # before the singular, which shares its first three words and would leave
    # "or colors of your choice" unconsumed — the refusal Dream Coat's ability
    # met. The plural is a different offer (a set of colours, CR 105.2), so it
    # carries its own sentinel rather than collapsing into the singular's.
    if stream.accept_phrase("the", "color", "or", "colors", "of", "your", "choice"):
        return ast.BecomeColor(subject, ast.CHOSEN_COLORS, _parse_duration(stream))
    if stream.accept_phrase("the", "color", "of", "your", "choice"):
        return ast.BecomeColor(subject, ast.CHOSEN_COLOR, _parse_duration(stream))
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word in COLOR_WORDS:
        stream.advance()
        # The duration is read rather than assumed. Without it the four words
        # of "until end of turn" would be unconsumed text and the line would
        # refuse — which is the *safe* failure, but it costs five cards; and
        # skipping them instead would turn a turn-long colour change into the
        # Lace cycle's indefinite one.
        return ast.BecomeColor(subject, COLOR_WORDS[word], _parse_duration(stream))
    animated = _parse_become_creature(stream, subject)
    if animated is not None:
        return animated
    gained = _parse_gain_type(stream, subject)
    if gained is not None:
        return gained
    # "…**becomes snow**." (Arcum's Weathervane.) Read after the type form,
    # whose "becomes an artifact" opens with an article this branch does not
    # accept, so the two cannot claim each other's sentence.
    supertype = _parse_becomes_supertype(stream, subject)
    if supertype is not None:
        return supertype
    land_type = _parse_becomes_land_type(stream, subject)
    if land_type is not None:
        return land_type
    raise stream.error("expected a colour or a creature body after 'becomes'")


def _parse_becomes_land_type(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeLandType | None":
    """``… becomes a Swamp until its controller's next untap step.``
    (Orcish Farmer.)

    Last of the ``becomes`` branches, because it is the one that accepts a bare
    noun after the article and would otherwise claim "becomes an artifact
    creature" — the animation and the gained-type forms both open the same way
    and both say more than a land type. Read against the land-type catalog
    (`data/vocabulary/`) rather than a list of the five basics, so a set
    printing a new one needs `scripts/fetch_vocabulary.py` and nothing here.
    """
    mark = stream.mark()
    # "…becomes **the basic land type of your choice** until end of turn."
    # (Jinx.) CR 609.3 makes the choice part of resolving the spell, so the
    # sentence names no type and the node carries the sentinel — the same shape
    # "becomes the color of your choice" takes two branches up, and read before
    # the article branch below, which would see "the" and refuse.
    if stream.accept_phrase("the", "basic", "land", "type", "of", "your", "choice"):
        return ast.ChangeLandType(
            subject, ast.CHOSEN_LAND_TYPE, _parse_duration(stream)
        )
    if not (stream.accept_word("a") or stream.accept_word("an")):
        stream.reset(mark)
        return None
    word = stream.peek_word()
    if word is None or word not in LAND_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    return ast.ChangeLandType(subject, word, _parse_duration(stream))


def _parse_becomes_supertype(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeSupertype | None":
    """``… becomes snow.`` (Arcum's Weathervane.)

    A bare supertype word, with no "in addition to its other types" tail:
    CR 205.4a puts supertypes in front of the card types, so adding one
    displaces nothing and the printed sentence has nothing more to say. The word
    is checked against the vocabulary catalog rather than a literal — a set
    printing a new supertype needs `scripts/fetch_vocabulary.py` and nothing
    here.
    """
    word = stream.peek_word()
    if word is None or word not in TYPE_LINE_SUPERTYPES:
        return None
    stream.advance()
    return ast.ChangeSupertype(subject, word, True, _parse_duration(stream))


def _parse_no_longer_supertype(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.ChangeSupertype | None":
    """``<subject> is no longer snow.`` (Arcum's Weathervane's other ability.)

    The mirror of :func:`_parse_becomes_supertype`, and non-consuming on
    refusal: "is" opens sentences this production has no business claiming, so
    anything it cannot finish keeps the refusal it already had.

    A **quantified** subject is declined here, in the parse rather than in the
    lowering. "All lands are no longer snow" (Melting) is a static ability of a
    permanent rather than a one-shot effect, and its home is
    `engine/land_types.py`'s derivation table beside the other board-wide land
    statics — exactly as "All Mountains are Plains" sits beside
    `change_land_type`. `derived.py` is consulted only where the grammar refuses
    the line *in full*, so a production that parsed the sentence and left the
    lowering to raise would take the table's line away and give it back to
    nobody: parsed-but-unlowered is still parsed.
    """
    mark = stream.mark()
    if not stream.accept_word("is", "are"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("no", "longer"):
        stream.reset(mark)
        return None
    word = stream.peek_word()
    if word is None or word not in TYPE_LINE_SUPERTYPES:
        stream.reset(mark)
        return None
    if not (
        isinstance(subject, ast.TargetSpec)
        and subject.quantifier in ("target", "that", "it", "this")
    ):
        stream.reset(mark)
        return None
    stream.advance()
    return ast.ChangeSupertype(subject, word, False, _parse_duration(stream))


def _parse_gain_type(
    stream: TokenStream, subject: ast.Recipient
) -> ast.GainType | None:
    """``… becomes an artifact in addition to its other types.`` (Ashnod's
    Transmogrant.) ``… becomes an artifact creature with power and toughness
    each equal to its mana value.`` (Xenic Poltergeist.)

    Read after the creature-body form, whose "becomes a 3/3 …" opens with a
    P/T and cannot be confused with this. Every tail is required: without "in
    addition to its other types" or the mana-value P/T clause the sentence says
    something this does not implement, and consuming the type word alone would
    claim it.
    """
    mark = stream.mark()
    if not (stream.accept_word("a") or stream.accept_word("an")):
        stream.reset(mark)
        return None
    types: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or word not in CARD_TYPES:
            break
        types.append(word)
        stream.advance()
    if not types:
        stream.reset(mark)
        return None
    if stream.accept_phrase("with", "power", "and", "toughness", "each", "equal", "to"):
        if not stream.accept_phrase("its", "mana", "value"):
            stream.reset(mark)
            return None
        duration = _parse_duration(stream)
        return ast.GainType(subject, tuple(types), duration, pt_from_mana_value=True)
    if stream.accept_phrase("in", "addition", "to", "its", "other", "types"):
        return ast.GainType(subject, tuple(types), _parse_duration(stream))
    stream.reset(mark)
    return None


def _parse_become_creature(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BecomeCreature | None":
    """``a <P>/<T> <subtypes> creature [with <keywords>] in addition to its
    other types until end of turn`` (Riddleform).

    Every clause after the P/T is required, and each one is a way the sentence
    would otherwise be silently narrowed:

    * **"in addition to its other types"** is the difference between animating
      the permanent and *replacing* what it is — an enchantment that stopped
      being an enchantment is a different card;
    * **"until end of turn"** is the difference between this and a permanent
      animation, which is everything that happens after the turn ends.
    """
    mark = stream.mark()
    stream.accept_word("a", "an")
    try:
        power, power_negative, toughness, toughness_negative = expect_pt(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if power_negative or toughness_negative or not (
        isinstance(power, ast.Fixed) and isinstance(toughness, ast.Fixed)
    ):
        stream.reset(mark)
        return None
    subtypes: list[str] = []
    while True:
        matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
        if matched is None:
            break
        subtypes.append(matched[0])
        stream.advance(matched[1])
    # "…a 2/2 Assembly-Worker **artifact** creature" (Mishra's Factory). A card
    # type between the subtypes and the head noun, which the animation adds
    # alongside "creature" (CR 205.1b). Recorded rather than skipped: an
    # animated land that is not also an artifact is a different permanent, and
    # a word consumed and dropped is the rider bug this grammar refuses by
    # construction.
    card_types: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or word == "creature" or word not in CARD_TYPES:
            break
        card_types.append(word)
        stream.advance()
    # "…become 2/3 **creatures**" (Thelonite Druid). The plural head noun, for
    # a subject that names a set rather than one permanent. Read here rather
    # than as a second production: it is the same sentence with the noun
    # agreeing, and which subjects the animation can actually reach is the
    # lowering's question.
    if not stream.accept_word("creature", "creatures"):
        stream.reset(mark)
        return None
    keywords: list[str] = []
    if stream.accept_word("with"):
        while True:
            keyword = stream.peek_word()
            if keyword is None or keyword not in IMPLEMENTED_KEYWORDS:
                break
            keywords.append(keyword)
            stream.advance()
            if not (stream.accept_word("and") or stream.accept_punct(",")):
                break
        if not keywords:
            stream.reset(mark)
            return None
    # The addition clause, in any of the three places the pool prints it:
    # before the duration ("…in addition to its other types until end of turn",
    # Riddleform), as a relative clause on the noun itself ("…a 3/3 artifact
    # creature **that's still a land**", Mishra's Groundbreaker) or as its own
    # sentence after the duration ("…until end of turn. It's still a land.",
    # Mishra's Factory). One of the three is **required** — it is the difference
    # between animating the permanent and replacing what it is, and a production
    # that let it be absent would also let it be deleted.
    in_addition = stream.accept_phrase("in", "addition", "to", "its", "other", "types")
    if not in_addition:
        relative = stream.mark()
        if stream.accept_phrase("that", "'s", "still", "a"):
            kept = stream.peek_word()
            if kept is not None and _singular_type(kept) in CARD_TYPES:
                stream.advance()
                in_addition = True
            else:
                stream.reset(relative)
    # **Read, not required.** A sentence printing no duration is CR 611.2b's
    # default — the animation lasts indefinitely (Mishra's Groundbreaker) — and
    # the two lower to different instruction kinds, so the absence is carried
    # rather than defaulted. It is only optional once the addition clause has
    # already been consumed: the third spelling puts that clause *after* the
    # duration, so it has no sentence to find without one.
    until_eot = stream.accept_phrase("until", "end", "of", "turn")
    if not until_eot and not in_addition:
        stream.reset(mark)
        return None
    if not in_addition:
        stream.accept_punct(".")
        # "**They're still lands.**" (Thelonite Druid) is the plural of "It's
        # still a land." — the same sentence agreeing with a subject that names
        # a set, and the article goes with the number.
        if stream.accept_phrase("it", "'s", "still", "a"):
            plural_kept = False
        elif stream.accept_phrase("they're", "still"):
            plural_kept = True
        else:
            stream.reset(mark)
            return None
        # The type the sentence names is one the permanent already has, so
        # nothing reads it — the animation keeps every type either way. It is
        # still required to *be* a card type, because a sentence naming
        # something else is one this production has not understood.
        kept = stream.peek_word()
        if kept is None or _singular_type(kept) not in CARD_TYPES:
            stream.reset(mark)
            return None
        if plural_kept and kept == _singular_type(kept):
            # "They're still land" is not English and is not a sentence this
            # production has read; the plural subject takes the plural noun.
            stream.reset(mark)
            return None
        stream.advance()
    return ast.BecomeCreature(
        subject, power.value, toughness.value, tuple(subtypes), tuple(keywords),
        tuple(card_types), until_eot,
    )


