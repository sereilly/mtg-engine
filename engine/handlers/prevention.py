from __future__ import annotations

from typing import TYPE_CHECKING

from ..shields import (
    make_source_type_shield,
    make_targeting_source_shield,
    add_shield,
    make_capped_charge,
    make_capped_source,
    make_color_shield,
    make_life_gain_charge,
    make_life_gain_source,
    make_numeric_pool,
    make_subject_shield,
)
from ._common import resolve_amount, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import PlayerState
    from ..oracle import OracleInstruction


def _grant_pool(recipient, amount: int, source_name: str | None) -> None:
    """Arm one CR 615.7 numeric shield on *recipient*.

    A shield rather than an addition to a running total: several "prevent the
    next N damage" effects on one recipient are several effects, each with its
    own granting card for the badge. What they hold together is still the one
    number ``damage_prevention_pool`` reports.
    """
    if amount > 0:
        add_shield(recipient, make_numeric_pool(amount, source_name))


def apply_prevention_shield(
    game: Game,
    target: PlayerState,
    target_permanent_index: object,
    amount: int,
    source_name: str | None = None,
) -> str:
    """Grant `amount` prevention shields to a chosen creature, or otherwise to the
    target player. Records `source_name` (the granting card) so the UI can show
    its art on the shield badge. Returns the name of the beneficiary."""
    if (
        isinstance(target_permanent_index, int)
        and 0 <= target_permanent_index < len(target.battlefield)
        and target.battlefield[target_permanent_index].is_creature
    ):
        permanent = target.battlefield[target_permanent_index]
        _grant_pool(permanent, amount, source_name)
        game.log.append(f"{permanent.card.name} gains prevention shield for {amount} damage")
        return permanent.card.name
    _grant_pool(target, amount, source_name)
    game.log.append(f"{target.name} gains prevention shield for {amount} damage")
    return target.name


@effect_handler("grant_prevention_shield")
def grant_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    source_name = context.card.name if context.card else None
    # CoP-style abilities say "prevent damage to you" — protection_kind="color"
    # means the caster/controller is always the beneficiary. Conservator-style
    # abilities ("...dealt to you this turn") set to_self=True for the same reason.
    prevention_color = instruction.payload.get("prevention_color")
    # "a black **or red** source of your choice" (Greater Realm of
    # Preservation): one shield answering to either colour, never one shield
    # per colour — two would let a black source and a red source each be
    # prevented off a single activation.
    prevention_colors = tuple(
        instruction.payload.get("prevention_colors") or ()
    ) or ((prevention_color,) if prevention_color else ())
    # Circle of Protection: Artifacts — the same Circle keyed on a card type.
    # Its own branch rather than a widened colour one: `make_color_shield` sets
    # the colour field, and a shield holding a card type in it would be
    # compared against `source_colors` and never match.
    source_type = instruction.payload.get("prevention_source_type")
    if instruction.payload.get("protection_kind") == "source_type" and source_type:
        add_shield(caster, make_source_type_shield(str(source_type), source_name))
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            f"an {source_type} source"
        )
        return True, "resolved"
    if instruction.payload.get("protection_kind") == "color":
        # Circle of Protection: "The next time a <color> source of your choice
        # would deal damage to you this turn, prevent that damage." Each activation
        # arms one color-scoped shield that prevents the entire next damage event
        # from a source of that color (CR 615) — distinct from the generic numeric
        # prevention pool so it only stops matching-colored damage.
        #
        # Only when a colour was actually recorded: CR 615.9 rechecks the
        # source's properties against the shield's, so a shield naming no colour
        # can never match anything. The legacy parse rule can still produce one
        # from a card whose text has no colour word, and arming nothing is what
        # the old list-of-None amounted to.
        for _ in range(max(1, amount) if prevention_colors else 0):
            add_shield(caster, make_color_shield(prevention_colors, source_name))
        # The chosen source (if the controller picked a specific permanent) is
        # recorded only for the log; matching is by color.
        chosen_perm = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
        chosen = chosen_perm.card.name if chosen_perm is not None else None
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            + (
                f"{chosen} (a {'/'.join(prevention_colors)} source)"
                if chosen
                else f"a {'/'.join(prevention_colors)} source"
            )
        )
        return True, "resolved"

    if instruction.payload.get("to_self"):
        _grant_pool(caster, amount, source_name)
        game.log.append(f"{caster.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    # Rock Hydra: "{R}: Prevent the next 1 damage that would be dealt to this
    # creature this turn." The shield protects the ability's own source
    # permanent, never the (defaulted) target.
    if instruction.payload.get("to_source"):
        source_perm = context.source_permanent
        if source_perm is not None:
            _grant_pool(source_perm, amount, source_name)
            game.log.append(
                f"{source_perm.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    apply_prevention_shield(game, target, context.target_permanent_index, amount, source_name)
    return True, "resolved"


@effect_handler("grant_reverse_damage_shield")
def grant_reverse_damage_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Reverse Damage: arm a one-shot shield against "a source of your choice".

    The caster picks the source — a permanent on any battlefield (chosen via
    target_permanent_index) or a spell on the stack (the threatening burn spell,
    chosen via stack_target). Only damage from that source is prevented and gained
    as life. With no chosen source (AI / headless casts), fall back to a generic
    charge that shields the entire next damage event from any source.
    """
    caster = context.caster
    chosen = None
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
    granted_by = context.card.name if context.card else None
    if chosen is not None:
        add_shield(caster, make_life_gain_source(chosen, granted_by))
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name} armed a Reverse Damage shield against {getattr(source_card, 'name', 'a source')}"
        )
    else:
        add_shield(caster, make_life_gain_charge(granted_by))
        game.log.append(f"{caster.name} armed a Reverse Damage shield")
    return True, "resolved"


@effect_handler("grant_forcefield_shield")
def grant_forcefield_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Honor the chosen unblocked attacker so only that creature's combat damage is
    # capped to 1. Fall back to a generic "next combat damage" cap for AI/headless
    # activations that supply no target.
    chosen = resolve_target_permanent(game, context, fallback_players=())
    if chosen is not None:
        add_shield(caster, make_capped_source(chosen))
        game.log.append(f"Forcefield will prevent all but 1 combat damage from {chosen.card.name}")
    else:
        add_shield(caster, make_capped_charge())
        game.log.append("Forcefield shield granted")
    return True, "resolved"


@effect_handler("redirect_one_damage_to_owner")
def redirect_one_damage_to_owner(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
        source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
    ) + 1
    game.log.append(f"{card.name} will redirect next 1 damage to its owner")
    return True, "resolved"


@effect_handler("jade_monolith_redirect")
def jade_monolith_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Jade Monolith: "The next time a source of your choice would deal damage to
    target creature this turn, that source deals that damage to you instead."

    The controller chooses the target creature (target_permanent_index on the
    target player's battlefield) AND the damage source (choices["chosen_source"]: a
    battlefield permanent or a stack spell's card). The next damage that source
    would deal to the creature is redirected to the controller; with no recorded
    source choice (AI/legacy activations) any source's damage is redirected.
    """
    caster = context.caster
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        caster_idx = game.players.index(caster)
        target_creature.metadata["redirect_damage_to_player"] = caster_idx
        chosen_source = context.choices.get("chosen_source")
        if chosen_source is not None:
            target_creature.metadata["redirect_damage_source"] = chosen_source
            source_name = getattr(getattr(chosen_source, "card", chosen_source), "name", "source")
            game.log.append(
                f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}"
                f" (source: {source_name})"
            )
        else:
            target_creature.metadata.pop("redirect_damage_source", None)
            game.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
    return True, "resolved"


@effect_handler("shield_target_land_from_destruction")
def shield_target_land_from_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pyramids mode 2: "The next time target land would be destroyed this
    turn, remove all damage marked on it instead." Arms a one-shot shield the
    destroy paths consume via _consume_land_destruction_shield."""
    card = context.card
    target_land = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.card.primary_type == "land",
        fallback_players=(context.caster, context.target),
    )
    if target_land is None:
        game.log.append(f"{card.name}: no valid land target")
        return True, "resolved"
    target_land.metadata["land_destruction_shield_this_turn"] = True
    game.log.append(
        f"{card.name}: the next time {target_land.card.name} would be destroyed this turn, "
        "all damage marked on it is removed instead"
    )
    return True, "resolved"


@effect_handler("arm_mirror_damage")
def arm_mirror_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Eye for an Eye: the next damage dealt to you this turn by "a source of
    your choice" also hits that source's controller for the same amount.

    Mirrors Reverse Damage's shape: the caster picks the source — a permanent on
    any battlefield (target_permanent_index) or a spell on the stack
    (stack_target) — and only damage from that source is mirrored, matched by
    identity in _deal_damage_to_player. With no chosen source (AI / headless
    casts) fall back to a generic charge that mirrors the next damage event from
    any source."""
    caster = context.caster
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
    if chosen is not None:
        caster.mirror_damage_sources.append(chosen)
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name}: the next damage {getattr(source_card, 'name', 'a source')} "
            f"deals to them this turn is mirrored to its controller ({context.card.name})"
        )
    else:
        caster.mirror_damage_charges += 1
        game.log.append(
            f"{caster.name}: the next damage dealt to them this turn is mirrored "
            f"to its source's controller ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("grant_source_class_prevention_shield")
def grant_source_class_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Al-abara's Carpet: "Prevent all damage that would be dealt to you this
    turn by attacking creatures without flying."

    One :class:`~engine.shields.Shield` on the ability's controller carrying the
    printed noun phrase, so this needs no field on ``PlayerState`` and no
    clearing line in a turn step — the sweep reads its ``lifetime``.

    The *set* of sources is deliberately not captured: the phrase is re-matched
    when damage would be dealt (CR 615.9), so a creature that attacks after this
    resolves is covered and one that gains flying in the meantime is not.
    """
    caster = context.caster
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(caster)
    source_name = context.card.name if context.card else None
    add_shield(caster, make_subject_shield(described, seat, source_name))
    game.log.append(
        f"{caster.name} is shielded this turn from damage dealt by matching "
        f"sources ({source_name})"
    )
    return True, "resolved"


@effect_handler("prevent_damage_to_target_until_eot")
def prevent_damage_to_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all damage that would be dealt to it this turn." (Glyph of
    Destruction.)

    The recipient half of ``prevent_damage_by_target_until_eot``, and a separate
    instruction for the reason that one's docstring gives in the other
    direction: a creature that cannot be hurt and a creature that cannot hurt
    anything are different cards, and one flag covering both would make either
    card's creature untouchable in combat.

    "It" is whatever the sentence in front of this one named — the chosen target
    if the spell chose one, and otherwise the ability's own source. The printed
    pronoun cannot say which, so the referent is resolved here where both are
    known rather than guessed at compile time.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention import (
        COMBAT_SHIELD_BOTH, COMBAT_SHIELD_TO, add_directional_shield,
    )

    combat_only = bool(instruction.payload.get("combat_only"))
    # "…dealt **to and dealt by** that creature this turn" (Ebony Horse, Maze
    # of Ith). The printed sentence puts one object on both ends of the event,
    # which is a *direction* the shield reader already answers for — so it is
    # this instruction with one payload key rather than a second kind. The word
    # is what separates Maze of Ith from Awe Strike: one creature is harmless
    # as well as unhurt, the other only unhurt.
    both_ends = bool(instruction.payload.get("to_and_by"))
    direction = COMBAT_SHIELD_BOTH if both_ends else COMBAT_SHIELD_TO
    perm = resolve_target_permanent(
        game, context,
        predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        perm = context.source_permanent
    if perm is None:
        game.log.append(f"{context.card.name}: no permanent to shield")
        return True, "resolved"
    add_directional_shield(perm, direction, combat_only=combat_only)
    game.log.append(
        f"all {'combat ' if combat_only else ''}damage that would be dealt to "
        + ("and dealt by " if both_ends else "")
        + f"{perm.card.name} this turn is prevented ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("prevent_damage_by_target_until_eot")
def prevent_damage_by_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all [combat] damage that would be dealt by target creature this
    turn." (Horn of Deafening, Lady Evangela, Kry Shield.)

    The printed word "combat" is payload, not a second kind: with it the shield
    sees combat damage alone, without it (Kry Shield) it sees the creature's
    ping abilities too. Dropping it would make Horn of Deafening the wider card
    it is not.

    A shield on the damage's **source**, not on a recipient: the creature is
    still perfectly able to be dealt combat damage and to die to it. That
    direction is what the marker carries, and it is why this is not Ebony
    Horse's two-way flag with a different name — folding them together would
    make every creature either card touches unkillable in combat.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention import COMBAT_SHIELD_BY, add_directional_shield

    combat_only = bool(instruction.payload.get("combat_only"))
    perm = resolve_target_permanent(
        game, context,
        predicate=lambda p: p.is_creature,
        fallback_players=tuple(game.players),
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no creature to silence")
        return True, "resolved"
    shielded = [perm]
    # "…by that creature **and each creature blocking it**." (Feint.) The second
    # printed source is a set named by a combat relation to the first, so it is
    # read from the combat maps at resolution rather than from any description:
    # a creature that started blocking after the spell was cast is one of them
    # (CR 611.2c fixes the set when the effect begins, which is now), and a
    # blocker of a *different* attacker is not.
    if instruction.payload.get("also_blocking_target"):
        for blocker in game.creatures_blocking(perm):
            if not any(blocker is already for already in shielded):
                shielded.append(blocker)
    for creature in shielded:
        add_directional_shield(creature, COMBAT_SHIELD_BY, combat_only=combat_only)
        game.log.append(
            f"all {'combat ' if combat_only else ''}damage {creature.card.name} "
            f"would deal this turn is prevented ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("prevent_damage_from_targeting_sources_until_eot")
def prevent_damage_from_targeting_sources_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Silhouette: "Choose target creature. If a spell or ability that targets
    that creature would cause a source to deal damage to that creature this
    turn, prevent that damage."

    The spell's own chosen creature (CR 601.2c — the first sentence is the
    choosing) carries the shield, so nothing here re-reads the text or picks a
    creature of its own. With the target gone the spell simply does nothing,
    which is CR 608.2b rather than a failure.
    """
    target = resolve_target_permanent(game, context, fallback_players=())
    if target is None:
        game.log.append(f"{context.card.name}: its target is gone")
        return True, "resolved"
    add_shield(
        target,
        make_targeting_source_shield(context.card.name if context.card else None),
    )
    game.log.append(
        f"{target.card.name} is shielded from spells and abilities that target it"
    )
    return True, "resolved"
