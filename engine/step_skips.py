"""A static ability that skips a step of every player's turn (CR 614.10, 500.11).

"Players skip their upkeep steps." (Eon Hub.) CR 614.1b: an effect that uses
the word "skip" is a replacement effect, and CR 614.10 makes "skip [a step]"
the same as "instead of doing [it], do nothing" — so the step never begins:
nothing triggers "at the beginning of" it (CR 603.2g: a replaced event triggers
nothing), nobody receives priority in it, an ability that may be activated only
during it cannot be, and anything scheduled for it waits for the first one that
is not skipped (CR 614.10a — "until your next upkeep" outlives a skipped one).
CR 500.11: "to skip a step … is to proceed past it as though it didn't exist."

A static of the permanent, so like every derivation table here the step asks
the board's permanents' own text as it would begin (``step_skip_source``) and
there is nothing to arm or clear: a source that leaves stops skipping, and one
that arrives mid-turn skips the next such step, never one already begun
(CR 614.10's last sentence).

**The step is payload, admitted only where the step asks.** The sentence names
a step; what makes it a *working* sentence is that step's code asking this
table before it begins. The upkeep asks (``phases/upkeep_step.resolve_upkeep``,
and the web's beginning phase before it gathers any upkeep prompt,
``web/turn_steps._resolve_upkeep_step``). The untap step's spelling of the same
sentence (Stasis) is ``untap_restrictions.py``'s, which aggregates it with the
step's other restrictions; a step nobody asks here is refused rather than
claimed, so a card printing it stays unsupported instead of skipping nothing.

The readers — the step, the grammar's parse claim
(``grammar.registries.registry_for_line``), the support gate
(``derived_static_claims``) and ``scripts/parse_coverage.py`` — all ask
:func:`skipped_step_of_line`, so what is skipped and what is claimed cannot
drift.
"""

from __future__ import annotations

import re
from functools import lru_cache

#: The label the grammar's registry claim gives the line (``ast.RegistryLine``).
CLAIM = "step_skips"

#: The steps whose own code asks this table before it begins. A step joins by
#: its step asking; listing one that does not would claim a skip nothing does.
STEPS_ASKED = frozenset({"upkeep"})

#: CR 109.2's plural and its distributive twin — one rule in two printed
#: spellings, as ``untap_restrictions`` reads Stasis's.
_EVERY_PLAYER_SKIPS = re.compile(
    r"^(?:players skip their (?P<plural>[a-z]+) steps"
    r"|each player skips their (?P<single>[a-z]+) step)$"
)


def skipped_step_of_line(line: str) -> str | None:
    """The step *line* makes every player skip, when it is, in full, this
    static and the step is one whose code asks (:data:`STEPS_ASKED`)."""
    normalized = " ".join((line or "").split()).strip().lower().rstrip(".")
    match = _EVERY_PLAYER_SKIPS.match(normalized)
    if match is None:
        return None
    step = match.group("plural") or match.group("single")
    return step if step in STEPS_ASKED else None


@lru_cache(maxsize=None)
def steps_skipped_by(oracle_text: str) -> frozenset[str]:
    """Every step *oracle_text* makes every player skip. Cached on the text,
    which is immutable on a ``CardDefinition``, so the step's per-permanent scan
    costs one dict lookup a permanent."""
    if "skip" not in (oracle_text or "").lower():
        return frozenset()
    return frozenset(
        step for line in oracle_text.splitlines()
        if (step := skipped_step_of_line(line)) is not None
    )


def step_skip_source(game, step: str):
    """The first permanent on the battlefield whose static skips *step* of the
    turn about to reach it, or None when the step begins.

    "Players" names every seat, so the whole board is asked and no seat is: a
    narrower printing ("Your opponents skip …") would be a row here with the
    seat as payload, never a branch in the step. Read off ``effective_card``
    (CR 707.2, CR 612.1)."""
    for permanent in game.all_permanents():
        if step in steps_skipped_by(permanent.effective_card.oracle_text or ""):
            return permanent
    return None


__all__ = [
    "CLAIM", "STEPS_ASKED", "skipped_step_of_line", "step_skip_source",
    "steps_skipped_by",
]
