from __future__ import annotations

from typing import TYPE_CHECKING

from ..auras import detach_aura
from ..dexterity import flip_lands_on
from ..static_bonuses import singular_land_type
from ..models import Permanent, PlayerState
from ..oracle_types import PER_OBJECT_SEAT_RECORDS
from ..resumption import run_resumable
from ._common import (
    apply_damage_to_creature, permanent_matches_filter, resolve_target_permanent,
    resolve_target_permanents,
)
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
                    # See `_mass_damage_players_and_creatures`: marking is half
                    # a damage event, and a sweep that stops there is damage
                    # nothing can trigger on.
                    apply_damage_to_creature(game, perm, destroyed, card)
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

    # Who controlled each victim, read **before** the sweep (CR 608.2h /
    # CR 400.7): a later "for each … destroyed this way, its controller …"
    # asks about a permanent that is a card in a graveyard by then.
    controllers = {
        perm.permanent_id: seat
        for player in game.players
        for perm in game.controlled_by(player)
        if _matches(perm)
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    died: list[Permanent] = []
    for player in game.players:
        died.extend(game._destroy_swept_permanents(
            player, _matches, allow_regeneration=regeneration_allowed
        ))
    # "…where X is the number of creatures that **died this way**" (Hellfire).
    # What actually died, not what the sweep aimed at: a regenerated or
    # indestructible permanent is still there, and CR 701.8c is explicit that
    # a replaced destruction is not a death.
    #
    # The **objects** ride beside the number, and did not until this round —
    # these five sweeps recorded the count alone. `_lower_for_each_destroyed`
    # gates on the count being produced, so "Destroy all creatures. For each
    # creature that died this way, …" over one of them compiled *supported* and
    # then iterated an empty list. `destroy_all_matching` beside them has
    # recorded both since Glyph of Reincarnation; the difference was invisible
    # because no printed card had asked yet.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = {
        perm.permanent_id: controllers[perm.permanent_id]
        for perm in died
        if perm.permanent_id in controllers
    }
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


def _was_blocked_by(candidate: Permanent, blocker_id: int) -> bool:
    """Was *candidate* blocked by ``blocker_id`` this turn?

    CR 509.1a's relation read **off the candidate**, not off the blocker. The
    two directions of the pair are written together by
    ``declare_blockers_step._record_block_history``, so either end answers — but
    only this end survives the blocker leaving the battlefield, and the blocker
    leaving is the ordinary way Glyph of Doom is played: the Wall blocks, the
    delayed ability waits for the end of combat, and combat damage kills the
    Wall in between. Reading the record off the Wall answered "the creature
    whose blocks it names is gone" and destroyed nothing, on the card's own main
    line.

    ``blocked_ids`` beside it stays as it is: Glyph of Reincarnation names a
    Wall it *targets*, so CR 608.2b has already required that Wall to still be
    there, and that branch reads a second record (which seat controlled each
    attacker) that has no mirror.
    """
    return blocker_id in set(
        candidate.metadata.get("blocked_by_blocker_ids_this_turn") or ()
    )


def _stood_opposite(candidate: Permanent, other_id: int) -> bool:
    """Was *candidate* on the other side of a block from ``other_id`` this turn?

    CR 509.1a's relation read in both directions, off the pair of records
    ``declare_blockers_step`` writes when a block is declared: a blocker names
    the attackers it blocked, and an attacker names the blockers that blocked
    it. Both live on the *candidate*, which is what lets the question be asked
    after the creature on the other side has died.
    """
    return other_id in set(
        candidate.metadata.get("blocked_attacker_ids_this_turn") or ()
    ) or other_id in set(
        candidate.metadata.get("blocked_by_blocker_ids_this_turn") or ()
    )


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
        if key not in (
            "attached_to", "bypass_regeneration", "targets",
            "blocked_by_bound_object", "blocked_by_target_object",
            "in_combat_with_bound_object",
        )
    }
    # "…all creatures that were blocked by **that creature** this turn."
    # (Glyph of Doom.) A relation, resolved here for the reason `attached_to`
    # below is: the record lives on the blocker the delayed ability was bound
    # to, and `permanent_matches_filter` answers about a permanent alone.
    #
    # An unresolvable bound object ends the resolution rather than falling
    # through — a dropped relation here is not a sweep that does less, it is a
    # sweep that destroys every creature on the battlefield.
    blocked_ids: set[int] | None = None
    blocked_by_blocker_id: int | None = None
    if instruction.payload.get("blocked_by_bound_object"):
        blocked_by_blocker_id = (context.trigger_context or {}).get(
            "bound_permanent_id"
        )
        if blocked_by_blocker_id is None:
            # No binding at all — no creature was named, so no block can be
            # named either. Ending here rather than falling through, for the
            # reason the branches below end: a dropped relation is not a sweep
            # that does less, it is one that takes the board.
            game.log.append(
                f"{context.card.name}: the creature whose blocks it names is gone"
            )
            return True, "resolved"
    # "…all creatures that **blocked or were blocked by** it this turn."
    # (Venomous Breath.) The two-way reading of the same relation, and unlike
    # the one-way branch above it does not need the bound creature to still be
    # there: both halves are answered from a *candidate's* own metadata. That
    # is the only reading that works when the creature the spell named died in
    # the very combat the sentence is about — the ordinary way this card is
    # played, not an edge case.
    #
    # Its own key rather than a widening of `blocked_ids`: the two phrases name
    # different sets, and one field meaning either would leave the sweep
    # guessing which the card printed.
    in_combat_with_id: int | None = None
    if instruction.payload.get("in_combat_with_bound_object"):
        in_combat_with_id = (context.trigger_context or {}).get("bound_permanent_id")
        if in_combat_with_id is None:
            # No binding at all — nothing on the board can stand opposite an
            # object the ability never named. Ending here rather than falling
            # through, for the reason the branch above ends: a dropped relation
            # is not a sweep that does less, it is one that takes the board.
            game.log.append(
                f"{context.card.name}: the creature whose combat it names is gone"
            )
            return True, "resolved"
    # "…all creatures that were blocked by **target Wall** this turn." (Glyph
    # of Reincarnation.) The same record read off a different referent: the
    # blocker is this spell's own target. Resolved by id, never by index — the
    # sweep below removes permanents, and CR 400.7 makes an index meaningless
    # the moment one leaves.
    #
    # The seats frozen beside those ids travel on to the next sentence, which
    # names "the player who controlled that creature the last time it became
    # blocked by that Wall". Read *here*, while the Wall is still the object
    # the spell targeted: once the sweep has run the creatures are cards in a
    # graveyard and nothing on the board can answer the question.
    blocked_controllers: dict[int, int] = {}
    if instruction.payload.get("blocked_by_target_object"):
        blocker = game.permanent_by_id(context.target_permanent_id)
        if blocker is None:
            # CR 608.2b would normally have countered the spell for having no
            # legal target left; a blocker that is nonetheless gone (an ability
            # naming it, a copy resolving late) names no blocks this effect can
            # read. Ending here rather than falling through, for the reason the
            # bound-object branch above ends: the relation is the whole card.
            game.log.append(
                f"{context.card.name}: the creature whose blocks it names is gone"
            )
            return True, "resolved"
        blocked_ids = set(blocker.metadata.get("blocked_attacker_ids_this_turn") or ())
        blocked_controllers = dict(
            blocker.metadata.get("blocked_attacker_controllers_this_turn") or {}
        )
    attached_to = instruction.payload.get("attached_to")
    host = None
    if attached_to is not None:
        # Every referent the noun parser can produce is answered here. Falling
        # through with `host` still None would drop the relation and sweep every
        # matching permanent on the board, which is the widening this whole
        # payload key exists to prevent — so an unresolvable one ends the
        # resolution instead.
        if attached_to == "target":
            host = game.permanent_by_id(context.target_permanent_id)
        elif attached_to == "source":
            host = context.source_permanent
        if host is None:
            game.log.append(
                f"{context.card.name}: nothing is attached to a permanent that is gone"
            )
            return True, "resolved"
    # Through ``subject_matches`` rather than the pure matcher, for the reason
    # the bounce handler asks it: "all enchantments **you control**" (Remove
    # Enchantments) is a seat comparison no read of the enchantment alone can
    # make, and so is the host phrase inside "Auras attached to permanents you
    # control". The observer is CR 109.5's — the controller of the spell or
    # ability doing the destroying, never whoever controls what it hits.
    #
    # The lowering's gate is the same key set this answers, which is what stops
    # a phrase arriving here that would be dropped: a dropped narrowing on a
    # sweep is not a card that does less, it is one that takes the board.
    # Late import: ``subject_filters`` imports this package's ``_common``, so
    # the edge is taken at call time rather than at module load — the same
    # reason ``bounce_target_creature`` takes it late.
    from ..subject_filters import subject_matches

    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, filters,
            observer=observer, source=context.source_permanent,
        )
        and (host is None or perm.metadata.get("attached_to") is host)
        and (blocked_ids is None or perm.permanent_id in blocked_ids)
        and (
            blocked_by_blocker_id is None
            or _was_blocked_by(perm, blocked_by_blocker_id)
        )
        and (
            in_combat_with_id is None
            or _stood_opposite(perm, in_combat_with_id)
        )
    ]
    if not matched:
        context.results["destroyed_this_way"] = 0
        context.results["destroyed_this_way_objects"] = []
        game.log.append(f"{context.card.name}: nothing to destroy")
        return True, "resolved"
    died: list[Permanent] = []
    for perm in matched:
        seat = game.controller_index_of(perm)
        if seat is None:
            continue
        died.extend(game._destroy_swept_permanents(
            game.players[seat],
            lambda candidate, target=perm: candidate is target,
            allow_regeneration=not instruction.payload.get("bypass_regeneration"),
        ))
    # See `_sweep_by_type`: the record is what died, which is what a later
    # "that died this way" counts. The *objects* ride beside the number for a
    # later sentence that iterates them rather than counting them (Glyph of
    # Reincarnation), and the number is derived from the list so the two
    # records cannot come to disagree.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    # The seat each of them was under when the named blocker blocked it, keyed
    # by the same permanent ids. Recorded only when the sweep read a block
    # relation at all, so no other card carries an empty map it never asked for.
    if blocked_controllers:
        context.results[PER_OBJECT_SEAT_RECORDS["controller_when_blocked"]] = {
            perm.permanent_id: blocked_controllers[perm.permanent_id]
            for perm in died
            if perm.permanent_id in blocked_controllers
        }
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

    # Who controlled each victim, read **before** the sweep (CR 608.2h / CR
    # 400.7): "For each land destroyed this way, this spell deals 1 damage to
    # that land's controller" (Stench of Evil) asks about a permanent that is a
    # card in a graveyard by the time the loop runs, and no board read can
    # answer for it.
    controllers = {
        perm.permanent_id: seat
        for player in game.players
        for perm in game.controlled_by(player)
        if _matches(perm)
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    died: list[Permanent] = []
    for player in game.players:
        died.extend(
            game._destroy_swept_permanents(player, _matches, allow_regeneration=False)
        )
    # The record every other destroy sweep keeps, and this one did not: what a
    # later sentence of the same spell counts or iterates. `destroy_all_lands`
    # and `destroy_all_matching` have written it since Hellfire; the by-type
    # sweep beside them was the sweep that recorded nothing, which is invisible
    # until a card asks — the second sentence reads an empty set and the card
    # reports itself supported having done half of what it says.
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = {
        perm.permanent_id: controllers[perm.permanent_id]
        for perm in died
        if perm.permanent_id in controllers
    }
    game.log.append(f"All {land_type}s were destroyed")
    return True, "resolved"


@effect_handler("destroy_target_permanent")
def destroy_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    # "Destroy X target snow lands." (Avalanche.) The several-targets
    # description says a *list* was collected, so each slot resolves strictly
    # and one that has left is dropped rather than slid onto another
    # (CR 608.2b) — the same reading `untap_target_permanent` takes for
    # Candelabra of Tawnos, through the same helper.
    targets_desc = instruction.payload.get("targets") or {}
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        from ..subject_filters import subject_matches

        filters = {
            key: value for key, value in instruction.payload.items()
            if key not in ("targets", "bypass_regeneration")
        }
        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, filters,
                observer=observer, source=source_permanent,
            ),
        )
        died: list[Permanent] = []
        for perm in chosen:
            seat = game.controller_index_of(perm)
            if seat is None:
                continue
            died.extend(game._destroy_swept_permanents(
                game.players[seat],
                lambda candidate, victim=perm: candidate is victim,
                allow_regeneration=not instruction.payload.get("bypass_regeneration"),
            ))
        # What a later sentence of the same spell counts. Recorded under the
        # key the sweep uses, because "the number of Mountains put into a
        # graveyard this way" is the same question whichever branch destroyed
        # them.
        context.results["destroyed_this_way_objects"] = died
        context.results["destroyed_this_way"] = len(died)
        game.log.append(
            f"{card.name} destroyed " + ", ".join(p.card.name for p in died)
            if died else f"{card.name}: nothing to destroy"
        )
        return True, "resolved"
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
            # "You gain life equal to **its** mana value." (Divine Offering.)
            # Recorded here, before the destruction, for two reasons: the
            # permanent is gone by the time the next step runs (CR 608.2h), and
            # the words name the object rather than the outcome — a regenerated
            # or indestructible artifact still has a mana value to gain.
            # Through `effective_card` so a copy effect's cost is the one read
            # (CR 707.2), which is the same reading Crumble's fused kind takes.
            context.results["its_mana_value"] = int(victim.effective_card.cmc or 0)
            # "**If that land was a snow land**, …" (Icequake, Thermokarst).
            # The permanent itself, recorded here for the same reason its mana
            # value is and one moment earlier than it would survive: after the
            # destroy it is a card in a graveyard with no characteristics at all
            # (CR 613.1), so a condition asking what it *was* has to read the
            # object it was (CR 608.2h). The `Permanent` keeps its state after
            # leaving the battlefield, which is exactly what last-known
            # information means.
            context.results["destroyed_target"] = victim
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
        attached_to_filter=instruction.payload.get("attached_to_filter"),
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
    # The flip itself is a CR 104.1 physical action the engine cannot perform;
    # ``engine.dexterity`` is the one place that substitution is made and
    # explained. Only the count is this card's ("up to two permanents").
    chosen = flip_lands_on(candidates, maximum=2)
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


@effect_handler("arm_self_action_at_next_end_step")
def arm_self_action_at_next_end_step(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy this artifact at the beginning of the next end step." (Rocket
    Launcher.) "Return this artifact to its owner's hand …" (Rakalite.)

    Creates a delayed triggered ability (CR 603.7) rather than doing anything
    now. The permanent is recorded by ``permanent_id``, so one that leaves and
    comes back is a new object (CR 400.7) and the ability that was waiting for
    the old one finds nothing — which is right: the delayed trigger names the
    object it was created for, not whatever is standing in its place.
    """
    source = context.source_permanent
    if str(instruction.payload.get("subject", "source")) == "bound":
        # "Destroy **it** at the beginning of the next end step." (Glyph of
        # Destruction.) The object the sentence in front of this one named,
        # which for a spell is the target it chose. Resolved here rather than at
        # compile time because the printed pronoun does not say which of the two
        # it is, and the fallback is the source — the reading every other
        # printing of this sentence has.
        chosen = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_on_invalid_choice=False,
        )
        if chosen is not None:
            source = chosen
    if source is None:
        return False, "ability not implemented"
    # Onto the flags the end step's existing delayed-removal sweep already
    # reads. Rocket Launcher's self-destruction has been marked this way since
    # before the grammar could read its sentence — the damage handler set it
    # from a payload flag — so writing a second queue beside it would have been
    # two mechanisms for one rule, and the *older* one is the one every other
    # delayed removal in the engine (Dragon Whelp, Berserk) already uses.
    # "**Sacrifice** it at the beginning of the next end step." (Krovikan
    # Elementalist, Celestial Sword.) Its own flag rather than the destruction
    # one, because the end step's sweep already reads both and its comment says
    # why keeping them apart is a rules feature: a sacrifice is not a
    # destruction (CR 701.21a), so no replacement effect applies to it.
    action = str(instruction.payload.get("self_action", "destroy"))
    key = {
        "bounce": "bounce_at_next_end_step",
        "sacrifice": "sacrifice_at_next_end_step",
    }.get(action, "destroy_at_next_end_step")
    source.metadata[key] = True
    return True, "resolved"


@effect_handler("destroy_self")
def destroy_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**Destroy this Aura.**" (Imprison.)

    The twin of ``sacrifice_self``: the sentence names the ability's own
    source, so nothing is chosen and nothing is looked up. Destruction rather
    than sacrifice because the two are different events — a destroy is a
    CR 701.7 action a regeneration shield or indestructible can answer, and a
    sacrifice (CR 701.21) is neither — and a card that prints one must not
    perform the other.

    Through ``_destroy_swept_permanents``, the same seam
    ``destroy_attached_permanent`` beside it uses, so regeneration, the
    indestructible check and the graveyard move behave as they do for a
    targeted destroy. A source already gone destroys nothing, which is
    CR 608.2b doing as much as possible rather than a failure.
    """
    source = context.source_permanent
    seat = game.controller_index_of(source) if source is not None else None
    if source is None or seat is None:
        game.log.append(f"{context.card.name}: nothing left to destroy")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is source,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} was destroyed")
    return True, "resolved"


@effect_handler("sacrifice_attached_permanent")
def sacrifice_attached_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…unless they sacrifice **that artifact**." (Curse Artifact.)

    The permanent read off the source's own attachment, exactly as
    ``destroy_attached_permanent`` below reads it and for the same reason: the
    trigger's condition named it ("the upkeep of enchanted artifact's
    controller"), so the sentence chooses nothing and there is nothing for a
    picker to have offered.

    Through ``Game.sacrifice_permanent``, never a hand-rolled removal — that is
    the one seam a sacrifice passes through (ownership, tokens, replacements,
    Aura teardown, the death count and the dies-triggers all hang off it), and
    a second spelling of it is how seven of those were skipped before it
    existed.

    CR 701.16b: only the permanent's controller may sacrifice it, and that is
    who the offer was made to — ``handlers/control_flow._action_is_takeable``
    withdraws the offer when the Aura has come unattached, so reaching here
    with nothing attached means the offer was never narrowed and the right
    answer is to do nothing rather than to charge a cost that cannot be paid.
    """
    source = context.source_permanent
    attached = source.metadata.get("attached_to") if source is not None else None
    if attached is None or not game.is_on_battlefield(attached):
        game.log.append(f"{context.card.name}: nothing attached to sacrifice")
        return True, "resolved"
    game.sacrifice_permanent(attached)
    game.log.append(f"{context.card.name}: {attached.card.name} was sacrificed")


@effect_handler("destroy_bound_permanent")
def destroy_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this artifact leaves the battlefield this turn, **destroy that
    creature**." (War Barge.)

    The victim is the object the creating ability bound (CR 603.7c), carried by
    id in the trigger's context — the creature War Barge's own activation
    targeted, which is *not* the object the delay watched. Nothing is chosen
    here and nothing is addressed by index: an id is the identity a permanent
    keeps across everything that renumbers a battlefield (CR 400.7).

    Through ``_destroy_swept_permanents``, the same seam ``destroy_self`` and
    ``destroy_attached_permanent`` beside it use, so the indestructible check
    and the graveyard move behave as they do for a targeted destroy — and "a
    creature destroyed this way can't be regenerated" is this handler's
    ``bypass_regeneration``, not a second reading of CR 701.19c.

    A creature already gone is destroyed by nothing, which is CR 608.2b doing
    as much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    seat = game.controller_index_of(victim) if victim is not None else None
    if victim is None or seat is None:
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is victim,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} destroyed {victim.card.name}")
    return True, "resolved"


@effect_handler("destroy_attached_permanent")
def destroy_attached_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When enchanted land becomes tapped, destroy it." (Blight.)

    The victim is read off the source's own attachment rather than from a
    target: CR 303.4b makes "enchanted" a name for the object this Aura is
    already attached to, so the sentence chooses nothing and there is nothing
    for a picker to have offered or for the resolution context to carry.

    It goes through ``_destroy_swept_permanents`` — the same seam every other
    "destroy this particular permanent" handler uses — so regeneration, the
    indestructible check and the graveyard move behave exactly as they do for a
    targeted destroy. An Aura that has come unattached destroys nothing, which
    is the window CR 303.4c's state-based action has not closed yet.
    """
    source = context.source_permanent
    attached = source.metadata.get("attached_to") if source is not None else None
    if attached is None:
        game.log.append(f"{context.card.name}: nothing attached to destroy")
        return True, "resolved"
    seat = game.controller_index_of(attached)
    if seat is None:
        game.log.append(f"{context.card.name}: nothing attached to destroy")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is attached,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} destroyed {attached.card.name}")
    return True, "resolved"


@effect_handler("destroy_each_unless_life_paid")
def destroy_each_unless_life_paid(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each land, destroy that land unless any player pays 1 life."
    (Cleansing.)

    A sweep whose members are bought off one at a time. The offer goes to
    **every** player in APNAP order (CR 101.4) about **each** land in turn, and
    the first seat to pay ends that land's round — so a seat that saved one
    land has said nothing about the next, which is the whole difference between
    this and "destroy all lands unless a player pays".

    The loop is resumable (``engine/resumption.py``): a human seat's offer
    suspends it and answering carries it on from the land it stopped at. That
    is why the destruction is a *step of the loop* — the ``None`` seat at the
    end of each land's round — rather than work written after it. Work after a
    resumable loop does not run when a step suspends, and nothing records it.

    The lands are frozen as ids before the first offer (CR 400.7: an index is
    not an identity, and this loop removes permanents as it goes). A land that
    has left by the time its round comes up is simply skipped: it is no longer
    there to destroy, and nobody should be charged to save it.
    """
    filters = dict(instruction.payload.get("filter") or {})
    life = int(instruction.payload.get("life", 1))
    seats = len(game.players)
    active = game.active_player_index if game.active_player_index is not None else 0
    apnap = [(active + offset) % seats for offset in range(seats)]
    targets = [
        perm.permanent_id
        for perm in sorted(game.all_permanents(), key=lambda p: p.permanent_id)
        if permanent_matches_filter(perm, filters)
    ]
    if not targets:
        game.log.append(f"{context.card.name}: nothing to destroy")
        return True, "resolved"
    saved: set[int] = set()
    # One flat list of steps rather than a loop inside a loop: `run_resumable`
    # records the rest of *itself* before each step, and a nested loop would
    # need its own record for the offers still owed about the land it stopped
    # on. The `None` seat is that land's verdict.
    steps = [
        (permanent_id, seat)
        for permanent_id in targets
        for seat in [*apnap, None]
    ]

    def _step(item) -> None:
        permanent_id, seat = item
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None or permanent_id in saved:
            return
        if seat is None:
            controller = game.controller_index_of(permanent)
            if controller is None:
                return
            game._destroy_swept_permanents(
                game.players[controller],
                lambda candidate, target=permanent: candidate is target,
            )
            game.log.append(
                f"{context.card.name} destroyed {permanent.card.name} "
                "(nobody paid to save it)"
            )
            return
        if game.players[seat].lost:
            return
        game.arm_pending_choice(
            "pay_life_to_save", seat,
            permanent_id=permanent_id,
            permanent_name=permanent.card.name,
            life=life,
            card_name=context.card.name,
            _saved=saved,
        )

    run_resumable(game, steps, _step)
    return True, "resolved"


@effect_handler("destroy_tapped_land_and_reoffer_aura")
def destroy_tapped_land_and_reoffer_aura(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Kudzu: "When enchanted land becomes tapped, destroy it. That land's
    controller may attach this Aura to a land of their choice."

    This used to be a name-keyed dispatcher (``ENCHANTED_LAND_TAPPED_FOR_MANA``)
    called from inside ``tap_land_for_mana``, which is the bug ``become_tapped``
    was built to end: the card says "becomes tapped" (CR 701.26a) and the
    dispatcher only saw the mana path, so an Icy Manipulator tapping the
    enchanted land destroyed nothing. As an instruction the line is *announced*
    by the tap seam like any other trigger, which fixes both halves at once —
    every tap path reaches it, and it goes on the stack (CR 603.3) rather than
    resolving inline where a name-keyed pass had put it.

    The land is read by the id the announcement froze rather than off the Aura's
    ``attached_to`` at resolution: the Aura may have been removed in response,
    and CR 603.10 says the ability uses the information the game had.
    """
    aura = context.source_permanent
    land_id = (context.trigger_context or {}).get("event_subject_permanent_id")
    land = game.permanent_by_id(land_id) if land_id is not None else None
    if aura is None or land is None:
        game.log.append("Kudzu: the enchanted land is gone, nothing to destroy")
        return True, "resolved"

    # The seat the announcement froze, not a board read (CR 603.10): "that
    # land's controller" is the controller it had when it became tapped, and a
    # control change in response does not move who is offered the re-attach.
    controller_index = (context.trigger_context or {}).get("event_subject_controller")
    if not isinstance(controller_index, int) or not (0 <= controller_index < len(game.players)):
        game.log.append("Kudzu: no recorded controller, nothing destroyed")
        return True, "resolved"
    player = game.players[controller_index]
    game.remove_from_battlefield(land)
    player.graveyard.append(land.card)
    aura.metadata.pop("attached_to", None)
    detach_aura(aura, land)
    game.log.append(f"{aura.card.name} destroyed {land.card.name}")

    # "…**may** attach this Aura to a land of their choice" — the land's
    # controller decides, not the Aura's. One `pending_choice`, so an
    # interactive seat is asked and every other seat takes the registered
    # default (the first land it controls) at once; that is the same split the
    # caller's old ``defer_choice`` flag hand-computed, asked of the registry
    # instead so a new seat kind needs no new argument.
    if any(perm.card.primary_type == "land" for perm in game.controlled_by(controller_index)):
        game.arm_pending_choice("kudzu_reattach", controller_index, aura=aura)
    return True, "resolved"
