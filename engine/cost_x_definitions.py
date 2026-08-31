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


def _counters_on_source(
    game: "Game", source: "Permanent", match: re.Match, target=None
) -> int | None:
    from .named_counters import counters_on

    return max(0, counters_on(source, match.group(1)))


def _twice_target_spell_mana_value(
    game: "Game", source: "Permanent", match: re.Match, target=None
) -> int | None:
    """"X is twice the mana value of that spell." (Reflecting Mirror.)

    "That spell" is the one the ability **targets**, so the number is not on the
    board at all: it is on the stack, and only the activation knows which object
    was named. That is why every reader here takes the chosen stack object
    beside the source — a definition that could only see the permanent would
    have to answer 0, which for a cost is the difference between an ability that
    prices itself off its victim and a free one.

    ``None`` when no spell was named, and ``None`` is refused by the activation
    rather than treated as zero (CR 107.2 is about a number that *can't* be
    determined; here the ability simply has not chosen its target yet).

    The mana value is read through ``targeting.stack_object_mana_value``, so an
    {X} spell on the stack is priced at what its controller announced
    (CR 202.3b) rather than at the 0 its printed cost carries.
    """
    if target is None:
        return None
    from .targeting import stack_object_mana_value

    return 2 * stack_object_mana_value(target)


#: ``(pattern, reader)``. The pattern matches the whole sentence, lowercased and
#: stripped of its full stop; the reader turns the ability's own source into the
#: number. One row today, and the noun it ends on is any permanent word, because
#: which type the card happens to be is not part of the question.
COST_X_DEFINITIONS: tuple[tuple[re.Pattern[str], Callable[..., int]], ...] = (
    (
        # The noun a card calls itself by. An Aura is an enchantment and an
        # Equipment an artifact (CR 205.3), but the printed word is the subtype
        # — Chromatic Armor says "on this **Aura**" and reached nothing at all
        # while this alternation listed only the card types, which is the same
        # one-word gap `enter_effects.chooses_color_on_enter` had.
        re.compile(
            r"^x is the number of ([a-z]+) counters on this "
            r"(?:artifact|aura|creature|enchantment|equipment|land|permanent)$"
        ),
        _counters_on_source,
    ),
    (
        re.compile(r"^x is twice the mana value of that spell$"),
        _twice_target_spell_mana_value,
    ),
)


def cost_x_definition_readable(sentence: str) -> bool:
    """Whether a row implements this printed "X is ..." sentence.

    The grammar's gate. A sentence nothing implements leaves the line refused,
    so the card reports unsupported naming the clause rather than being admitted
    with an X nobody computes.
    """
    return _match(sentence) is not None


def cost_x_is_defined(ability_line: str) -> bool:
    """Whether the ability's own text defines X (CR 107.3c).

    Separate from :func:`cost_x_value` because the two answers are different
    questions and the activation needs both: a card that defines X and whose
    definition cannot be computed *here* must refuse, where a card that defines
    no X lets its activator announce one. Folding them into one ``None`` made
    the uncomputable case look exactly like the ordinary one — which on an {X}
    ability means free.
    """
    return any(_match(sentence) is not None for sentence in (ability_line or "").split("."))


def cost_x_value(
    game: "Game", source: "Permanent", ability_line: str, *, target=None
) -> int | None:
    """The X the ability's cost uses, or None when there is no number to give.

    ``None`` is not zero, and it now covers two cases the caller has to tell
    apart with :func:`cost_x_is_defined`: the card defines no X at all (the
    player announces it, CR 601.2b — every ability in the pool but these), or it
    defines one that this activation cannot compute.

    *target* is the object the ability targeted, for a definition that reads
    something other than the source ("twice the mana value of **that spell**").
    """
    for sentence in (ability_line or "").split("."):
        matched = _match(sentence)
        if matched is not None:
            pattern_match, reader = matched
            return reader(game, source, pattern_match, target)
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
    "cost_x_is_defined",
    "cost_x_value",
]
