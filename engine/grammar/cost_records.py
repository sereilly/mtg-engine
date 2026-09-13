"""A characteristic of the object a **cost** consumed, named back by the sentence.

The parse-side mirror of ``lowering/_cost_records.py``, and it carries that
module's name for that reason: "sacrifice a creature: target creature gets +X/+0,
where X is **the sacrificed creature's power**" (Bloodrock Cyclops) is one
printed sentence whose two halves are a cost and a reference back to what the
cost took. That module lowers the reference; this one reads it.

Split out of ``records.py`` at the Phase 0 before the next set, when two waves'
additions left it 27 lines under the size guard. The seam is the one the mirror
had already drawn and named: ``lowering/_cost_records.py`` is "the other side of
the colon from ``_records.py``", split out of *it* at ULG wave 1 for the same
reason, and the parse halves of the two subjects had stayed in one file. What
stays in ``records`` is a quantity an **instruction** recorded — a step of an
effect, keyed by instruction kind; what moved is a quantity a **cost** recorded,
which no instruction kind can key because a cost is charged by
``engine/mixins/stack/activation.py`` and ``casting.py`` on the way to the stack
(CR 601.2h, CR 602.2b) rather than by anything the dispatcher runs.

Importers were pointed here rather than left going through ``records``, which is
the mirror's own decision restated: a re-export is a hop that is invisible until
somebody greps for the reader.
"""

from __future__ import annotations

from . import ast
from .lexer import PT
from .stream import TokenStream


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
