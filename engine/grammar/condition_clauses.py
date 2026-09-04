"""The printed *clauses* a condition is built from.

Split out of ``conditions.py`` at the guard, along the boundary that module
already had in its own shape: ``_parse_single_condition`` is a dispatcher over
the whole vocabulary of conditions, and these are the readers it hands a
sentence to - one printed clause each, read to its end, non-consuming on
refusal so the dispatcher's next branch keeps its say.

The name is ``sentence_clauses``' one layer over, and for the same reason: that
module holds the clauses ``parse_statement`` reads around a body, and this one
holds the clauses ``_parse_condition`` reads inside one. Below ``conditions``,
which calls into it and is never imported back.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .nouns import parse_object_filter
# The moved block's own imports, and they moved *with* it: a function that
# changes module leaves its imports behind, which is the failure this
# package's scans exist to catch loudly rather than at the line that runs.
from .phrases import (_accept_self_reference, _parse_duration,
                      parse_bound_subject)
from .stream import TokenStream
from .vocabulary import CARD_TYPES, COLOR_WORDS, NUMBER_WORDS


def _parse_self_in_graveyard_above(
    stream: TokenStream,
) -> "ast.SelfInGraveyardWithCardsAbove | None":
    """``this card is in your graveyard with <N> <type> card(s) [directly] above
    it``, or None without consuming when the sentence is something else.

    Non-consuming on refusal, like every other tried-first production in this
    package: a clause that read "this card is in your graveyard" and then failed
    on the words after it would take the whole line's refusal site with it.

    "Above" is CR 404.3's order — a graveyard is an ordered zone and a card put
    there later sits on top — so the count and the "directly" are both about
    *positions*, which is why they are separate fields rather than one number.
    """
    if not stream.accept_phrase("this", "card", "is", "in", "your", "graveyard"):
        return None
    if not stream.accept_word("with"):
        raise stream.error("expected 'with' after the graveyard clause")
    at_least = False
    if stream.accept_word("a", "an"):
        count = 1
    else:
        word = stream.peek_word()
        if word not in NUMBER_WORDS:
            raise stream.error("expected a number of cards above it")
        stream.advance()
        count = NUMBER_WORDS[word]
        # "three **or more**". Without it the clause is an exact count, which is
        # a different question and one no card in the pool prints — so it is
        # read rather than assumed, and the lowering carries whichever was
        # printed.
        at_least = bool(stream.accept_phrase("or", "more"))
    card_type = stream.peek_word()
    if card_type not in CARD_TYPES:
        raise stream.error("expected a card type above it")
    stream.advance()
    if not stream.accept_word("card", "cards"):
        raise stream.error("expected 'card' or 'cards' above it")
    directly = bool(stream.accept_word("directly"))
    if not stream.accept_phrase("above", "it"):
        raise stream.error("expected 'above it'")
    return ast.SelfInGraveyardWithCardsAbove(
        card_type=card_type, count=count, at_least=at_least, directly=directly,
    )


def _parse_blockers_of_bound_creature(
    stream: TokenStream,
) -> ast.BlockersOfBoundCreature | None:
    """"<quantifier> <noun phrase> is/are blocking that creature".

    The quantifier is what the clause *counts*, and every spelling the pool
    prints is read here rather than being split across productions: "no" is a
    zero, "at least N" and "N or more" are the same minimum written two ways,
    and a bare "a"/"an" is that minimum with the one left implicit. None of
    them is baked into a kind — the number rides the comparison, so a card
    printed "at least two" needs no code.

    Returns None (rather than raising) when the words parse as a noun phrase
    that is simply not followed by this relation, so the caller's reset hands
    the sentence back to the productions after it.
    """
    negated = bool(stream.accept_word("no"))
    at_least: int | None = None
    if not negated:
        if stream.accept_phrase("at", "least"):
            amount = parse_amount(stream)
            if not isinstance(amount, ast.Fixed):
                # The evaluator compares an integer; an X or a board count
                # would be compared against a node. Refused rather than
                # coerced, exactly as `SubjectPowerIs` refuses one.
                raise stream.error("the blocker count is a printed number")
            at_least = amount.value
        else:
            count_mark = stream.mark()
            try:
                amount = parse_amount(stream)
            except GrammarError:
                amount = None
            if isinstance(amount, ast.Fixed) and stream.accept_phrase("or", "more"):
                at_least = amount.value
            else:
                stream.reset(count_mark)
                # "a Wall is blocking that creature" — the minimum left
                # implicit. Accepted with the article consumed so the noun
                # parser below reads the same phrase either way; the article is
                # not required, because "creatures blocking that creature" is
                # the same clause with the plural doing the work.
                stream.accept_word("a", "an")
                at_least = 1
    other = bool(stream.accept_word("other"))
    filt = parse_object_filter(stream)
    if other:
        # "at least one **other** Wall creature": the asking permanent never
        # satisfies its own condition — it is already blocking that creature,
        # which is why the trigger fired at all.
        filt = dataclasses.replace(filt, other_than_source=True)
    if not (stream.accept_word("is") or stream.accept_word("are")):
        return None
    if not stream.accept_phrase("blocking", "that", "creature"):
        return None
    comparison = (
        ast.Comparison("eq", ast.Fixed(0))
        if negated
        else ast.Comparison("ge", ast.Fixed(at_least or 1))
    )
    return ast.BlockersOfBoundCreature(filt, comparison)


def _accept_it_is(stream: TokenStream, *, negated: bool) -> bool:
    """``it isn't`` / ``it is not`` — the negative spelling of "it's".

    Its own reader because the negation is printed three ways and the
    contraction is one token to the lexer's eye in only one of them; a branch
    that read "isn't" alone would leave "is not" unread, and an unread negation
    is the condition answering the opposite of what the card says.
    """
    mark = stream.mark()
    if stream.accept_word("it") and (
        stream.accept_word("isn't")
        or (stream.accept_word("is") and stream.accept_word("not"))
    ):
        return negated
    stream.reset(mark)
    return False


def _accept_quality_with_implied_noun(
    stream: TokenStream, noun: str
) -> "ast.ObjectFilter | None":
    """The filter "was **nonbasic**" states about a *noun* named earlier.

    "If that land was nonbasic, …" (Choking Sands) prints the quality without
    its head noun, because the sentence supplied one two words back. The
    adjective run is lifted out, the noun put on the end, and the rebuilt
    phrase handed to :func:`parse_object_filter` — the **same** reader the
    spelled-out "a nonbasic land" beside it goes through, which is what keeps
    the two spellings one restriction rather than two readings of an adjective.

    Non-consuming on refusal, and the run stops at the first non-word token —
    for this clause the comma before the consequence — so a quality this cannot
    read leaves the condition to the readers behind it rather than swallowing
    the rest of the sentence.
    """
    from .lexer import tokenize

    start = stream.mark()
    count = 0
    while stream.peek_word(count) is not None:
        count += 1
    if count == 0:
        return None
    phrase = stream.text_between(start, start + count)
    if not phrase:
        return None
    rebuilt = f"a {phrase} {noun}"
    lexed = tokenize(rebuilt)
    if not lexed.tokens:
        return None
    inner = TokenStream(lexed.tokens, rebuilt)
    inner.accept_word("a")
    try:
        filt = parse_object_filter(inner)
    except GrammarError:
        return None
    if not inner.exhausted:
        return None
    stream.advance(count)
    return filt

def _accept_record_condition(stream: TokenStream) -> "ast.Condition | None":
    """Every condition answered by a **record** of something already done.

    "It was a creature card" (Scavenging Ooze), "a white creature dies this way"
    (Cinder Cloud), "the discarded card was a land card" (Land's Edge), "a
    permanent was put into your hand from the battlefield this turn" (Barrin) —
    none of them is answerable by looking at the board, because the object each
    asks about has already left the zone the effect took it from (CR 608.2h) or
    the event it asks about is over.

    That is the cut ``ast/conditions.py`` and ``ast/records.py`` already draw one
    package over, taken here when ``conditions`` crossed the thousand-line guard
    at a wave's integration — on nobody's branch, four groups' additions merely
    summing, which is the guard surfacing a boundary that was already there.

    A clause reader like the three above it and with the same contract: it reads
    a sentence to its end and returns the node, or returns None **with the
    cursor where it found it**, so the dispatcher's next branch keeps its say.
    Every probe inside marks and resets its own attempt for the same reason —
    "it was" opens both a card test and a combat-record test, and a branch that
    consumed the pronoun unconditionally made the second one fail as "expected a
    subject", a refusal naming the wrong layer.

    Which object a pronoun names is the *lowering's* question, not this one's:
    the parser cannot see the sentence in front of it, and every node here is
    refused downstream unless a step of the same effect declared the producer.
    """
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
        noun = stream.peek_word()
        if noun is not None and stream.peek_word(1) == "was":
            stream.advance(2)
            stream.accept_word("a", "an")
            quality_mark = stream.mark()
            try:
                return ast.DestroyedTargetWas(parse_object_filter(stream))
            except GrammarError:
                pass
            stream.reset(quality_mark)
            # "if that land was **nonbasic**" (Choking Sands) — the same
            # question with the head noun left out, because the sentence said
            # it two words earlier. Read only after the spelled-out form above
            # refuses, and answered by putting the noun back rather than by a
            # second reader of the adjective: the rebuilt phrase goes to the
            # same `parse_subject_filter` every printed noun phrase does, so
            # "nonbasic" narrows a land exactly as "a nonbasic land" would.
            implied = _accept_quality_with_implied_noun(stream, noun)
            if implied is not None:
                return ast.DestroyedTargetWas(implied)
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
    return None
