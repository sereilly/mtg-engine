"""What a permanent *is*: P/T, keywords, colour, printed text, counters.

The `gets`/`gains`/`loses`/`has` family (CR 613 layers 6 and 7), base-P/T
setting, colour changes, the printed-text swaps of Sleight of Mind and Magical
Hack, and +1/+1-style counters including the "for each creature that died"
repetition.

Counters are here rather than with the board because what a counter does is
change a characteristic; where it sits is incidental.
"""

import dataclasses

from .. import ast
from ..amounts import accept_counters_on_source, accept_fraction_head, accept_rounding, expect_pt, parse_amount, parse_equal_to
from ..bounds import accept_life_gain_cap
from ..cost_records import accept_counters_removed_for_cost
from ..records import (_parse_for_each_this_way,
                       scaled_by_recorded_count,
                      accept_plus_per_cost_paid,
                      parse_for_each_milled_this_way,
                      parse_for_each_sacrificed_this_way)

from ..errors import GrammarError
from ..lexer import PT, PUNCT, QUOTE, SELF, tokenize
from ..nouns import parse_object_filter
from ..references import parse_recipient, parse_target_spec
from ..stream import TokenStream

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
        # "The player gets **another** poison counter …" (Sabertooth Cobra.)
        # A count of one written as a comparison with what the sentence in
        # front of it already placed. It is one more counter and not a
        # different kind of placement — the store is additive — so it reads as
        # the number rather than as a node nothing would do anything with.
        # Read here rather than in `parse_amount`, where the word means
        # "not this one" about an *object* and never a quantity.
        if stream.accept_word("another"):
            count: ast.Amount = ast.Fixed(1)
        else:
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
    # "…for each creature card **put into your graveyard this way**" (Song of
    # Blood). Read before the board count below, which shares its first two
    # words and would claim "creature card" and strand the participle.
    per_each_milled = (
        parse_for_each_milled_this_way(stream, parse_object_filter)
        if not per_each_tapped else None
    )
    per_each, per_each_beyond_first = (
        _parse_per_each_objects(stream)
        if not per_each_tapped and per_each_milled is None else (None, False)
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
        per_each_milled=per_each_milled,
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

    # "…gets -2/+2 and **loses flying** until end of turn." (Leering Gargoyle.)
    # The mirror of the conjunction above, and its own arm rather than a verb
    # alternative inside it for the reason `_KEYWORD_REMOVAL` is its own pattern
    # in `auras.py`: a grant and a removal are opposite contributions to one
    # layer (CR 613.4/613.9), so folding them together would let "loses flying"
    # come back as a grant of it.
    mark_loss = stream.mark()
    if stream.accept_word("and") and stream.at_word("loses", "lose"):
        stream.advance()
        keywords, _disjunctive = parse_keyword_list(stream)
        keyword_duration = _parse_duration(stream)
        if duration.kind is None and keyword_duration.kind is not None:
            pump = ast.Pump(
                subject, power, toughness, keyword_duration,
                power_negative, toughness_negative,
            )
        return ast.Conjunction((
            pump, ast.LoseKeyword(subject, keywords, keyword_duration),
        ))
    stream.reset(mark_loss)
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
    # No duration is read. CR 611.2a makes an untimed control change one that
    # lasts indefinitely, which is what this printing is; a card printing a
    # duration behind this spelling would leave it unconsumed and fail the line
    # loudly rather than being silently given the wrong lifetime.
    if isinstance(subject, ast.PlayerRef):
        control_mark = stream.mark()
        if stream.accept_phrase("control", "of"):
            try:
                # ``parse_recipient`` and not ``parse_target_spec``: this is the
                # same "what is being handed over" phrase
                # ``effects/control_changes._parse_gain_control`` reads, and that
                # one has always used the wider reader. The narrow one has no
                # SELF branch, so **"That permanent's controller gains control of
                # Starke"** (Starke of Rath) refused on the card's own name while
                # the identical sentence written "…of this creature" parsed —
                # which is one printed sentence with two readers, disagreeing
                # about the one spelling pre-Sixth-Edition templating actually
                # uses.
                #
                # Narrowed back to an object: ``parse_recipient`` opens with a
                # player reference, and a player is not something a player gains
                # control of. Declining rather than raising keeps every other
                # "gains …" reading below reachable, which is this branch's own
                # rule.
                what = parse_recipient(stream)
            except GrammarError:
                what = None
            if isinstance(what, ast.TargetSpec):
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
                # consuming. The printed number is a **rate**: "gain 1 life for
                # each card exiled this way" (Rysorian Badger) is the record
                # itself, "**gain 2 life** for each enchantment destroyed this
                # way" (Multani's Decree) is twice it, and so is "You gain **2**
                # life for each card revealed this way" (Jasmine Seer, Scent of
                # Jasmine). All three go through
                # ``records.scaled_by_recorded_count``, the reader the counter
                # family one file over already uses for the same clause — so the
                # two effects cannot come to read one printed sentence as two
                # numbers, and a printed 1 still folds away to the bare record
                # rather than to ``Times(1, …)``.
                #
                # This refused a printed 2 outright until those cards, on the
                # reading that ``ThatMuch`` cannot carry a multiplication. True
                # of that node and beside the point: ``ast.Times`` is the node
                # for one and the shared reader had been minting it for the
                # counter spelling of this very clause since Mind Maggots. Two
                # groups of one wave found it independently and wrote the same
                # three lines of code; refusing had kept it loud rather than
                # wrong, which is why the fix is the multiplier and not a wider
                # gate.
                if per_each is None:
                    counted = _parse_for_each_this_way(stream)
                    if counted is not None:
                        return ast.GainLife(
                            player, scaled_by_recorded_count(amount, counted, stream)
                        )
                if per_each is None:
                    # "You gain 2 life **for each permanent sacrificed this
                    # way**." (Renounce.) A count of what the sentence in front
                    # of this one took off the battlefield, which no reading of
                    # a board or of ``_THIS_WAY_COUNTS`` can answer: "any
                    # number" prints no count, and the record holds the *cards*
                    # rather than a number — which is exactly why that table
                    # declines the phrase and this production owns it.
                    #
                    # Read **before** the plain noun-phrase fallback below for
                    # the reason the draw one file over states: that reading
                    # consumes "permanent" and leaves "sacrificed this way" as
                    # unconsumed text, having already claimed the clause for a
                    # count of the whole battlefield — a strictly larger number
                    # than the card prints, and the failure that took this line
                    # down.
                    per_each = parse_for_each_sacrificed_this_way(
                        stream, parse_object_filter
                    )
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
                            # "You gain 2 life **for each elixir counter
                            # removed this way**." (Essence Bottle.) The
                            # counters the ability's own cost took off, which
                            # after CR 601.2h is the complement of what the
                            # reader above counts: by resolution the artifact
                            # holds none, so "on this artifact" would answer
                            # zero on every activation. One reader for the
                            # phrase, shared with the damage and mana families
                            # that print it (`records`).
                            per_each = accept_counters_removed_for_cost(stream)
                        if per_each is None:
                            try:
                                per_each = parse_object_filter(stream)
                            except GrammarError:
                                stream.reset(for_each_mark)
                if per_each is None:
                    # "…**plus an additional 3 life for each additional {1}{G}
                    # you paid**" (Taste of Paradise) — one gain whose amount
                    # scales with a CR 601.2b payment.
                    scaled = accept_plus_per_cost_paid(stream, amount, "life")
                    if scaled is not None:
                        return ast.GainLife(player, scaled)
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

    # "…gains **landwalk of each of the land types of the sacrificed land**"
    # (Excavator). Read before the keyword list, which matches "landwalk" on its
    # own and then strands "of each of…" — the whole line failing on a phrase
    # whose first word it had already taken, the same probe-order trap the
    # "with protection from" branch avoids one package over.
    #
    # No keyword travels: CR 702.14a builds the ability's *name* out of a land
    # type, and which land type is a fact about the cost that was paid rather
    # than about the sentence. The node carries the record instead.
    # "…another target creature **gains it**" (Phyrexian Splicer). The pronoun
    # names the ability the activation chose, which is why it is read here and
    # not by the noun parser: after "gains" there is no object to be, and the
    # keyword list below would refuse "it" and take the whole line with it.
    #
    # Read generally and refused in the *lowering* unless the sentence is the
    # move this card prints — a pronoun admitted here and dropped there is a
    # card that compiles and grants nothing.
    it_mark = stream.mark()
    if stream.accept_word("it"):
        return ast.GainKeyword(
            subject, (), _parse_duration(stream), chosen_ability=True,
        )
    stream.reset(it_mark)

    landwalk_mark = stream.mark()
    if stream.accept_word("landwalk") and stream.accept_phrase(
        "of", "each", "of", "the", "land", "types", "of", "the", "sacrificed",
        "land",
    ):
        return ast.GainKeyword(
            subject, (), _parse_duration(stream), landwalk_from="sacrificed",
        )
    stream.reset(landwalk_mark)

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

    # "{1}{G}: This creature **gains flying and loses trample** until end of
    # turn." (Canopy Dragon.) One sentence over both halves of layer 6, and the
    # trailing duration governs both — the same join the two branches above
    # make, with the opposite contribution on the right. Kept as its own arm
    # rather than folded into the keyword list, because a list is a set of
    # words the subject *gains*; a removal in it would be a grant.
    loss_mark = stream.mark()
    if stream.accept_word("and") and stream.at_word("loses", "lose"):
        stream.advance()
        lost, lost_disjunctive = parse_keyword_list(stream)
        loss_duration = _parse_duration(stream)
        if duration.kind is None and loss_duration.kind is not None:
            grant = ast.GainKeyword(
                subject, keywords, loss_duration, choose_one=choose_one
            )
        elif loss_duration.kind is None:
            loss_duration = duration
        return ast.Conjunction((
            # The right half carries its own connective, for the reason the
            # bare loss below reads one: "and loses A or B" takes one away and
            # "and loses A and B" takes both, and a dropped flag is a removal
            # the card never printed.
            grant,
            ast.LoseKeyword(
                subject, lost, loss_duration, choose_one=lost_disjunctive
            ),
        ))
    stream.reset(loss_mark)

    # "{2}, {T}: Until end of turn, target creature you control **gains flying
    # and has base toughness 1**." (Chariot of the Sun.) A layer-6 grant joined
    # to CR 613.4b's base-P/T rewrite — the same join the three arms above make
    # with a different right-hand side, and under the same duration rule:
    # whichever half printed one governs both, and the leading spelling this
    # card uses is distributed over the conjunction by the sentence layer.
    #
    # Its own arm rather than a member of the keyword list, for the reason the
    # loss arm beside it is one: a base P/T is not a word layer 6 holds, and a
    # list carrying it would be a grant of something that is not an ability.
    # "base" is checked before dispatching, exactly as the untap conjunct one
    # module up checks its verb: "gains flying and has flying" opens on the
    # same two words and is a keyword sentence this arm must not claim.
    base_mark = stream.mark()
    if (
        stream.accept_word("and")
        and stream.at_word("has", "have")
        and stream.peek_word(1) == "base"
    ):
        base = _parse_has_base_pt(stream, subject)
        if isinstance(base, ast.SetBasePT):
            if duration.kind is None and base.duration.kind is not None:
                grant = ast.GainKeyword(
                    subject, keywords, base.duration, choose_one=choose_one
                )
            elif base.duration.kind is None:
                base = dataclasses.replace(base, duration=duration)
            return ast.Conjunction((grant, base))
    stream.reset(base_mark)
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
    # "…this creature loses "Prevent all damage that would be dealt to this
    # creature."" (Glittering Lion.) The gain branch's quoted reading with the
    # verb turned round, through the same reader of the quoted text — CR
    # 613.1f's removal of a whole printed ability rather than of a word.
    if stream.at_kind(QUOTE):
        abilities, self_name = _parse_quoted_abilities(stream)
        return ast.LoseAbilityText(
            subject, abilities, _parse_duration(stream), self_name=self_name
        )
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
    # "loses **life equal to its power**" (Death Watch, Lich, Illicit Auction).
    # The mirror of the gain production's own first branch, in the word order
    # this shape prints: "life" comes *before* the quantity, so the
    # amount-then-noun reading below cannot see it — `parse_amount` refuses on
    # the word "life", the whole production falls through to the keyword list,
    # and the line dies on "expected a keyword ability" naming a word the
    # sentence does not contain.
    #
    # One printed idea, two verbs. A gain and a loss of the same amount are the
    # same clause with the sign flipped (CR 119.3), and reading it for one
    # verb only is what made "you gain life equal to its toughness" legal and
    # "its controller loses life equal to its power" not — on the two halves of
    # a single printed sentence.
    equal_mark = stream.mark()
    if stream.at_word("life"):
        stream.advance()
        amount = parse_equal_to(stream)
        if amount is None:
            stream.reset(equal_mark)
        else:
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            return ast.LoseLife(player, amount)
    try:
        amount = parse_amount(stream)
        if stream.accept_word("life"):
            player = subject if isinstance(subject, ast.PlayerRef) else ast.PlayerRef("you")
            # "loses 2 life for each creature card in their graveyard"
            # (Liliana, Death Mage) — a multiplier over a count of objects,
            # recorded rather than consumed-and-dropped.
            #
            # The *history* spellings are read first and through
            # ``phrases._parse_for_each``, the reader the gain-life production
            # already uses: "for each creature that died this way" (Reign of
            # Terror) has a relative clause the bare noun phrase below stops in
            # front of, so it used to leave "that died this way" as unconsumed
            # text and take the whole line down. A second inline reader here is
            # what made one printed idiom mean two things depending on the verb
            # in front of it.
            per_each: object | None = _parse_for_each(stream, allow_this_way=True)
            if per_each is None:
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
    # "…target creature with the chosen ability **loses it**" (Phyrexian
    # Splicer). The other half of the same pronoun the gain production reads,
    # and read here for the same reason: "it" is not a keyword and the list
    # would refuse it.
    it_mark = stream.mark()
    if stream.accept_word("it"):
        return ast.LoseKeyword(
            subject, (), _parse_duration(stream), chosen_ability=True,
        )
    stream.reset(it_mark)
    # "…target creature **loses all abilities**…" (Humble, Soul Sculptor.)
    # CR 613.1f's blanket removal, and the words are not a keyword list: read by
    # ``_parse_keywords`` below the line died on "expected a keyword ability at
    # 'all abilities'", a refusal naming a word the card does print and a
    # category it does not belong to.
    #
    # Read after the counter branch above, which has already backtracked off
    # this phrase on the missing word "counter" (its own comment says so), and
    # before the keyword list, which is the only reader left. Both words are
    # required: "loses all" alone names no set, and a card printing "loses all
    # <something else>" is a sentence this has no reading for and must keep
    # refusing.
    all_mark = stream.mark()
    if stream.accept_phrase("all", "abilities"):
        all_duration = _parse_duration(stream)
        stripped = ast.LoseKeyword(
            subject, (), all_duration, all_abilities=True,
        )
        # "…loses all abilities **and has base power and toughness 0/1**."
        # (Humble.) The same join the grant arm above makes with the same
        # right-hand side and under the same duration rule — whichever half
        # printed a window governs both — and it is read here for that arm's
        # reason: a base P/T is not a word layer 6 holds, so it can be neither a
        # member of a keyword list nor a second sentence, and left unread it is
        # unconsumed text that takes the whole line down.
        #
        # "base" is checked before dispatching, exactly as that arm checks it:
        # "loses all abilities and has flying" opens on the same two words and
        # is a sentence this must not claim.
        base_mark = stream.mark()
        if (
            stream.accept_word("and")
            and stream.at_word("has", "have")
            and stream.peek_word(1) == "base"
        ):
            base = _parse_has_base_pt(stream, subject)
            if isinstance(base, ast.SetBasePT):
                if all_duration.kind is None and base.duration.kind is not None:
                    stripped = ast.LoseKeyword(
                        subject, (), base.duration, all_abilities=True,
                    )
                elif base.duration.kind is None:
                    base = dataclasses.replace(base, duration=all_duration)
                return ast.Conjunction((stripped, base))
        stream.reset(base_mark)
        return stripped
    stream.reset(all_mark)
    # "loses **your choice of** flying, first strike, or trample" (Walking
    # Sponge) — the mirror of the four words :func:`_parse_gains` reads for
    # Alchemist's Gift, and read here for that branch's reason exactly: CR
    # 608.2d announces the pick while the effect is applied, so the connective
    # is *read* rather than normalised away.
    #
    # It was not, and the disjunction went with it. ``_parse_keywords`` throws
    # away the flag ``parse_keyword_list`` returns, so "loses flying, first
    # strike, or trample" removed all three — the same near miss the grant's
    # own docstring records on the other side of the layer, and the one word
    # away from being a card that does more than it prints.
    choose_one = bool(stream.accept_phrase("your", "choice", "of"))
    keywords, disjunctive = parse_keyword_list(stream)
    choose_one = choose_one or disjunctive
    duration = _parse_duration(stream)
    if choose_one and len(keywords) < 2:
        raise stream.error("a choice of keywords needs more than one")
    return ast.LoseKeyword(subject, keywords, duration, choose_one=choose_one)


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
    # "…**has base toughness 1**." (Chariot of the Sun.) The half CR 613.4b's
    # rewrite leaves the other stat printed, which is exactly what
    # ``set_base_pt``'s None already expresses — People of the Woods is the
    # same asymmetry one file over, where a characteristic-defining ability
    # names the toughness and the printed power stands. Read before "power" is
    # demanded, because the word is not there.
    if stream.accept_word("toughness"):
        toughness = parse_amount(stream)
        return ast.SetBasePT(subject, None, toughness, _parse_duration(stream))
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
    # "…has base power 1 **or base toughness 1**." (Vhati il-Dal.) A choice
    # between two rewrites of the same creature, and CR 608.2d's kind rather
    # than CR 700.2's: 700.2 defines a modal ability as a *bulleted* list
    # preceded by "Choose one —", and this sentence prints no bullets, so the
    # option is announced while the effect is applied rather than as the ability
    # is activated.
    #
    # Read **after** the "and toughness" branch above and after the amount, not
    # before either. Placed ahead of them it consumed the "and" of "base power
    # and toughness 0/2" as an amount and took Sorceress Queen, Jolrael and
    # Cycle of Life down with it — three shipped cards, and the differential is
    # the only thing that said so.
    or_mark = stream.mark()
    if stream.accept_word("or") and stream.words_from()[:2] == ("base", "toughness"):
        stream.advance(2)
        alternative_toughness = parse_amount(stream)
        duration = _parse_duration(stream)
        return ast.SetBasePT(
            subject, power, None, duration,
            alternative=ast.SetBasePT(subject, None, alternative_toughness, duration),
        )
    # An "or" that opens anything else is not this sentence's — put back, so the
    # statement layer keeps whatever refusal it has today rather than getting a
    # manufactured one from a production that was never a candidate.
    stream.reset(or_mark)
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
