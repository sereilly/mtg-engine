from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..static_bonuses import singular_land_type
from ..models import Permanent, PlayerState
from ._common import permanent_matches_filter
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("volcanic_eruption")
def volcanic_eruption(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Destroy X target Mountains, then deal damage to each creature and each
    player equal to the number of Mountains put into a graveyard this way."""
    target = context.target
    card = context.card
    x_value = max(0, context.x_value or 0)

    def _is_mountain(perm: Permanent) -> bool:
        return perm.card.primary_type == "land" and perm.has_type("mountain")

    # Resolve the chosen Mountains. The UI supplies either a cross-seat divided
    # list (Mountains may be chosen on both battlefields at once) or explicit
    # indices on the target player's battlefield; fall back to the first X
    # Mountains anywhere for AI/no explicit choice.
    chosen: list[tuple[PlayerState, Permanent]] = []
    divided = context.choices.get("divided_targets")
    if divided:
        for seat, index in divided:
            if index is None or not (0 <= seat < len(game.players)):
                continue
            player = game.players[seat]
            if 0 <= index < len(player.battlefield) and _is_mountain(player.battlefield[index]):
                chosen.append((player, player.battlefield[index]))
    raw_idx = context.target_permanent_index
    indices = raw_idx if isinstance(raw_idx, list) else ([raw_idx] if isinstance(raw_idx, int) else [])
    if not chosen:
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
                perm = target.battlefield[idx]
                if _is_mountain(perm):
                    chosen.append((target, perm))
    if not chosen:
        for seat, perm in game.permanents_with_controller():
            if _is_mountain(perm) and len(chosen) < x_value:
                chosen.append((game.players[seat], perm))

    chosen = chosen[:x_value]
    destroyed = 0
    for owner, perm in chosen:
        if game.controls(owner, perm) and not game._is_indestructible(perm):
            # By identity. ``list.remove`` compares by value, and :class:`Permanent`
            # is a dataclass with generated ``__eq__`` — two Mountains that entered
            # on the same turn and are both untapped are ``==``, so ``remove``
            # would take whichever comes first rather than the one that was
            # chosen. (Same bug the control seam documents for ``in``.)
            game.remove_from_battlefield(perm)
            game._permanent_to_graveyard(owner, perm)
            game._process_land_dies(game.players.index(owner))
            destroyed += 1
    game.log.append(f"{card.name} destroyed {destroyed} Mountain(s)")

    if destroyed > 0:
        for player in game.players:
            game._deal_damage_to_player(player, destroyed, source=card)
        for player in game.players:
            for perm in list(player.battlefield):
                if perm.is_creature:
                    game._mark_damage_on_permanent(perm, destroyed, source=card)
    game.log.append(f"{card.name} dealt {destroyed} damage to each creature and each player")
    return True, "resolved"


# "Destroy all <types>" — one sweep, parameterised by the types it names and
# whether regeneration may replace the destruction.
#
# These were four handlers with the same three lines of body, differing only in
# those two values, and adding "destroy all artifacts" (Shatterstorm) would have
# made a fifth. The kinds stay distinct because the compiler, the grammar's
# lowering table and the behaviour snapshots all key on them; only the bodies
# are shared.
#
# Types are read through has_type/is_creature (CR 613 layer 4), so a Copy
# Artifact copy counts as both its types and an animated land counts as a
# creature.
_SWEEP_TYPES: dict[str, tuple[tuple[str, ...], bool]] = {
    # kind -> (types any of which qualifies, regeneration allowed)
    "destroy_all_creatures": (("creature",), True),
    "destroy_all_artifacts": (("artifact",), True),
    "destroy_all_enchantments": (("enchantment",), False),
    "destroy_all_lands": (("land",), False),
    "destroy_all_artifacts_creatures_enchantments": (
        ("artifact", "creature", "enchantment"),
        True,
    ),
}


def _sweep_by_type(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    types, regeneration_allowed = _SWEEP_TYPES[instruction.kind]
    # "They can't be regenerated" on a card whose family normally allows it.
    if instruction.payload.get("bypass_regeneration"):
        regeneration_allowed = False

    def _matches(perm: Permanent) -> bool:
        return any(
            perm.is_creature if name == "creature" else perm.has_type(name)
            for name in types
        )

    for player in game.players:
        game._destroy_swept_permanents(
            player, _matches, allow_regeneration=regeneration_allowed
        )
    game.log.append(f"All {', '.join(types)}s were destroyed")
    return True, "resolved"


for _kind in _SWEEP_TYPES:
    effect_handler(_kind)(_sweep_by_type)


@effect_handler("destroy_creatures_in_combat_with_source")
def destroy_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Abu Ja'far: "When this creature dies, destroy all creatures blocking or
    blocked by it. They can't be regenerated."

    The source is already in the graveyard by the time this resolves, so the
    victims are captured at fire time (CR 603.10 last-known information) and
    passed in ``trigger_context["combat_opponents"]``. Each is destroyed only
    if it is still on a battlefield — one that died to combat damage in the
    same event is simply skipped."""
    bypass_regen = instruction.payload.get("bypass_regeneration", False)
    victims = (context.trigger_context or {}).get("combat_opponents")
    if victims is None and context.source_permanent is not None:
        # No capture (an ability invoked outside the death trigger): fall back
        # to whatever combat relationship the source still has.
        victims = game.creatures_in_combat_with(context.source_permanent)
    victims = list(victims or ())
    destroyed_names: list[str] = []
    for player in game.players:
        destroyed = game._destroy_swept_permanents(
            player,
            lambda p: any(p is victim for victim in victims),
            allow_regeneration=not bypass_regen,
        )
        destroyed_names.extend(perm.card.name for perm in destroyed)
    if destroyed_names:
        game.log.append(
            f"{context.card.name} destroyed {', '.join(destroyed_names)} "
            "(blocking or blocked by it)"
        )
    else:
        game.log.append(f"{context.card.name}: no creatures were blocking or blocked by it")
    return True, "resolved"


@effect_handler("destroy_all_matching")
def destroy_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy all Equipment attached to that creature." (Turn to Slag.)

    A sweep over a filter rather than over a card type, so one handler covers
    every narrowing the matcher can test — where the per-scope kinds beside it
    each name one scope.

    ``attached_to`` is resolved **here** rather than by the matcher, for the
    reason the ``controls`` condition resolves "another" here: what an Equipment
    is attached to is a relation, and ``permanent_matches_filter`` answers about
    a permanent alone.

    "That creature" is the spell's own target, and it is still on the
    battlefield: CR 608.2b would have stopped the spell resolving at all if the
    target had become illegal, and CR 704.3 checks state-based actions only when
    a player would receive priority — so a creature this same spell has just
    dealt lethal damage to is *there*, wearing its Equipment, and both are
    destroyed. The host resolving to nothing is the case where it left in
    response to something else, and then there is nothing attached to destroy.
    """
    filters = {
        key: value for key, value in instruction.payload.items()
        if key not in ("attached_to", "bypass_regeneration", "targets")
    }
    attached_to = instruction.payload.get("attached_to")
    host = None
    if attached_to == "target":
        host = game.permanent_by_id(context.target_permanent_id)
        if host is None:
            game.log.append(
                f"{context.card.name}: nothing is attached to a creature that is gone"
            )
            return True, "resolved"
    matched = [
        perm for perm in game.all_permanents()
        if permanent_matches_filter(perm, filters)
        and (host is None or perm.metadata.get("attached_to") is host)
    ]
    if not matched:
        game.log.append(f"{context.card.name}: nothing to destroy")
        return True, "resolved"
    for perm in matched:
        seat = game.controller_index_of(perm)
        if seat is None:
            continue
        game._destroy_swept_permanents(
            game.players[seat],
            lambda candidate, target=perm: candidate is target,
            allow_regeneration=not instruction.payload.get("bypass_regeneration"),
        )
    game.log.append(
        f"{context.card.name} destroyed " + ", ".join(p.card.name for p in matched)
    )
    return True, "resolved"


@effect_handler("destroy_all_lands_of_type")
def destroy_all_lands_of_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # "Destroy all Islands" arrives plural; "Destroy all Plains" does not,
    # because Plains is spelled the same either way. Stripping a trailing "s"
    # unconditionally turned it into "plain", which no land has ever been — the
    # old substring match hid that ("plain" is a substring of "plains"), and
    # asking the layer system for an exact subtype does not.
    land_type = singular_land_type(str(instruction.payload.get("land_type", "")))

    def _matches(perm: Permanent) -> bool:
        if perm.card.primary_type != "land":
            return False
        # has_type, so CR 305.7 is applied in one place: a land whose subtype
        # was set REPLACES its printed types, and asking the layer system is the
        # only way every reader agrees about that.
        return perm.has_type(land_type)

    for player in game.players:
        game._destroy_swept_permanents(player, _matches, allow_regeneration=False)
    game.log.append(f"All {land_type}s were destroyed")
    return True, "resolved"


@effect_handler("destroy_target_permanent")
def destroy_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    # A later step of the same resolution may read the victim's controller
    # ("Destroy target creature. Its controller loses 2 life." — Liliana,
    # Death Mage), and by then the permanent is gone — record it now
    # (CR 608.2h, last-known information).
    if isinstance(context.target_permanent_index, int):
        victim = game.chosen_permanent(
            target, context.target_permanent_index, context.target_permanent_id
        )
        if victim is not None:
            seat = game.controller_index_of(victim)
            if seat is not None:
                context.results["last_target_controller_index"] = seat
    destroyed = game._destroy_target_permanent(
        target,
        type_filter=instruction.payload.get("type_filter"),
        color_filter=instruction.payload.get("color_filter"),
        target_permanent_index=context.target_permanent_index,
        exclude_colors=instruction.payload.get("exclude_colors"),
        exclude_types=instruction.payload.get("exclude_types"),
        bypass_regeneration=instruction.payload.get("bypass_regeneration", False),
        subtype_filter=instruction.payload.get("subtype_filter"),
        tapped_only=instruction.payload.get("tapped_only", False),
        attached_to_land=instruction.payload.get("attached_to_land", False),
    )
    if destroyed:
        if source_permanent is not None:
            game.log.append(f"{card.name} destroyed {destroyed.name}")
        else:
            game.log.append(f"Destroyed {destroyed.name}")
    else:
        game.log.append("No valid target permanent found")
    return True, "resolved"


@effect_handler("chaos_orb_flip")
def chaos_orb_flip(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    source_permanent = context.source_permanent
    # Collect all permanents from all players except Chaos Orb itself
    candidates: list[tuple[PlayerState, Permanent]] = [
        (game.players[seat], perm)
        for seat, perm in game.permanents_with_controller()
        if perm is not source_permanent
    ]
    num_to_destroy = random.randint(0, min(2, len(candidates)))
    chosen = random.sample(candidates, num_to_destroy) if num_to_destroy > 0 else []
    for victim_player, victim_perm in chosen:
        game.remove_from_battlefield(victim_perm)
        game._permanent_to_graveyard(victim_player, victim_perm)
        game.log.append(f"Chaos Orb flip destroyed {victim_perm.card.name}")
    # Always destroy Chaos Orb itself
    if source_permanent is not None:
        holder = game.controller_index_of(source_permanent)
        if holder is not None:
            player = game.players[holder]
            game.remove_from_battlefield(source_permanent)
            game._permanent_to_graveyard(player, source_permanent)
    game.log.append("Chaos Orb was destroyed after flip")
    return True, "resolved"


@effect_handler("destroy_artifact_controller_gains_mana_value")
def destroy_artifact_controller_gains_mana_value(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Crumble: destroy target artifact, its controller gains life equal to its
    mana value.

    One handler rather than a `sequence` of destroy-then-gain, and the reason is
    worth stating: the second clause is about *the object the first clause
    destroyed* — its controller, its mana value — and by the time a second step
    ran, that permanent is in a graveyard. Passing it between steps needs the
    execution context to carry the affected object, which it does not yet do
    (``results`` carries values, not objects). When it does, this becomes two
    steps and this kind goes away.
    """
    target = context.target
    index = context.target_permanent_index
    artifact = None
    if isinstance(index, int) and 0 <= index < len(target.battlefield):
        candidate = target.battlefield[index]
        if candidate.has_type("artifact"):
            artifact = candidate
    if artifact is None:
        artifact = next((p for p in game.controlled_by(target) if p.has_type("artifact")), None)
    if artifact is None:
        game.log.append(f"{context.card.name} did nothing: no artifact to destroy")
        return True, "resolved"

    # Read before destroying: afterwards the permanent is gone and its
    # controller is no longer answerable from the battlefield (CR 603.10).
    controller_index = game.controller_index_of(artifact)
    life = int(artifact.effective_card.cmc)
    name = artifact.card.name

    game._destroy_target_permanent(
        target,
        type_filter="artifact",
        # By identity. ``list.index`` compares by value, so two equally-stated
        # Moxen (both untapped, both played this turn) would resolve to the same
        # slot and Crumble would destroy the first of them rather than the one
        # it targeted. ``battlefield_index_of`` is the seam's identity search.
        target_permanent_index=game.battlefield_index_of(artifact),
        bypass_regeneration=bool(instruction.payload.get("bypass_regeneration")),
    )
    if controller_index is not None:
        game.players[controller_index].life += life
        game.log.append(
            f"{context.card.name} destroyed {name}; "
            f"{game.players[controller_index].name} gained {life} life"
        )
    return True, "resolved"


@effect_handler("sacrifice_expansion_permanents")
def sacrifice_expansion_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Golgothian Sylex: "Each nontoken permanent with a name originally printed
    in the Antiquities expansion is sacrificed by its controller."

    The set is a code on the payload, resolved from the manifest when the line
    was parsed — so this is the same effect for any set, which is what Homelands'
    Apocalypse Chime is.

    "Originally printed" is ``CardDefinition.original_printing`` — ``printings[0]``,
    the first set the card appeared in — and *not* whichever set happened to load
    first. That distinction is the whole content of the word "originally": nineteen
    Antiquities cards were reprinted in Revised, and reading the loaded set code
    would miss every one of them. It is the same read City in a Bottle makes.

    The Sylex sacrifices itself: it is an Antiquities card and its own ability
    does not exempt it. Nothing here excludes the source, deliberately.
    """
    wanted = str(instruction.payload.get("set_code", "")).lower()
    if not wanted:
        return False, "no expansion named"

    doomed = [
        (seat, perm)
        for seat, perm in game.permanents_with_controller()
        if not perm.metadata.get("is_token")
        and perm.card.original_printing.lower() == wanted
    ]
    for seat, perm in doomed:
        game._permanent_to_graveyard(game.players[seat], perm)
        game.log.append(f"{perm.card.name} sacrificed ({context.card.name})")
    game.remove_all_from_battlefield([perm for _seat, perm in doomed])
    return True, "resolved"
