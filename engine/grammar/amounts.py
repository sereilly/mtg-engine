"""Quantity sub-parser: numbers, X, counts, and back-references.

The legacy rules re-derived quantities inline in every regex, and used a
lenient number parse that turned an unrecognized word into a silent ``0``
("deals <n> damage" with an unparsed n dealt nothing). Quantities parse in one
place here and an unknown quantity word is an error, not a zero.
"""

from __future__ import annotations

from ..oracle_types import LIFE_LOST_THIS_WAY, MANA_PAID_BY_SEAT
from . import ast
from .errors import GrammarError
from .lexer import GToken, NUMBER, PT, WORD
# `parse_equal_to` below reads the record-shaped quantities too — one
# printed "equal to …" reaches both families, which is why the split is
# by what the quantity *is* rather than by which reader asks for it.
from .cost_records import (accept_counters_removed_for_cost,
                           accept_cost_channel_possessive,
                           accept_cost_characteristic_of)
from .records import accept_damage_dealt_by_chosen_cast
from .stream import TokenStream
from .vocabulary import ALL_SUBTYPES, CARD_TYPES, NUMBER_WORDS, singular as _singular


def _accept_variable_offset(stream: TokenStream, variable: ast.Var) -> ast.Amount:
    """``X plus <n>`` — the variable with the constant the sentence adds to it.

    "You gain **X plus 1** life, where X is the number of green creatures on the
    battlefield." (An-Havva Inn.) "…deals **X plus 3** damage to you."
    (Hellfire.) One reading, here, because the two cards print the same
    quantity: ``effects/damage.py`` had read its own copy of this since Hellfire
    landed, so the same three words were a quantity in a damage clause and
    unconsumed text everywhere else — the fork that round 8 found in the
    where-clause parsers, one production over. The damage branch still stands
    for its *other* left-hand sides ("half X plus 1"); this one claims the
    variable case first and builds the identical node, so nothing about Hellfire
    changes.

    Only a printed **number** follows, and only after "plus". "X minus 1" is
    left entirely unconsumed rather than read as a negative offset: no card in
    the pool prints it, and an unread word fails the line loudly, which is the
    direction this parser exists to fail in.

    A ``Fixed`` right-hand side is the whole vocabulary for the same reason —
    "X plus the number of …" is a sum of two computed quantities, and the
    resolution reads one X.
    """
    mark = stream.mark()
    if not stream.accept_word("plus"):
        return variable
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        return ast.Plus(variable, ast.Fixed(int(token.text)))
    number = NUMBER_WORDS.get(stream.peek_word() or "")
    if number is not None:
        stream.advance()
        return ast.Plus(variable, ast.Fixed(number))
    stream.reset(mark)
    return variable


def parse_amount(stream: TokenStream, *, back_reference: str | None = None) -> ast.Amount:
    """Parse a quantity at the cursor.

    *back_reference* names the result key a bare "that much" refers to, for a
    caller that knows it from the words it has already read. The default is
    None, because in general the sentence does not say: "that much" points at
    the enclosing effect's earlier step or at the event that fired the ability,
    and only lowering can see either. See :class:`ast.ThatMuch`.
    """
    token = stream.peek()
    if token is None:
        raise stream.error("expected a quantity")

    if token.kind == NUMBER:
        stream.advance()
        return ast.Fixed(int(token.text))

    if token.kind == WORD:
        word = token.text
        if word in ("x", "y"):
            stream.advance()
            return _accept_variable_offset(stream, ast.Var(word))
        # "a third of their life" (Pox). Read **before** the number-word table,
        # which maps a bare "a" onto 1 — without this the fraction parses as the
        # quantity one and the rest of the phrase is unconsumed text.
        fraction = _accept_fraction(stream, back_reference=back_reference)
        if fraction is not None:
            return fraction
        if word in NUMBER_WORDS:
            stream.advance()
            return ast.Fixed(NUMBER_WORDS[word])
        if word == "all":
            stream.advance()
            return ast.AllOf()
        if word == "half":
            stream.advance()
            inner = _parse_counted_amount(stream, back_reference=back_reference)
            # "…, rounded down" (Backdraft) prints a comma in front of the
            # rider; "half X rounded up" does not. `_accept_rounding` reads both,
            # and reads them for the "a <ordinal> of" spelling beside this one.
            return ast.Half(inner, _accept_rounding(stream))
        if word == "that":
            mark = stream.mark()
            stream.advance()
            # "that much" refers back to a recorded quantity; "that many"
            # (Basri Ket's "create that many … tokens") to a counted set. One
            # node for both — the back-reference names what is counted.
            if stream.accept_word("much", "many"):
                return ast.ThatMuch(back_reference)
            stream.reset(mark)
        if word == "any":
            mark = stream.mark()
            stream.advance()
            if stream.accept_phrase("amount", "of"):
                return ast.AllOf()
            # "remove **any number of** +1/+1 counters" (Tetravus). A different
            # node from "any amount of" beside it: that one is unbounded and
            # nobody chooses it, this one is a choice with a ceiling.
            if stream.accept_phrase("number", "of"):
                return ast.AnyNumber()
            stream.reset(mark)

    raise stream.error("expected a quantity")


#: The denominators the pool spells out. "Half" has its own word and its own
#: branch above; these are the ones printed as "a <ordinal> of". A closed table
#: for the reason every table in this grammar is closed — an ordinal nobody
#: listed would otherwise be read as some other number entirely.
_FRACTION_WORDS: dict[str, int] = {"third": 3, "quarter": 4, "fourth": 4}


def _accept_fraction(
    stream: TokenStream, *, back_reference: str | None = None
) -> "ast.Half | None":
    """``a <ordinal> of <quantity>`` — "a third of their life" (Pox).

    :class:`ast.Half` with a denominator, not a node of its own: see that
    class's own note. The rounding rider is read here as well, in both the
    printed shapes "half" already accepts, so a card printing "a third of their
    life, rounded up" needs nothing further — Pox prints its rounding once at
    the end of the paragraph instead, which ``statements._round_every_half``
    already distributes.

    Nothing is consumed unless the whole opening is there, so a bare "a" keeps
    the number-word reading it has everywhere else.
    """
    mark = stream.mark()
    divisor = _accept_ordinal_head(stream)
    if divisor is None:
        return None
    try:
        inner = _parse_counted_amount(stream, back_reference=back_reference)
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.Half(inner, _accept_rounding(stream), divisor)


def _accept_ordinal_head(stream: TokenStream) -> int | None:
    """``a <ordinal> of`` — the denominator, or None with nothing consumed."""
    mark = stream.mark()
    if not stream.accept_word("a"):
        return None
    ordinal = stream.peek_word()
    divisor = _FRACTION_WORDS.get(ordinal) if ordinal is not None else None
    if divisor is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    return divisor


def accept_fraction_head(stream: TokenStream) -> int | None:
    """``half`` or ``a <ordinal> of`` — the denominator, or None (nothing
    consumed).

    For the positions where the thing being divided is the production's own
    noun rather than a quantity it can hand to :func:`parse_amount`: "loses
    **half their life**", "discards **a third of the cards in their hand**",
    "sacrifices **a third of the creatures they control**". One reader, because
    the two spellings of a fraction are one printed idea and a production that
    knew only "half" is a production Pox refuses.
    """
    if stream.accept_word("half"):
        return 2
    return _accept_ordinal_head(stream)


def accept_rounding(stream: TokenStream) -> str:
    """Public name for :func:`_accept_rounding`, for the productions that read
    a fraction's noun themselves."""
    return _accept_rounding(stream)


def _accept_rounding(stream: TokenStream) -> str:
    """``[,] rounded up|down`` after a fraction, defaulting to down.

    Shared by "half" and by the "a <ordinal> of" reader above, because it is one
    printed rider and reading it twice is two places for the comma handling to
    come apart. The comma is put back when what follows it is a different
    clause: eating it unconditionally would take the separator a later
    production needs.
    """
    comma = stream.mark()
    had_comma = stream.accept_punct(",")
    if stream.accept_word("rounded"):
        if stream.accept_word("up"):
            return "up"
        stream.accept_word("down")
        return "down"
    if had_comma:
        stream.reset(comma)
    return "down"


#: The three readers below all delimit one printed phrase — "the number of
#: <kind> counters on <somewhere>" — and differ only in the operator in front of
#: it and in whose pile it names. They sit together for that reason: the fork
#: they were is what a fragment fork always is, three readers of one sentence in
#: three modules, and the second one to be extended is the moment it shows.
def _accept_counter_count(
    stream: TokenStream, *, comparison: tuple[str, ...], on_source: bool,
) -> str | None:
    """``<comparison> the number of <kind> counters on <referent>``, as the
    counter's printed name — or None with the cursor exactly where it was.

    *on_source* picks the referent, and it is the whole difference between the
    two bounds this serves: the ability's own **source** (Wave of Terror,
    Legacy's Allure), read through ``accept_source_reference`` so a card naming
    itself needs no code, against a bare "it" (Corrosion), which names the
    object being tested. They are different piles, so a reader that admitted
    either would answer one card's phrase with the other card's count — which
    is why "it" is refused outright by the source form rather than falling
    through to it.

    Refuses without consuming, so "with mana value 3 or less" keeps its own
    reading.
    """
    mark = stream.mark()
    if not stream.accept_phrase(*comparison, "the", "number", "of"):
        stream.reset(mark)
        return None
    kind = stream.peek_word()
    if kind is None:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("counters", "on"):
        stream.reset(mark)
        return None
    if on_source:
        # Late import for `accept_counters_on_source`'s reason below: `nouns`
        # reads this module for its comparisons, so the cycle is broken at call
        # time rather than at import time.
        from .nouns import accept_source_reference

        if stream.at_word("it") or not accept_source_reference(stream):
            stream.reset(mark)
            return None
    elif not stream.accept_word("it"):
        stream.reset(mark)
        return None
    return kind


def accept_source_counter_bound(
    stream: TokenStream, *, comparison: tuple[str, ...] = ("equal", "to"),
) -> str | None:
    """``<comparison> the number of <kind> counters on <this permanent>``
    — "with mana value **equal to** …" (Wave of Terror), "with power **less
    than or equal to** …" (Legacy's Allure).

    *comparison* is the caller's, because the caller is what knows which field
    the answer lands in: the two operators bound different characteristics and
    reach different matchers. Reading either here and returning only the kind
    would let one card's operator be tested as the other's — a narrowing
    silently widened, on a phrase whose whole job is to narrow.
    """
    return _accept_counter_count(stream, comparison=comparison, on_source=True)


def accept_counters_on_it_bound(stream: TokenStream) -> str | None:
    """``less than or equal to the number of <kind> counters on it``
    (Corrosion).

    The bound above with the pronoun in place of the source. "On **it**" is
    required: that word is the whole difference between a count on the object
    being tested and a count on the ability's own permanent.
    """
    return _accept_counter_count(
        stream,
        comparison=("less", "than", "or", "equal", "to"),
        on_source=False,
    )


def accept_counter_kind(stream: TokenStream) -> "GToken | None":
    """The counter's written name as its token, or None with the cursor where
    it was.

    **CR 122.1's open key space, read in one place.** A counter's kind is
    whatever word the card invented ("bounty", "corpse", "wind", "mire") *or* a
    P/T token, which the lexer gives its own kind — and "counter"/"counters"
    itself is never the kind, which is what stops a bare "put a counter on it"
    from inventing a counter called "counter".

    Written here because the reading was **four** productions in four modules
    by the time a fifth wanted it: ``phrases._expect_counter_kind`` (the same
    question, raising instead of declining),
    ``condition_clauses._accept_counter_kind``, the inline form inside
    :func:`accept_counters_on_source` below, and now the noun-phrase
    postmodifier "…with a <kind> counter on it". Each was correct when written
    and each was a place the next kind of counter could be forgotten. In
    ``amounts`` because this module is unlayered — every parse layer may read
    it — and the four callers sit at four different layers, so no layered home
    could serve them all.

    ``+1/+0`` is the reason it is not ``peek_word``: the lexer gives a P/T its
    own token kind, so a word-only reader silently refused "three or more
    **+1/+0** counters" while its "**echo** counters" twin worked.
    """
    token = stream.peek()
    if token is None or token.kind not in (PT, WORD):
        return None
    if token.is_word("counter", "counters"):
        return None
    stream.advance()
    return token


def accept_counters_on_source(stream: TokenStream) -> "ast.CountersOnSource | None":
    """``<word> counters on <the source>`` — the count of a named counter the
    ability's own source is carrying, or None when the words are something else.

    Sits in front of the noun parser in both readers of "the number of …",
    because a counter kind is a bare word and ``parse_object_filter`` would
    refuse it as an unknown noun — so without this the whole line falls, which
    is what left Armageddon Clock's draw-step damage to a regex in a phase
    mixin.

    The kind is whatever word the card invented (CR 122.1), matching
    ``engine/named_counters.py``'s open key space — **or** a P/T counter, which
    the lexer reads as a ``pt`` token rather than a word ("the number of +1/+1
    counters on it", Primordial Ooze). Both spellings are one production because
    the sentence is one sentence: what is being counted is what is sitting on
    the source, and CR 122.1 makes a +1/+1 counter a counter like any other. The
    reader that resolves the count is what knows the difference between a store
    the card invented and the P/T channel.
    """
    mark = stream.mark()
    token = accept_counter_kind(stream)
    if token is not None:
        kind = token.text
        if stream.accept_word("counter", "counters") and stream.accept_word("on"):
            # Late import for the reason the noun imports below give: nouns
            # depends on this module for comparisons, so the cycle is broken at
            # call time.
            from .nouns import accept_source_reference

            if accept_source_reference(stream):
                return ast.CountersOnSource(kind)
    stream.reset(mark)
    return None


def accept_counters_on_event_subject(
    stream: TokenStream,
) -> "ast.CountersOnEventSubject | None":
    """``<word> counters on that <noun>`` — the count of a named counter the
    object the firing event was about was carrying, or None when the words are
    something else.

    The twin of :func:`accept_counters_on_source` over the other referent a
    counter clause can name. Only "**that** <noun>" is admitted, and never a
    bare "it": a pronoun after a trigger is rebound to the event's subject in
    one place (``rebinding.rebind_pronoun_to_event_subject``) and reading it a
    second time here would be a second answer to which object a sentence means.

    The noun is checked but not otherwise read. What the phrase names is decided
    by the trigger the sentence sits under, so the word is a printed agreement
    with that event rather than a filter — and a clause naming some *other*
    noun than the event's is one this cannot answer, which is why the word must
    still be there for the production to claim the line.
    """
    mark = stream.mark()
    token = accept_counter_kind(stream)
    if token is not None:
        kind = token.text
        if (
            stream.accept_word("counter", "counters")
            and stream.accept_word("on")
            and stream.accept_word("that")
        ):
            noun = stream.peek_word()
            if noun is not None and _singular(noun) in _EVENT_SUBJECT_NOUNS:
                stream.advance()
                return ast.CountersOnEventSubject(kind)
    stream.reset(mark)
    return None


def _parse_counted_amount(
    stream: TokenStream, *, back_reference: str | None = None
) -> ast.Amount:
    """``the number of <noun phrase>``, or any ordinary quantity.

    Split out so "half" can take one of either — "half **the number of cards in
    their library**" (Peer into the Abyss) is a half of a count, and
    :func:`parse_amount`'s own recursion could only read the plain quantities.
    Both readers reach the same noun parser, so the count means one thing
    wherever it is printed.
    """
    mark = stream.mark()
    if stream.accept_word("the") and stream.accept_phrase("number", "of"):
        counters = accept_counters_on_source(stream)
        if counters is not None:
            return counters
        # Late import for the reason `parse_equal_to` gives: nouns depends on
        # this module for comparisons, so the cycle is broken at call time.
        from .nouns import parse_object_filter
        from .where_x import accept_this_way_count

        filt = parse_object_filter(stream)
        # "…this way" turns the count into a back-reference — see
        # `parse_equal_to`, which reads the identical trailer through the
        # identical shared reader.
        this_way = accept_this_way_count(stream, filt)
        if this_way is not None:
            return this_way
        return _accept_excess_of(stream, ast.CountOf(filt))
    stream.reset(mark)
    # "half **the sacrificed creature's power**, rounded down" (Freyalise
    # Supplicant). A characteristic of what the ability's own cost ate, read
    # here for the reason the count above is read here: `parse_equal_to` asks
    # the same two payment-channel readers, but it hands "half" straight to the
    # quantity parser *before* it reaches them — so a fraction **of** a channel
    # had no reader at all and the line refused at "the sacrificed creature 's
    # power" while the unhalved sentence one card over parsed fine.
    #
    # The leading "the" is this reader's, exactly as it is one function up.
    channel = stream.mark()
    stream.accept_word("the")
    payment = accept_cost_channel_possessive(stream)
    if payment is not None:
        return payment
    stream.reset(channel)
    # "half **the damage dealt by one of those sorcery spells this turn**"
    # (Backdraft). A history narrowed by a choice, not a count of anything, so
    # it is read here where "half" can take it — the same position "the number
    # of" is read from, for the same reason.
    chosen = accept_damage_dealt_by_chosen_cast(stream)
    if chosen is not None:
        return chosen
    return parse_amount(stream, back_reference=back_reference)


def _accept_excess_of(stream: TokenStream, counted: ast.Amount) -> ast.Amount:
    """``<count> **in excess of** <count>`` (Superior Numbers), or *counted*
    unchanged when the phrase is absent.

    The trailing half of the same "equal to …" clause rather than a clause of
    its own, which is why it is read here and not by a production: "the number
    of creatures you control in excess of the number of creatures target
    opponent controls" is **one** quantity, and a reader that stopped at the
    first count would leave the rest of the sentence unconsumed — the loud
    failure the full-consumption rule exists for, and the right one, because a
    dropped subtrahend is a spell dealing the larger number.

    Only a count may follow, and it is read by re-entering this module's own
    "the number of …" reader rather than by a copy of it: the two halves of a
    difference are the same kind of phrase, and a second reader is a second
    answer to what "the number of Xs a player controls" means.
    """
    mark = stream.mark()
    if not stream.accept_phrase("in", "excess", "of"):
        return counted
    stream.accept_word("the")
    if not stream.accept_phrase("number", "of"):
        stream.reset(mark)
        return counted
    from .nouns import parse_object_filter

    return ast.Minus(counted, ast.CountOf(parse_object_filter(stream)))


def parse_equal_to(stream: TokenStream) -> ast.Amount | None:
    """Parse an "equal to …" quantity clause, or return None if absent.

    Handles the two shapes the card pool uses: a count of matching objects
    ("equal to the number of Swamps you control") and a back-reference to a
    value produced earlier in the same resolution ("equal to the damage
    dealt").

    A printed multiplier in front of either of them ("equal to **twice** the
    number of nonbasic lands that player controls", Price of Progress) is read
    here rather than inside :func:`_parse_equal_to_body`, for the reason
    ``where_x.parse_where_x_definition`` reads it in front of *its* body: the
    factor scales whichever definition follows, so wiring it into one of them
    would leave every other definition unable to carry a factor the card
    printed. Both front ends therefore ask ``where_x.accept_multiplier`` — two
    copies of the word table is how "twice" comes to mean 2 in one printed
    sentence and nothing in the next.
    """
    mark = stream.mark()
    if not stream.accept_phrase("equal", "to"):
        return None
    # Late, and inside the function, for the reason every other `where_x`
    # import here is: `where_x` reads noun phrases and `nouns` reads this
    # module, so the cycle is broken at call time.
    from .where_x import accept_multiplier

    factor = accept_multiplier(stream)
    body = _parse_equal_to_body(stream)
    if body is None:
        # The multiplier is consumed only if a definition follows it. Resetting
        # to before "equal to" leaves the caller exactly the tokens it had, so a
        # sentence this cannot read fails full-token consumption rather than
        # half-matching.
        stream.reset(mark)
        return None
    return body if factor is None else ast.Times(factor, body)


def _parse_equal_to_body(stream: TokenStream) -> ast.Amount | None:
    """The definition itself, once "equal to" and any multiplier in front of it
    are consumed.

    Split from :func:`parse_equal_to` so the multiplier scales every
    alternative below rather than being wired into one of them — the same split
    ``where_x.parse_where_x_definition_body`` is, one front end over.
    """
    mark = stream.mark()

    # "…draws cards equal to **the greatest number of cards a player discarded
    # this way**." (Windfall.) A maximum taken across seats over a record an
    # earlier step of this same effect wrote — no board holds it and no scalar
    # names it — so it is read whole by the one production that owns the phrase,
    # before the counts below get a chance to claim "the … number of cards".
    from .records import accept_greatest_discarded_this_way

    greatest = accept_greatest_discarded_this_way(stream)
    if greatest is not None:
        return greatest

    # "equal to **half** the number of cards in their library" (Peer into the
    # Abyss). Handed to the quantity parser, which reads the half and the count
    # under it; the shapes below are the ones that are not quantities at all.
    if stream.at_word("half"):
        return parse_amount(stream)

    # "equal to **3 minus the number of cards they discarded this way**" (Mind
    # Bomb). A named count with a printed constant, and the same table the
    # ", where X is …" trailer reads — the two front ends print the same
    # phrases about the same counts, so they ask one reader rather than keeping
    # a row each. It consumes nothing unless a whole row matches, so every
    # other "equal to …" below keeps the reading it had.
    #
    # Late, and inside the function: `where_x` reads noun phrases, `nouns`
    # reads this module for its comparisons, so the cycle is broken at call
    # time exactly as `parse_object_filter`'s is below.
    from .where_x import accept_board_count

    named = accept_board_count(stream)
    if named is not None:
        return named

    # Remembered rather than discarded, because two branches below need to know
    # whether the sentence printed a determiner at all: "**the** artifact's mana
    # value" (Viashino Heretic) arrives here with its article already eaten, and
    # the possessive reader at the foot of this function was written to require
    # one. Read there as "no determiner", the card refused its whole ability
    # while the identical sentence written "**that** artifact's mana value"
    # parsed — one printed possessive with two readings, which is the fork
    # SET_PLAYBOOK records from Revised's round 8.
    had_article = bool(stream.accept_word("the"))

    if stream.accept_phrase("number", "of"):
        # "…equal to **the number of pain counters removed this way**"
        # (Torture Chamber). The two readers below diverge at the tail — "on
        # this artifact" against "removed this way" — so neither can claim the
        # other's sentence, and what separates them is the question rather than
        # the order: this counts what the ability's own cost took off
        # (CR 601.2h) and the one under it counts what is still there. By
        # resolution those are complements, and the permanent holds none.
        removed = accept_counters_removed_for_cost(stream)
        if removed is not None:
            return removed
        counters = accept_counters_on_source(stream)
        if counters is not None:
            return counters
        # Late import: nouns depends on this module for comparisons, so the
        # cycle is broken at call time rather than import time.
        from .nouns import parse_object_filter
        from .where_x import accept_this_way_count

        filt = parse_object_filter(stream)
        # "equal to the number of Mountains **put into a graveyard this way**"
        # (Volcanic Eruption). The trailing participle makes the count a
        # back-reference to an earlier step of this same effect, and it is read
        # through the reader the ", where X is …" trailer already uses — the
        # two front ends print the same phrases about the same records, so they
        # ask one function rather than keeping a row each (the same argument
        # `accept_board_count` above states for the named counts).
        this_way = accept_this_way_count(stream, filt)
        if this_way is not None:
            return this_way
        # "…**in excess of** the number of …" (Superior Numbers), read through
        # the same helper `_parse_counted_amount` above reads it through. Two
        # productions read "the number of <noun phrase>" — this one and that one
        # — and a trailer taught to only one of them would make which
        # definitions a card may use depend on which sentence it printed them
        # in, which is the fork SET_PLAYBOOK records from Revised's round 8.
        return _accept_excess_of(stream, ast.CountOf(filt))

    # "equal to **the sacrificed creature's toughness**" (Life Chisel, Diamond
    # Valley) — a characteristic of the permanent the ability's own *cost* ate,
    # not of anything a step of the effect touched. Read before the
    # back-references below because it names its own channel and needs no
    # producer: CR 601.2h pays the cost before the ability is on the stack, so
    # by the time this resolves the creature is a memory the activation path
    # recorded (`sacrificed_for_cost`).
    #
    # The noun and the characteristic are both read as printed, so "the
    # sacrificed **artifact's** mana value" is the same production. Which of
    # them a handler can actually answer is the lowering's question.
    # "…where X is **the exiled card's mana value**" (Necropolis) — the same
    # shape one zone over. Its own reader so both front ends (this one and the
    # where-clause in `where_x.py`) ask one function: two copies of a phrase
    # that names a payment channel is how the two come to name different ones.
    # "…equal to **the mana value of the discarded card**." (Pyromancy.) The
    # same four payment channels the possessive readers below name, with the
    # genitive the other way round — English puts a possessor in front of its
    # noun or behind it with "of", and a card prints whichever it likes. One
    # reader for both orders (``cost_records.accept_cost_characteristic_of``), so a
    # channel taught to one spelling is not a channel the other cannot find.
    #
    # Read before the possessives because the two cannot collide: this one opens
    # on a characteristic word and each of those opens on a participle.
    inverted = accept_cost_characteristic_of(stream)
    if inverted is not None:
        return inverted

    # "…equal to **the tapped creature's power**" (Unerring Sling), and the
    # sacrificed, exiled and discarded channels beside it: every payment
    # channel's possessive through the one reader the where-clause front end
    # asks too (``cost_records.accept_cost_channel_possessive``).
    possessive = accept_cost_channel_possessive(stream)
    if possessive is not None:
        return possessive

    # "…equal to **the amount of mana they paid this way**." (Liege of the
    # Hollows.) A back-reference to a payment an earlier step of this same
    # effect took, which is why it reads like every other "this way": the
    # lowering demands the producer, so with no such step the words name
    # nothing rather than computing a zero. The possessive is read and dropped
    # — "they" and "you" name whichever seat is performing the sentence, and
    # which seat that is was settled before this clause was reached.
    mark_mana = stream.mark()
    if stream.accept_phrase("amount", "of", "mana"):
        stream.accept_word("they", "you", "that")
        stream.accept_word("player")
        if stream.accept_phrase("paid", "this", "way"):
            return ast.ThatMuch(MANA_PAID_BY_SEAT)
    stream.reset(mark_mana)

    # "…each opponent loses 1 life. You gain life equal to **the life lost this
    # way**." (Subversion.) A back-reference to what the sentence in front of
    # this one took, and "this way" is what makes it one: the printed 1 is per
    # opponent, so the number the gain reads is a sum that exists nowhere but
    # the record the loss wrote. Read beside "the damage dealt" below and in the
    # same shape, because it is the same question about the other of CR 120.3's
    # two ways a life total goes down — and like that one it needs no producer
    # check here, the lowering's own gate refusing the words when no step of
    # this effect took any life.
    if stream.accept_phrase("life", "lost", "this", "way"):
        return ast.ThatMuch(LIFE_LOST_THIS_WAY)

    if stream.accept_phrase("damage", "dealt"):
        # "…equal to the damage dealt **this way**" (Syphon Soul). "This way"
        # says the number is the one *this effect* produced rather than any
        # damage dealt elsewhere in the turn — which is exactly what the
        # back-reference already means: `_back_reference_payload` resolves it
        # against the steps of this same effect and refuses when no step
        # produced one. So the words are consumed, not dropped: the reading
        # they ask for is the only reading available.
        stream.accept_phrase("this", "way")
        return ast.ThatMuch("damage_dealt")

    # "equal to its power" — a characteristic of the object the *preceding*
    # step acted on, not a value in the resolution scratchpad. Nothing records
    # it, so `_PRODUCES` never names it and any lowering that reads a bare
    # occurrence is refused for want of a producer; only a lowering that
    # computes the power itself (the fused exile-and-gain-life handler) accepts
    # it. That is the intended asymmetry: the words are recognized, and what
    # they need is a handler rather than a parse.
    if stream.accept_phrase("its", "power"):
        # "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3: the
        # number is the read characteristic plus a printed constant, so the
        # constant rides the same node rather than being a second amount.
        bonus = 0
        mark_bonus = stream.mark()
        if stream.accept_word("plus"):
            token = stream.peek()
            printed = (
                int(token.text) if token is not None and token.kind == NUMBER
                else NUMBER_WORDS.get(token.text) if token is not None else None
            )
            if printed is None:
                stream.reset(mark_bonus)
            else:
                stream.advance()
                bonus = printed
        return ast.ThatMuch("its_power", bonus=bonus)

    # "equal to **its** mana value" (Divine Offering: "Destroy target artifact.
    # You gain life equal to its mana value."). "It" is the object the
    # *preceding step of this same effect* acted on, which by the time the gain
    # runs is in a graveyard — so the step records the number and this reads the
    # record. Named for the words rather than for one producer, because the
    # question is the same whichever verb the sentence in front of it printed;
    # the producer gate in ``_back_reference_payload`` is what makes the words
    # legal, so a card whose first sentence records nothing refuses by name
    # instead of gaining zero life.
    if stream.accept_phrase("its", "mana", "value"):
        return ast.ThatMuch("its_mana_value")

    # "equal to **its** toughness" (Exile: "Exile target nonwhite attacking
    # creature. You gain life equal to its toughness."). The same
    # back-reference "that creature's toughness" reads below, written with the
    # pronoun instead of the noun spelled out — one key, because it is one
    # question about one recorded object, and the producer gate in
    # ``_back_reference_payload`` is what makes the words legal either way.
    # A card whose first sentence records no toughness refuses by name rather
    # than gaining zero life.
    if stream.accept_phrase("its", "toughness"):
        return ast.ThatMuch("its_toughness")

    # "equal to **that creature's** power" (Terror of the Peaks) — the power of
    # the creature the *trigger's event* was about, not of the ability's source.
    # A different referent from "its power" above and so a different key: read
    # as that one it would deal the Dragon's own power, which is a number the
    # card never mentions.
    # "…equal to **the creature's** power" (Cinder Cloud, Kaervek's Purge). The
    # definite article is the same back-reference under the other determiner —
    # ``references.py`` has read "**the** creature's controller" beside "that
    # creature's controller" since Creature Bond, and a possessive whose two
    # spellings meant two referents would be a fork in a fragment.
    # …and "equal to **the** creature's power" (Cinder Cloud, Kaervek's Purge),
    # which arrives here with the article already eaten by the
    # ``accept_word("the")`` above — so the branch reads the possessive alone.
    # The definite article is the same back-reference under the other
    # determiner: ``references.py`` has read "**the** creature's controller"
    # beside "that creature's controller" since Creature Bond, and a possessive
    # whose two spellings meant two referents would be a fork in a fragment.
    if stream.accept_phrase("that", "creature", "'s", "power") or (
        stream.accept_phrase("creature", "'s", "power")
    ):
        return ast.ThatMuch("event_subject_power")

    # "…and its toughness is equal to **that creature's toughness**" (Broken
    # Visage) — the same creature, one characteristic over, and a *plain*
    # producer-gated back-reference where the power beside it also has a
    # trigger reading. The asymmetry is the pool's rather than this table's:
    # `_EVENT_QUANTITIES` is keyed by trigger kind and every row of it names a
    # *power* (the entering creature's, the damage dealt), so a toughness read
    # through that channel would silently be handed a power. Under a trigger
    # the words therefore refuse for want of a producer, which is the loud
    # failure; a step of the same effect that records one is what makes them
    # legal.
    if stream.accept_phrase("that", "creature", "'s", "toughness"):
        return ast.ThatMuch("its_toughness")

    # "equal to **that creature's mana value**" (Niambi, Esteemed Speaker) — the
    # creature the *preceding step* moved, not the trigger's event object and not
    # the ability's source. A third referent and so a third key: the step records
    # what it bounced and this reads that record, which is why the producer check
    # in ``_back_reference_payload`` is what makes the words legal rather than a
    # phrase table. Mana value is the printed cost of the card that left the
    # battlefield (CR 202.3, CR 400.7 — it is a new object in the hand, but its
    # mana value is a printed characteristic and does not change).
    if stream.accept_phrase("that", "creature", "'s", "mana", "value"):
        return ast.ThatMuch("returned_mana_value")

    # "equal to **that Wall's** mana value" (Word of Blasting) — the same
    # back-reference as "its mana value" above, written with the noun the
    # sentence in front of it used instead of a pronoun. One key, because it is
    # one question about one recorded object: the *producer* gate is what makes
    # the words legal, so a sentence with no destroy or bounce in front of it
    # still refuses by name. The noun is required to be one, and is not carried:
    # there is exactly one record to read.
    noun_mark = stream.mark()
    # The determiner is required and may already have been consumed: the "the"
    # branch at the head of this function eats one, so "the artifact's mana
    # value" reaches this point with the noun first. ``had_article`` is what
    # says a determiner was printed — accepting a bare "artifact's mana value"
    # instead would read a possessive that names no antecedent at all.
    if stream.accept_word("that", "the") or had_article:
        noun = stream.peek_word()
        if noun is not None and _singular(noun) in _POSSESSIVE_NOUNS:
            stream.advance()
            if stream.accept_phrase("'s", "mana", "value"):
                return ast.ThatMuch("its_mana_value")
    stream.reset(noun_mark)

    stream.reset(mark)
    return None


#: Nouns a "that <noun>'s mana value" phrase may name. Card types and subtypes
#: both, for the reason ``references.parse_player_ref`` admits both in the same
#: position: "that Wall" names an object exactly as "that creature" does, and
#: which word the card prints is the card's business.
#:
#: **"card" is in the set for the same reason and is not a card type.** CR 400.1
#: makes "card" the word for an object outside the battlefield, so a sentence
#: whose preceding step named a *graveyard* prints it where a sentence about a
#: permanent prints the type: "Put target creature **card** from a graveyard
#: onto the battlefield … You lose life equal to **that card's** mana value"
#: (Reanimate). Same referent, same record, one more word — and its absence
#: refused the whole line rather than narrowing anything, because a card type is
#: what the *previous* zone happened to be called.
_POSSESSIVE_NOUNS = CARD_TYPES | ALL_SUBTYPES | {"card"}

#: Nouns a "…counter on **that** <noun>" phrase may name — the same set, and
#: for the same reason: the word agrees with whatever the trigger's condition
#: called the object, and Sporogenesis' "that creature" is one printing of it
#: while a card whose death trigger named a tribe would print that instead.
#:
#: Its own name rather than the constant above reused inline, so a later
#: narrowing of one phrase's vocabulary cannot silently narrow the other's.
_EVENT_SUBJECT_NOUNS = _POSSESSIVE_NOUNS


def parse_pt_pair(text: str) -> tuple[ast.Amount, bool, ast.Amount, bool]:
    """Split a P/T token ("+3/+3", "-0/-2", "+X/+0", "0/2") into
    ``(power, power_negative, toughness, toughness_negative)``."""
    left, _, right = text.partition("/")

    def _one(part: str) -> tuple[ast.Amount, bool]:
        negative = part.startswith("-")
        body = part.lstrip("+-")
        if body in ("x", "y"):
            return ast.Var(body), negative
        return ast.Fixed(int(body)), negative

    power, power_negative = _one(left)
    toughness, toughness_negative = _one(right)
    return power, power_negative, toughness, toughness_negative


def expect_pt(stream: TokenStream) -> tuple[ast.Amount, bool, ast.Amount, bool]:
    token = stream.accept_kind(PT)
    if token is None:
        raise stream.error("expected a power/toughness value")
    return parse_pt_pair(token.text)


__all__ = ["expect_pt", "parse_amount", "parse_equal_to", "parse_pt_pair"]

