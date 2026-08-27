"""What the X in an activated ability's **cost** is, when the card defines it.

CR 601.2b: the activating player announces the value of X. A handful of cards
take that choice away by printing a definition instead -- Voodoo Doll's

    {X}{X}, {T}: This artifact deals damage equal to the number of pin counters
    on it to any target. **X is the number of pin counters on this artifact.**

-- so the cost is not a number the player picks but one the board decides.

This is the twin of ``engine/activation_restrictions.py`` and it is a table for
the same reason: the sentence reads the same on any card that prints it, so the
counter's kind and the noun are payload. It is genuinely textual, not per-card.

**Both readers read this table.** The grammar consumes the sentence
(``_parse_cost_x_definition``, beside the "Activate only ..." reader it copies)
and refuses a definition no row here implements, so a card cannot be admitted
with the clause dropped; the activation path charges the cost from the same
table. A definition consumed by one and unknown to the other is an ability whose
{X}{X} costs whatever the activator felt like announcing -- nothing, most of the
time -- which is the quiet failure this file exists to prevent.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


def _counters_on_source(game: "Game", source: "Permanent", match: re.Match) -> int:
    from .named_counters import counters_on

    return max(0, counters_on(source, match.group(1)))


#: ``(pattern, reader)``. The pattern matches the whole sentence, lowercased and
#: stripped of its full stop; the reader turns the ability's own source into the
#: number. One row today, and the noun it ends on is any permanent word, because
#: which type the card happens to be is not part of the question.
COST_X_DEFINITIONS: tuple[tuple[re.Pattern[str], Callable[..., int]], ...] = (
    (
        re.compile(
            r"^x is the number of ([a-z]+) counters on "
            r"this (?:artifact|creature|enchantment|land|permanent)$"
        ),
        _counters_on_source,
    ),
)


def cost_x_definition_readable(sentence: str) -> bool:
    """Whether a row implements this printed "X is ..." sentence.

    The grammar's gate. A sentence nothing implements leaves the line refused,
    so the card reports unsupported naming the clause rather than being admitted
    with an X nobody computes.
    """
    return _match(sentence) is not None


def cost_x_value(game: "Game", source: "Permanent", ability_line: str) -> int | None:
    """The X the ability's cost uses, or None when the card defines none.

    ``None`` is not zero: it means the player announces X the ordinary way
    (CR 601.2b), which is every ability in the pool but these.
    """
    for sentence in (ability_line or "").split("."):
        matched = _match(sentence)
        if matched is not None:
            pattern_match, reader = matched
            return reader(game, source, pattern_match)
    return None


def _match(sentence: str) -> tuple[re.Match, Callable[..., int]] | None:
    cleaned = " ".join(sentence.lower().split()).strip(" .")
    if not cleaned.startswith("x is "):
        return None
    for pattern, reader in COST_X_DEFINITIONS:
        found = pattern.match(cleaned)
        if found is not None:
            return found, reader
    return None


__all__ = [
    "COST_X_DEFINITIONS",
    "cost_x_definition_readable",
    "cost_x_value",
]
