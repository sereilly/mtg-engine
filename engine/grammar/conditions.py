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

Two modules have left since, and they were cut along different lines.
`condition_clauses` took the long *readers* this dispatcher hands a sentence to,
whatever they ask about — a cut by shape. `condition_counts` took every clause
that asks **how many**, of a seat's board, of a zone, of a life total, of the
battlefield — a cut by subject. What is left is asked of one object: this
source and the pronouns that name it, this spell, this flip, this turn.

`condition_clauses` has since been cut by subject too: the longest of its
readers, the one over conditions answered by a **record**, is
`record_conditions`, and what it keeps is the graveyard position and the
counter-state questions. This dispatcher calls all three.

Anything the table does not model raises so the line falls back rather than
silently losing the condition — the legacy compiler dropped intervening-ifs
entirely, which made every conditional trigger fire unconditionally.
"""

from . import ast
from .errors import GrammarError
from .bounds import parse_comparison
from .readers import accept_source_reference, accept_source_reference_spec
from .references import parse_target_spec
from .durations import _parse_duration
from .phrases import _parse_keywords
from .condition_clauses import (_accept_counter_condition,
                                _parse_self_in_graveyard_above,
                                _parse_self_only_of_type_in_graveyard)
# The counted half: the filter parser, the seat references, the life totals and
# the colour table all left with it, and so — one Phase 0 later — did the
# blocker count it used to reach into `condition_clauses` for.
from .condition_counts import accept_counted_condition
# The long record reader and the one short one that had sat beside it. Imported
# from their own module rather than through `condition_clauses`, which no longer
# reads either.
from .record_conditions import (_accept_record_condition,
                                accept_mana_added_with_this_ability)
from .stream import TokenStream
from .vocabulary import CARD_TYPES, NUMBER_WORDS


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
    # "…**if Rayne is enchanted**" (Rayne, Academy Chancellor). CR 303.4a's
    # state, read off the attachment record through the same test the
    # ``enchanted_only`` filter key uses — one question about one permanent, one
    # answer. A row here rather than a production for the reason this table has
    # rows at all: it is "it is <word>" with a different field name.
    ("enchanted", "enchanted", False),
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
    joiner = None
    while True:
        mark = stream.mark()
        # "…is in a graveyard **or** a nontoken permanent … is on the
        # battlefield" (Bazaar of Wonders). Read in the same loop as "and" and
        # under the same backtracking rule, because both are about the clause
        # *list*: what changes is only whether every part must hold.
        #
        # A sentence may not mix them. "A and B or C" has two readings in
        # English and neither is written down on any card in the pool, so the
        # second joiner refuses rather than being resolved by precedence — a
        # guessed grouping is a condition that holds on boards the card does
        # not name.
        word = "and" if stream.at_word("and") else ("or" if stream.at_word("or") else None)
        if word is None or (joiner is not None and word != joiner):
            break
        stream.advance()
        try:
            parts.append(_parse_single_condition(stream))
        except GrammarError:
            stream.reset(mark)
            break
        joiner = word
    if len(parts) == 1:
        return first
    return ast.EveryOf(tuple(parts)) if joiner == "and" else ast.SomeOf(tuple(parts))


#: Where a "with the same name" clause may look, as ``(printed words, zone)``.
#: Closed on purpose: the evaluator searches exactly these two piles, and a
#: third zone admitted here would be a clause consumed and answered about
#: somewhere else.
_SAME_NAME_ZONES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("in", "a", "graveyard"), "graveyard"),
    (("on", "the", "battlefield"), "battlefield"),
)


def _parse_same_named_object(stream: TokenStream) -> "ast.SameNamedObject | None":
    """``a [nontoken] <card|permanent> with the same name is <where>`` — Bazaar
    of Wonders' condition, or None with the cursor untouched.

    "The same name" as the object the *firing event* named, which is why this
    is a condition node rather than an ``ObjectFilter`` with ``named`` set: that
    field holds a printed literal, and nothing here is printed — the name is
    not known until the trigger fires. The lowering refuses the clause under any
    event that freezes no such object.

    Every word is required. "a card with the same name" and "a nontoken
    permanent with the same name" are the two the card prints, and the noun
    decides nothing on its own: what separates them is the *zone*, which is read
    from a closed table so a third one cannot be consumed and then searched
    somewhere else.
    """
    mark = stream.mark()
    # "**another** permanent with the same name" (Winnow) compares against the
    # object the effect targets rather than against what an event named — the
    # article is the whole difference, so it is recorded and the lowering
    # decides which referent each spelling may read.
    other = bool(stream.accept_word("another"))
    if not other and not stream.accept_word("a", "an"):
        return None
    nontoken = bool(stream.accept_word("nontoken"))
    if not stream.accept_word("card", "permanent"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("with", "the", "same", "name", "is"):
        stream.reset(mark)
        return None
    for words, zone in _SAME_NAME_ZONES:
        if stream.accept_phrase(*words):
            return ast.SameNamedObject(zone, nontoken=nontoken, other=other)
    stream.reset(mark)
    return None




def _parse_single_condition(stream: TokenStream) -> ast.Condition:
    """Conditions the grammar models today. Anything else raises so the line
    falls back rather than silently losing the condition — the legacy compiler
    dropped intervening-ifs entirely, making conditional triggers always fire."""
    mark = stream.mark()

    # "…get +2/+2 **as long as they all share a color**." (Common Cause.)
    # Three fixed words after a pronoun, read first because "they" is a word no
    # other condition here opens with and because the readers below would take
    # "all" for a quantifier and then fail on the verb.
    #
    # "They" names the set the sentence has already described, so nothing is
    # carried: `statics._lower_static_ability` copies the anthem's own filter
    # onto the payload, which is what keeps the noun phrase read once.
    if stream.accept_phrase("they", "all", "share", "a", "color"):
        return ast.SubjectsShareAColor()
    stream.reset(mark)

    # "**a card with the same name is in a graveyard**" / "**a nontoken
    # permanent with the same name is on the battlefield**" (Bazaar of
    # Wonders). Read first because both openers are noun phrases the general
    # readers below would consume as far as "with", leaving "the same name" to
    # fail the line at a phrase this production does read.
    same_name = _parse_same_named_object(stream)
    if same_name is not None:
        return same_name

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

    # "**all cards revealed this way are creature cards**" (Game Preserve).
    # Read here, near the top, because it opens on five fixed words no other
    # condition in this file begins with, and it consumes nothing when they are
    # not all there.
    revealed_mark = stream.mark()
    if stream.accept_phrase("all", "cards", "revealed", "this", "way", "are"):
        card_type = stream.peek_word()
        if card_type in CARD_TYPES and stream.peek_word(1) == "cards":
            stream.advance()
            stream.advance()
            return ast.AllRevealedTopCardsAre(card_type=card_type)
    stream.reset(revealed_mark)

    # "**this card is the only creature card in your graveyard**" (Nether
    # Spirit). The clause above's sibling — same opener, same CR 113.6b claim,
    # a census of the pile instead of a position in it — read beside it and
    # after it, because the first is settled by the four words "in your
    # graveyard" landing immediately after "is" and this one by their not.
    only_of_type = _parse_self_only_of_type_in_graveyard(stream)
    if only_of_type is not None:
        return only_of_type
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

    # "**you haven't added mana with this ability this turn**" (Carpet of
    # Flowers). Read before the flip branch below, which opens on the same
    # "you" and resets cleanly either way, and read as a *record* rather than
    # a board state for the reason `ast.ManaAddedWithThisAbility` gives: the
    # mana pool empties at every step (CR 500.5), so nothing but the ability's
    # own note can answer which ability produced anything.
    mana_added = accept_mana_added_with_this_ability(stream)
    if mana_added is not None:
        return mana_added

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

    # Every condition that is a **count** — what a seat controls, how tall a
    # pile is, a life total, what the battlefield holds, the parity of a number
    # already taken — is read below, in ``condition_counts``. What the
    # dispatcher keeps is asked of one *object*: this source, this spell, this
    # flip, this turn.
    #
    # Read exactly where the block it replaces stood, because the order of
    # these branches is part of the grammar: "the number of permanents" has to
    # be tried after "the number is", whose phrase it is a prefix of, and "you
    # control …" before the source references that open on the same pronoun.
    # The reader consumes nothing when it refuses, so every branch below keeps
    # the say it had.
    counted_condition = accept_counted_condition(stream)
    if counted_condition is not None:
        return counted_condition

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

    # "…**if it's an opponent's turn**" (Discordant Spirit) / "if it's your
    # turn". Whose turn it is, printed as an intervening-if rather than as the
    # timing clause `_parse_turn_scoped_static_line` reads ("During your turn,
    # …") — one question, so it lands on that clause's node and reaches that
    # clause's evaluator instead of getting a second reading of the same fact.
    #
    # "An opponent's turn" is `negated`, and the node's own docstring is the
    # reason it can be: it warns that "turns other than yours" is not the
    # phrase "an opponent's turn" and then says what the difference would be —
    # a seat that is neither you nor an opponent. This engine has none. There
    # are no teams (CR 810's shared turns are in `rules_progress.EXCLUDED`), so
    # every seat that is not the ability's controller is an opponent and the
    # two phrases pick out exactly the same turns. A second node would be two
    # readers of one fact, free to drift.
    #
    # Read **above** the record clauses below, which share the two opening
    # words: "it's <a card>" consumes an article and asks the noun parser for a
    # card filter, and "an opponent's turn" is not one. W1G2 wrote it inside
    # that run and it is here instead, because whose turn it is is a question
    # about the game *now* — which is the line the split draws.
    turn_mark = stream.mark()
    if stream.accept_phrase("it", "'s") or stream.accept_phrase("it", "is"):
        if stream.accept_phrase("your", "turn"):
            return ast.TurnIsYours()
        if stream.accept_phrase("an", "opponent", "'s", "turn"):
            return ast.TurnIsYours(negated=True)
    stream.reset(turn_mark)

    # The long record readers — "it was a creature card", "a white creature dies
    # this way", "the discarded card was a land card", "a permanent was put into
    # your hand this turn" — are read below, in ``record_conditions``. The
    # reader left this module for ``condition_clauses`` when it crossed the
    # thousand-line guard at a wave's *integration*, on nobody's branch: four
    # groups' additions merely summed, which is the guard surfacing a boundary
    # that was already there. It left *that* module for its own at the Phase 0
    # before Nemesis, fourteen lines under the same guard.
    #
    # **The boundary between this function and that reader is a shape, not a
    # subject**, and the sentence that used to stand here said otherwise — "the
    # dispatcher keeps the conditions answered by looking at the game *now*".
    # It never did. Eleven record clauses are read by this function: the
    # additional cost, the flip, "it entered from", the turn's four ``IsState``
    # axes, "started the turn", "dealt damage … this turn", and both two-sided
    # block histories. So ``record_conditions`` is the long reader this
    # dispatcher hands a sentence to and not every record clause the grammar
    # knows — the record/now line is drawn whole one package over, in
    # ``ast/records.py`` and ``lowering/_record_conditions.py``, and only in
    # part on this side.
    recorded = _accept_record_condition(stream)
    if recorded is not None:
        return recorded

    # The counter-state questions (CR 122), in `condition_clauses` for the
    # reason the record conditions above left: this module crossed the
    # thousand-line guard at a wave's integration, on nobody's branch, and
    # the family boundary was already drawn two packages over.
    counters = _accept_counter_condition(stream)
    if counters is not None:
        return counters

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
    if subject is None:
        # "…unless **that creature** attacked this turn." (Insubordination.)
        # The repeated noun instead of the pronoun — idiom 20's other spelling,
        # and the same referent: under a trigger whose own condition named a
        # permanent ("the end step of enchanted creature's controller") the
        # words name that permanent. Which one it is stays the *lowering's*
        # question, through ``_events.names_attached_permanent``, exactly as it
        # is for the pronoun; this reader only says the phrase was printed.
        #
        # Read after the pronoun and gated on a state phrase following it: the
        # block below returns only when one of its fixed clauses matches and
        # resets otherwise, so "that creature" opening any other sentence is
        # handed back whole.
        that_mark = stream.mark()
        if stream.accept_word("that"):
            noun = stream.peek_word()
            if noun is not None and noun in CARD_TYPES:
                stream.advance()
                subject = ast.TargetSpec(
                    "that", ast.ObjectFilter(card_types=(noun,))
                )
            else:
                stream.reset(that_mark)
    if subject is not None:
        if stream.accept_word("is") or stream.accept_word("'s"):
            for word, state, negated in _PRESENT_STATES:
                if stream.accept_word(word):
                    return ast.IsState(subject, state, negated=negated)
            # "…**is on the battlefield**" (Tombstone Stairwell). A zone
            # question rather than a state of the permanent, which is why it is
            # not another row of the table above: every word there is a field
            # the object carries, and CR 400.1's "which zone is it in" is the
            # game's to answer. Read after the table so a state word still wins
            # its own reading.
            if stream.accept_phrase("on", "the", "battlefield"):
                return ast.SourceOnBattlefield(subject)
            # "…**is an enchantment**" / "…**is a creature**" (the Hidden /
            # Opal / Veiled cycle). CR 205.2's card type asked of the source,
            # answered by CR 613 layer 4 rather than by the printed type line —
            # which is the whole point of the clause, since the effect behind it
            # is what changes the answer. Read after the state table and the
            # zone clause, whose words this branch does not accept, so each
            # keeps the sentence it owns.
            type_mark = stream.mark()
            if stream.accept_word("a", "an"):
                word = stream.peek_word()
                if word is not None and word in CARD_TYPES:
                    stream.advance()
                    return ast.SourceIsType(subject, (word,))
            stream.reset(type_mark)
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
        # "…**was dealt damage this turn**" (Wall of Resistance). The passive
        # voice, and that is the whole difference from `DealtDamageThisTurn`:
        # that clause asks what this creature *dealt* and this one asks what was
        # dealt *to* it. One record already answers it — the flag `deal_damage`
        # stamps on every recipient at the one damage seam, which the noun
        # phrase "a creature that has been dealt damage this turn" (Giant Shark)
        # reads as a filter key. So the condition and the filter are one fact,
        # and a creature regenerated since still answers yes (CR 701.19a wipes
        # `damage_marked`, not what was dealt), which is what the words say.
        if stream.accept_phrase("was", "dealt", "damage", "this", "turn"):
            return ast.IsState(subject, "was_dealt_damage_this_turn")
        # "…**regenerated this turn**" (Spiny Starfish). A record of the turn
        # like the two above, kept by ``engine/regeneration._apply`` — the one
        # place a regeneration happens — and read here as its presence half.
        if stream.accept_phrase("regenerated", "this", "turn"):
            return ast.IsState(subject, "regenerated_this_turn")
    stream.reset(state_mark)

    raise stream.error("unrecognized condition")
