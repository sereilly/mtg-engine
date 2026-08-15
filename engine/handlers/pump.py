from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..pt import add_pt_modifier, set_base_pt
from ._common import (
    apply_temp_pt_boost,
    permanent_matches_filter,
    resolve_amount,
    resolve_target_permanent,
    resolve_target_permanents,
)
from .registry import effect_handler
from ..keywords import grant_keyword, remove_keyword

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("berserk_pump")
def berserk_pump(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_perm = resolve_target_permanent(game, context)
    if target_perm is not None:
        boost = target_perm.effective_power
        # "+X/+0 until end of turn" — apply now and track it so cleanup removes it
        # if the creature survives (Berserk only destroys it if it attacked).
        apply_temp_pt_boost(target_perm, boost)
        grant_keyword(target_perm, "trample", until_eot=True)
        # "At the beginning of the next end step, destroy that creature if it
        # attacked this turn." Mark it; the end step checks attacked_this_turn.
        target_perm.metadata["destroy_if_attacked_eot"] = True
        game.log.append(f"{card.name} pumped {target_perm.card.name} by +{boost}/+0 and granted trample")
    else:
        game.log.append(f"{card.name}: no valid creature target")
    return True, "resolved"


@effect_handler("pump_enchanted_creature")
def pump_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    enchanted = source_permanent.metadata.get("attached_to")
    if enchanted is None:
        return False, "aura not attached to a creature"
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    apply_temp_pt_boost(enchanted, power_delta, toughness_delta)
    game.log.append(f"{card.name} grants {enchanted.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


@effect_handler("pump_self")
def pump_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    apply_temp_pt_boost(source_permanent, power_delta, toughness_delta)
    game.log.append(f"{card.name} gets +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


@effect_handler("pump_self_with_sacrifice_condition")
def pump_self_with_sacrifice_condition(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    apply_temp_pt_boost(source_permanent, 1)
    activation_count = int(source_permanent.metadata.get("pump_activation_count", 0)) + 1
    source_permanent.metadata["pump_activation_count"] = activation_count
    if activation_count >= 4:
        source_permanent.metadata["sacrifice_at_next_end_step"] = True
    game.log.append(
        f"{card.name} gets +1/+0 until end of turn (activation {activation_count})"
    )
    return True, "resolved"


@effect_handler("pump_target_creature_until_eot")
def pump_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    x_value = context.x_value
    # "…where X is the number of cards in your graveyard" (Liliana, Waker of
    # the Dead): X is defined by a zone count at resolution, not announced.
    # The sign travels separately because the payload's "x" cannot be negated.
    x_count = instruction.payload.get("x_from_count")
    if x_count is not None:
        owner = caster if x_count.get("owner", "you") == "you" else (target or caster)
        wanted_types = tuple(x_count.get("card_types") or ())
        x_value = sum(
            1
            for c in owner.graveyard
            if not wanted_types or c.primary_type in wanted_types
        )
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    if instruction.payload.get("power_negative"):
        power_delta = -power_delta
    if instruction.payload.get("toughness_negative"):
        toughness_delta = -toughness_delta
    blocking_only = bool(instruction.payload.get("blocking_only"))

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        # Righteousness: the target must be a creature that is currently blocking.
        if blocking_only and not game._is_blocking_creature(perm):
            return False
        return True

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(target, caster)
    )
    if target_perm is not None:
        apply_temp_pt_boost(target_perm, power_delta, toughness_delta)
        game.log.append(f"{card.name} gives {target_perm.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


# buff_creatures_global from a SPELL (sorcery/instant): locks in the set of
# affected creatures at resolution (611.2c). Uses power_bonus so it is NOT
# recalculated dynamically (unlike static abilities which use static_buff_*).
@effect_handler("buff_creatures_global")
def buff_creatures_global(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    color_sym = instruction.payload.get("color")
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    blocking_only = bool(instruction.payload.get("blocking_only"))
    if instruction.payload.get("opponents_only"):
        # "Creatures your opponents control get -2/-2 until end of turn"
        # (Massacre Wurm): every opponent's board and none of the caster's.
        target_players = [
            game.players[i] for i in game.opponents_of(game.players.index(caster))
        ]
    else:
        target_players = game.players if instruction.payload.get("all") else [caster]
    for player in target_players:
        for perm in list(player.battlefield):
            if not perm.is_creature:
                continue
            # Army of Allah: only creatures attacking at resolution are buffed.
            if attacking_only and not perm.attacking:
                continue
            # Piety: only creatures blocking at resolution are buffed.
            if blocking_only and not game._is_blocking_creature(perm):
                continue
            actual_colors = set(perm.card.colors)
            if "color_override" in perm.metadata:
                actual_colors = {perm.metadata["color_override"]}
            if color_sym and color_sym not in actual_colors:
                continue
            apply_temp_pt_boost(perm, power_delta, toughness_delta)
    game.log.append(f"{card.name} buffed matching creatures")
    return True, "resolved"


@effect_handler("grant_team_keyword_until_eot")
def grant_team_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures you control gain flying until end of turn." (Basri, Devoted
    Paladin's −6.) The affected set locks in at resolution (CR 611.2c), which
    is why this walks the board now instead of contributing a derived buff.

    ``every_permanent`` widens the same grant to the whole board (Heroic
    Intervention's "Permanents you control gain hexproof and indestructible"):
    both keywords are asked of the permanent, not of the creature — hexproof is
    read by ``_can_be_targeted`` and indestructible by ``_is_indestructible``,
    neither of which cares what type it is — so the only thing that changes is
    who is in the loop."""
    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    granted = 0
    for perm in game.controlled_by(caster_index):
        if not every_permanent and not perm.is_creature:
            continue
        for keyword in keywords:
            grant_keyword(perm, keyword, until_eot=True)
        granted += 1
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {granted} {noun} gain {', '.join(keywords)} until end of turn"
    )
    return True, "resolved"


@effect_handler("grant_team_assign_unblocked_until_eot")
def grant_team_assign_unblocked_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Garruk, Savage Herald's −7: creatures you control gain "You may have
    this creature assign its combat damage as though it weren't blocked" until
    end of turn. The combat damage step reads the flag; cleanup clears it (the
    key is in _EOT_METADATA_KEYS)."""
    caster_index = game.players.index(context.caster)
    granted = 0
    for perm in game.controlled_by(caster_index):
        if perm.is_creature:
            perm.metadata["assign_combat_damage_as_unblocked_until_eot"] = True
            granted += 1
    game.log.append(
        f"{context.card.name}: {granted} creature(s) may assign combat damage as though unblocked"
    )
    return True, "resolved"


@effect_handler("add_loyalty_counters")
def add_loyalty_counters(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a loyalty counter on Garruk." (Garruk, Unleashed's −2.) Loyalty on
    the battlefield IS its loyalty counters (CR 306.5c), the same key damage
    and loyalty costs adjust. The source may already have left — a walker that
    paid itself to 0 dies before its ability resolves — in which case the
    counter lands on nothing (CR 608.2b handles the analogous target)."""
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: its source has left, no loyalty added")
        return True, "resolved"
    count = int(instruction.payload.get("count", 1))
    loyalty = int(source.metadata.get("loyalty_counters", 0))
    source.metadata["loyalty_counters"] = loyalty + count
    game.log.append(
        f"{context.card.name}: {count} loyalty counter(s) added (now {loyalty + count})"
    )
    return True, "resolved"


@effect_handler("add_variable_power_counters_to_self")
def add_variable_power_counters_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Clockwork Beast: "{X}, {T}: Put up to X +1/+0 counters on this creature.
    # This ability can't cause the total number of +1/+0 counters on this
    # creature to be greater than seven."
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    current = int(source_permanent.metadata.get("plus_1_0_counters", 0))
    requested = max(0, context.x_value or 0)
    added = min(requested, max(0, 7 - current))
    if added:
        source_permanent.power_bonus += added
        source_permanent.metadata["plus_1_0_counters"] = current + added
    game.log.append(f"{card.name} gets {added} +1/+0 counter(s)")
    return True, "resolved"


@effect_handler("add_plus1_counters_for_each_creature_died")
def add_plus1_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Khabál Ghoul: "At the beginning of each end step, put a +1/+1 counter on
    this creature for each creature that died this turn." Resolves off the stack;
    the death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    game.place_plus1_counters(source, count)
    game.log.append(f"{source.card.name} gets {count} +1/+1 counter(s)")
    return True, "resolved"


@effect_handler("add_counter_to_self")
def add_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    game.place_plus1_counters(source_permanent)
    game.log.append(f"{card.name} gets a +1/+1 counter")
    return True, "resolved"


@effect_handler("add_counter_to_target")
def add_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on target creature", and on *each of up to N* target
    creatures.

    The kind Dwarven Weaponsmith's hook has always emitted (it resolved to
    nothing before this handler existed) and the grammar now lowers to as well.
    How many targets it takes is payload rather than a second instruction kind,
    because the effect is identical and only the count differs — the same reason
    a combat restriction carries its land type as data.

    The two counts take different resolvers on purpose. One target falls back to
    scanning when the chosen one is gone, which is the behaviour every
    single-target handler in the engine has; several are resolved strictly, so a
    dead target is dropped (CR 608.2b) rather than replaced by whichever creature
    the scan reached first — twice, if two slots decayed.
    """
    card = context.card
    targets = instruction.payload.get("targets") or {}
    maximum = targets.get("count") if isinstance(targets, dict) else None

    if isinstance(maximum, int) and maximum > 1:
        filters = targets.get("filter") or {}
        # The filter decides which permanents qualify, including "you control" —
        # asking it rather than assuming the caster's side is what keeps
        # "up to two target creatures" (Basri's Aegis, either side) and "up to
        # two other target creatures you control" (Basri's Acolyte) one handler.
        source = context.source_permanent

        def eligible(perm) -> bool:
            if not permanent_matches_filter(perm, filters):
                return False
            # "other" (CR 109.5's exclusion of the source) and "you control" are
            # both outside permanent_matches_filter's vocabulary — it answers
            # about a permanent alone, and these two need the source and the
            # board — so they are asked here rather than widened into it.
            if filters.get("exclude_self") and perm is source:
                return False
            if filters.get("controller") == "you" and not game.controls(context.caster, perm):
                return False
            return True

        chosen = resolve_target_permanents(game, context, predicate=eligible)
        if not chosen:
            # "Up to two" may legally name none, and every named target may have
            # become illegal since (CR 608.2b) — both resolve to nothing here.
            game.log.append(f"{card.name}: no creatures were given counters")
            return True, "resolved"
        for creature in chosen[:maximum]:
            game.place_plus1_counters(creature)
            game.log.append(f"{creature.card.name} gets a +1/+1 counter ({card.name})")
        return True, "resolved"

    filters = instruction.payload.get("targets", {}).get("filter") or {}

    def counter_target_legal(perm) -> bool:
        # "target creature with a +1/+1 counter on it" (Tempered Veteran): the
        # counter restriction is enforced at resolution too, so the fallback
        # scan can never land on a counterless creature.
        return perm.is_creature and permanent_matches_filter(perm, filters)

    target_creature = resolve_target_permanent(game, context, predicate=counter_target_legal)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    game.place_plus1_counters(target_creature)
    game.log.append(f"{target_creature.card.name} gets a +1/+1 counter ({card.name})")
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) Read *after* the placement, so the one just put down
    # is doubled too — and placed through the same seam, so a Conclave Mentor
    # raises the doubling exactly as it raised the first counter (CR 614).
    if instruction.payload.get("then_double"):
        existing = int(target_creature.metadata.get("plus_counters", 0))
        if existing:
            game.place_plus1_counters(target_creature, existing)
            game.log.append(
                f"{target_creature.card.name}'s +1/+1 counters doubled to "
                f"{target_creature.metadata.get('plus_counters', 0)} ({card.name})"
            )
    return True, "resolved"


@effect_handler("double_target_power_until_eot")
def double_target_power_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Double the power of target creature until end of turn." (Unleash Fury.)

    The power is read at resolution and added as an until-end-of-turn boost, so
    doubling a 3/3 that a Giant Growth already pumped doubles the *six*, not the
    printed three — which is what "double" means and what an amount fixed when
    the spell was cast could not express.
    """
    card = context.card
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda perm: perm.is_creature
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    power = target_creature.effective_power
    if power <= 0:
        # Doubling nothing (or a negative power) adds nothing: CR 107.1b has no
        # negative power on the battlefield, and +0/+0 is not worth logging as
        # an effect that happened.
        game.log.append(f"{card.name}: {target_creature.card.name} has no power to double")
        return True, "resolved"
    apply_temp_pt_boost(target_creature, power, 0)
    game.log.append(
        f"{card.name} doubled {target_creature.card.name}'s power to "
        f"{target_creature.effective_power}"
    )
    return True, "resolved"


@effect_handler("add_counter_to_each_you_control")
def add_counter_to_each_you_control(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on each creature you control." (Basri's
    Solidarity.) Read through the control seam, so a borrowed creature counts
    and a lost one does not."""
    card = context.card
    caster = context.caster
    for perm in game.controlled_by(caster):
        if not perm.is_creature:
            continue
        game.place_plus1_counters(perm)
    game.log.append(f"{card.name}: each creature {caster.name} controls gets a +1/+1 counter")
    return True, "resolved"


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    grant_keyword(source_permanent, "flying", until_eot=True)
    game.log.append(f"{card.name} gains flying until end of turn")
    return True, "resolved"


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        game.log.append(f"{target_creature.card.name} gains flying until end of turn from {card.name}")
    return True, "resolved"


@effect_handler("grant_target_keyword_until_eot")
def grant_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature gains <keyword(s)> until end of turn." The payload
    carries the words; the lowering admits only implemented keywords, so a
    grant here always grants behaviour that exists."""
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        grant_keyword(target_creature, keyword, until_eot=True)
    game.log.append(
        f"{target_creature.card.name} gains {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


@effect_handler("remove_target_keyword_until_eot")
def remove_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"It loses indestructible until end of turn." (Soul Sear — the pronoun
    binds the damage sentence's target.) `remove_keyword` puts the removal
    into layer 6, so it beats an older grant by timestamp and expires at
    cleanup with everything else until-end-of-turn."""
    card = context.card
    # The damage target may be a planeswalker, so no creature predicate: the
    # removal reaches whatever permanent the spell chose.
    target = resolve_target_permanent(game, context, predicate=lambda p: True)
    if target is None:
        game.log.append(f"{card.name}: no valid target to strip")
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        remove_keyword(target, keyword, until_eot=True)
    game.log.append(
        f"{target.card.name} loses {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


@effect_handler("grant_self_keyword_until_eot")
def grant_self_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature gains <keyword(s)> until end of turn." (Fetid Imp.)"""
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        grant_keyword(source_permanent, keyword, until_eot=True)
    game.log.append(
        f"{card.name} gains {' and '.join(keywords)} until end of turn"
    )
    return True, "resolved"


@effect_handler("grant_islandwalk_and_linked_destroy")
def grant_islandwalk_and_linked_destroy(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sandals of Abdallah: "Target creature gains islandwalk until end of
    turn. When that creature dies this turn, destroy this artifact." The grant
    is an until-end-of-turn layer-6 grant; the death link is recorded on the
    creature and drained by _permanent_to_graveyard + the state-based sweep."""
    card = context.card
    source_permanent = context.source_permanent
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    grant_keyword(target_creature, "islandwalk", until_eot=True)
    if source_permanent is not None:
        links = target_creature.metadata.setdefault("on_death_destroy_permanents", [])
        if source_permanent not in links:
            links.append(source_permanent)
    game.log.append(f"{target_creature.card.name} gains islandwalk until end of turn ({card.name})")
    return True, "resolved"


@effect_handler("set_base_pt_target_until_eot")
def set_base_pt_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sorceress Queen ("has base power and toughness 0/2") / Singing Tree
    ("has base power 0", toughness untouched). ``payload["toughness"]`` is
    None when the ability only sets power."""
    card = context.card
    source_permanent = context.source_permanent
    exclude_self = bool(instruction.payload.get("exclude_self"))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    flying_only = bool(instruction.payload.get("flying_only"))

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        if exclude_self and source_permanent is not None and perm is source_permanent:
            return False
        if attacking_only and not perm.attacking:
            return False
        if flying_only and not game._has_keyword(perm, "flying"):
            return False
        return True

    target_perm = resolve_target_permanent(game, context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"

    power = instruction.payload.get("power")
    toughness = instruction.payload.get("toughness")
    set_base_pt(target_perm, power, toughness, until_eot=True)
    if toughness is None:
        game.log.append(f"{card.name}: {target_perm.card.name} has base power {power} until end of turn")
    else:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base power and toughness {power}/{toughness} until end of turn"
        )
    return True, "resolved"


@effect_handler("grant_flying_and_delayed_destruction")
def grant_flying_and_delayed_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _is_legal(perm) -> bool:
        return (
            perm.is_creature
            and perm.effective_toughness < source_permanent.effective_power
        )

    # Honor the player-chosen creature (Stone Giant targets "target creature you
    # control with toughness less than this creature's power"). Fall back to the
    # first legal creature only for AI/untargeted activations — an explicitly
    # chosen illegal target fizzles.
    target_creature = resolve_target_permanent(
        game, context, player=caster, predicate=_is_legal, fallback_on_invalid_choice=False
    )
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        target_creature.metadata["destroy_at_next_end_step"] = True
        game.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
    else:
        game.log.append("No valid target for Stone Giant effect")
    return True, "resolved"
