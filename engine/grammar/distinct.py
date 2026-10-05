"""What a **count** may be taken over instead of objects: the distinct values of
one characteristic among them.

"…for each **basic land type among** lands you control" is domain (CR 207.2c's
ability word), the count Invasion prints in ten sentences; "…a land **of each
basic land type**" (Global Ruin, Coalition Victory) is the same characteristic
asked the other way round — not how many values are present, but whether all of
them are. Both spellings read one table here, so they cannot come to name
different characteristics.

Above `nouns`, whose object parser reads the phrase on the far side of "among"
and in front of "of each", and never imported back: `parse_object_filter` is
also what a target, a sweep and a trigger subject call, and "destroy target
basic land type among …" is not a sentence. A count position opts in by calling
`parse_counted_objects` instead.

Its own module rather than forty more lines of `nouns`, which the two readers
took to within 40 lines of the size guard the day they were written. No mirror
name to reuse: on the lowering side the whole of it is one branch of
`_amounts.count_spec`, and on the AST side one field, `ObjectFilter.distinct`,
which this module is named for.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .nouns import parse_object_filter
from .stream import TokenStream
from .vocabulary import BASIC_LAND_WORDS, COLOR_WORDS


#: The characteristics a count may be taken over **instead of** the objects
#: that carry them: the printed words that name one (both inflections — "for
#: each" takes the singular and "the number of" the plural, and a row that knew
#: one would make the same count readable in half its sentences) and the
#: count spec's aggregate name it means.
#:
#: "…for each **basic land type** among lands you control" is domain
#: (CR 207.2c), and it is one row because the next ("for each **color** among
#: permanents you control", which ``effects/cards`` still reads on its own for
#: the one draw that prints it) is data rather than a second production.
#:
#: The last two columns are what "a land **of each** basic land type" needs:
#: the values the rules give the characteristic (CR 305.6: five) and the
#: ``ObjectFilter`` field one of them narrows. They are here, beside the words,
#: because they are facts about the characteristic and not about either
#: sentence that reads one.
_COUNTED_CHARACTERISTICS: tuple[
    tuple[tuple[tuple[str, ...], ...], str, str, tuple[str, ...]], ...
] = (
    (
        (("basic", "land", "type"), ("basic", "land", "types")),
        "distinct_basic_land_types",
        "subtypes",
        BASIC_LAND_WORDS,
    ),
)


#: Characteristics "of each" abbreviates **only where every noun is a keep** —
#: one object chosen per value, each filling one slot — as ``(spellings,
#: filter field, values)``.
#:
#: "…chooses one card **of each color** from it" (Noxious Vapors): five picks,
#: a white card, a blue card and so on (CR 105.1's five, in the printed order),
#: and a gold card is the pick for one of its colours.
#:
#: Deliberately not a row of the table above, and the reason is on record at
#: its other reader (``condition_counts``, Coalition Victory's second
#: conjunct): in a *condition*, "a creature of each color" is a relation on one
#: noun — a gold permanent answers for each of its colours at once
#: (``Controls.of_each_color``) — so the same three words mean five slots in a
#: choice and one relation in a question. Which is being read is the caller's
#: to say (``keeps=True``), and a count position never reads this table at all.
_KEPT_CHARACTERISTICS: tuple[
    tuple[tuple[tuple[str, ...], ...], str, tuple[str, ...]], ...
] = (
    ((("color",),), "colors", tuple(COLOR_WORDS.values())),
)


def _accept_counted_characteristic(
    stream: TokenStream,
) -> tuple[str, str, tuple[str, ...]] | None:
    """The characteristic named at the cursor, as ``(aggregate, filter field,
    values)``, or None with nothing consumed."""
    for spellings, aggregate, field, values in _COUNTED_CHARACTERISTICS:
        for phrase in spellings:
            if stream.accept_phrase(*phrase):
                return aggregate, field, values
    return None


def accept_one_of_each(
    stream: TokenStream, described: ast.ObjectFilter, *, keeps: bool = False,
) -> tuple[ast.ObjectFilter, ...] | None:
    """``of each <characteristic>`` trailing the noun phrase *described* — as
    one filter **per value**, in printed order — or None with nothing consumed.

    "…if you control a land **of each basic land type**" (Coalition Victory);
    "…chooses from the lands they control a land **of each basic land type**"
    (Global Ruin). The phrase is an abbreviation and is read as what it
    abbreviates: "a Plains, an Island, a Swamp, a Mountain and a Forest", each
    still a land. The rewrite is in the parse, so both sentences land on shapes
    that already exist — the condition on the "you control X and Y"
    conjunction, the choice on Cataclysm's list of keep slots — and neither
    needs a node, a lowering or an evaluator of its own.

    What the rewrite preserves is the question each of those shapes already
    asks: a conjunction is satisfied by a Tropical Island for two of its
    conjuncts (the card asks whether the types are *present*), and a keep slot
    holds one permanent, so a dual land is kept as one type or the other. Both
    are the printed card.

    One table with ``parse_counted_objects`` below, so "of each basic land
    type" and "for each basic land type among" cannot come to name different
    characteristics.

    *keeps* is the caller saying every noun the phrase stands for is a **pick**
    — one object per value, each filling one slot — which additionally admits
    ``_KEPT_CHARACTERISTICS``: "one card **of each color**" (Noxious Vapors).
    False everywhere else, so a condition keeps its own reading of those words.
    """
    mark = stream.mark()
    if stream.accept_phrase("of", "each"):
        named = _accept_counted_characteristic(stream)
        if named is not None:
            _aggregate, field, values = named
        elif keeps:
            field, values = next(
                (
                    (kept_field, kept_values)
                    for spellings, kept_field, kept_values in _KEPT_CHARACTERISTICS
                    if any(stream.accept_phrase(*phrase) for phrase in spellings)
                ),
                (None, ()),
            )
        else:
            field, values = None, ()
        if field is not None:
            return tuple(
                dataclasses.replace(
                    described, **{field: getattr(described, field) + (value,)}
                )
                for value in values
            )
    stream.reset(mark)
    return None


def parse_counted_objects(stream: TokenStream) -> ast.ObjectFilter:
    """The set a **count** is taken over — ``parse_object_filter``, plus the
    one spelling only a count can mean: ``basic land type[s] among <objects>``.

    "This creature gets +1/+1 for each **basic land type among lands you
    control**." (Wayfaring Giant.) The plain noun parser reads "basic land" as
    a noun phrase and stops at "type", which is where every domain card in
    Invasion failed. What follows "among" is an ordinary noun phrase and is
    read by the ordinary reader; what the phrase in front of it changes is
    *what is counted*, which travels as ``ObjectFilter.distinct`` (see that
    field) for ``lowering/_amounts.count_spec`` to lift onto the spec.

    A separate entry point rather than a branch inside ``parse_object_filter``:
    that function is also what a target, a sweep and a trigger subject call,
    and "destroy target basic land type among …" is not a sentence. A caller
    opts in by calling this one, which is the claim that its lowering hands the
    filter to ``count_spec``.

    Refuses exactly as ``parse_object_filter`` does, with the cursor wherever
    the refusal left it — every caller already rewinds its own mark.
    """
    mark = stream.mark()
    named = _accept_counted_characteristic(stream)
    if named is not None and stream.accept_word("among"):
        return dataclasses.replace(parse_object_filter(stream), distinct=named[0])
    stream.reset(mark)
    return parse_object_filter(stream)


__all__ = ["accept_one_of_each", "parse_counted_objects"]
