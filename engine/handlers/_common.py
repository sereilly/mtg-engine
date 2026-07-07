"""Shared helpers for effect handlers.

The leading underscore keeps this module out of the handler-registry import
pattern in ``engine/handlers/__init__.py`` — it registers no handlers, it only
hosts logic the registered handlers share.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Sequence

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent, PlayerState


def resolve_amount(raw: object, x_value: int | None) -> int:
    """Numeric value of a parsed amount payload; ``"x"`` resolves to the cast's
    X (never negative)."""
    return max(0, x_value or 0) if raw == "x" else int(raw)


def flip_coin(win_probability: float = 0.5) -> bool:
    """Flip a coin, returning True on a win (CR 705). Draws from the module-level
    RNG that ``run_ai_simulation`` seeds, so a given seed replays identically."""
    return random.random() < win_probability


def resolve_own_combatant(
    context: OracleExecutionContext,
) -> tuple[PlayerState, int, Permanent] | None:
    """Resolve a trigger fired *on a permanent about itself* — the shape combat
    triggers use, where ``_fire_creature_attacks_triggers`` /
    ``_fire_creature_blocks_triggers`` thread the permanent's own controller and
    battlefield index through ``target``/``target_permanent_index``. Returns
    ``(controller, index, permanent)``, or ``None`` if the context no longer
    points at a live permanent (already left combat/the battlefield)."""
    controller = context.target
    idx = context.target_permanent_index
    if controller is None or not isinstance(idx, int) or not (0 <= idx < len(controller.battlefield)):
        return None
    return controller, idx, controller.battlefield[idx]


def apply_temp_pt_boost(perm: Permanent, power: int = 0, toughness: int = 0) -> None:
    """Apply an until-end-of-turn P/T change and track it so the cleanup step
    can remove it. Thin wrapper over the single P/T write API in engine/pt.py."""
    from ..pt import add_pt_modifier

    add_pt_modifier(perm, power, toughness, until_eot=True)


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


def permanent_effective_colors(perm: Permanent) -> set[str]:
    """The color symbols a permanent currently has, honoring color overrides
    (laces) and copied colors (Clone records ``copied_colors``; Vesuvan
    Doppelganger deliberately doesn't, so its printed blue shows through)."""
    override = perm.metadata.get("color_override")
    if override:
        return {override}
    copied_colors = perm.metadata.get("copied_colors")
    if copied_colors is not None:
        return set(copied_colors)
    return set(perm.card.colors)


def permanent_matches_filter(perm: Permanent, payload: dict) -> bool:
    """Whether *perm* satisfies a target-filter payload (the key vocabulary
    produced by ``engine.parsing.common.TargetFilter.to_payload``:
    type/subtype/color filters, tapped_only, exclusions).

    Uses has_type/is_creature/effective colors so copies keep all their types
    (a Copy Artifact copy is an Artifact Enchantment), animated lands count as
    creatures, and color overrides are honored. Shared by destroy-target
    resolution, cast validation, and the legality enumerator so they can never
    disagree about what a filter means.
    """
    type_filter = payload.get("type_filter")
    subtype_filter = payload.get("subtype_filter")
    color_filter = payload.get("color_filter")
    tapped_only = payload.get("tapped_only", False)
    exclude_colors = payload.get("exclude_colors") or []
    exclude_types = payload.get("exclude_types") or []

    # Pyramids: "target Aura attached to a land" — only Auras whose enchanted
    # permanent is currently a land qualify.
    if payload.get("attached_to_land"):
        attached = perm.metadata.get("attached_to")
        if attached is None or getattr(getattr(attached, "card", None), "primary_type", "") != "land":
            return False

    type_line = perm.effective_card.type_line.lower()
    if type_filter:
        if type_filter == "artifact_or_enchantment":
            if not (perm.has_type("artifact") or perm.has_type("enchantment")):
                return False
        elif type_filter == "creature":
            if not perm.is_creature:
                return False
        elif type_filter not in type_line:
            return False
    if subtype_filter:
        # A single subtype string, or several OR'd alternatives ("Djinn or
        # Efreet") as a list — any one matching is enough.
        subtypes = [subtype_filter] if isinstance(subtype_filter, str) else subtype_filter
        if not any(s in type_line for s in subtypes):
            return False
    if tapped_only and not perm.tapped:
        return False
    colors = permanent_effective_colors(perm)
    if color_filter and color_filter not in colors:
        return False
    if exclude_colors and any(c in colors for c in exclude_colors):
        return False
    if exclude_types and any(t in type_line for t in exclude_types):
        return False
    return True


def pick_target_permanent(
    player: PlayerState | None,
    index: int | None,
    *,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Core "honor the chosen battlefield index, else fall back" resolution.

    1. If ``index`` is a valid index into ``player``'s battlefield and that
       permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    explicit = isinstance(index, int)
    if explicit and player is not None and 0 <= index < len(player.battlefield):
        candidate = player.battlefield[index]
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


def resolve_target_permanent(
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Resolve the permanent a spell or ability acts on — the context-based
    wrapper over :func:`pick_target_permanent` (see it for the semantics)."""
    return pick_target_permanent(
        player if player is not None else context.target,
        context.target_permanent_index,
        predicate=predicate,
        fallback_players=fallback_players,
        fallback_on_invalid_choice=fallback_on_invalid_choice,
    )
