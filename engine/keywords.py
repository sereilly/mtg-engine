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


__all__ = [
    "ABILITY_EFFECTS", "ability_effects", "clear_until_eot_keywords",
    "grant_keyword", "remove_keyword",
]
