"""Quantities read off a record of something that already happened.

The parse-side mirror of ``lowering/_records.py``, and it carries that module's
name for that reason: a handler writes a value into the resolution scratchpad
and a later sentence of the same effect reads it back, and this is the half that
reads the *printed* half of that pair. "The amount of damage dealt to this
creature this turn" (Blazing Effigy), "the sacrificed creature's toughness"
(Life Chisel), "as many cards as they discarded this way" (Forget) — every
production here answers "how many?" by naming an event rather than a number.

Split out of ``amounts.py`` when two waves' additions summed past the
1,000-line guard. The boundary is not the size: what stays in ``amounts`` is a
quantity the sentence *states* — a number, an X, a fraction, a comparison, a
printed P/T — and what moved is a quantity the sentence *refers* to. A cap on a
quantity ("but not more than the player's life total before the damage was
dealt") states its own bound and stays behind with the vocabulary.
"""

from __future__ import annotations

from ..oracle_types import EXILED_THIS_WAY, REVEALED_THIS_WAY
from .errors import GrammarError
from . import ast
from .lexer import MANA, NUMBER, PT, SELF, WORD
from .readers import accept_source_reference
from .stream import TokenStream
from .vocabulary import CARD_TYPES, NUMBER_WORDS


def accept_damage_dealt_this_turn(
    stream: TokenStream,
) -> "ast.DamageDealtThisTurn | None":
    """``amount of damage dealt to <the source> this turn by [other] sources
    named <this card>`` — or None, cursor unmoved, when the words are not this.

    Blazing Effigy's where-clause. Called with the leading "the" already
    consumed, from the one reader of a where-clause definition, so the phrase
    means the same wherever a card prints it.

    Every narrowing is read rather than assumed, and the production refuses the
    moment one of them is missing. "This turn" is the ledger's window and a
    clause without it is asking about a different one; "other" is CR 109.5's
    identity exclusion and dropping it would count the creature's own damage to
    itself; and the name must be the SELF token — the card naming itself — so a
    clause comparing against some *other* printed name refuses here instead of
    quietly being read as this one. That last refusal is the dropped-rider bug
    with a card name on it.
    """
    mark = stream.mark()
    if not stream.accept_phrase("amount", "of", "damage", "dealt", "to"):
        stream.reset(mark)
        return None
    if not accept_source_reference(stream):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn", "by"):
        stream.reset(mark)
        return None
    others_only = bool(stream.accept_word("other"))
    if not (stream.accept_word("sources", "source") and stream.accept_word("named")):
        stream.reset(mark)
        return None
    if stream.accept_kind(SELF) is None:
        stream.reset(mark)
        return None
    return ast.DamageDealtThisTurn(others_only=others_only)


def accept_added_base(stream: TokenStream) -> int | None:
    """``<number> plus`` in front of a quantity — the constant it is added to.

    "…where X is **3 plus** the amount of damage dealt …" (Blazing Effigy). The
    number is payload for the reason every other printed number in this file is:
    a card printing "2 plus" is the same shape with one digit changed, and
    spelling the 3 into the phrase would make every other one a non-match.

    Returns None with the cursor where it found it, so a definition that does
    not open with a sum keeps the refusal it already had.
    """
    mark = stream.mark()
    token = stream.peek()
    if token is not None and token.kind == NUMBER:
        stream.advance()
        if stream.accept_word("plus"):
            return int(token.text)
    stream.reset(mark)
    return None


def accept_damage_dealt_by_chosen_cast(
    stream: TokenStream,
) -> "ast.DamageDealtByChosenCast | None":
    """``the damage dealt by one of those <type> spells this turn`` — or None,
    cursor unmoved, when the words are not this.

    Backdraft's amount. "One of those" is a back-reference to the set an earlier
    sentence described, and it is a *choice* rather than a sum: the whole point
    of the words is that the spells are several and one of them is picked. The
    lowering is where that choice becomes a step, and where the missing
    producer is refused.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "damage", "dealt", "by", "one", "of", "those"):
        stream.reset(mark)
        return None
    # Late import for the reason every other reader in this module gives: the
    # vocabulary side depends on this one, so the cycle is broken at call time.
    from .vocabulary import CARD_TYPES, singular

    word = stream.peek_word()
    if word is None or singular(word) not in CARD_TYPES:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("spells", "this", "turn"):
        stream.reset(mark)
        return None
    return ast.DamageDealtByChosenCast(singular(word))


#: The four **payment channels** a printed genitive may name, keyed by the
#: participle the card prints and mapped to the node it becomes.
#:
#: One table rather than four copies of one branch, and it earned that the day a
#: fourth channel arrived: the three readers below were byte-identical apart from
#: the word and the class, so a characteristic taught to one of them was a
#: characteristic the other two silently could not read. What separates the four
#: is *which record the payment path wrote*, which is the class — everything
#: else about the phrase is the same phrase.
_COST_CHANNEL_NODES: dict[str, type] = {
    "sacrificed": ast.SacrificedForCost,
    "exiled": ast.ExiledForCost,
    "tapped": ast.TappedForCost,
    # "…equal to the mana value of **the discarded card**." (Pyromancy.) The
    # fourth, and the only one no card prints in the possessive — it is in the
    # table anyway, because which genitive a card prints is a fact about the
    # sentence and this table is about the channel.
    "discarded": ast.DiscardedForCost,
}


def _accept_characteristic(stream: "TokenStream") -> str | None:
    """The characteristic word a cost-channel genitive names, or None.

    Named once because both genitives read it — "the sacrificed creature's
    **power**" and "the **mana value** of the discarded card" ask for the same
    three things in the two positions English allows. Which of them a given
    channel's evaluator can actually answer is the lowering's question, exactly
    as it was when each reader carried its own copy of this branch.
    """
    if stream.accept_phrase("mana", "value"):
        return "mana_value"
    word = stream.peek_word()
    if word in ("power", "toughness"):
        stream.advance()
        return str(word)
    return None


def _accept_possessive_cost_channel(stream: "TokenStream", participle: str):
    """``<participle> <noun>'s <characteristic>`` — or None, cursor unmoved.

    The shared body of the three named readers below. The noun is read as
    printed and not carried: "the sacrificed **artifact's** mana value" is the
    same production as "the sacrificed **creature's**", because what the words
    name is the one thing that payment ate.
    """
    node_cls = _COST_CHANNEL_NODES[participle]
    mark = stream.mark()
    if stream.accept_word(participle):
        noun = stream.peek_word()
        if noun is not None:
            stream.advance()
            if stream.accept_word("'s"):
                characteristic = _accept_characteristic(stream)
                if characteristic is not None:
                    return node_cls(characteristic)
    stream.reset(mark)
    return None


def accept_cost_characteristic_of(stream: "TokenStream"):
    """``<characteristic> of [the] <participle> <noun>`` — or None, unmoved.

    The **other** genitive, and the only one Pyromancy prints: "equal to the
    mana value of the discarded card". English puts a possessor either in front
    of its noun or behind it with "of", and a card is free to print either — so
    the alternation is read here, once, over the same channel table the
    possessive readers use, rather than as a fourth copy of a branch that
    already exists three times.

    The leading "the" is the caller's, as it is for every reader in this module;
    the determiner in front of the *participle* is this one's and is optional,
    because "of the discarded card" and "of discarded cards" are the same phrase
    to a channel that holds exactly what one payment took.

    Refuses without moving the cursor whenever any part is absent, so a sentence
    that opens "the power of a creature you control" — a board read, not a
    payment — keeps whatever reading the productions behind this one give it.
    """
    mark = stream.mark()
    characteristic = _accept_characteristic(stream)
    if characteristic is None or not stream.accept_word("of"):
        stream.reset(mark)
        return None
    stream.accept_word("the")
    node_cls = _COST_CHANNEL_NODES.get(stream.peek_word() or "")
    if node_cls is None:
        stream.reset(mark)
        return None
    stream.advance()
    if stream.peek_word() is None:
        stream.reset(mark)
        return None
    stream.advance()
    return node_cls(characteristic)


def accept_sacrificed_for_cost(stream: "TokenStream") -> "ast.SacrificedForCost | None":
    """``the sacrificed <noun>'s <characteristic>`` — or None, cursor unmoved.

    "equal to **the sacrificed creature's toughness**" (Life Chisel, Diamond
    Valley); "where X is **the sacrificed creature's mana value**" (Burnt
    Offering). A characteristic of the permanent the spell's or ability's own
    *cost* ate, not of anything a step of the effect touched: CR 601.2h pays the
    cost before the object is on the stack, so by resolution the creature is a
    memory the payment path recorded (``sacrificed_for_cost``).

    The noun and the characteristic are both read as printed, so "the sacrificed
    **artifact's** mana value" is the same production. Which of them a handler
    can actually answer is the lowering's question.

    A named function rather than an inline branch for
    :func:`accept_exiled_for_cost`'s reason: two front ends read the phrase — an
    "equal to" amount and a where-clause — and two copies of a phrase that names
    a payment channel is how the two come to name different ones. The leading
    "the" is the caller's.
    """
    return _accept_possessive_cost_channel(stream, "sacrificed")


def accept_tapped_for_cost(stream: "TokenStream") -> "ast.TappedForCost | None":
    """``the tapped <noun>'s <characteristic>`` — or None, cursor unmoved.

    "This artifact deals damage equal to **the tapped creature's power** to
    target attacking or blocking creature with flying." (Unerring Sling.) The
    third sibling of :func:`accept_sacrificed_for_cost`, reading the permanent
    the cost *tapped* — and a named function for that one's reason exactly: two
    front ends read the phrase, so two copies is how they come to name two
    channels. The leading "the" is the caller's.
    """
    return _accept_possessive_cost_channel(stream, "tapped")


def accept_counters_removed_for_cost(
    stream: "TokenStream",
) -> "ast.CountersRemovedForCost | None":
    """``<kind> counter[s] removed this way`` — or None, cursor unmoved.

    "You gain 2 life for each **elixir counter removed this way**" (Essence
    Bottle); "…equal to the number of **pain counters removed this way**"
    (Torture Chamber); "…add an additional {B} for each **charge counter
    removed this way**" (the five Mana Batteries).

    :func:`accept_sacrificed_for_cost`'s fourth sibling and a named function for
    that one's reason exactly, which this phrase had already broken: three front
    ends print it — a "for each" multiplier, an "equal to the number of"
    amount, and the mana family's own multiplier — and ``effects/mana.py`` had
    grown a private copy, so which sentences could read the phrase depended on
    what the card did with the number.

    The kind is read as free text (CR 122.1 leaves counter names open) but the
    surrounding words pin the structure: "counter"/"counters" and then
    "removed this way" in full. Dropping "this way" would turn a payment into
    a board count, which after CR 601.2h is always zero.

    The leading word is the caller's: "the number of" is followed by the plural
    and "for each" by the singular. Both inflections are accepted here rather
    than pinned per caller, because a card is free to print either and the
    phrase means one thing.
    """
    mark = stream.mark()
    kind = stream.peek_word()
    if kind is None:
        # "…equal to the number of **+1/+1** counters removed this way."
        # (Molten Hydra.) A CR 122.1a counter names itself with a power/toughness
        # pair rather than an invented word, so the lexer hands it over as a
        # ``PT`` token and ``peek_word`` answers None — which dropped the phrase
        # through to the noun parser, where "+1/+1" is not an object and the
        # whole ability refused.
        #
        # Read here rather than by a second production, for this function's own
        # stated reason: three front ends print this clause, and what separates
        # "+1/+1" from "pain" is which token kind carries the word, not the
        # question being asked. The kind travels as the printed text, which is
        # what ``named_counters.counters_on`` and ``pt.pt_counter_key`` already
        # key the store on — so no channel learns a new spelling.
        token = stream.peek()
        if token is not None and token.kind == PT:
            kind = token.text
    if kind is not None and kind not in ("counter", "counters"):
        stream.advance()
        if (
            stream.accept_word("counter", "counters")
            and stream.accept_phrase("removed", "this", "way")
        ):
            return ast.CountersRemovedForCost(str(kind))
    stream.reset(mark)
    return None


def accept_exiled_for_cost(stream: "TokenStream") -> "ast.ExiledForCost | None":
    """``the exiled card's <characteristic>`` — or None with the cursor unmoved.

    The twin of :func:`accept_sacrificed_for_cost` one zone over, and a named
    function for the same reason: two front ends read it, an "equal to" amount
    and a where-clause. The leading "the" is the caller's.
    """
    return _accept_possessive_cost_channel(stream, "exiled")


# ---------------------------------------------------------------------------
# "…for each <noun> <participle> this way" — a count an earlier step recorded
# ---------------------------------------------------------------------------
#
# Here rather than in ``phrases`` because what it produces is an
# :class:`ast.ThatMuch` — a quantity, which is this module's whole subject —
# while its look-alike ``phrases._parse_for_each`` produces a *set*. The two
# read the same four opening words and answer different questions, and keeping
# the count beside the other counts is what says which is which. It moved when
# ``phrases`` crossed the thousand-line guard, along the line the two clauses
# already differed on.

# "for each card **discarded this way**" — the printed participles that name a
# set an *earlier step of this same effect* produced, and the resolution
# scratchpad key that step records its size under. Data rather than branches for
# this file's stated reason, and narrow on purpose: the noun and the participle
# are checked together, so "for each creature discarded this way" is a sentence
# nobody printed and refuses instead of quietly counting cards.
_THIS_WAY_COUNTS: dict[tuple[str, str], str] = {
    ("card", "discarded"): "discarded_count",
    # "…you gain 1 life for each card **exiled this way**." (Rysorian Badger.)
    # The count the graveyard exile in front of it recorded. The key is
    # ``oracle_types``' own constant rather than a fourth spelling of the
    # string: the handler writes it, ``lowering/_records`` declares it and this
    # table reads it, and a second spelling is how a producer gate goes vacuous
    # while the amount reads an empty record.
    ("card", "exiled"): EXILED_THIS_WAY,
    # "Reveal any number of blue cards in your hand. **… for each card revealed
    # this way.**" (Brine Seer and the eleven Urza's Destiny cards printed with
    # it — a life gain, a mana addition, a cost multiplier and a repeated
    # return, all reading one row.) The count the reveal in front of the
    # sentence recorded, and the reason the row is keyed on the *pair* rather
    # than on the participle: "card revealed" is this record and "damage
    # prevented" one row down is a shield, so a table keyed on the verb alone
    # would answer one sentence with the other's producer.
    ("card", "revealed"): REVEALED_THIS_WAY,
    # "…for each 1 **damage prevented** this way." (Sacred Boon.) What the
    # earlier step recorded here is the *shield*, not a number — the total is
    # not known when the spell resolves and goes on accumulating all turn — so
    # the key names the shield and the lowering that reads it is the one that
    # knows to ask it for its total.
    ("damage", "prevented"): "prevention_shield",
}


def _parse_for_each_this_way(stream: TokenStream) -> ast.ThatMuch | None:
    """``for each <noun> <participle> this way`` — a trailing repetition clause
    whose number is one earlier step's result.

    A *count*, not a set, which is why it produces :class:`ast.ThatMuch` rather
    than the ``ObjectFilter`` / :class:`ast.DiedThisTurn` that
    :func:`_parse_for_each` above returns. The two clauses look alike and ask
    different questions: "for each creature that died this turn" iterates a
    window of the turn's history that anything may have contributed to, and this
    one counts exactly what the sentence in front of it did.

    "This way" is required rather than defaulted, for :func:`_parse_for_each`'s
    reason: without the words the clause would name some other set, and letting
    them be absent would let them be *deleted* with no change to the parse.
    Lowering then refuses unless a step of the same effect really records the
    key — with no producer the words name nothing, and a zero is a number the
    card never printed.

    Returning None leaves the cursor where it was, so a caller that does not
    find the clause still owes the rest of its line to full-token consumption.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    # "for each **1** damage prevented this way" (Sacred Boon) — the printed
    # unit. Only one, because the clause is a rate and the count beside it is
    # what is placed per unit: "for each 2 damage" would be a division this
    # produces no node for, and reading the number and dropping it would place
    # twice what the card says. So it is read and checked rather than skipped.
    unit = stream.peek()
    if unit is not None and unit.kind == NUMBER:
        if unit.text != "1":
            stream.reset(mark)
            return None
        stream.next()
    noun = stream.peek()
    if noun is None or noun.kind != WORD:
        stream.reset(mark)
        return None
    singular = noun.text[:-1] if noun.text.endswith("s") else noun.text
    stream.next()
    participle = stream.peek()
    key = (
        _THIS_WAY_COUNTS.get((singular, participle.text))
        if participle is not None and participle.kind == WORD
        else None
    )
    if key is None:
        stream.reset(mark)
        return None
    stream.next()
    if not stream.accept_phrase("this", "way"):
        stream.reset(mark)
        return None
    return ast.ThatMuch(key)


def scaled_by_recorded_count(
    printed: "ast.Amount", counted: "ast.ThatMuch", stream: TokenStream
) -> "ast.Amount":
    """The one number *"<printed> X for each <unit> <participle> this way"* names.

    "For each card discarded this way, put **two** +1/+1 counters on this
    creature." (Mind Maggots.) The clause is a **rate**: what the sentence
    printed is placed once per unit of what an earlier step recorded, so the
    number is the product — and :class:`ast.Times` is the node the grammar
    already has for one, minted here so the two printed word orders reach it
    through one reader.

    A printed 1 folds away rather than becoming ``Times(1, …)``, which is what
    keeps every card written before a multiplier existed compiling to the
    byte-identical program it did.

    Refuses anything that is not a printed number, and the refusal is the point:
    a rate over a quantity the resolution has yet to compute is two unknowns
    multiplied, which no card prints — and reading the clause while dropping the
    printed count would place one counter where the card says two.
    """
    if not isinstance(printed, ast.Fixed) or printed.value < 1:
        raise stream.error(
            "a rate per recorded unit multiplies a printed number"
        )
    if printed.value == 1:
        return counted
    return ast.Times(printed.value, counted)


def _parse_for_each_damage_dealt_to(
    stream: TokenStream,
) -> "ast.DamageDealtThisTurn | None":
    """``for each 1 damage dealt to <player> this turn`` — a trailing repetition
    clause whose number is a *history*.

    "At the beginning of each end step, … put a +1/+1 counter on this creature
    **for each 1 damage dealt to you this turn**." (Discordant Spirit.)

    Its own reader beside :func:`_parse_for_each_this_way`, which shares the
    first three tokens and answers a different question: "this way" counts what
    the sentence in front of it just did, and this counts what the *turn* did,
    to a player, from any source at all. The turn's ledger
    (``engine/damage_ledger.py``) is the record — nothing on a board holds it,
    because a life total says only what the whole turn came to and a player who
    gained life in between would read as never having been hit.

    "This turn" is required for :func:`phrases._parse_for_each`'s reason: the
    ledger's window is the turn, so a clause naming another one is a different
    number, and letting the words be absent would let them be deleted with no
    change to the parse. So is the printed unit "1" — the clause is a rate, and
    "for each 2 damage" is a division this produces no node for.

    Returning None leaves the cursor where it was.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    unit = stream.peek()
    if unit is None or unit.kind != NUMBER or unit.text != "1":
        stream.reset(mark)
        return None
    stream.next()
    if not stream.accept_phrase("damage", "dealt", "to"):
        stream.reset(mark)
        return None
    # Only "you" today. The ledger records the recipient seat of every event, so
    # "an opponent" is the same read with a different comparison — but no card
    # in the pool prints it, and a recipient word admitted with no reader behind
    # it is a narrowing dropped on the floor.
    if not stream.accept_word("you"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("this", "turn"):
        stream.reset(mark)
        return None
    # ``source_name`` None is "from any source": the clause names none, where
    # Blazing Effigy's spelling of this node prints "by sources named ~". A
    # default of ``"self"`` here would silently count only the Spirit's own
    # damage, which is nothing at all.
    return ast.DamageDealtThisTurn(recipient="you", source_name=None)


def _parse_for_each_put_into_graveyard(
    stream: TokenStream, parse_filter,
) -> "ast.CountOfDeaths | None":
    """``for each <objects> put into your graveyard from the battlefield this
    turn`` — CR 700.4's "dies", spelled out, and counted for one seat.

    "…put a +1/+1 counter on ~ **for each creature put into your graveyard from
    the battlefield this turn**." (Asmira, Holy Avenger.)

    The set-valued twin ``phrases._parse_for_each`` reads the short spelling
    ("for each creature that died this turn") and produces a *game-wide* window;
    this one names a graveyard, so it is one seat's tally and lands on
    :class:`ast.CountOfDeaths` with the owner scope. "From the battlefield" is
    required rather than defaulted: without it the clause would also count a
    discard and a mill, which are not deaths and which the tally does not see.

    *parse_filter* is ``nouns.parse_object_filter``, handed down rather than
    imported: this module sits **below** ``nouns`` in the parse layering, and
    the inversion is the one ``delayed`` and ``postmodifiers`` already make for
    the same reason. Reading the noun phrase through the shared parser rather
    than matching a bare word is what lets the lowering refuse a narrowing the
    tally cannot apply, instead of the phrase quietly widening back to every
    creature.

    Returning None leaves the cursor where it was.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "put", "into", "your", "graveyard", "from", "the", "battlefield",
        "this", "turn",
    ):
        stream.reset(mark)
        return None
    return ast.CountOfDeaths(filt, scope="into_your_graveyard")


def _parse_for_each_history(stream: TokenStream, parse_filter) -> "ast.Amount | None":
    """Every ``for each …`` clause whose number is a history of *this turn*.

    One dispatcher, so a caller spending such a count reaches all of them at
    once; each reader below declines with the cursor unmoved, so the order here
    decides nothing but which refusal a caller sees.
    """
    dealt = _parse_for_each_damage_dealt_to(stream)
    if dealt is not None:
        return dealt
    return _parse_for_each_put_into_graveyard(stream, parse_filter)


#: The pronoun a "this way" back-reference uses for the seat the verb in front
#: of it already named. A table rather than a bare "consume whatever pronoun is
#: there": "target player discards two cards, then draws as many cards as
#: **they** discarded this way" and "…as **you** discarded this way" are two
#: different seats, and a reader that accepted either would let the sentence
#: count one player's answer and act on another's.
_SEAT_PRONOUNS: dict[str, tuple[str, ...]] = {
    "you": ("you",),
    "target_player": ("they",),
    "target_opponent": ("they",),
    "each_player": ("they",),
    "each_opponent": ("they",),
    "that_player": ("they",),
}


def accept_as_many_as(
    stream: TokenStream, noun: tuple[str, ...], player: "ast.PlayerRef"
) -> "ast.ThatMuch | None":
    """``as many <noun> as <pronoun> <participle> this way`` — or None, unmoved.

    The comparative spelling of the back-reference ``_parse_for_each_this_way``
    above reads: "draws **as many cards as they discarded this way**" (Forget)
    names the count one earlier step of this same resolution produced, and it
    reads it through the same ``_THIS_WAY_COUNTS`` table for that function's
    stated reason — the noun and the participle are checked *together*, so "as
    many cards as they exiled this way" is a sentence nobody printed and
    refuses rather than quietly counting discards.

    *noun* is the caller's own noun ("card"/"cards" for a draw), because the
    phrase puts the noun inside the amount where every other quantity puts it
    after: the caller has already committed to what is being counted, and a
    clause counting something else is not this clause.

    *player* is the seat the verb names, and the pronoun has to agree with it
    (``_SEAT_PRONOUNS``). A mismatch refuses: the record is one seat's answer,
    and a pronoun naming a different seat would be read as though it named this
    one.
    """
    mark = stream.mark()
    if not stream.accept_phrase("as", "many"):
        return None
    counted = stream.peek()
    if counted is None or counted.kind != WORD or counted.text not in noun:
        stream.reset(mark)
        return None
    singular = counted.text[:-1] if counted.text.endswith("s") else counted.text
    stream.next()
    if not stream.accept_word("as"):
        stream.reset(mark)
        return None
    pronouns = _SEAT_PRONOUNS.get(player.kind)
    if pronouns is None or not stream.accept_word(*pronouns):
        stream.reset(mark)
        return None
    participle = stream.peek()
    key = (
        _THIS_WAY_COUNTS.get((singular, participle.text))
        if participle is not None and participle.kind == WORD
        else None
    )
    if key is None:
        stream.reset(mark)
        return None
    stream.next()
    if not stream.accept_phrase("this", "way"):
        stream.reset(mark)
        return None
    return ast.ThatMuch(key)


def accept_additional_cost_paid(stream: "TokenStream") -> str | None:
    """``additional {1}{G} you paid`` — the printed symbols, or None with the
    cursor unmoved.

    "For each **additional {1}{R} you paid**, destroy another target artifact"
    (Primitive Justice); "…plus an **additional 3 life for each additional
    {1}{G} you paid**" (Taste of Paradise). A quantity that refers to a
    *payment*, which is why it is here beside the sacrificed- and
    exiled-for-cost readers rather than in ``amounts``: CR 601.2b's optional
    additional cost was announced and paid before the spell was ever on the
    stack, and by resolution the pool that paid it is empty (CR 500.5).

    A named function rather than an inline branch for
    :func:`accept_sacrificed_for_cost`'s reason, and the same reason twice over
    here: two front ends read the phrase — the leading "for each" iterator and
    the trailing life-gain multiplier — and two copies of a phrase that names a
    payment channel is how the two come to name different ones.

    The symbols are captured **as printed** and interpreted by nobody here.
    ``lowering/loops.optional_cost_key`` turns them into the canonical key
    through ``mana_payment``, which is the same pair of functions the payment
    recorded them under — so one reader decides what "{1}{R}" means and the
    parse cannot disagree with the charge. The leading "for each" is the
    caller's word to consume; this reads from "additional".
    """
    mark = stream.mark()
    if not stream.accept_word("additional"):
        return None
    symbols = ""
    while stream.at_kind(MANA):
        symbols += stream.next().text
    if not symbols or not stream.accept_phrase("you", "paid"):
        stream.reset(mark)
        return None
    return symbols


def accept_plus_per_cost_paid(
    stream: "TokenStream", base: "ast.Amount", unit: str
) -> "ast.Plus | None":
    """``plus an additional 3 life for each additional {1}{G} you paid`` — the
    whole quantity, or None with the cursor unmoved.

    Taste of Paradise's amount. One life gain (CR 119.3), not a base gain and a
    loop beside it: a replacement watching "if you would gain life" sees one
    event of 3 + 3N, and lowering this as two effects would show it two.

    Built out of the nodes that already exist for exactly this — a
    :class:`ast.Plus` of the printed base and a :class:`ast.Times` of the
    per-payment step — so no lowering has to learn a fourth shape of
    arithmetic. What is new is only the leaf being multiplied.

    *unit* is the printed noun the second number counts ("life"), taken as an
    argument rather than written in: the arithmetic is what this reads, and a
    card printing the same shape over cards or damage would want the same
    production with one word changed.
    """
    mark = stream.mark()
    if not stream.accept_phrase("plus", "an", "additional"):
        return None
    step = accept_printed_number(stream)
    if (
        step is None
        or not stream.accept_word(unit)
        or not stream.accept_phrase("for", "each")
    ):
        stream.reset(mark)
        return None
    symbols = accept_additional_cost_paid(stream)
    if symbols is None:
        stream.reset(mark)
        return None
    return ast.Plus(base, ast.Times(step, ast.AdditionalCostPaidCount(symbols)))


def accept_printed_number(stream: "TokenStream") -> int | None:
    """A printed count, as a digit token or as a word. Nothing consumed when the
    next token is neither.

    ``amounts`` holds the general number parser and sits *above* this module, so
    the two readings are spelled out here rather than imported down through the
    layer order. Both are read because a card may print either and reading only
    one would refuse the sentence on its spelling.

    Public because `seat_comparisons` one layer up reads the same printed
    threshold ("at least **two** more"). A second spelling of these four lines
    would be the fork in a fragment this package closes elsewhere — which
    reading a card got would then depend on which clause printed its number.
    """
    digit = stream.accept_kind(NUMBER)
    if digit is not None:
        return int(digit.text)
    word = stream.peek_word()
    if word in NUMBER_WORDS:
        stream.advance()
        return int(NUMBER_WORDS[word])
    return None


# ---------------------------------------------------------------------------
# "…each player **who <did something>**" — a seat narrowed by a record
# ---------------------------------------------------------------------------

def accept_player_deed(stream: TokenStream, parse_filter) -> "ast.PlayerDeed | None":
    """``who <did something>`` — which seats a sentence is about, or None.

    "…each player **who tapped a land for mana this turn** sacrifices a land of
    their choice. … deals 2 damage to each player **who sacrificed a Plains
    this way**." (Desolation.) Both clauses narrow a player reference by
    something the seat *did*, one within the turn and one within this very
    resolution, and one reader answers both so the two sentences of that card
    cannot drift about what "who" introduces.

    Here rather than in ``references``, where the word "who" is read: this
    module is where a quantity named by an *event* is parsed, and a seat named
    by an event is the same question with a seat for an answer. It is also the
    module with room, and ``references`` is the one that has none.

    *parse_filter* is ``nouns.parse_object_filter``, handed down rather than
    imported — this module sits below ``nouns`` in the parse layering, the same
    inversion :func:`_parse_for_each_put_into_graveyard` already makes.

    **Every word is required and nothing is defaulted.** "This turn" and "this
    way" are two different windows over two different records, so a reader that
    let either be absent would let the words be *deleted* with no change to the
    parse. Returning None leaves the cursor where it was, so a caller that does
    not find the clause still owes the rest of its line to full-token
    consumption — which is what makes a clause no lowering can carry fail the
    line rather than widen the sentence to every seat.
    """
    mark = stream.mark()
    if not stream.accept_word("who"):
        return None
    if stream.accept_phrase(
        "tapped", "a", "land", "for", "mana", "this", "turn"
    ):
        return ast.PlayerDeed("tapped_land_for_mana_this_turn")
    if stream.accept_word("sacrificed"):
        # "…who sacrificed **a Plains** this way". The noun phrase is read by
        # the shared parser rather than matched as a bare word, so a card
        # printed about an artifact or a black creature is the same clause with
        # one word changed — and so the lowering can refuse a narrowing the
        # card-record matcher cannot test instead of dropping it.
        # The indefinite article, consumed here rather than by the noun parser
        # — which reads "Plains" and not "a Plains", because everywhere else an
        # article marks a different noun phrase. Nothing is lost by consuming
        # it: "a Plains" and "Plains" describe the same card, where the *words*
        # that follow ("this way") are the ones that would change the set.
        stream.accept_word("a", "an")
        try:
            filt = parse_filter(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        if not stream.accept_phrase("this", "way"):
            stream.reset(mark)
            return None
        return ast.PlayerDeed("sacrificed_this_way", filter=filt)
    stream.reset(mark)
    return None


def accept_greatest_discarded_this_way(
    stream: TokenStream,
) -> "ast.GreatestDiscardedThisWay | None":
    """``the greatest number of cards a player discarded this way`` — or None,
    cursor unmoved.

    Windfall's second half. Every word is required, and each one of them is
    load-bearing rather than ceremony:

    * "greatest" is the aggregate, and without it the phrase would be a plain
      count of somebody's discard;
    * "a player" is what says the maximum is taken **across seats** — "they
      discarded this way" is one seat's own answer and a different number;
    * "this way" is the record, and letting it be absent would let the words be
      deleted with no change to the parse.

    Returning None leaves the cursor where it was.
    """
    mark = stream.mark()
    if not stream.accept_phrase(
        "the", "greatest", "number", "of", "cards", "a", "player",
        "discarded", "this", "way",
    ):
        stream.reset(mark)
        return None
    return ast.GreatestDiscardedThisWay()


def parse_for_each_sacrificed_this_way(
    stream: TokenStream, parse_filter,
) -> "ast.CountOfSacrificesThisWay | None":
    """``for each <objects> sacrificed this way`` — how many of what an earlier
    step of this same effect *sacrificed* answer a printed noun phrase.

    "Sacrifice any number of artifacts, creatures, and/or lands. Draw a card
    **for each permanent sacrificed this way**." (Reprocess.)

    Its own reader beside :func:`parse_for_each_milled_this_way`, which it is
    shaped exactly like and names a different record: a mill puts cards there
    from a library and this took permanents off the battlefield, so reading one
    as the other counts a set the card never named.

    Not a row in ``_THIS_WAY_COUNTS`` above, and the difference is what the
    record *is*: every key in that table names a scratchpad slot holding a
    **number**, and the sacrifice records the **cards** — which is what lets a
    narrowed spelling ask how many of them were creatures, and what makes a
    bare ``int()`` of the slot a type error rather than a count.

    Returning None leaves the cursor where it was.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("sacrificed", "this", "way"):
        stream.reset(mark)
        return None
    return ast.CountOfSacrificesThisWay(filt)


def parse_for_each_milled_this_way(
    stream: TokenStream, parse_filter,
) -> "ast.CountOfMillsThisWay | None":
    """``for each <objects> put into your graveyard this way`` — how many of
    what an earlier step of this same effect *milled* answer a noun phrase.

    "Mill four cards. Whenever a creature attacks this turn, it gets +1/+0
    until end of turn **for each creature card put into your graveyard this
    way**." (Song of Blood.)

    Its own reader beside :func:`_parse_for_each_put_into_graveyard`, which
    shares six of its words and names a different set: that one is CR 700.4's
    "dies" spelled out — *from the battlefield*, a window of the whole turn
    anything may have contributed to — and this is exactly the cards one step
    of this effect put there from a library. A mill is not a death, so reading
    either as the other counts a set the card never named.

    And distinct from ``where_x``'s "put into **a** graveyard this way", which
    is the same participle over the *destruction* record. The possessive is the
    whole difference and it is the honest one: a mill goes to its own
    controller's graveyard, and a sweep goes to each victim's.

    The count is **filtered**, which is what makes it a node rather than a bare
    back-reference: "four cards" were milled and the sentence asks how many of
    them were creature cards. The lowering is what refuses a narrowing the
    card-record matcher cannot answer.

    Returning None leaves the cursor where it was.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    try:
        filt = parse_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "put", "into", "your", "graveyard", "this", "way"
    ):
        stream.reset(mark)
        return None
    return ast.CountOfMillsThisWay(filt)
