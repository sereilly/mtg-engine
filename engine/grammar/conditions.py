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
from .readers import accept_source_reference
from .references import parse_player_ref, parse_target_spec
from .phrases import _parse_duration, _parse_keywords, parse_bound_subject
from .stream import TokenStream
from .vocabulary import NUMBER_WORDS


#: What every state condition below is asked *about*: the ability's own source.
#: The subject is fixed because the evaluator reads ``context.source_permanent``
#: — a spec naming anything else would describe a permanent nothing looks up.
_SOURCE_SPEC = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))

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
            # (Chrome Replicator). Read where it is printed, in front of the
            # noun phrase, and only when "or more" follows the number: a bare
            # number here would be a different condition ("exactly two"), and no
            # card in the pool prints one, so guessing which it meant is the
            # kind of silent widening a threshold must never take.
            at_least: int | None = None
            if not negated and not another:
                count_mark = stream.mark()
                try:
                    amount = parse_amount(stream)
                except GrammarError:
                    amount = None
                if (
                    isinstance(amount, ast.Fixed)
                    and stream.accept_phrase("or", "more")
                ):
                    at_least = amount.value
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
            elif at_least is not None:
                comparison = ast.Comparison("ge", ast.Fixed(at_least))
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
            if not negated and at_least is None and not shared_name:
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
    if stream.accept_phrase("it", "was"):
        stream.accept_word("a", "an")
        return ast.ItWas(parse_object_filter(stream))

    # "if **the discarded card** was a land card" (Land's Edge). The same
    # past-tense back-reference as the clause above, naming its producer in
    # words instead of with a pronoun — which is why it is a separate node: the
    # sentence says *which* record it means, and reading it as "it" would let
    # the condition answer off whatever an earlier step happened to write.
    if stream.accept_phrase("the", "discarded", "card", "was"):
        stream.accept_word("a", "an")
        return ast.DiscardedCardWas(parse_object_filter(stream))

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
    if stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is"):
        stream.accept_word("a", "an")
        try:
            revealed_filter = parse_object_filter(stream)
        except GrammarError:
            revealed_filter = None
        if revealed_filter is not None and revealed_filter.card_types:
            return ast.RevealedCardIs(revealed_filter)
    stream.reset(it_mark)

    # "if **that creature was destroyed this way**" (Infinite Authority). The
    # bound object is read through the shared reader rather than skipped: the
    # sentence is checked at the next end step, long after the destruction it
    # asks about, and which creature it names is the whole question.
    this_way = stream.mark()
    bound = parse_bound_subject(stream)
    if bound is not None and stream.accept_phrase("was", "destroyed", "this", "way"):
        return ast.DestroyedThisWay(bound.filter)
    stream.reset(this_way)

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
    if accept_source_reference(stream) and (
        stream.accept_word("is") or stream.accept_word("'s")
    ):
        if stream.accept_word("tapped"):
            return ast.IsState(_SOURCE_SPEC, "tapped")
        if stream.accept_word("untapped"):
            return ast.IsState(_SOURCE_SPEC, "tapped", negated=True)
    stream.reset(state_mark)

    raise stream.error("unrecognized condition")


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
