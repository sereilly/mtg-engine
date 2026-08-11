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
    game: Game,
    context: OracleExecutionContext,
) -> tuple[PlayerState, int, Permanent] | None:
    """Resolve a trigger fired *on a permanent about itself* — the shape combat
    triggers use, where ``_fire_creature_attacks_triggers`` /
    ``_fire_creature_blocks_triggers`` thread the permanent's own controller and
    battlefield index through ``target``/``target_permanent_index``. Returns
    ``(controller, index, permanent)``, or ``None`` if the context no longer
    points at a live permanent (already left combat/the battlefield).

    An attack trigger is the clearest case for identity: it is put on the stack
    during declare-attackers and resolves after every other trigger above it,
    any of which may have destroyed a creature and shifted the attacker's slot.
    The index is still returned, because callers report it — but it is
    *re-derived* from the permanent the id found, never carried."""
    controller = context.target
    if controller is None:
        return None
    permanent_id = context.target_permanent_id
    if isinstance(permanent_id, int):
        found = game.permanent_by_id(permanent_id)
        if found is not None and game.controls(controller, found):
            index = game.battlefield_index_of(found)
            if index is not None:
                return controller, index, found
    idx = context.target_permanent_index
    if not isinstance(idx, int) or not (0 <= idx < len(controller.battlefield)):
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
    then: Callable[[int], None] | None = None,
    asks: bool = False,
) -> int:
    """Mark non-combat damage on a single creature and fire its "dealt damage"
    triggers if it survived.

    Destruction is not this function's job: lethal damage is a state-based
    action (CR 704.5g, regeneration replacing it per CR 701.19), checked in
    ``check_state_based_actions``. Handlers used to have to call the sweep by
    hand at nine separate sites, and any new damage effect that forgot left a
    lethally damaged creature alive.

    ``log_message`` receives the damage actually dealt, and ``then`` is anything
    further the caller would do with it. Both run *inside* the damage event, not
    after it: the event can stop to ask the affected player which effect applies
    first (CR 616.1e), and while it waits there is nothing to report. Returns
    the amount dealt, which is 0 while suspended."""

    def finish(dealt: int) -> None:
        if log_message is not None:
            game.log.append(log_message(dealt))
        if dealt > 0 and perm.damage_marked < perm.effective_toughness:
            game._fire_dealt_damage_triggers(perm)
        if then is not None:
            then(dealt)

    return game._mark_damage_on_permanent(perm, amount, source=source, then=finish, asks=asks)


def permanent_effective_colors(perm: Permanent) -> set[str]:
    """The color symbols a permanent currently has.

    Computed through the layer system, so a colour override (the laces) is an
    ordinary layer-5 continuous effect rather than a step in a precedence chain
    written out by hand — and a copy's colours arrive in layer 1 before it, as
    the copiable value CR 707.2a says they are.
    """
    return perm.effective_colors


def permanent_matches_filter(perm: Permanent, payload: dict) -> bool:
    """Whether *perm* satisfies a target-filter payload (the key vocabulary
    produced by ``engine.grammar.ast.ObjectFilter.to_payload``:
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

    def _has_type(name: str) -> bool:
        # is_creature (not the printed line) so animated lands count.
        return perm.is_creature if name == "creature" else perm.has_type(name)

    if type_filter:
        if type_filter == "artifact_or_enchantment":
            if not (perm.has_type("artifact") or perm.has_type("enchantment")):
                return False
        elif isinstance(type_filter, (list, tuple)):
            # A type union ("target artifact, creature, or land") — any match
            # qualifies.
            if not any(_has_type(name) for name in type_filter):
                return False
        elif not _has_type(type_filter):
            return False
    if subtype_filter:
        # A single subtype string, or several OR'd alternatives ("Djinn or
        # Efreet") as a list — any one matching is enough.
        #
        # has_type, not the printed type line: a land turned into a Swamp by
        # Magical Hack / Phantasmal Terrain / Evil Presence IS a Swamp under CR
        # 613 layer 4, and this function promises destroy-target resolution,
        # cast validation and the legality enumerator can never disagree about
        # what a filter means. Reading the printed line made it disagree with
        # layer 4 — the divergence is unreachable in the current pool (no card
        # here filters on a basic land subtype) but reachable the moment one
        # ships.
        subtypes = [subtype_filter] if isinstance(subtype_filter, str) else subtype_filter
        if not any(perm.has_type(s) for s in subtypes):
            return False
    if tapped_only and not perm.tapped:
        return False
    colors = permanent_effective_colors(perm)
    if color_filter and color_filter not in colors:
        return False
    if exclude_colors and any(c in colors for c in exclude_colors):
        return False
    if exclude_types and any(perm.has_type(t) for t in exclude_types):
        return False
    return True


def pick_target_permanent(
    player: PlayerState | None,
    index: int | None,
    *,
    game: Game | None = None,
    permanent_id: object = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Core "honor the chosen target, else fall back" resolution.

    0. If ``permanent_id`` still names a permanent *player* controls and it
       passes ``predicate``, that is the target. This is the stable answer: the
       id was recorded when the target was chosen (CR 601.2c) and means the same
       permanent however the battlefield has been renumbered since.
    1. Otherwise, if ``index`` is a valid index into ``player``'s battlefield and
       that permanent passes ``predicate`` (default: is a creature), return it.
    2. Otherwise scan ``fallback_players`` (default: just ``player``) for the
       first permanent passing ``predicate``. Pass ``()`` to disable fallback,
       or ``fallback_on_invalid_choice=False`` to skip the fallback only when
       the player explicitly chose an illegal index (the choice fizzles).

    Step 0 is *additive*: when the id no longer resolves — the target died, or
    changed controller — this falls through to exactly the index behaviour it
    has always had, rather than inventing a fizzle the rest of the engine is not
    yet written for. So the id can only turn a wrong answer into a right one.
    """
    if predicate is None:
        predicate = lambda p: p.is_creature
    if game is not None and isinstance(permanent_id, int) and player is not None:
        chosen = game.permanent_by_id(permanent_id)
        # Scoped to *player* on purpose: the callers pass the battlefield the
        # target was chosen from ("a creature you control", "target artifact an
        # opponent controls"), and widening that here would be a targeting
        # change wearing an identity change's clothes.
        if chosen is not None and game.controls(player, chosen) and predicate(chosen):
            return chosen
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
    game: Game,
    context: OracleExecutionContext,
    *,
    player: PlayerState | None = None,
    predicate: Callable[[Permanent], bool] | None = None,
    fallback_players: Sequence[PlayerState] | None = None,
    fallback_on_invalid_choice: bool = True,
) -> Permanent | None:
    """Resolve the permanent a spell or ability acts on — the context-based
    wrapper over :func:`pick_target_permanent` (see it for the semantics).

    Takes the game because identity is a *board* question: the id on the context
    means nothing without something to resolve it against. Every handler already
    receives the game as its first argument, so this reads the same way the
    handler signature does."""
    return pick_target_permanent(
        player if player is not None else context.target,
        context.target_permanent_index,
        game=game,
        permanent_id=context.target_permanent_id,
        predicate=predicate,
        fallback_players=fallback_players,
        fallback_on_invalid_choice=fallback_on_invalid_choice,
    )
