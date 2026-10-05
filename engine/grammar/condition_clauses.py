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

Two readers are left, and both are asked of the ability's own source: where its
card sits in a graveyard (CR 113.6b, CR 404.3), and the counter-state questions
(CR 122) — how many counters of a kind are on it, and whether one ever was.

Three things have left since, each to the module whose subject it already was.
The seat clauses went to ``seat_records``. The long reader of conditions
answered by a **record** went to ``record_conditions`` at the Phase 0 before
Nemesis, with this module fourteen lines under the guard — that reader was more
than half of the file and is the half that grows with the pool, and its
docstring carries the measurement. And "<N> <noun> is blocking that creature"
went to ``condition_counts`` in the same cut: it is a count, that module's
docstring had named it as its own since the day it was written, and it was the
clause's only caller. This module is no longer read by either.
"""

from __future__ import annotations

from . import ast
from .amounts import accept_counter_kind
from .lexer import PT
from .readers import accept_source_reference
from .stream import TokenStream
from .vocabulary import CARD_TYPES, NUMBER_WORDS


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
        # "…if **this card is in your graveyard**, you may pay {1}{B}{B}."
        # (Pyre Zombie.) The clause with no position asked: CR 113.6b's
        # statement of where the ability functions and nothing more. The same
        # node with a floor of zero cards above it — every position the card
        # holds qualifies — rather than a second node, because the graveyard
        # scan, the re-check on resolution and the ``functions_from`` stamp are
        # all this node's already and a sibling would have to repeat each.
        # The type is the one every printing of the longer clause names and is
        # never consulted: a floor of zero is met by any pile.
        return ast.SelfInGraveyardWithCardsAbove(
            card_type="creature", count=0, at_least=True, directly=False,
        )
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


def _parse_self_only_of_type_in_graveyard(
    stream: TokenStream,
) -> "ast.SelfIsOnlyCardOfTypeInGraveyard | None":
    """``this card is the only <type> card in your graveyard``, or None without
    consuming.

    The clause above's sibling (Nether Spirit against Nether Shadow), and the
    same two claims in one node: CR 113.6b's statement of where the ability
    functions, and a census of the pile. Non-consuming on refusal for that
    clause's reason — "this card is" opens both, and a branch that ate the
    pronoun would take the whole line's refusal site with it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("this", "card", "is", "the", "only"):
        stream.reset(mark)
        return None
    card_type = stream.peek_word()
    if card_type not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("card", "in", "your", "graveyard"):
        # The type is read and the zone is not: another sentence about the same
        # card, left whole for the branch that can read it.
        stream.reset(mark)
        return None
    return ast.SelfIsOnlyCardOfTypeInGraveyard(card_type=card_type)


def _accept_exiled_object_reference(stream: TokenStream) -> bool:
    """The ability's own source **or the card it put into exile** — "it", "this
    card", "that card", "the card".

    ``accept_source_reference`` reads the first two and stops, which is right
    everywhere it is asked: those three spellings name an object the ability is
    an ability *of*. The two definite spellings here name an object in exile
    that the ability is merely *about* — "…**that card** is exiled, remove a
    delay counter from **it**" (Ertai's Meddling), where the delayed ability was
    created by a spell that is already in a graveyard.

    They reach the same answer, and that is why this is a reader rather than a
    second node: ``exiled_records.source_object`` resolves "the source" as the
    resolving ability's permanent *or* the exile record its trigger was fired
    for, so a clause asking about either is answered by one function. The two
    referents differ in what put the card there, not in which object the
    condition tests.

    Scoped to this module's counter and exile clauses on purpose. "That card"
    all over the pool names a card an earlier step recorded — a dead creature, a
    milled card — and widening the shared reader would let every one of those
    read as the ability's own source.
    """
    if accept_source_reference(stream):
        return True
    mark = stream.mark()
    if stream.accept_word("that", "the") and stream.accept_word("card"):
        return True
    stream.reset(mark)
    return False


def _accept_counter_kind(stream: TokenStream) -> str | None:
    """The counter's written name, or None with the cursor untouched.

    A **P/T token or a word**, because CR 122.1a spells one kind with symbols
    and CR 122.1 lets the rest have any name.

    Two lines, because the reading is now ``amounts.accept_counter_kind`` and
    it used to be four productions in four modules. This copy was written out
    rather than imported "because a condition declines where that one raises" —
    a real difference from ``phrases._expect_counter_kind``, and the wrong one
    to settle by copying the *reader*: declining and raising are one accept plus
    what its caller does with a None, and the copy meant a counter kind could be
    admitted in one module and refused in another. ``amounts`` is unlayered, so
    a condition may read it.
    """
    token = accept_counter_kind(stream)
    return None if token is None else token.text


def _accept_counter_condition(stream: TokenStream) -> "ast.Condition | None":
    """The counter-state questions, or None to let the chain carry on.

    Moved out of ``conditions._parse_single_condition`` when that module
    crossed the thousand-line guard at Visions' wave-1 **integration** — on
    nobody's branch, four groups' additions merely summing, which is the
    guard surfacing a family boundary that was already there. It is the
    second time in one wave, after ``lowering/categories.py``.

    The line is the one ``lowering/counters.py`` and ``effects/counters.py``
    already draw one package over, asked here about a *condition*: how many
    counters of a kind sit on an object, and whether one ever did (CR 122).
    Everything left in the chain asks about a zone, a turn, a life total, a
    board count or a permanent's own state.

    Every declining path resets the mark it took, so a caller continues
    exactly where it did before — the contract ``_accept_record_condition``
    already keeps, in ``record_conditions``.
    """

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
    if _accept_exiled_object_reference(stream) and stream.accept_phrase("is", "exiled", "with"):
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

    # "…**if that card is exiled**, remove a delay counter from it."
    # (Ertai's Meddling.) The clause above with nothing behind it: the object is
    # in exile and the sentence asks no more than that. Read *after* it, so the
    # longer question keeps its own words — this one would otherwise consume
    # "is exiled" out of All Hallow's Eve and strand the counter phrase.
    bare_exiled_mark = stream.mark()
    if _accept_exiled_object_reference(stream) and stream.accept_phrase("is", "exiled"):
        return ast.SourceExiled()
    stream.reset(bare_exiled_mark)

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
    if _accept_exiled_object_reference(stream) and stream.accept_word("has"):
        # "if this artifact has **a** charge counter on it" (Ventifact
        # Bottle). The article is English's way of printing "one or more":
        # the clause is a *presence* test, and a card that had exactly one
        # counter and a card that had five both satisfy it. Read here rather
        # than as a number word, because "a" as a count would mean exactly
        # one — the tighter reading, and the one that would stop the Bottle
        # emptying after its second activation.
        article = stream.mark()
        if stream.accept_word("a", "an"):
            counter_word = stream.peek_word()
            if counter_word is not None and counter_word not in (
                "counter", "counters"
            ):
                stream.advance()
                if (
                    stream.accept_word("counter", "counters")
                    and stream.accept_phrase("on", "it")
                ):
                    return ast.SourceCounterCount(
                        counter_word, 1, comparison="at_least"
                    )
            stream.reset(article)
        # "as long as this creature has **no** shell counters on it" (Roc
        # Hatchling). The zero of the same possessive spelling, and the
        # "there are no …" branch above already reads the zero of the
        # existential one — so the sentence had two halves implemented and
        # neither of them was this card's, which is the shape the production
        # above calls out about its own axes: the spelling nobody listed reads
        # as a parser gap rather than as the same question.
        #
        # "no more" is the same optional word it is up there, and for the same
        # reason: the difference is English, not a different question.
        # `comparison` is left at its default equality — a count of zero read
        # as "at least zero" is a static that always holds, which for a Roc
        # Hatchling is a 4/4 flier on turn one.
        empty = stream.mark()
        if stream.accept_word("no"):
            stream.accept_word("more")
            counter_word = _accept_counter_kind(stream)
            if counter_word is not None and (
                stream.accept_word("counters", "counter")
                and stream.accept_phrase("on", "it")
            ):
                return ast.SourceCounterCount(counter_word, 0)
            stream.reset(empty)
        word = stream.peek_word()
        if word is not None and word in NUMBER_WORDS:
            stream.advance()
            if stream.accept_phrase("or", "more"):
                counter_word = _accept_counter_kind(stream)
                if counter_word is not None and (
                    stream.accept_word("counters", "counter")
                    and stream.accept_phrase("on", "it")
                ):
                    return ast.SourceCounterCount(
                        counter_word, NUMBER_WORDS[word], comparison="at_least"
                    )
    stream.reset(threshold_mark)

    # "if **that creature has three or more +1/+0 counters on it**" (Consuming
    # Ferocity). The same count over the permanent an Aura is attached to
    # rather than over the Aura itself — a different object, so a different
    # node: read as :class:`ast.SourceCounterCount` the clause would ask the
    # enchantment how many +1/+0 counters *it* had, which is always none, and
    # the card would never reach its own payoff.
    #
    # Both printed subjects reach it. "Enchanted creature" names the host
    # outright; "that creature" is the host only because the sentence in front
    # of it named one, which is a fact about the *effect* — so it rides the
    # node and the lowering is what checks a step really named it.
    attached_mark = stream.mark()
    bound = None
    if stream.accept_word("enchanted"):
        bound = False
    elif stream.accept_word("that"):
        bound = True
    if bound is not None:
        noun = stream.peek_word()
        if noun is not None and noun in CARD_TYPES:
            stream.advance()
            if stream.accept_word("has"):
                word = stream.peek_word()
                if word is not None and word in NUMBER_WORDS:
                    stream.advance()
                    if stream.accept_phrase("or", "more"):
                        counter_word = _accept_counter_kind(stream)
                        if counter_word is not None and (
                            stream.accept_word("counters", "counter")
                            and stream.accept_phrase("on", "it")
                        ):
                            return ast.AttachedCounterCount(
                                counter_word, NUMBER_WORDS[word], bound=bound,
                            )
    stream.reset(attached_mark)

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
        # "…**if it had a death counter on it**" (Bogardan Phoenix). The same
        # sentence about a counter with no rules meaning of its own (CR 122.3),
        # whose word is invented by the card — so it is read as a word and
        # carried as payload, and a set inventing another needs nothing here.
        # Its own node because the *record* is a different one; see
        # ``ast.HadNamedCounter``.
        word = stream.peek_word()
        if word is not None and word not in ("counter",):
            named_mark = stream.mark()
            stream.advance()
            if stream.accept_phrase("counter", "on", "it"):
                return ast.HadNamedCounter(word)
            stream.reset(named_mark)
    stream.reset(counter_mark)
    return None
