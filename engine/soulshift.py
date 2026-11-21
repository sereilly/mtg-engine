"""Soulshift (CR 702.46), the keyword and the triggered ability it *is*.

CR 702.46a does not describe soulshift, it **defines** it: "Soulshift N" means
"When this permanent is put into a graveyard from the battlefield, you may
return target Spirit card with mana value N or less from your graveyard to your
hand." So this is the rewrite ``engine/modular.py`` made for modular, one line
out instead of two: the printed keyword line becomes the sentence the rules say
it already is, applied by ``line_rewrites.expand_ability_lines`` before any line
is classified. From there nothing downstream knows the word:

* the trigger is an ordinary ``dies`` trigger (CR 700.4: "dies" means "is put
  into a graveyard from the battlefield", the rule's own words) — a
  leaves-the-battlefield ability that looks back in time (CR 603.10a), put on
  the stack the next time a player would receive priority (CR 603.3);
* its effect is the graveyard return Gravedigger already goes through, narrowed
  by the subtype (``graveyard_subtypes``) and the mana value ceiling
  (``graveyard_mana_value``) the grammar reads off the sentence, and wrapped in
  the resolution's "you may" offer;
* "target" is a card in a graveyard, chosen as the trigger goes on the stack
  (CR 603.3d, CR 115.1d) — the death has happened by then, so the creature
  itself is in the graveyard and is a legal choice whenever it answers the
  narrowing. No Champions of Kamigawa soulshift creature can (every one's mana
  value exceeds its N: Thief of Hope is 3 with soulshift 2), but one that could
  would be offered itself, which is what the rule's own words allow. With no
  Spirit card to name the ability is removed from the stack (CR 603.3d).

**CR 702.46b** (several instances each trigger separately): two printed lines
are two sentences, two triggers; and **one line printing a run of instances**
— "Soulshift 4, soulshift 4" (Forked-Branch Garami), CR 702.1's comma-joined
keyword list — is rewritten to one rules-text line per instance, so it is two
triggers too, each choosing its own target (its 2005-02-01 ruling: "both
soulshift abilities trigger"). Its reminder text's "up to two target Spirit
cards" is not the rule; the CR's two instances are.

**N is a numeral**, as the reminder text prints it and as the grammar reads a
mana value ceiling ("mana value 3 or less"). A line the shape test admits but
the rewrite cannot read ("Soulshift X") stays as printed and
:func:`unread_soulshift_line` keeps the card unsupported naming it — fading's
and modular's shape test, wider than the reader, so a noncreature card whose
other line compiles cannot report supported with the keyword dropped.

**The word itself is still an ability the permanent has** (CR 702.46a calls it
a triggered ability), and the layer-6 seed reads it from the ingested keywords
field (``printed_characteristics``), which lists "Soulshift" for every printed
instance. No card in the pool asks "with soulshift", so no printed-line reader
is added beside it (modular has one because Arcbound Overseer asks).
"""

from __future__ import annotations

import re

#: The rules text CR 702.46a gives the keyword, quoted word for word, with N
#: written as the reminder text writes it.
SOULSHIFT_RULES_TEXT = (
    "When this permanent is put into a graveyard from the battlefield, you may "
    "return target Spirit card with mana value {count} or less from your "
    "graveyard to your hand."
)

#: "soulshift 3" as the printed line survives reminder-text removal.
_SOULSHIFT_LINE = re.compile(r"^soulshift\s+(?P<count>\d+)$", re.IGNORECASE)

#: Any line that *is* a soulshift keyword line, readable or not — "Soulshift
#: X", a bare "Soulshift". The keyword and at most one argument, and nothing
#: after, so a sentence that merely mentions the word is never mistaken for
#: the keyword line — or a comma-joined run of such instances ("Soulshift 4,
#: soulshift 4"), so a run with one unreadable member is still the gate's.
_SOULSHIFT_SHAPE = re.compile(
    r"^soulshift(?:\s+[^\s,]+)?(?:\s*,\s*soulshift(?:\s+[^\s,]+)?)*\s*\.?$",
    re.IGNORECASE,
)

_REMINDER = re.compile(r"\([^)]*\)")


def _stripped(line: str) -> str:
    return " ".join(_REMINDER.sub("", line or "").split()).strip()


def soulshift_count(line: str) -> int | None:
    """The printed N of one soulshift line, or None when *line* is not a
    soulshift line this module can rewrite."""
    match = _SOULSHIFT_LINE.match(_stripped(line).rstrip("."))
    if match is None:
        return None
    return int(match.group("count"))


def is_soulshift_line(line: str) -> bool:
    """Whether *line* is a printed soulshift keyword line, whether or not
    :func:`expand_soulshift_line` can read it."""
    return _SOULSHIFT_SHAPE.match(_stripped(line)) is not None


def soulshift_counts(line: str) -> tuple[int, ...] | None:
    """The printed N of every soulshift instance on one line — one for
    "Soulshift 3", two for "Soulshift 4, soulshift 4" — or None when *line*
    is not a line of soulshift instances this module can rewrite (every
    comma-separated item must be one, or the line is left as printed)."""
    items = _stripped(line).rstrip(".").split(",")
    counts: list[int] = []
    for item in items:
        match = _SOULSHIFT_LINE.match(item.strip())
        if match is None:
            return None
        counts.append(int(match.group("count")))
    return tuple(counts)


def expand_soulshift_line(line: str) -> str | None:
    """The CR 702.46a rules text for one printed soulshift line, or None —
    one rules-text line per instance the line prints (CR 702.46b)."""
    counts = soulshift_counts(line)
    if counts is None:
        return None
    return "\n".join(SOULSHIFT_RULES_TEXT.format(count=count) for count in counts)


def expand_soulshift_lines(oracle_text: str) -> str:
    """*oracle_text* with every soulshift keyword line rewritten to its rules
    text. Text without one is returned unchanged."""
    if not oracle_text or "oulshift" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_soulshift_line(line) or line for line in oracle_text.split("\n")
    )


def unread_soulshift_line(oracle_text: str) -> str | None:
    """A printed soulshift-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run, as ``modular.unread_modular_line`` is.
    """
    if not oracle_text or "oulshift" not in oracle_text:
        return None
    for line in oracle_text.split("\n"):
        if is_soulshift_line(line):
            return _stripped(line)
    return None


__all__ = [
    "SOULSHIFT_RULES_TEXT",
    "expand_soulshift_line",
    "expand_soulshift_lines",
    "is_soulshift_line",
    "soulshift_count",
    "soulshift_counts",
    "unread_soulshift_line",
]
