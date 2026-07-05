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
- 7c (modify by +X/+Y): ``power_bonus`` / ``toughness_bonus`` attributes,
  plus the ``static_buff_*`` metadata recomputed by lord passes and the
  conditional ``attacking_buff_*`` channel. Until-end-of-turn boosts are
  additionally tracked in ``temporary_*_bonus_until_eot`` metadata so the
  cleanup step can subtract them.
- 7d (switch): ``pt_switched`` metadata flag (cleared at cleanup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Permanent


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


def clear_base_pt(perm: Permanent, *, until_eot: bool = False) -> None:
    """Remove a 7a/7b base override, restoring the printed base."""
    if until_eot:
        perm.metadata.pop("absolute_power_until_eot", None)
        perm.metadata.pop("absolute_toughness_until_eot", None)
    else:
        perm.metadata.pop("absolute_power", None)
        perm.metadata.pop("absolute_toughness", None)


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
