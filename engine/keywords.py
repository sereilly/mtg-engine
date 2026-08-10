"""Single write API for keyword abilities (CR 613 layer 6).

Granting and removing an ability share one layer, so which one wins is decided
by **timestamp**, not by which code path happened to run last (CR 613.9's
worked example is exactly this: an Aura granting flying and one removing it,
resolved by whichever is newer). Recording each grant and removal in order is
what makes that answerable.

The engine previously stored one metadata flag per keyword per direction —
``gains_flying``, ``gains_flying_until_eot``, ``loses_flying``,
``gains_trample_until_eot`` and so on — read by an if-chain that checked
removals first and so made removal always win. That is a rule the rules do not
have, and it needed a new flag and a new branch for every keyword.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .continuous import next_timestamp

if TYPE_CHECKING:
    from .models import Permanent

# Key under which a permanent's ordered grants/removals live.
ABILITY_EFFECTS = "ability_effects"

# Key under which *derived* grants live — abilities a permanent has because of
# something else on the battlefield right now (a lord's "other Goblins have
# mountainwalk"). They carry no timestamp of their own because they are not
# recorded: the channel is cleared and rebuilt from the board on every
# continuous-effects recompute, exactly like the derived layer-7c P/T channels.
#
# Recording them through :func:`grant_keyword` instead would append one entry
# per recompute forever, and CR 611.3a means the recompute runs constantly.
DERIVED_GRANTS = "derived_ability_grants"


def _record(perm: Permanent, keyword: str, *, grant: bool, until_eot: bool) -> None:
    effects = perm.metadata.setdefault(ABILITY_EFFECTS, [])
    effects.append(
        {
            "keyword": keyword.lower(),
            "grant": grant,
            "until_eot": until_eot,
            "timestamp": next_timestamp(),
        }
    )


def grant_keyword(perm: Permanent, keyword: str, *, until_eot: bool = False) -> None:
    """Layer 6: give *perm* a keyword ability from now (613.7b)."""
    _record(perm, keyword, grant=True, until_eot=until_eot)


def remove_keyword(perm: Permanent, keyword: str, *, until_eot: bool = False) -> None:
    """Layer 6: take a keyword ability away. Whether this beats a grant is
    decided by timestamp, so a later grant restores the ability."""
    _record(perm, keyword, grant=False, until_eot=until_eot)


def clear_until_eot_keywords(perm: Permanent) -> None:
    """Drop the until-end-of-turn grants and removals during cleanup."""
    effects = perm.metadata.get(ABILITY_EFFECTS)
    if not effects:
        return
    remaining = [entry for entry in effects if not entry.get("until_eot")]
    if remaining:
        perm.metadata[ABILITY_EFFECTS] = remaining
    else:
        perm.metadata.pop(ABILITY_EFFECTS, None)


def ability_effects(perm: Permanent) -> list[dict]:
    """The recorded grants and removals, oldest first."""
    return list(perm.metadata.get(ABILITY_EFFECTS) or ())


def clear_derived_grants(perm: Permanent) -> None:
    """Drop the grants derived from the current board (CR 611.3b).

    Called by the same function that rebuilds them. Splitting the clear from the
    rebuild is how a derived channel turns into an accumulating one.
    """
    perm.metadata.pop(DERIVED_GRANTS, None)


def add_derived_grant(perm: Permanent, keyword: str) -> None:
    """Layer 6: *perm* has *keyword* for as long as the source keeps granting it."""
    granted = perm.metadata.setdefault(DERIVED_GRANTS, [])
    lowered = keyword.lower()
    if lowered not in granted:
        granted.append(lowered)


def derived_grants(perm: Permanent) -> tuple[str, ...]:
    """The abilities *perm* currently has from a board-wide source."""
    return tuple(perm.metadata.get(DERIVED_GRANTS) or ())


__all__ = [
    "ABILITY_EFFECTS", "DERIVED_GRANTS", "ability_effects", "add_derived_grant",
    "clear_derived_grants", "clear_until_eot_keywords", "derived_grants",
    "grant_keyword", "remove_keyword",
]
