"""Condition productions: the *event* half of a trigger or an intervening-if.

Split out of `statements.py` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut, because a condition answers a different question
from everything left behind: a statement says what an effect **will do**, a
condition describes what **has happened** — "a creature you control dies", "you
control seven or more lands", "you win the flip". Nothing here builds an
`ast.Effect` and nothing here can, which is why the file depends on `nouns`,
`amounts` and `phrases` and on no statement production at all.

That independence is the layer position: `conditions` sits beside `statements`
rather than above it, and `parser` reads both.

Anything the table does not model raises so the line falls back rather than
silently losing the condition — the legacy compiler dropped intervening-ifs
entirely, which made every conditional trigger fire unconditionally.
"""

import dataclasses

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import PT
from .amounts import parse_comparison
from .nouns import parse_object_filter
from .readers import accept_source_reference, accept_source_reference_spec
from .references import parse_player_ref, parse_target_spec
from .phrases import (_accept_self_reference, _parse_duration,
                      _parse_keywords, parse_bound_subject)
from .condition_clauses import (_accept_it_is,
                                _parse_blockers_of_bound_creature,
                                _parse_self_in_graveyard_above)
from .stream import TokenStream
from .vocabulary import COLOR_WORDS, NUMBER_WORDS


#: What every state condition below is asked *about*: the ability's own source.
#: The subject is fixed because the evaluator reads ``context.source_permanent``
#: — a spec naming anything else would describe a permanent nothing looks up.
_SOURCE_SPEC = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))

#: ``(printed word, state, negated)`` for the present-tense "it is …" clause.
#: Each state is a field ``evaluate_condition`` reads straight off the
#: permanent, which is what keeps this a table rather than a branch per card:
#: "it's blocking" (Snow Devil) and "it's attacking" (Snowblind) are the same
#: production as "it's tapped" with a different field name, and a word listed
#: here that no permanent carries would answer False forever.
_PRESENT_STATES: tuple[tuple[str, str, bool], ...] = (
    ("tapped", "tapped", False),
    ("untapped", "tapped", True),
    ("attacking", "attacking", False),
    ("blocking", "blocking", False),
)

#: The characteristics a "…'s <X> is N or greater" / "…has <X> N or greater"
#: clause may ask about. A table rather than a literal in the production for the
#: usual reason: the two words reach the same accessor pair through the same
#: comparison, so a card printing the other one is data, not a second branch.
CHARACTERISTIC_WORDS: tuple[str, ...] = ("power", "toughness")


#: Whom a damage *history* clause names, longest phrase first — the same set
#: `triggers._DAMAGE_RECIPIENTS` reads on the event side, because one printed
#: phrase should mean one thing whether a card asks about the damage as it
#: happens or about the damage it dealt earlier this turn.
_DAMAGE_HISTORY_RECIPIENTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("an", "opponent"), "an opponent"),
    (("a", "player"), "a player"),
    (("you",), "you"),
)


def _parse_condition(stream: TokenStream) -> ast.Condition:
    """One condition, or several joined by "and".

    "If you control an Urza's Mine **and** an Urza's Tower" (the Antiquities
    cycle) is the shape that needed this. The conjunction is read here rather
    than in each clause because it belongs to the clause *list*: nothing stops
    a card conjoining two different condition kinds, and a per-clause "and"
    would have to be written into every one of them.

    The loop backtracks. An "and" that is not followed by a condition belongs
    to whatever comes next — most often the effect ("If you control an Island,
    draw a card **and** gain 1 life") — so a failed continuation rewinds and
    the single condition is returned unchanged.
    """
    first = _parse_single_condition(stream)
    parts = [first]
    while True:
        mark = stream.mark()
        if not stream.accept_word("and"):
            break
        try:
            parts.append(_parse_single_condition(stream))
        except GrammarError:
            stream.reset(mark)
            break
    return first if len(parts) == 1 else ast.EveryOf(tuple(parts))


def _parse_single_condition(stream: TokenStream) -> ast.Condition:
    """Conditions the grammar models today. Anything else raises so the line
    falls back rather than silently losing the condition — the legacy compiler
    dropped intervening-ifs entirely, making conditional triggers always fire."""
    mark = stream.mark()

    # "**this card is in your graveyard with a creature card directly above
    # it**" (Death Spark, Krovikan Horror) / "…**with three or more creature
    # cards above it**" (Nether Shadow). Read first because the opener is three
    # printed words no other condition here begins with, and because it is the
    # one clause whose answer is *where the ability functions* rather than what
    # the board looks like (CR 113.6b).
    grave = _parse_self_in_graveyard_above(stream)
    if grave is not None:
        return grave
    stream.reset(mark)

    # "**this spell's additional cost was paid**" (Undergrowth) — CR 601.2b's
    # optional additional cost, asked about rather than counted. Read here at
    # the top because it is settled by seven fixed words and consumes nothing
    # when they are not there.
    if stream.accept_phrase(
        "this", "spell", "'s", "additional", "cost", "was", "paid"
    ):
        return ast.AdditionalCostWasPaid()
    stream.reset(mark)

    # "you win the flip" / "you lose the flip" (CR 705.2). Read before the
    # player reference below, which would consume the "you" and then reset — and
    # read as a *back-reference* rather than a board state, because the answer is
    # the value an earlier sentence of this same resolution recorded. Lowering
    # refuses one with no flip in front of it.
    if stream.accept_word("you"):
        if stream.accept_phrase("win", "the", "flip"):
            return ast.CoinFlipResult(won=True)
        if stream.accept_phrase("lose", "the", "flip"):
            return ast.CoinFlipResult(won=False)
    stream.reset(mark)

    # "it entered from your graveyard or you cast it from your graveyard"
    # (Archfiend's Vessel). Both halves are required by this production, because
    # the card prints both and either one alone is a narrower condition than the
    # sentence states — an "or" that consumed only its first half would leave
    # the rest as unaccounted text and fail the line, which is the safe
    # direction, but reading it as the first half alone would not be.
    # "two or more of those creatures are attacking you and/or planeswalkers
    # you control" (Mangara). Every word required: "those creatures" is what
    # binds the count to this attack's batch, and the aim clause is what makes
    # it a question about *this* player rather than about attacking at large.
    if stream.at_word("two") or stream.at_word("one") or stream.at_word("three"):
        mark_aim = stream.mark()
        word = stream.peek_word()
        if word in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase(
                "or", "more", "of", "those", "creatures", "are", "attacking",
                "you", "and", "or", "planeswalkers", "you", "control",
            ):
                return ast.AttackersAimedAtYou(NUMBER_WORDS[word])
        stream.reset(mark_aim)
    if stream.accept_phrase("it", "entered", "from"):
        if stream.accept_word("your"):
            zone = stream.peek_word()
            if zone in ("graveyard", "exile", "hand", "library"):
                stream.advance()
                or_cast = False
                after = stream.mark()
                if stream.accept_phrase("or", "you", "cast", "it", "from", "your"):
                    if stream.accept_word(zone):
                        or_cast = True
                    else:
                        stream.reset(after)
                return ast.EnteredFrom(zone, or_cast=or_cast)
    stream.reset(mark)

    # "if **your library has ten or more cards in it**" (Phyrexian Portal).
    # How tall a pile is, which is a different question from every other clause
    # here that reads a player: those ask what the board holds and answer
    # through the layer system, and this one counts a zone nobody can see into.
    #
    # Read before the player reference below because the possessive determiner
    # is its own reading of the seat - ``parse_player_ref`` reads "you", never
    # "your", so the reference parser cannot open this clause at all. Both
    # spellings are here rather than one, because "target opponent's library
    # has …" is the same question about a pile this player may not look at.
    zone_mark = stream.mark()
    zone_owner = None
    if stream.accept_word("your"):
        zone_owner = ast.PlayerRef("you")
    else:
        possessive = parse_player_ref(stream)
        if possessive is not None and stream.accept_word("'s"):
            zone_owner = possessive
    if zone_owner is not None:
        zone = stream.peek_word()
        if zone in ("library", "graveyard", "hand") and stream.peek_word(1) == "has":
            stream.advance(2)
            comparison = parse_comparison(stream)
            stream.expect_word("cards", "card")
            # "…in it" is printed by this template and dropped: it names the
            # zone the sentence has already said.
            stream.accept_phrase("in", "it")
            return ast.ZoneHasCards(zone_owner, zone, comparison)
    stream.reset(zone_mark)

    # "if **that player has five or more cards in hand**" (Misers' Cage,
    # Paupers' Cage) / "if **that player has 5 or less life**" (Razor Pendulum).
    #
    # The hand half is the *same question* the possessive spelling above asks
    # ("your hand has five or more cards"), so it produces the same node and
    # reaches the same evaluator — one behaviour, two printed word orders, which
    # is the arrangement this file keeps for every clause a card can spell two
    # ways. Read here, before the "controls" reference below, because both
    # openers are a player reference and this one is settled by the word after
    # it.
    have_mark = stream.mark()
    counted = parse_player_ref(stream)
    if counted is not None and stream.accept_word("has", "have"):
        comparison = parse_comparison(stream)
        if stream.accept_word("life"):
            return ast.PlayerLifeIs(counted, comparison)
        if stream.accept_word("cards", "card") and stream.accept_phrase("in", "hand"):
            return ast.ZoneHasCards(counted, "hand", comparison)
    stream.reset(have_mark)

    player = parse_player_ref(stream)
    if player is not None:
        if stream.accept_word("control", "controls"):
            # "if an opponent controls more creatures than you" (Garruk,
            # Unleashed). The comparison is against the asker's own count, so
            # it is an op of its own rather than a number to compare with.
            if stream.accept_word("more"):
                filt = parse_object_filter(stream)
                if not stream.accept_phrase("than", "you"):
                    raise stream.error("expected 'than you' after the count")
                return ast.Controls(player, filt, ast.Comparison("more_than_you", ast.Fixed(0)))
            negated = stream.accept_word("no")
            # "you control **a** Swamp". The article carries no meaning of its
            # own, but the noun parser refuses it as an unknown adjective, so
            # leaving it would refuse every singular condition in the pool.
            # "**another** creature…" (Turret Ogre) is an article carrying the
            # source-exclusion — CR 109.5's "other", contracted — so it sets
            # the same field the leading adjective "other" does.
            another = stream.accept_word("another")
            if not another:
                stream.accept_word("a", "an")
            # "you control **two or more** nonland, nontoken permanents…"
            # (Chrome Replicator) / "you control **three or fewer** lands"
            # (Sheltered Valley). Read where it is printed, in front of the
            # noun phrase, and only when "or more"/"or fewer" follows the
            # number: a bare number here would be a different condition
            # ("exactly two"), and no card in the pool prints one, so guessing
            # which it meant is the kind of silent widening a threshold must
            # never take.
            #
            # The two directions are one production because they are one
            # sentence with one word changed, and the word rides the comparison
            # rather than the kind — the evaluator (`handlers/control_flow.
            # _compare_count`) already answers "le" and always did; nothing had
            # ever printed the word that reaches it.
            bound: tuple[str, int] | None = None
            if not negated and not another:
                count_mark = stream.mark()
                try:
                    amount = parse_amount(stream)
                except GrammarError:
                    amount = None
                if isinstance(amount, ast.Fixed) and stream.accept_phrase("or", "more"):
                    bound = ("ge", amount.value)
                elif isinstance(amount, ast.Fixed) and stream.accept_phrase(
                    "or", "fewer"
                ):
                    bound = ("le", amount.value)
                else:
                    stream.reset(count_mark)
            filt = parse_object_filter(stream)
            if another:
                filt = dataclasses.replace(filt, other_than_source=True)
            # "…**with the same name as one another**". A relation over the set
            # just counted, so it is read after the noun phrase and kept off the
            # filter — see `ast.Controls.shared_name`.
            shared_name = bool(
                stream.accept_phrase("with", "the", "same", "name", "as", "one", "another")
            )
            comparison = None
            if negated:
                comparison = ast.Comparison("eq", ast.Fixed(0))
            elif bound is not None:
                comparison = ast.Comparison(bound[0], ast.Fixed(bound[1]))
            first = ast.Controls(player, filt, comparison, shared_name)

            # "you control an Urza's Mine **and** an Urza's Tower" (the
            # Antiquities cycle). The conjunction shares one player and one
            # verb and repeats only the noun, so it is desugared into the same
            # `AllOf` the clause-level "and" builds — "control X and control Y"
            # is what the shared-verb form means, and having one node for both
            # keeps the evaluator from needing a second shape.
            #
            # Only for the plain form. A negated, counted or shared-name clause
            # ("you control no creatures and…") would need the qualifier
            # distributed over each conjunct to stay faithful, and no card in
            # the pool prints one — so it refuses to widen instead of guessing
            # which of the two readings was meant.
            if not negated and bound is None and not shared_name:
                parts = [first]
                while True:
                    conj = stream.mark()
                    if not stream.accept_word("and"):
                        break
                    stream.accept_word("a", "an")
                    try:
                        extra = parse_object_filter(stream)
                    except GrammarError:
                        stream.reset(conj)
                        break
                    parts.append(ast.Controls(player, extra))
                if len(parts) > 1:
                    return ast.EveryOf(tuple(parts))
            return first
        # "you gained 3 or more life this turn" (Indulging Patrician). "Or more"
        # is the only printed comparison on this clause, so the threshold is a
        # plain minimum rather than a Comparison: inventing "or less" here would
        # be a production no card exercises.
        if stream.accept_word("gained"):
            amount = parse_amount(stream)
            if isinstance(amount, ast.Fixed) and stream.accept_phrase(
                "or", "more", "life", "this", "turn"
            ):
                return ast.LifeGainedThisTurn(player, amount.value)
        stream.reset(mark)

    # "if at least one other Wall creature is blocking that creature and no
    # non-Wall creatures are blocking that creature" (Wall of Caltrops). CR
    # 603.4 over CR 509.1a's relation: the clause counts what else is blocking
    # the creature the firing block event named, so its far end is neither the
    # source nor a target and no `ObjectFilter` can carry it — see
    # `ast.BlockersOfBoundCreature`.
    #
    # Read before the source-reference clauses below and after the "you
    # control" one, because it opens on a quantifier rather than on a pronoun
    # and so overlaps neither; the mark/reset is what lets a noun phrase that
    # is *not* followed by "is blocking that creature" fall through unchanged.
    blockers_mark = stream.mark()
    try:
        blocking = _parse_blockers_of_bound_creature(stream)
    except GrammarError:
        blocking = None
    if blocking is not None:
        return blocking
    stream.reset(blockers_mark)

    # "if **no creatures are on the battlefield**" (Pestilence, Withering
    # Wisps). The board's own count, with no seat in it — read here, beside the
    # "you control" clause it is *not*: that one asks a player what they have,
    # and this one asks the zone. Pestilence used to reach a name-keyed hook
    # whose key was this whole sentence, so the identical line on a second card
    # reached nothing at all.
    #
    # The quantifier carries the comparison and only the two English articles
    # are read: a printed number ("if two or more creatures are on the
    # battlefield") is a threshold this does not model, and it falls through
    # rather than being taken as presence.
    zone_mark = stream.mark()
    quantifier = "no" if stream.accept_word("no") else (
        "a" if stream.accept_word("a", "an") else None
    )
    if quantifier is not None:
        try:
            present = parse_object_filter(stream)
        except GrammarError:
            present = None
        if present is not None and (
            stream.accept_phrase("are", "on", "the", "battlefield")
            or stream.accept_phrase("is", "on", "the", "battlefield")
        ):
            return ast.OnBattlefield(
                present,
                ast.Comparison("eq", ast.Fixed(0)) if quantifier == "no"
                else ast.Comparison("ge", ast.Fixed(1)),
            )
    stream.reset(zone_mark)

    # "if **the number is odd**" (Chaos Moon). The parity below with the noun
    # phrase replaced by a back-reference: the number is whatever the "Count the
    # number of permanents." sentence in front of it recorded, so nothing is
    # counted here at all. Read *before* that branch, whose phrase this one is a
    # prefix of — "the number of" would consume "the number" and then fail on
    # "is", taking the line with it.
    counted_mark = stream.mark()
    if stream.accept_phrase("the", "number", "is"):
        for word in ("even", "odd"):
            if stream.accept_word(word):
                return ast.CountedNumber(ast.Comparison(word, ast.Fixed(0)))
    stream.reset(counted_mark)

    # "if **the number of permanents is even**" (Chaos Lord). The same board
    # count as the branch above, compared by *parity* rather than against a
    # threshold — so it is the same node with a different operator, not a
    # second condition kind: what is counted, and where, is identical.
    #
    # The noun phrase is read rather than assumed. "The number of permanents"
    # is the whole board (CR 110.1 makes every object on the battlefield a
    # permanent, whoever controls it), and a card counting something narrower
    # is this same sentence with a different phrase.
    parity_mark = stream.mark()
    if stream.accept_phrase("the", "number", "of"):
        try:
            counted = parse_object_filter(stream)
        except GrammarError:
            counted = None
        if counted is not None and stream.accept_word("is"):
            for word in ("even", "odd"):
                if stream.accept_word(word):
                    return ast.OnBattlefield(
                        counted,
                        # The parity is the whole comparison: the sentence
                        # prints no threshold, and a zero here would read as
                        # one to anything that looked. `lowering/conditions.py`
                        # emits no count for these operators for that reason.
                        ast.Comparison(word, ast.Fixed(0)),
                    )
    stream.reset(parity_mark)

    # "if **it doesn't have rampage**" (Rapid Fire). Read before the two
    # back-references below, which open with the same pronoun: this branch is
    # pinned by the verb that follows it, and it resets when no keyword does.
    keyword_mark = stream.mark()
    if stream.accept_word("it"):
        negated = bool(stream.accept_word("doesn't") or stream.accept_phrase("does", "not"))
        if stream.accept_word("has") or stream.accept_word("have"):
            try:
                keywords = _parse_keywords(stream)
            except GrammarError:
                keywords = None
            if keywords:
                return ast.ObjectHasKeyword(keywords, negated=negated)
    stream.reset(keyword_mark)

    # "if it was a creature card" (Scavenging Ooze). A back-reference, like the
    # flip above and unlike everything below it: no read of the board can answer
    # it, because the card it asks about has already left the zone the effect
    # took it from (CR 608.2h). Which object "it" names is lowering's question,
    # not the parser's — the parser cannot see the sentence in front of it.
    #
    # Guarded and reset, because "it was" is **not** unambiguous: "if it **was
    # blocked this turn**" (Fyndhorn Druid) opens with the same two words and is
    # a question about a combat record, not about a card that left a zone. This
    # branch used to consume the pronoun unconditionally and let the noun parser
    # raise, so that clause failed as "expected a subject" — a refusal naming
    # the wrong layer — and no later production could ever see it.
    it_was_mark = stream.mark()
    if stream.accept_phrase("it", "was"):
        stream.accept_word("a", "an")
        try:
            return ast.ItWas(parse_object_filter(stream))
        except GrammarError:
            pass
    stream.reset(it_was_mark)

    # "Exile the top card of your library. **If that card is a land card**, …"
    # (Chaos Harlequin.) The same back-reference with the pronoun's noun spelled
    # out, exactly as "that <noun> was …" further down spells out the destroy's
    # — so it is the same node rather than a second one: which object it names is
    # still the lowering's question, and the lowering still refuses unless a step
    # in front of it exiled something.
    #
    # **Present tense, and only present tense.** The card is in exile, a zone it
    # has not left again, so "is" is what the card prints and no printed type
    # changed on the way there. The past-tense spelling is left to
    # ``DestroyedTargetWas`` below, whose production reads "that <noun> was" for
    # any noun: taking "that card was" here would steal that clause from it for
    # a sentence no card in the pool prints.
    that_card = stream.mark()
    if stream.accept_phrase("that", "card", "is"):
        stream.accept_word("a", "an")
        try:
            return ast.ItWas(parse_object_filter(stream))
        except GrammarError:
            pass
    stream.reset(that_card)

    # "if **the discarded card** was a land card" (Land's Edge). The same
    # past-tense back-reference as the clause above, naming its producer in
    # words instead of with a pronoun — which is why it is a separate node: the
    # sentence says *which* record it means, and reading it as "it" would let
    # the condition answer off whatever an earlier step happened to write.
    if stream.accept_phrase("the", "discarded", "card", "was"):
        stream.accept_word("a", "an")
        return ast.DiscardedCardWas(parse_object_filter(stream))

    # "if **the exiled creature was a Thrull**" (Soul Exchange); "if **the
    # sacrificed creature was a Thrull**" (Ebon Praetor). The same past-tense
    # back-reference as the two above, naming a *cost* channel instead of a step
    # of the effect: CR 601.2h paid it before the object was on the stack, so
    # the answer is the record the payment kept (CR 608.2h).
    #
    # One production for both verbs, because they are one printed template with
    # the verb changed — and the noun after it is read and dropped the way
    # "that <noun> was …" drops its repeated noun: it names the object the cost
    # ate, which the channel already says.
    #
    # Both tenses. "…**if the exiled card is a snow land**" (Storm Elemental) is
    # the same question about the same record: the card is sitting in exile, so
    # what it *is* and what it *was* are one printed type line — and a second
    # node for the second tense would be two readers of one channel, which is
    # the drift this production was written as one branch to avoid.
    cost_mark = stream.mark()
    if stream.accept_word("the"):
        verb = stream.peek_word()
        if verb in ("sacrificed", "exiled") and stream.peek_word(2) in ("was", "is"):
            stream.advance(3)
            stream.accept_word("a", "an")
            try:
                return ast.CostObjectWas(str(verb), parse_object_filter(stream))
            except GrammarError:
                pass
    stream.reset(cost_mark)

    # "if it's a creature or land card" (Track Down) — the present-tense twin of
    # the clause above, and a different question: that one asks what an object
    # *was* before it left a zone, this one asks what a card revealed by an
    # earlier sentence of this same effect *is*. Different producers, so
    # different nodes.
    #
    # Guarded and reset, unlike the past-tense branch, because "it's" is not
    # unambiguous the way "it was" is: "This creature gets +0/+3 **as long as
    # it's untapped**" (Giant Tortoise) opens with the same two words and is a
    # state test, not a card test. So this branch takes the sentence only when a
    # noun phrase naming card *types* follows, and hands it back otherwise.
    it_mark = stream.mark()
    # "If it **isn't** a land card, …" (Wand of Ith) is the same test read the
    # other way, so it is the same branch carrying the word rather than a
    # second one — two readings of one record are two places for it to drift.
    negated = bool(stream.at_word("it")) and _accept_it_is(stream, negated=True)
    if negated or stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is"):
        # "…**if it's red**" (Hydroblast, Pyroblast). A bare colour word, read
        # before the article below because that is what separates the two
        # clauses sharing these two words: "if it's **a** red creature card"
        # keeps its article and is a question about a revealed card, where this
        # is a question about the object the effect targets. The colour is
        # consumed against `COLOR_WORDS` rather than through the noun parser,
        # which needs a head noun and would refuse the phrase outright.
        colour = stream.peek_word()
        if colour in COLOR_WORDS:
            stream.advance()
            return ast.ItIsColor(COLOR_WORDS[colour], negated=negated)
        stream.accept_word("a", "an")
        try:
            revealed_filter = parse_object_filter(stream)
        except GrammarError:
            revealed_filter = None
        if revealed_filter is not None and revealed_filter.card_types:
            return ast.RevealedCardIs(revealed_filter, negated=negated)
    stream.reset(it_mark)

    # "if **one or more creature cards were put into that graveyard this
    # way**" (Helm of Obedience). A back-reference to the set the loop in front
    # of it recorded, read before the bound-subject clause below because both
    # open on a noun phrase and only this one opens on the printed floor.
    milled_mark = stream.mark()
    if stream.accept_phrase("one", "or", "more"):
        try:
            milled_filter = parse_object_filter(stream)
        except GrammarError:
            milled_filter = None
        if milled_filter is not None and stream.accept_phrase(
            "were", "put", "into", "that", "graveyard", "this", "way"
        ):
            return ast.MilledThisWay(milled_filter)
    stream.reset(milled_mark)

    # "if **a white creature dies this way**" (Cinder Cloud), "if **that
    # creature dies this way**" (Kaervek's Purge). The present tense, asked in
    # the same resolution as the destroy in front of it — which is what makes it
    # a different clause from Infinite Authority's past tense below: that one is
    # checked at the next end step about a destruction an earlier step *armed*,
    # and this one is about what the sentence before it just did.
    #
    # One node with the loop spelling ("for each creature that died this way"),
    # because it names the same set: `ast.DiedThisWay` is the destroy family's
    # own record, and a second node for the same record would be a second
    # answer to which objects the words mean.
    #
    # Read **before** the past tense below, whose "that <noun>" opening this
    # shares: tried second, the bound reader would consume "that creature" and
    # then fail on "dies", taking the whole condition with it.
    dies_mark = stream.mark()
    stream.accept_word("a", "an")
    try:
        dying = parse_object_filter(stream)
    except GrammarError:
        dying = None
    if dying is not None and stream.accept_phrase("dies", "this", "way"):
        return ast.DiedThisWay(dying)
    stream.reset(dies_mark)
    if stream.accept_word("that"):
        # "if **that creature** dies this way" — the bound spelling, whose noun
        # is the one the destroy in front of it used. The noun is consumed and
        # dropped for the reason the past-tense reader below drops its own: the
        # object is whatever that step recorded, and the lowering is what checks
        # a step in front of it destroyed something.
        bound_noun = stream.mark()
        try:
            named = parse_object_filter(stream)
        except GrammarError:
            named = None
        if named is not None and stream.accept_phrase("dies", "this", "way"):
            return ast.DiedThisWay(named)
        stream.reset(bound_noun)
        stream.reset(dies_mark)

    # "if **that creature was destroyed this way**" (Infinite Authority). The
    # bound object is read through the shared reader rather than skipped: the
    # sentence is checked at the next end step, long after the destruction it
    # asks about, and which creature it names is the whole question.
    this_way = stream.mark()
    bound = parse_bound_subject(stream)
    if bound is not None and stream.accept_phrase("was", "destroyed", "this", "way"):
        return ast.DestroyedThisWay(bound.filter)
    stream.reset(this_way)

    # "if **that land** was a snow land" (Icequake, Thermokarst). The same
    # past tense as the pronoun further up, naming its referent with the noun
    # the destroy in front of it used — and asked of a *permanent*, so the whole
    # noun phrase is read rather than a printed type line. The repeated noun is
    # consumed and dropped: it is the object the earlier step chose, and
    # lowering is what checks a step in front of it destroyed one.
    #
    # **Read after "that <noun> was destroyed this way"**, whose prefix this is:
    # tried first it would consume "that creature was" and then fail on
    # "destroyed this way", and Infinite Authority's condition would stop
    # parsing. The filter parse is guarded for the same reason — a `that …
    # was …` opening that is some other clause has to rewind rather than raise
    # out of the whole condition.
    that_mark = stream.mark()
    if stream.accept_word("that"):
        if stream.peek_word() is not None and stream.peek_word(1) == "was":
            stream.advance(2)
            stream.accept_word("a", "an")
            try:
                return ast.DestroyedTargetWas(parse_object_filter(stream))
            except GrammarError:
                pass
    stream.reset(that_mark)
    stream.reset(this_way)

    # "if a creature **dealt damage by this creature this turn** died"
    # (Krovikan Vampire). Read before the bare spelling below it — the two share
    # their first two words and differ in everything that follows — and read as
    # its own condition rather than as a filter on that one, because the
    # relation has no payload form and would be dropped (see the node).
    relation = stream.mark()
    if stream.accept_phrase("a", "creature", "dealt", "damage", "by"):
        if _accept_self_reference(stream) and stream.accept_phrase(
            "this", "turn", "died"
        ):
            _parse_duration(stream)
            return ast.DamagedBySourceDiedThisTurn()
    stream.reset(relation)

    if stream.accept_phrase("a", "creature", "died"):
        _parse_duration(stream)
        return ast.DiedThisTurn(ast.ObjectFilter(card_types=("creature",)))

    # "if a permanent was put into your hand from the battlefield this turn"
    # (Barrin, Tolarian Archmage). Every word is read: "from the battlefield"
    # is what keeps a draw or a graveyard return from satisfying it.
    if stream.accept_phrase(
        "a", "permanent", "was", "put", "into", "your", "hand",
        "from", "the", "battlefield",
    ):
        _parse_duration(stream)
        return ast.ReturnedToHandThisTurn()

    # "if **this card is exiled with a scream counter on it**" (All Hallow's
    # Eve). CR 603.4's intervening-if over an object in exile — the one zone
    # this engine had no way to ask about, because a card there is a bare
    # ``CardDefinition`` with no object to carry state. The register in
    # ``engine/exiled_records.py`` is what answers it.
    #
    # Read before the tapped/untapped state clause below, which shares the
    # "<source> is" opening: both mark and reset, so the order decides only
    # which refusal survives, and the more specific question asking first keeps
    # "exiled" from being reported as an unrecognised state word.
    exiled_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase("is", "exiled", "with"):
        stream.accept_word("a", "an")
        counter_word = stream.peek_word()
        if counter_word is not None and counter_word not in ("counter", "counters"):
            stream.advance()
            if (
                stream.accept_word("counter", "counters")
                and stream.accept_phrase("on", "it")
            ):
                return ast.SourceExiledWithCounter(counter_word)
    stream.reset(exiled_mark)

    # "if **there are no more scream counters on it**" (All Hallow's Eve),
    # "if **there are no time counters on this Aura**" (Tourach's Gate),
    # "as long as **there is exactly one tide counter on this creature**"
    # (Homarid, Tidal Influence). One production over the three axes the pool
    # varies independently, for the reason the tapped/untapped clause below
    # states about its own four spellings: written out as one phrase each, the
    # spelling nobody listed reads as a parser gap rather than as the same
    # question.
    #
    # The axes are the copula ("there is" for a singular counter, "there are"
    # for a plural), the number ("no", "no more", "exactly one", "exactly
    # three" — every one of them an *equality*), and how the card names the
    # object holding them ("on it", "on this Aura", "on this creature"), which
    # is `accept_source_reference`'s question everywhere else.
    #
    # "no more" and "no" are one phrase with an optional word: the difference
    # is English, not a different question — both say the count is zero. So is
    # "exactly": it is the comparison this node already defaults to, printed
    # out loud because the card needs to distinguish one tide counter from
    # three.
    empty_mark = stream.mark()
    if stream.accept_word("there") and stream.accept_word("is", "are"):
        count: int | None = None
        if stream.accept_word("no"):
            stream.accept_word("more")
            count = 0
        elif stream.accept_word("exactly"):
            word = stream.peek_word()
            if word is not None and word in NUMBER_WORDS:
                stream.advance()
                count = NUMBER_WORDS[word]
        if count is not None:
            counter_word = stream.peek_word()
            if counter_word is not None and counter_word not in ("counter", "counters"):
                stream.advance()
                if stream.accept_word("counters", "counter") and stream.accept_word("on"):
                    if accept_source_reference(stream):
                        return ast.SourceCounterCount(counter_word, count)
    stream.reset(empty_mark)

    # "if **it has five or more hunger counters on it**" (Fasting) — the same
    # count of the same source's counters, with the comparison the card prints.
    # A second spelling rather than a second node: `SourceCounterCount` already
    # carries the number, and its docstring said the wider comparison should
    # extend this production. "it has" and "there are" are the two printed
    # subjects for one question, so both read a source reference here —
    # `accept_source_reference` also takes the card naming itself, which is how
    # a pre-modern printing ("if Fasting has …") reaches the same branch.
    threshold_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_word("has"):
        word = stream.peek_word()
        if word is not None and word in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase("or", "more"):
                counter_word = stream.peek_word()
                if counter_word is not None and counter_word not in (
                    "counter", "counters"
                ):
                    stream.advance()
                    if (
                        stream.accept_word("counters", "counter")
                        and stream.accept_phrase("on", "it")
                    ):
                        return ast.SourceCounterCount(
                            counter_word, NUMBER_WORDS[word], comparison="at_least"
                        )
    stream.reset(threshold_mark)

    # "if **this ability has been activated four or more times this turn**"
    # (Farrelite Priest, Initiates of the Ebon Hand). The one condition here
    # that asks about the ability rather than about a board: how often the very
    # line carrying it has been used since the turn began.
    #
    # Every word is required, and two of them carry the whole meaning. The
    # number and its comparison are read rather than skipped — a threshold read
    # as "at least once" arms the drawback on the first activation, which is a
    # strictly harsher card. "**This turn**" is the window, and without it the
    # clause would be the lifetime count the same ledger also keeps
    # (``activations_ever``), which is a different question.
    tally_mark = stream.mark()
    if stream.accept_phrase("this", "ability", "has", "been", "activated"):
        word = stream.peek_word()
        if word is not None and word in NUMBER_WORDS:
            stream.advance()
            if (
                stream.accept_phrase("or", "more")
                and stream.accept_word("times")
                and stream.accept_phrase("this", "turn")
            ):
                return ast.SourceAbilityActivations(NUMBER_WORDS[word])
    stream.reset(tally_mark)

    # "if it had a +1/+1 counter on it" (Basri's Lieutenant). Past tense, and
    # that is the whole point: "it" is the creature that just died, so the
    # answer is last-known information (CR 603.10) recorded as the trigger
    # fires rather than a board state anything could read afterwards.
    # "+1/+1" lexes as a PT token, so the phrase is matched in two halves
    # around it rather than as a word run.
    counter_mark = stream.mark()
    if stream.accept_phrase("it", "had", "a"):
        token = stream.peek()
        if token is not None and token.kind == PT and token.text == "+1/+1":
            stream.advance()
            if stream.accept_phrase("counter", "on", "it"):
                return ast.HadPlus1Counter()
    stream.reset(counter_mark)

    # "if this artifact is tapped" (Mana Vault), "if it's untapped" (Aladdin's
    # Ring), "if this is untapped" — one production over the two axes the pool
    # varies independently: how the card names itself, and which way round the
    # state is asked. Writing the four printed spellings out as four phrases is
    # what left "is tapped" unread while "is untapped" worked, which for an
    # intervening-if is the silent direction — a gate nothing can fail.
    #
    # "it's untapped" reaches the same branch as "it is": the lexer splits the
    # contraction into "it" + "'s", so both copulas are accepted here rather
    # than the apostrophe being skipped wherever it turns up.
    # "if this creature dealt damage to an opponent this turn" (Whirling
    # Dervish). CR 603.4's intervening-if over a *history*: the board says
    # nothing about whom this permanent has damaged, so the damage seam records
    # it (`engine/damage_events.py`) and this reads that record.
    #
    # Whom the damage went to is read from the same recipient table the damage
    # *trigger* uses, and for the same reason: a card printed "…to a player" or
    # "…to you" is this production with a different payload, not a second
    # condition. The duration is required rather than optional — "dealt damage"
    # with no window is a different claim, and admitting it would answer a
    # question the record cannot ask.
    # "if **it has blocked or been blocked since your last upkeep**" (Wiitigo).
    # A history over a window that spans the opponents' turns, so no board read
    # answers it: the declare-blockers step stamps a seat-turn ordinal and
    # `turn_state.in_a_block_since_seats_last_upkeep` does the arithmetic.
    #
    # Every word is required. "Blocked or been blocked" is CR 509.1a's relation
    # from both ends and the stamp is written for both, so reading only the
    # first half would be a narrower condition than the card prints — and the
    # window is what makes the question answerable at all, so a sentence with a
    # different one has to fail here rather than borrow this one.
    block_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase(
        "has", "blocked", "or", "been", "blocked", "since", "your", "last", "upkeep"
    ):
        return ast.InABlockSinceLastUpkeep(_SOURCE_SPEC)
    stream.reset(block_mark)

    # "if this creature **attacked or blocked this combat**" (the four Clockwork
    # creatures, Kjeldoran Home Guard). The same two-sided history over the
    # narrowest window there is. Read as a condition rather than left to the
    # text probe the end-of-combat step used to carry: with no production here
    # the whole line compiled as a *static* line, which is a printed trigger
    # nothing announces — fine while one card's counter removal was hard-coded
    # beside the sweep, and no use at all to the next card that prints it.
    #
    # Every word required. "Attacked this combat" alone is a narrower claim and
    # "this turn" a wider window, and both are different sentences.
    combat_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase(
        "attacked", "or", "blocked", "this", "combat"
    ):
        return ast.AttackedOrBlockedThisCombat(_SOURCE_SPEC)
    stream.reset(combat_mark)

    damage_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase("dealt", "damage", "to"):
        for phrase, recipient in _DAMAGE_HISTORY_RECIPIENTS:
            if stream.accept_phrase(*phrase):
                if _parse_duration(stream).kind == "this_turn":
                    return ast.DealtDamageThisTurn(_SOURCE_SPEC, recipient)
                break
    stream.reset(damage_mark)

    # "if **this creature's power is 1 or more**" (Lesser Werewolf). A question
    # about the source's computed power (CR 613 layer 7), so it is read from the
    # same source-reference vocabulary the state and damage-history clauses
    # above use, and the bound is parsed by the same reader every "power N or
    # greater" noun phrase uses — one printed comparison, one meaning.
    #
    # Read before the state clause below, which shares the "<source>'s" prefix:
    # both mark and reset, so the order decides only which error survives, and
    # the more specific question asking first is what keeps "power" from being
    # reported as an unrecognised tapped/untapped word.
    power_mark = stream.mark()
    if accept_source_reference(stream) and (
        stream.accept_word("'s") or stream.accept_word("is")
    ):
        for word in CHARACTERISTIC_WORDS:
            if stream.accept_phrase(word, "is"):
                return ast.SubjectCharacteristicIs(
                    _SOURCE_SPEC, word, parse_comparison(stream)
                )
    stream.reset(power_mark)

    # "if **target creature has toughness 5 or greater**" (Blood Lust). The same
    # question about the same accessor, asked of an object the clause *names*
    # rather than of the ability's source — so the subject is parsed as an
    # ordinary noun phrase and travels on the node.
    #
    # This is the one condition that may introduce a target (CR 601.2c): the
    # spell's whole effect is the branch, so the creature is chosen here and the
    # arms refer back to it. The printed word "target" is therefore **required**
    # — "if a creature has toughness 5 or greater" is a question about a *set*,
    # which this node cannot ask and which would silently become a question
    # about whichever creature the resolver happened to hand back.
    has_mark = stream.mark()
    try:
        spec = parse_target_spec(stream)
    except GrammarError:
        spec = None
    if spec is not None and spec.targeted and stream.accept_word("has"):
        for word in CHARACTERISTIC_WORDS:
            if stream.accept_word(word):
                return ast.SubjectCharacteristicIs(
                    spec, word, parse_comparison(stream)
                )
    stream.reset(has_mark)

    # "if this creature **started the turn** untapped" (Rasputin Dreamweaver).
    # The same tapped/untapped axis the present-tense clause below reads, asked
    # of the moment the turn began — a different node, so nothing that knows
    # only the present tense can answer it by accident. Read before that clause
    # because both open on a source reference and only this one has a verb of
    # its own; the order decides which error survives, not which card is read.
    started_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase(
        "started", "the", "turn"
    ):
        if stream.accept_word("tapped"):
            return ast.StartedTheTurnState(_SOURCE_SPEC, "tapped")
        if stream.accept_word("untapped"):
            return ast.StartedTheTurnState(_SOURCE_SPEC, "tapped", negated=True)
    stream.reset(started_mark)

    state_mark = stream.mark()
    # The spec, not the bare predicate: a printed "it" is a pronoun and may name
    # the object the trigger's condition described (Aggression's "…if **it**
    # didn't attack this turn", printed on an Aura and asked of the creature it
    # enchants), while "this creature" and the card's own name always mean the
    # source. `rebinding` tells them apart by the quantifier, so the word has to
    # survive this far.
    subject = accept_source_reference_spec(stream)
    if subject is not None:
        if stream.accept_word("is") or stream.accept_word("'s"):
            for word, state, negated in _PRESENT_STATES:
                if stream.accept_word(word):
                    return ast.IsState(subject, state, negated=negated)
        # "…**didn't attack this turn**" / "…**attacked this turn**"
        # (Aggression, and the delayed end-step destruction Norritt's family
        # prints about a creature it chose). The same axis the present-tense
        # clause above reads, asked of the turn's record rather than of the
        # board — `Permanent.attacked_this_turn`, which the cleanup step sweeps.
        if stream.accept_phrase("didn't", "attack", "this", "turn"):
            return ast.IsState(subject, "attacked_this_turn", negated=True)
        if stream.accept_phrase("attacked", "this", "turn"):
            return ast.IsState(subject, "attacked_this_turn")
        # "…**was blocked this turn**" (Fyndhorn Druid). CR 509.1a's relation
        # from the attacker's end, over the whole turn rather than the current
        # combat — which is why it is not the present-tense "it's blocked" the
        # table above would give: the creature this asks about is usually dead
        # by the time the question is asked, and a creature blocked in the first
        # combat is still one in the second main phase.
        if stream.accept_phrase("was", "blocked", "this", "turn"):
            return ast.IsState(subject, "was_blocked_this_turn")
        # "…**regenerated this turn**" (Spiny Starfish). A record of the turn
        # like the two above, kept by ``engine/regeneration._apply`` — the one
        # place a regeneration happens — and read here as its presence half.
        if stream.accept_phrase("regenerated", "this", "turn"):
            return ast.IsState(subject, "regenerated_this_turn")
    stream.reset(state_mark)

    raise stream.error("unrecognized condition")
