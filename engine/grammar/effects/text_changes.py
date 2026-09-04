"""Rewriting a printed word — "Change the text of <subject> by replacing all
instances of one <vocabulary> with another." (CR 612.)

Split out of ``effects/characteristics.py`` when Mirage's second wave took that
module past the thousand-line guard, and it left under the name
``engine/text_changes.py`` and ``INSTRUCTION_CATEGORIES``' ``"text_change"``
already give the subject — the mirror it re-forms is the module that *performs*
the swap rather than a lowering family, which is why the layering guard lists it
as a parse family with no twin on the other two sides (``search`` and
``control_changes`` are there for the same reason: the size guard fired on the
productions and on nothing else).

The seam is the one ``characteristics``' own docstring draws when it lists what
a permanent *is*: P/T, keywords, colour, counters — all read off the object.
A text change is not a characteristic at all. It rewrites the *words*, and
everything downstream reads the result through ``Permanent.effective_card``
rather than through any accessor this family owns.
"""

from .. import ast
from ..references import parse_recipient
from ..stream import TokenStream


# Vocabularies a printed text change can swap, one literal phrase per mode
# (CR 612.1). Closed on purpose: `mark_text_modified` substitutes exactly these
# two, and a card naming a third — a creature type, a card name — is a text
# change the engine does not perform. Listing the phrases keeps that card
# failing here instead of reaching the handler as a mode it will ignore.
_TEXT_CHANGE_MODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_type", ("basic", "land", "type")),
    ("color_word", ("color", "word")),
)


#: "…replacing all instances of one color word with another **or one basic land
#: type with another**" (Mind Bend). A card that offers *either* vocabulary,
#: which is not a third substitution but a choice between the two above — so it
#: is one mode value rather than two instructions, and which of them happens is
#: a decision its controller owes as the spell resolves (CR 612.1).
_EITHER_VOCABULARY = "color_word_or_land_type"


def _parse_change_text(stream: TokenStream) -> ast.ChangeText:
    """``Change the text of <subject> by replacing all instances of one <what>
    with another.`` (Magical Hack, Sleight of Mind.)

    One production for the pair: they are the same sentence with one word
    changed, which is what makes the swapped vocabulary payload rather than part
    of the effect's name. Every word between the subject and the mode is
    required — "all instances of **one**" is what says a single word is
    replaced everywhere, and a card replacing something else, or only the first
    instance, would be a different effect wearing this one's sentence.
    """
    stream.expect_word("change")
    stream.expect_word("the")
    stream.expect_word("text")
    stream.expect_word("of")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to change the text of")
    if not stream.accept_phrase("by", "replacing", "all", "instances", "of", "one"):
        raise stream.error("expected 'by replacing all instances of one'")
    for mode, phrase in _TEXT_CHANGE_MODES:
        if stream.accept_phrase(*phrase):
            if not stream.accept_phrase("with", "another"):
                raise stream.error("expected 'with another'")
            # "…**or one basic land type with another**" (Mind Bend). A second
            # vocabulary offered by the same sentence, read as a tail rather
            # than as a third row above: the alternation is between the two
            # modes that already exist, and a row spelling out both phrases
            # would be a third literal to keep in step with them. Every word is
            # required, and the second vocabulary must be one of the rows —
            # a sentence offering something this cannot substitute refuses here
            # rather than reaching the handler as a mode it will ignore.
            alternative = _accept_text_change_alternative(stream, mode)
            if alternative is not None:
                return ast.ChangeText(subject, alternative)
            return ast.ChangeText(subject, mode)
    raise stream.error("no text substitution replaces this")


def _accept_text_change_alternative(
    stream: TokenStream, first: str
) -> str | None:
    """``or one <other vocabulary> with another`` — the union mode, or None with
    the cursor untouched.

    Only the pairing Mind Bend prints is admitted: the two rows of
    :data:`_TEXT_CHANGE_MODES`, in either printed order, and never the same one
    twice. A sentence offering a vocabulary this engine does not substitute
    would otherwise be consumed and then ignored, which is a text change that
    silently does the other half.
    """
    mark = stream.mark()
    if not stream.accept_phrase("or", "one"):
        return None
    for mode, phrase in _TEXT_CHANGE_MODES:
        if mode == first:
            continue
        if stream.accept_phrase(*phrase):
            if stream.accept_phrase("with", "another"):
                return _EITHER_VOCABULARY
            break
    stream.reset(mark)
    return None
