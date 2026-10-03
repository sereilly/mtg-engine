"""Fading (CR 702.32), the keyword and the two abilities it *is*.

CR 702.32a does not describe fading, it **defines** it: "Fading N" means "This
permanent enters with N fade counters on it" and "At the beginning of your
upkeep, remove a fade counter from this permanent. If you can't, sacrifice the
permanent." So this is the rewrite ``engine/echo.py`` made for echo and
``engine/equipment.py`` for equip — the printed keyword line becomes the
sentences the rules say it already is, applied by
``oracle.expand_ability_lines`` before any line is classified, and from there
nothing downstream knows the word.

**Both sentences already had a reader**, which is the whole argument for a
rewrite into sentences over a trigger built by hand (``echo.py``'s docstring
makes it at length). The entry sentence is ``enter_effects``'
``enters_with_named_counter`` — the same pattern Malefic Scythe's soul counter
and the Mercadian depletion lands go through, read by the support gate and by
the entry state, so what is claimed and what is placed cannot drift. The
upkeep sentence is an ordinary ``upkeep_self`` trigger: "remove a fade counter
from this permanent" is the named-counter removal, and "If you can't" is the
``CouldNot`` branch rider over that step's ``removed_counter`` result. So a card
printing either sentence in longhand works the same as one printing the word.

**Two lines, not one.** CR 702.32a says the keyword "represents two abilities"
— a static ability that functions as the permanent enters (CR 614.1c) and a
triggered one — and CR 113.3 makes each its own line to every reader. Joining
them into one paragraph would leave the compiler to split a static from a
trigger, which is a different rewrite (``expand_static_then_trigger_lines``)
gated on the static being one it can *prove* it implements.

**The rule's wording, not the reminder's**, as echo carries its rule's. The
reminder says "sacrifice it"; CR 702.32a says "sacrifice **the permanent**",
and the grammar reads that as the same back-reference to the source "the
creature" has always been (``references.parse_recipient``'s definite-article
branch). Before that branch knew the generic noun, "the permanent" fell through
to the bound-subject reader and reached the forced-sacrifice prompt as an empty
filter — *sacrifice any permanent you control*, a different card that happens
to compile — which is why ``lowering/board.py``'s prompt now refuses a
back-reference outright rather than offering it as a choice.

**N is spelled as a word**, as the reminder text prints it ("enters with three
fade counters"), because that is the form the entry-state reader reads; a
count the number table cannot spell keeps the keyword line *unread*, and
:func:`unread_fading_line` keeps the card unsupported naming it — the shape
test wider than the reader that ``echo.is_echo_line`` and
``cycling.is_cycling_line`` both keep, for their reason. Without that gate an
artifact or enchantment whose *other* line compiles would report supported with
its fading dropped, which is exactly what Rejuvenation Chamber and Saproling
Burst did before this module existed.
"""

from __future__ import annotations

import re

#: The rules text CR 702.32a gives the keyword, one line per ability, quoted
#: word for word except that N is spelled as the reminder text spells it.
FADING_RULES_TEXT = (
    "This permanent enters with {count} fade {noun} on it.\n"
    "At the beginning of your upkeep, remove a fade counter from this "
    "permanent. If you can't, sacrifice the permanent."
)

#: "fading 3" as the printed line survives reminder-text removal.
_FADING_LINE = re.compile(r"^fading\s+(?P<count>\d+)$", re.IGNORECASE)

#: Any line that *is* a fading keyword line, readable or not — "Fading X", a
#: count with no word, a bare "Fading". The wider shape is what the support
#: gate asks, so a variant the expansion refuses stays refused *as fading*
#: rather than reaching a classifier that has never heard of the word.
#:
#: The keyword and at most one argument, and nothing after: wider than the
#: reader, but not so wide that a sentence opening with a card *named*
#: "Fading …" is taken for a keyword line.
_FADING_SHAPE = re.compile(r"^fading(?:\s+\S+)?\s*\.?$", re.IGNORECASE)

_REMINDER = re.compile(r"\([^)]*\)")


def _count_word(count: int) -> str | None:
    """*count* spelled the way the entry-state reader reads it, or None.

    Inverted from the grammar's own number table rather than a second list, so
    a number the reader cannot read is a number this cannot write. The
    articles are skipped: "a fade counters" is not a sentence anything prints.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    for word, value in NUMBER_WORDS.items():
        if value == count and word not in ("a", "an"):
            return word
    return None


def fading_count(line: str) -> int | None:
    """The printed N of one fading line, or None when *line* is not a fading
    line this module can rewrite.

    The admission test as well as the reader, as ``echo.echo_cost`` is: a count
    the entry sentence could not carry is refused here, so the card stays
    unsupported rather than entering with no counters and dying at its first
    upkeep.
    """
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")
    match = _FADING_LINE.match(stripped)
    if match is None:
        return None
    count = int(match.group("count"))
    if count < 1 or _count_word(count) is None:
        return None
    return count


def is_fading_line(line: str) -> bool:
    """Whether *line* is a printed fading keyword line, whether or not
    :func:`expand_fading_line` can read it."""
    stripped = " ".join(_REMINDER.sub("", line or "").split())
    return _FADING_SHAPE.match(stripped) is not None


def expand_fading_line(line: str) -> str | None:
    """The CR 702.32a rules text for one printed fading line, or None."""
    count = fading_count(line)
    if count is None:
        return None
    return FADING_RULES_TEXT.format(
        count=_count_word(count), noun="counter" if count == 1 else "counters"
    )


def expand_fading_lines(oracle_text: str) -> str:
    """*oracle_text* with every fading keyword line rewritten to its rules text.

    Text without a fading line is returned unchanged. Applied by the compiler
    before any line is classified, beside the echo and cycling rewrites, so the
    compiler and every other reader of a card's lines read one text.
    """
    # A fast path on the substring both cases share, as ``expand_echo_lines``
    # does: a card whose text merely says "fading" elsewhere pays one split.
    if not oracle_text or "ading" not in oracle_text:
        return oracle_text
    lines = oracle_text.split("\n")
    return "\n".join(expand_fading_line(line) or line for line in lines)


def unread_fading_line(oracle_text: str) -> str | None:
    """A printed fading-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run, as ``cycling.unread_cycling_line`` is: a line still reading as fading
    by then is one :func:`fading_count` refused.
    """
    for line in (oracle_text or "").split("\n"):
        if is_fading_line(line):
            return " ".join(_REMINDER.sub("", line).split()).strip()
    return None


__all__ = [
    "FADING_RULES_TEXT",
    "expand_fading_line",
    "expand_fading_lines",
    "fading_count",
    "is_fading_line",
    "unread_fading_line",
]
