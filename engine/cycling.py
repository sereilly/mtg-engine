"""Cycling (CR 702.29), the keyword the rules define as a rewrite.

CR 702.29a: *"Cycling is an activated ability that functions only while the
card with cycling is in a player's hand. 'Cycling [cost]' means '[Cost],
Discard this card: Draw a card.'"*

So this module is ``engine/equipment.py``'s equip half one keyword over, and
for the identical reason: a keyword whose definition **is** a sentence gets one
reader — the rewrite — rather than a second path beside every seam an activated
ability already passes through. :func:`expand_cycling_lines` turns the printed
line into that sentence before the compiler classifies anything, and from there
the grammar reads the effect, ``engine/oracle.py``'s cost parser reads the
"Discard this card" cost, ``engine/activation_zones.py`` reads CR 113.6j off
that cost, and the web layer offers it like any other hand-activatable ability.
Nothing downstream knows the word.

**The half that is not the rewrite is CR 702.29b**, and it is the half a naive
expansion gets wrong: *"Although the cycling ability can be activated only if
the card is in a player's hand, it continues to exist while the object is on
the battlefield and in all other zones."* Six of Urza's Saga's cycling cards
are lands and eight are creatures, so after this rewrite every one of them is a
permanent carrying an activated ability it must not be able to activate. That
is not enforced here — it is CR 113.6j ("an activated ability that has a cost
that can't be paid while the object is on the battlefield functions from any
zone in which its cost can be paid"), which is a rule about *costs* and not
about this keyword, and it lives in ``engine/activation_zones.py`` where every
activation path asks it.

**Typecycling (CR 702.29e) is refused, loudly.** "Plainscycling {2}" means a
library search rather than a draw, and CR 702.29f makes it a cycling ability
for every purpose — so a card printing one must not be quietly read as though
it printed the draw, and must not slip past as an unclaimed line either.
:func:`is_cycling_line` is deliberately the *wide* shape, exactly as
``equipment.is_equip_line`` is: a variant the expansion cannot read reaches the
support gate in ``engine/oracle.py`` and is refused naming the line.
"""

from __future__ import annotations

import re

#: "Cycling {2}", "Cycling {1}{U}". Matched on the printed line with its
#: reminder text removed, case-insensitively; the cost is taken from the
#: printed line so a coloured pip keeps its letter.
_CYCLING_LINE = re.compile(
    r"^cycling\s+(?P<cost>(?:\{[^{}]+\})+)$", re.IGNORECASE
)
_REMINDER = re.compile(r"\([^)]*\)")
#: Any line that *is* a cycling keyword line, readable or not — CR 702.29e's
#: "Plainscycling {2}" and "Basic landcycling {1}{G}" included. The wider shape
#: is what the support gate asks, so a variant the expansion refuses is reported
#: as an unimplemented cycling line rather than falling through to a gate that
#: never heard of the keyword. `\w*cycling` and not `cycling`, because
#: typecycling's type name is glued to the word.
_CYCLING_SHAPE = re.compile(r"^[a-z ]*cycling\b", re.IGNORECASE)

#: The rules text CR 702.29a gives the keyword.
CYCLING_RULES_TEXT = "{cost}, Discard this card: Draw a card."


def cycling_cost(line: str) -> str | None:
    """The cost of a printed cycling keyword line, or None.

    None for a typecycling line (CR 702.29e) — its cost is readable but its
    *effect* is a library search this rewrite does not produce, and returning
    the cost would rewrite the card into one that draws.
    """
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip().rstrip(".")
    match = _CYCLING_LINE.match(stripped)
    return match.group("cost") if match is not None else None


def is_cycling_line(line: str) -> bool:
    """Whether *line* is a printed cycling keyword line, whether or not
    :func:`expand_cycling_line` can read it (CR 702.29e's typecycling is one
    it cannot)."""
    stripped = " ".join(_REMINDER.sub("", line or "").split()).strip()
    if not stripped or not _CYCLING_SHAPE.match(stripped):
        return False
    # The shape is a *keyword line*: the word (with an optional type glued to
    # its front) and a cost, and nothing else. Fluctuator's "Cycling abilities
    # you activate cost {2} less to activate" begins with the word and is a
    # static ability about other cards' cycling, not a cycling line — reading it
    # as one would refuse a card whose ability is a cost modifier.
    return bool(re.fullmatch(r"[a-z ]*cycling\s+(?:\{[^{}]+\})+\.?", stripped, re.IGNORECASE))


def expand_cycling_line(line: str) -> str | None:
    """The CR 702.29a rules text for one printed cycling line, or None."""
    cost = cycling_cost(line)
    return None if cost is None else CYCLING_RULES_TEXT.format(cost=cost)


def expand_cycling_lines(oracle_text: str) -> str:
    """*oracle_text* with every cycling keyword line rewritten to its rules text.

    Text without a cycling line is returned unchanged, so applying this to every
    card costs nothing but a scan. Applied by the compiler before any line is
    classified — beside ``expand_equip_lines`` and for the same reason: what the
    compiler reads and what every other reader of a card's lines (targeting,
    parse coverage, hook reliance) reads must be one text.
    """
    if not oracle_text or "ycling" not in oracle_text:
        return oracle_text
    return "\n".join(
        expand_cycling_line(line) or line for line in oracle_text.split("\n")
    )


def unread_cycling_line(oracle_text: str) -> str | None:
    """A printed cycling-shaped line this module cannot rewrite, or None.

    The support gate's question, asked of the text **after** the expansion has
    run: a line still reading as cycling by then is one :func:`cycling_cost`
    refused, and the card is unsupported naming it. Without this a typecycling
    instant would report supported off its *other* line and silently drop the
    keyword — the population a refusal census cannot reach, which is exactly
    what the fourteen already-"supported" cycling cards in Urza's Saga were
    before this module existed.
    """
    for line in (oracle_text or "").split("\n"):
        if is_cycling_line(line):
            return " ".join(_REMINDER.sub("", line).split()).strip()
    return None


__all__ = [
    "CYCLING_RULES_TEXT",
    "cycling_cost",
    "expand_cycling_line",
    "expand_cycling_lines",
    "is_cycling_line",
    "unread_cycling_line",
]
