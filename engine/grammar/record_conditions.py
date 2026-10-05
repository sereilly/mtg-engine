"""The condition clauses answered by a **record** of something already done.

"If it was a creature card" (Scavenging Ooze), "if a white creature dies this
way" (Cinder Cloud), "if the discarded card was a land card" (Land's Edge), "if
you haven't added mana with this ability this turn" (Carpet of Flowers). No read
of the board answers any of them: the object each asks about has left the zone
the effect took it from (CR 608.2h), or the event it asks about is over.

The parse-side mirror of ``lowering/_record_conditions.py`` and the reader of
``ast/records.py``'s nodes, and it carries the lowering module's name for that
module's own reason: the mirror's word is ``records``, and ``records`` one layer
down is already the reader of a record as a *quantity*. Three packages, one
subject, one name.

Pre-split out of ``condition_clauses`` at the Phase 0 before Nemesis, when that
module sat fourteen lines under the thousand-line guard. The seam was measured
rather than inherited, because the sentences pointing at it disagree —
``seat_records`` says ``condition_clauses`` "holds every condition answered by a
*record*", and ``conditions`` says that module was cut by shape and that the
record line "is **not** the line drawn here". Both were describing one file
holding two things:

* Of the seventeen condition nodes ``_accept_record_condition`` builds, sixteen
  are defined in ``ast/records.py``, and so is the one
  ``accept_mana_added_with_this_ability`` builds. Of the nine the clauses left
  behind build, six are defined in ``ast/conditions.py`` and the other three
  are named below.
* The imports divide the same way. Only this half read ``phrases``,
  ``seat_records``, the colour table and the tokenizer; only the other half
  reads ``amounts.accept_counter_kind``, the P/T token and the card-type table.
* No function in either half calls one in the other.

It is also the half that **grows with the pool**. Of the seventeen commits that
touched ``condition_clauses`` the record reader grew in ten, from 334 lines to
504 with two seat clauses leaving for ``seat_records`` on the way; the counter
block has stood at 297 since Tempest's fourth wave. A set prints a new "this
way" far more often than a new way to ask about a counter.

Three things sit on the wrong side of the title and are named here rather than
left to be rediscovered:

* "If **it's red**" (Hydroblast) is a board read — ``ast.ItIsColor``, the one
  node of the seventeen that is not a record. It is an arm of the "it's" /
  "it isn't" branch whose other arm is the revealed card's type, sharing that
  branch's negation reader, so it moved whole rather than a branch being
  divided between two files.
* "If it had a +1/+1 counter on it", "if it had a death counter on it" and "if
  this ability has been activated four or more times this turn" are records,
  and stay in ``condition_clauses._accept_counter_condition``: they are arms of
  that function's CR 122 chain, which asks "how many counters … and whether one
  ever did" in one place.
* The dispatcher in ``conditions`` reads eleven short record clauses itself —
  the additional cost, the flip, "it entered from", the turn's histories. Its
  own comment lists them. What is here is the long reader it hands a sentence
  to, not every record condition the grammar knows.

A clause reader's contract, the one ``condition_clauses`` states: each reads a
sentence to its end and returns the node, or returns None with the cursor where
it found it, so the dispatcher's next branch keeps its say.

Above ``seat_records``, whose three seat clauses ``_accept_record_condition``
probes first, and below ``conditions``, which imports both names from here
directly — nothing is re-exported through ``condition_clauses``, and this
module reads neither it nor ``condition_counts``.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .nouns import parse_object_filter
# The moved block's own imports, and they moved *with* it — twice now: a
# function that changes module leaves its imports behind, which is the failure
# this package's scans exist to catch loudly rather than at the line that runs.
from .durations import _parse_duration
from .phrases import _accept_self_reference, parse_bound_subject
from .readers import accept_source_reference
from .seat_records import (_accept_seat_cast_record,
                           _accept_seat_damage_record,
                           _accept_seat_land_record)
from .stream import TokenStream
from .vocabulary import CARD_TYPES, COLOR_WORDS, NUMBER_WORDS


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


def _accept_colour_run(stream: TokenStream, *, negated: bool) -> "ast.Condition | None":
    """``red`` / ``white or blue`` after a copula, as a colour test on the
    pronoun's object — or None, consuming nothing, when no colour word is next.

    "…**if it's red**" (Hydroblast) is one colour; "If that creature is **white
    or blue**, …" (Lightning Dart) and "As long as enchanted permanent is **red
    or green**, …" (Essence Leak) are the same test with a disjunction inside
    the predicate. CR 105.2 makes an object's colours a set, so "is white or
    blue" is "is white, or is blue" — which is how it is built: one
    :class:`ast.ItIsColor` per printed word under the ``SomeOf`` the
    clause-level "or" already produces, so no evaluator learns a second shape.

    Read here rather than left to that clause-level loop, which asks for a
    whole condition after "or" and would hand "blue" back unread — leaving the
    line refused at a word this production does read.

    Negated, the disjunction flips (De Morgan): "it **isn't** white or blue" is
    neither, so the parts are conjoined. No card prints it; it is written out
    because the other reading would be the opposite condition.
    """
    first = stream.peek_word()
    if first not in COLOR_WORDS:
        return None
    stream.advance()
    colours = [COLOR_WORDS[first]]
    while stream.peek_word() == "or" and stream.peek_word(1) in COLOR_WORDS:
        colours.append(COLOR_WORDS[stream.peek_word(1)])
        stream.advance(2)
    parts = tuple(ast.ItIsColor(colour, negated=negated) for colour in colours)
    if len(parts) == 1:
        return parts[0]
    return ast.EveryOf(parts) if negated else ast.SomeOf(parts)


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

    A clause reader like ``condition_clauses``' and with the same contract: it reads
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
    # "…unless **one of their opponents was dealt damage this turn**"
    # (Antagonism). Probed first because it opens on "one", which no other
    # branch here reads, and it refuses without consuming like all of them.
    seat_damage = _accept_seat_damage_record(stream)
    if seat_damage is not None:
        return seat_damage
    # "…**if that player didn't cast a spell this turn**" (Impatience). Probed
    # beside the damage record above and for its reason: it opens on a seat word
    # no other branch here reads, and it refuses without consuming.
    seat_cast = _accept_seat_cast_record(stream)
    if seat_cast is not None:
        return seat_cast
    # "…**if you didn't play a land this turn**" (Mercadian Atlas). The cast
    # record's twin one special action over (CR 305.1), probed beside it and
    # after it: both open on the same seat words, and this one is settled by the
    # verb that follows. Neither consumes on refusal.
    seat_land = _accept_seat_land_record(stream)
    if seat_land is not None:
        return seat_land
    # "if this permanent **came under your control since the beginning of your
    # last upkeep**" — CR 702.30a, the whole of what echo adds to a sentence
    # this grammar already read (``engine/echo.py`` rewrites the keyword line
    # into it before any line is classified).
    #
    # A record condition, and a record for the reason Wiitigo's block clause in
    # ``conditions`` is: the moment it asks about may have been an opponent's
    # turn ago and nothing on the board says when a permanent changed hands, so
    # the upkeep step records which of a seat's upkeeps a permanent first saw
    # and ``turn_state`` answers off that.
    #
    # **Every word is required**, the discipline that clause states and this one
    # needs more: "came under your control" alone is a different, wider claim
    # (it is true of everything you have ever controlled), and "since the
    # beginning of your last upkeep" is the only window this stamp can answer.
    # A sentence naming another one has to fail here rather than borrow this
    # node, because a window silently widened is an echo that never stops.
    #
    # Read at the top, before the "it was" back-reference below: both openings
    # are a self-reference, this one is settled by eleven fixed words after it,
    # and it consumes nothing when they are not there.
    control_mark = stream.mark()
    if accept_source_reference(stream) and stream.accept_phrase(
        "came", "under", "your", "control", "since", "the", "beginning",
        "of", "your", "last", "upkeep",
    ):
        return ast.CameUnderControlSinceLastUpkeep(
            ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
        )
    stream.reset(control_mark)

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

    # "**If that player discards a card this way,** this creature deals 1
    # damage to each creature and each player." (Tainted Specter.) The yes/no
    # reading of a discard an earlier sentence of this same effect performed.
    # Read before the "the discarded card was …" clause below it, which is a
    # question about *what* went rather than whether anything did; the two open
    # on different words and neither consumes the other's.
    #
    # "That player" is the only printed subject and it is checked rather than
    # skipped: the words name the seat the offer in front of this was made to,
    # and a spelling that named somebody else would be asking about a discard
    # this record does not hold.
    this_way = stream.mark()
    if stream.accept_phrase("that", "player", "discards", "a", "card", "this", "way"):
        return ast.DiscardedThisWay()
    stream.reset(this_way)
    # "**If you discard a creature card this way,** return it from your
    # graveyard to the battlefield …" (Aether Rift.) The same back-reference
    # with the ability's controller as the discarder and a noun between the
    # article and "this way": what went, where the clause above asks whether
    # anything did. One node, because it is one record's question twice.
    #
    # The noun has to name a *card* with a printed type — a bare "a card" is
    # the clause above with a different subject, and reading it here would
    # demand the cards record of a discard that only counts.
    if stream.accept_phrase("you", "discard") and stream.accept_word("a", "an"):
        try:
            discarded = parse_object_filter(stream)
        except GrammarError:
            discarded = None
        if (
            discarded is not None
            and discarded.is_card
            and discarded.card_types
            and stream.accept_phrase("this", "way")
        ):
            return ast.DiscardedThisWay(filter=discarded)
    stream.reset(this_way)

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
    # "If **that creature is** white or blue, …" (Lightning Dart). The repeated
    # noun where Hydroblast prints the pronoun: both name the object the effect
    # beside the clause targets, and the lowering resolves which
    # (``pronoun_target_referent``). Taken only when a colour word follows the
    # copula, so "that creature is tapped" and every other "that <noun> is …"
    # sentence is handed back whole to the reader that owns it.
    that_mark = stream.mark()
    if stream.accept_word("that"):
        noun = stream.peek_word()
        if (
            (noun == "permanent" or noun in CARD_TYPES)
            and stream.peek_word(1) == "is"
            and stream.peek_word(2) in COLOR_WORDS
        ):
            stream.advance(2)
            return _accept_colour_run(stream, negated=False)
    stream.reset(that_mark)

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
        coloured = _accept_colour_run(stream, negated=negated)
        if coloured is not None:
            return coloured
        stream.accept_word("a", "an")
        try:
            revealed_filter = parse_object_filter(stream)
        except GrammarError:
            revealed_filter = None
        if revealed_filter is not None and (
            revealed_filter.card_types or revealed_filter.excluded_types
        ):
            # "If it's a **nonland** card" (Wand of Denial) is Wand of Ith's
            # "if it **isn't** a land card" with the negation inside the noun
            # phrase instead of on the copula — one question, two printed
            # spellings, and only one of them was read. The filter carries the
            # exclusion either way, so admitting the phrase costs the test
            # nothing and refusing it cost the card.
            return ast.RevealedCardIs(revealed_filter, negated=negated)
    stream.reset(it_mark)

    # "if **one or more creature cards were put into that graveyard this
    # way**" (Helm of Obedience). A back-reference to the set the loop in front
    # of it recorded, read before the bound-subject clause below because both
    # open on a noun phrase and only this one opens on the printed floor.
    # "if **a card with the chosen name was milled this way**" (Foreshadow).
    # Read before the counted spelling below, whose "one or more" opening this
    # does not share but whose tail it does — and read as its own clause rather
    # than as a filter on it, because "the chosen name" is a record and an
    # ``ObjectFilter``'s ``named`` is a printed literal.
    chosen_mark = stream.mark()
    if stream.accept_phrase(
        "a", "card", "with", "the", "chosen", "name", "was", "milled",
        "this", "way",
    ):
        return ast.ChosenNameMilledThisWay()
    stream.reset(chosen_mark)

    # "if **that card has the chosen name**" (Cursed Scroll). The same pair of
    # records asked of one card rather than of a milled set, so it is read here
    # beside its sibling. "That card" is the reveal's, which is the referent
    # every "if it's a …" above already uses — the lowering demands the reveal
    # and the naming both, so the words cannot name a record nothing wrote.
    # "if **two cards that share a color were milled this way**" (Grindstone).
    # Read here beside its two siblings and before the counted "one or more"
    # spelling below, whose noun-phrase opening it does not share: the relation
    # ("that share a color") is not a narrowing on a card, so the noun parser
    # would refuse it.
    shared_mark = stream.mark()
    shared_count = NUMBER_WORDS.get(stream.peek_word() or "")
    if shared_count is not None:
        stream.advance()
        if stream.accept_phrase(
            "cards", "that", "share", "a", "color", "were", "milled", "this",
            "way",
        ):
            return ast.SharedColorMilledThisWay(count=int(shared_count))
    stream.reset(shared_mark)

    named_mark = stream.mark()
    if stream.accept_phrase(
        "that", "card", "has", "the", "chosen", "name",
    ):
        return ast.RevealedCardHasChosenName()
    stream.reset(named_mark)

    milled_mark = stream.mark()
    # "if **one or more <noun> cards were put into that graveyard this way**"
    # (Helm of Obedience) and "if **a <noun> card was milled this way**"
    # (Saprazzan Breaker). One test — was there at least one such card in the
    # record the mill in front of it wrote — printed two ways, so it is one
    # clause with the noun phrase as the whole of what differs.
    #
    # The printed floor is one either way: "a" is the indefinite article, not a
    # count, and "one or more" states the same minimum in words. Reading them as
    # two clauses would be two answers to one question, and the second would
    # have to demand the same producer and refuse the same filters.
    #
    # The article is consumed *here* rather than by the noun parser, which
    # refuses one outright ("expected an object noun") — the same split every
    # caller of that parser makes.
    if stream.accept_phrase("one", "or", "more") or stream.accept_word("a", "an"):
        try:
            milled_filter = parse_object_filter(stream)
        except GrammarError:
            milled_filter = None
        # Both verbs and both spellings of the move. "Milled" is CR 701.17a's
        # keyword action and "put into that graveyard" is the words it stands
        # for, so a card printing either names the same record; the number
        # agreement follows the opening the card chose and neither is a
        # different question.
        if milled_filter is not None and (
            stream.accept_phrase(
                "were", "put", "into", "that", "graveyard", "this", "way"
            )
            or stream.accept_phrase(
                "was", "put", "into", "that", "graveyard", "this", "way"
            )
            or stream.accept_phrase("were", "milled", "this", "way")
            or stream.accept_phrase("was", "milled", "this", "way")
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

    # "if **no creatures attacked this turn**" (Keldon Twilight). The turn's
    # attack record asked game-wide and in the negative. Every word is read:
    # "this turn" is the window the record is kept for, and a sentence naming
    # another one has to fail here rather than borrow it.
    if stream.accept_phrase("no", "creatures", "attacked", "this", "turn"):
        return ast.CreaturesAttackedThisTurn(negated=True)

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


def accept_mana_added_with_this_ability(
    stream: TokenStream,
) -> "ast.ManaAddedWithThisAbility | None":
    """``you haven't added mana with this ability this turn`` (Carpet of
    Flowers), or None with the cursor untouched.

    CR 603.4's intervening-if over a record the ability writes as it resolves —
    see ``ast.ManaAddedWithThisAbility`` for why no board can answer it.

    Both polarities in one production, so a card printing the positive gets the
    same reader rather than a second one free to disagree about which six words
    follow. "With **this** ability" is required in full: dropping it would make
    the clause ask whether the player has added mana at all, which every land
    they tapped this turn already answers yes to.
    """
    mark = stream.mark()
    if stream.accept_phrase("you", "haven't", "added"):
        negated = True
    elif stream.accept_phrase("you", "'ve", "added"):
        negated = False
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "mana", "with", "this", "ability", "this", "turn"
    ):
        stream.reset(mark)
        return None
    return ast.ManaAddedWithThisAbility(negated=negated)
