"""Single write API for power/toughness channels (scoped CR 613).

``Permanent.effective_power`` / ``effective_toughness`` (engine/models.py)
read a fixed set of channels in CR-613 sublayer order. All WRITES must go
through this module so the channel vocabulary stays in one place; if a future
set ever needs per-effect timestamps or dependency ordering, only these
helpers change.

Channel → sublayer mapping:

- 7a (characteristic-defining) and 7b (set to N): ``absolute_power`` /
  ``absolute_toughness`` metadata; the ``_until_eot`` variants take priority
  and are cleared in the cleanup step (see ``_EOT_METADATA_KEYS`` in
  engine/mixins/_constants.py). Competing setters resolve last-write-wins on
  the metadata key, which IS timestamp order for stack-resolved effects.
- 7c (modify by +X/+Y) splits by *lifetime*, which is what keeps it correct:

  - ``power_bonus`` / ``toughness_bonus`` are **persistent** — counters and
    one-shot modifications that stay until something removes them.
    Until-end-of-turn boosts are additionally tracked in
    ``temporary_*_bonus_until_eot`` metadata so the cleanup step can subtract
    exactly what it added.
  - ``static_buff_*`` (lord passes) and ``derived_buff_*`` (conditional
    "as long as …" bonuses, Aspect of Wolf) are **derived**: cleared and
    rebuilt from the current board on every continuous-effects recompute.
    Nothing records what it contributed, because nothing has to take it back.

  A continuous effect must never write to the persistent channel. Doing so
  requires it to subtract itself later, and any mismatch compounds — CR 611.3a
  means the recompute runs constantly. Aspect of Wolf shipped that bug.
  Each derived channel is cleared by the same function that rebuilds it.
- 7d (switch): ``pt_switched`` metadata flag (cleared at cleanup).
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Permanent


#: The scheduled revert of a persistent base-P/T write ("until the end of your
#: next upkeep", Halfdane): ``{"seat": <whose upkeep>, "turn": <game.turn when
#: written>}``. The draw step — the moment the upkeep has just ended — clears
#: the base override of a permanent whose stamp names that seat and an
#: *earlier* turn; a stamp written this very upkeep survives to the next one,
#: which is how the re-applying trigger keeps its own effect alive. Named here
#: because this module owns the channel vocabulary: any later persistent write
#: supersedes the scheduled revert (last-write-wins is this engine's 7b
#: timestamp order), so :func:`set_base_pt` is what removes the stamp.
BASE_PT_REVERT_KEY = "base_pt_reverts_after_upkeep"


def set_base_pt(
    perm: Permanent, power: int | None, toughness: int | None, *, until_eot: bool = False
) -> None:
    """Layer 7a/7b: set base power and/or toughness ("becomes 0/2", CDAs,
    animation). Pass None for a stat to leave it untouched — Singing Tree's
    "has base power 0 until end of turn" sets only power, letting toughness
    keep tracking whatever else applies. 7c modifications still apply on top
    of the new base."""
    suffix = "_until_eot" if until_eot else ""
    if power is not None:
        perm.metadata[f"absolute_power{suffix}"] = int(power)
    if toughness is not None:
        perm.metadata[f"absolute_toughness{suffix}"] = int(toughness)
    if not until_eot:
        # A newer persistent write supersedes a scheduled revert: reverting
        # would clear the metadata key the newer effect just wrote, taking the
        # newer effect with it. The caller that wants a revert re-stamps after
        # writing (engine/handlers/base_pt.py).
        perm.metadata.pop(BASE_PT_REVERT_KEY, None)


def clear_base_pt(perm: Permanent, *, until_eot: bool = False) -> None:
    """Remove a 7a/7b base override, restoring the printed base."""
    if until_eot:
        perm.metadata.pop("absolute_power_until_eot", None)
        perm.metadata.pop("absolute_toughness_until_eot", None)
    else:
        perm.metadata.pop("absolute_power", None)
        perm.metadata.pop("absolute_toughness", None)
        perm.metadata.pop(BASE_PT_REVERT_KEY, None)


def add_pt_modifier(perm: Permanent, power: int = 0, toughness: int = 0, *, until_eot: bool = False) -> None:
    """Layer 7c: add a +X/+Y modification. With ``until_eot`` the delta is
    tracked in metadata so the cleanup step can remove it; both metadata keys
    are written even for a 0 delta (cleanup relies on their presence)."""
    perm.power_bonus += power
    perm.toughness_bonus += toughness
    if until_eot:
        perm.metadata["temporary_power_bonus_until_eot"] = int(
            perm.metadata.get("temporary_power_bonus_until_eot", 0)
        ) + power
        perm.metadata["temporary_toughness_bonus_until_eot"] = int(
            perm.metadata.get("temporary_toughness_bonus_until_eot", 0)
        ) + toughness


def switch_pt(perm: Permanent) -> None:
    """Layer 7d: switch power and toughness until end of turn (the flag is
    cleared at cleanup). Two switches cancel out."""
    perm.metadata["pt_switched"] = not perm.metadata.get("pt_switched", False)


_PT_COUNTER = re.compile(r"^([+-])(\d+)/([+-])(\d+)$")

# The three kinds with a metadata key the engine already reads, kept as they
# are spelled. CR 704.5q's cancellation sweep, the web card face and "a
# creature with a +1/+1 counter on it" were written against the first two;
# Clockwork Beast's cap ("can't cause the total number of +1/+0 counters … to
# be greater than seven") reads the third, and a second spelling would make the
# cap count a different pile from the one the placement fills.
#
# Every other CR 122.1a counter is a counter like any other and lives in the
# named-counter store under the name CR 122.1 makes its identity — a "-0/-2"
# counter and a "-1/-1" counter are not interchangeable, and two -0/-2 counters
# are.
_PT_COUNTER_KEYS = {
    "+1/+1": "plus_counters",
    "-1/-1": "minus_counters",
    "+1/+0": "plus_1_0_counters",
}


def pt_counter_deltas(kind: str) -> tuple[int, int] | None:
    """CR 122.1a: what one *kind* counter adds to power and toughness, or None
    if *kind* is not a P/T counter at all.

    Derived from the name rather than looked up in a list of the kinds the pool
    happens to print. The rule is written as "+X/+Y … similarly, -X/-Y", so the
    numbers are the counter's *name* and a table of them would be a list of the
    cards printed so far — which is exactly what it was: "-0/-2" (Spirit
    Shackle) and "-0/-1" (Takklemaggot, Lesser Werewolf) were rejected as
    unsupported counter kinds while "-1/-1" beside them was admitted.
    """
    match = _PT_COUNTER.match(kind)
    if match is None:
        return None
    power_sign, power, toughness_sign, toughness = match.groups()
    return (
        int(power) * (-1 if power_sign == "-" else 1),
        int(toughness) * (-1 if toughness_sign == "-" else 1),
    )


def pt_counter_key(kind: str) -> str:
    """The metadata key *kind*'s counters are recorded under.

    Everything outside the three established keys falls through to
    ``engine/named_counters.py``'s spelling rather than a second one of this
    module's own — that file's whole opening argument is that two stores for
    one concept is how a card ends up putting counters somewhere nothing reads.
    """
    from .named_counters import counters_key

    return _PT_COUNTER_KEYS.get(kind) or counters_key(kind)


def add_pt_counters(perm: Permanent, kind: str, count: int = 1) -> None:
    """Place *count* CR 122.1a counters of *kind*: the persistent P/T channel
    plus the counter record.

    The record is not cosmetic. The 704.5q sweep cancels +1/+1 against -1/-1,
    the web layer renders counters on the card face, and "target creature with
    a +1/+1 counter on it" (Tempered Veteran) is a question about *counters*,
    which a bare P/T bonus cannot answer — a Giant Growth also writes
    power_bonus, and reading the bonus as the counter would let it qualify.
    Unstable Mutation is the other half of that: its upkeep pass wrote the two
    bonuses and no record at all, under a comment saying "the counters are real
    -1/-1 counters … 704.5q applies" — which it could not, because nothing had
    put a counter anywhere for the sweep to find.

    Every handler that places a P/T counter goes through here, so the two
    channels cannot drift.
    """
    deltas = pt_counter_deltas(kind)
    if deltas is None:
        raise ValueError(f"{kind!r} is not a power/toughness counter")
    if count <= 0:
        return
    power, toughness = deltas
    add_pt_modifier(perm, power * count, toughness * count)
    key = pt_counter_key(kind)
    perm.metadata[key] = int(perm.metadata.get(key, 0)) + count


def add_plus1_counters(perm: Permanent, count: int = 1) -> None:
    """Place *count* +1/+1 counters — :func:`add_pt_counters` with the one kind
    most of the pool prints, kept as its own name because the seam above it
    (``Game.place_plus1_counters``) and its CR 614 replacements are about that
    kind specifically."""
    add_pt_counters(perm, "+1/+1", count)


def remove_plus1_counters(perm: Permanent, count: int = 1) -> int:
    """Remove up to *count* +1/+1 counters — both channels, floored at zero.

    Returns how many actually came off, because a shield sized by counters
    (Rock Hydra's automatic prevention) may only prevent that much: asking for
    five off a creature holding two removes two, and the caller deals the
    difference.
    """
    have = int(perm.metadata.get("plus_counters", 0))
    removed = min(max(count, 0), have)
    if removed <= 0:
        return 0
    add_pt_modifier(perm, -removed, -removed)
    perm.metadata["plus_counters"] = have - removed
    return removed
