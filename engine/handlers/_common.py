"""Shared helpers for effect handlers.

The leading underscore keeps this module out of the handler-registry import
pattern in ``engine/handlers/__init__.py`` — it registers no handlers, it only
hosts logic the registered handlers share.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent, PlayerState


def resolve_amount(raw: object, x_value: int | None) -> int:
    """Numeric value of a parsed amount payload; ``"x"`` resolves to the cast's
    X (never negative)."""
    return max(0, x_value or 0) if raw == "x" else int(raw)


def apply_temp_pt_boost(perm: Permanent, power: int = 0, toughness: int = 0) -> None:
    """Apply an until-end-of-turn P/T change and track it so the cleanup step
    can remove it. Both metadata keys are written even for a 0 delta."""
    perm.power_bonus += power
    perm.toughness_bonus += toughness
    perm.metadata["temporary_power_bonus_until_eot"] = int(
        perm.metadata.get("temporary_power_bonus_until_eot", 0)
    ) + power
    perm.metadata["temporary_toughness_bonus_until_eot"] = int(
        perm.metadata.get("temporary_toughness_bonus_until_eot", 0)
    ) + toughness


def apply_damage_to_creature(
    game: Game,
    perm: Permanent,
    amount: int,
    source,
    log_message: Callable[[int], str] | None = None,
) -> int:
    """Mark non-combat damage on a single creature, then either destroy it as a
    state-based action (which regeneration shields can replace, CR 704.5g /
    701.15) or fire its "dealt damage" triggers. ``log_message`` receives the
    damage actually dealt and is logged before the destruction check, so death
    logs follow the damage log. Returns the damage dealt after prevention."""
    dealt = game._mark_damage_on_permanent(perm, amount, source=source)
    if log_message is not None:
        game.log.append(log_message(dealt))
    if perm.damage_marked >= perm.effective_toughness:
        game._destroy_marked_creatures()
    elif dealt > 0:
        game._fire_dealt_damage_triggers(perm)
    return dealt


def resolve_target_permanent(
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Resolve the permanent a spell or ability acts on.

    1. If ``context.target_permanent_index`` is a valid index into ``player``'s
       battlefield (default: the context target's) and that permanent passes
       ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if player is None:
        player = context.target
    idx = context.target_permanent_index
    explicit = isinstance(idx, int)
    if explicit and player is not None and 0 <= idx < len(player.battlefield):
        candidate = player.battlefield[idx]
        if predicate(candidate):
            return candidate
    if explicit and not fallback_on_invalid_choice:
        return None
    if fallback_players is None:
        fallback_players = (player,) if player is not None else ()
    for scan in fallback_players:
        found = next((p for p in scan.battlefield if predicate(p)), None)
        if found is not None:
            return found
    return None
