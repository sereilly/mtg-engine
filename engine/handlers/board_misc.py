from __future__ import annotations

from typing import TYPE_CHECKING

from ..land_types import MIRE_COUNTER, change_land_type
from ..models import CardDefinition, Permanent
from ..oracle_types import OracleInstruction
from ..pt import set_base_pt
from ..text_changes import LAND_TYPE_WORDS, change_color_word, change_land_word
from ..tokens import make_token_card
from ._common import flip_coin, resolve_amount, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


@effect_handler("steal_target_permanent_linked_to_self")
def steal_target_permanent_linked_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Aladdin: "Gain control of target artifact for as long as you control
    this creature." The theft is recorded on Aladdin itself (not an Aura), so
    ON_LEAVE_BATTLEFIELD["Aladdin"] can revert it via _revert_stolen_permanent
    when Aladdin leaves the battlefield."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # Guardian Beast: "other players can't gain control of" the artifacts it
    # protects.
    target_perm = resolve_target_permanent(
        context,
        predicate=lambda p: p.has_type("artifact") and not game._untapped_artifact_protector_active(p),
    )
    if target_perm is None:
        game.log.append(f"{card.name}: no valid artifact target")
        return True, "resolved"
    if not game._take_control_linked(source_permanent, target_perm, caster):
        return True, "resolved"
    game.log.append(f"{card.name} gains control of {target_perm.card.name}")
    return True, "resolved"


@effect_handler("steal_creature_while_tapped_and_weaker")
def steal_creature_while_tapped_and_weaker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Old Man of the Sea: "Gain control of target creature with power less
    than or equal to this creature's power for as long as this creature
    remains tapped and that creature's power remains less than or equal to
    this creature's power." Both revert conditions are re-checked
    continuously by the game_ending.py SBA-style check (stolen_while_tapped_
    and_weaker marks this as that specific steal, distinct from Aladdin's
    single-condition linked duration)."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _eligible(perm: Permanent) -> bool:
        return perm.is_creature and perm.effective_power <= source_permanent.effective_power

    target_perm = resolve_target_permanent(context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    if not game._take_control_linked(
        source_permanent,
        target_perm,
        caster,
        extra_meta={"stolen_while_tapped_and_weaker": True},
    ):
        return True, "resolved"
    game.log.append(f"{card.name} gains control of {target_perm.card.name}")
    return True, "resolved"


@effect_handler("add_corpse_counters_for_each_creature_died")
def add_corpse_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Scavenging Ghoul: "At the beginning of each end step, put a corpse counter on
    this creature for each creature that died this turn." Resolves off the stack; the
    death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    source.metadata["corpse_counters"] = int(source.metadata.get("corpse_counters", 0)) + count
    game.log.append(f"{source.card.name} gets {count} corpse counter(s)")
    return True, "resolved"


@effect_handler("sacrifice_if_no_creatures")
def sacrifice_if_no_creatures(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pestilence-style: "At the beginning of the end step, if there are no creatures
    on the battlefield, sacrifice this." Resolves off the stack; the intervening-if is
    re-checked at resolution (CR 603.4)."""
    source = context.source_permanent
    if source is None:
        return True, "resolved"
    has_creatures = any(
        p.is_creature for pl in game.players for p in pl.battlefield
    )
    if has_creatures:
        return True, "resolved"
    for pl in game.players:
        if source in pl.battlefield:
            pl.battlefield.remove(source)
            pl.graveyard.append(source.card)
            game.log.append(f"{source.card.name} sacrificed at end step (no creatures)")
            break
    return True, "resolved"


@effect_handler("end_step_damage_if_not_attacked")
def end_step_damage_if_not_attacked(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Erg Raiders: "At the beginning of your end step, if this creature
    didn't attack this turn, it deals 2 damage to you unless it came under
    your control this turn." Both guards are re-checked at resolution (CR
    603.4), matching the Pestilence intervening-if precedent."""
    source = context.source_permanent
    caster = context.caster
    if source is None or caster is None:
        return True, "resolved"
    if source.metadata.get("attacked_this_turn"):
        return True, "resolved"
    if source.metadata.get("summoning_sickness_turn") == game.turn:
        return True, "resolved"
    amount = int(instruction.payload.get("amount", 0))
    game._deal_damage_to_player(
        caster, amount, source=source,
        then=lambda dealt: game.log.append(
            f"{source.card.name} dealt {dealt} damage to {caster.name}"
        ),
    )
    return True, "resolved"


@effect_handler("balance_resources")
def balance_resources(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    def _count(player, kind):
        return sum(1 for perm in player.battlefield if perm.card.primary_type == kind)

    min_lands = min(_count(p, "land") for p in game.players)
    min_creatures = min(_count(p, "creature") for p in game.players)
    min_hand = min(len(p.hand) for p in game.players)

    # Build the per-player reduction plan. Each player chooses which of their own
    # lands/creatures to sacrifice and which cards to discard down to these counts;
    # defer to a pending choice (human is prompted, AI/headless auto-resolves).
    plans: dict[int, dict] = {}
    for idx, player in enumerate(game.players):
        plan = {
            "lands": max(0, _count(player, "land") - min_lands),
            "creatures": max(0, _count(player, "creature") - min_creatures),
            "hand": max(0, len(player.hand) - min_hand),
        }
        if plan["lands"] or plan["creatures"] or plan["hand"]:
            plans[idx] = plan

    if not plans:
        game.log.append("Balance: nothing to normalize")
        return True, "resolved"

    # Each player owes their own removals, so each gets their own queued choice.
    for idx, plan in plans.items():
        game.arm_pending_choice("balance", idx, plan=plan)
    game.log.append("Balance: each player chooses what to sacrifice and discard")
    return True, "pending_balance"


# Mana symbol → the basic land type Magical Hack names. The chosen replacement
# type is passed through as the cast's "new color"; the mapping itself lives
# with the text-change API, which is what has to know the words.
_SYMBOL_TO_LAND_TYPE = LAND_TYPE_WORDS


@effect_handler("mark_text_modified")
def mark_text_modified(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    # Resolve the actual targeted permanent (default to the first one).
    target_perm = None
    if perm_idx is not None and 0 <= perm_idx < len(target.battlefield):
        target_perm = target.battlefield[perm_idx]
    elif target.battlefield:
        target_perm = target.battlefield[0]
    if target_perm is not None:
        target_perm.metadata["text_modified"] = True

    mode = instruction.payload.get("mode")
    new_symbol = (context.choices.get("new_color") or "").upper()
    old_symbol = (context.choices.get("old_color") or "").upper()

    # Magical Hack: "replacing all instances of one basic land type with
    # another". One text change (CR 612.1 / 613 layer 3), whatever the permanent
    # is: on a land the word is in the type line, so the land's subtypes and the
    # mana ability CR 305.6 gives it change; on a creature it is in the rules
    # text, so "swampwalk" becomes "islandwalk" — including inside a lord's
    # grant line. It does NOT change the permanent's color.
    if mode == "land_type":
        new_type = _SYMBOL_TO_LAND_TYPE.get(new_symbol)
        old_type = _SYMBOL_TO_LAND_TYPE.get(old_symbol)
        if old_type is None and target_perm is not None:
            # A cast that named only the replacement (a headless or AI cast, and
            # every call site before the "from" word existed): on a land the
            # word being replaced can only be the type it currently has.
            current = target_perm.basic_land_types
            old_type = current[0] if len(current) == 1 else None
        if target_perm is not None and new_type and old_type:
            # Magical Hack rewrites existing words: the old land type must
            # actually be written somewhere on the permanent. That covers a
            # printed type line ("Basic Land — Mountain"), a printed landwalk
            # (Bog Wraith's "Swampwalk") and a land word inside a granted
            # ability (Goblin King's "Other Goblins … have mountainwalk") — but
            # never grants islandwalk from nothing (White Knight). The
            # *effective* text, so a second Hack rewrites what the first wrote.
            effective = target_perm.effective_card
            written = " ".join(
                (effective.type_line, effective.oracle_text, *effective.keywords)
            ).lower()
            if old_type in written:
                change_land_word(target_perm, old_type, new_type, label=card.name)
                game.log.append(
                    f"{card.name} changed {old_type} to {new_type} in {target_perm.card.name}'s text"
                )
                game._recalculate_lord_buffs()
            else:
                game.log.append(
                    f"{card.name} had no effect: {target_perm.card.name} has no"
                    f" {old_type.title()} land type in its text"
                )
        return True, "resolved"

    # Sleight of Mind: replace one color word with another in the target's text.
    # Recorded as an ordered layer-3 contribution and applied once, by
    # Permanent.effective_card. It does NOT recolor the permanent.
    if mode == "color_word":
        if target_perm is not None and change_color_word(
            target_perm, old_symbol, new_symbol, label=card.name
        ):
            game.log.append(f"{card.name} changed {old_symbol} text to {new_symbol} on {target_perm.card.name}")
        return True, "resolved"

    game.log.append(f"{card.name} applied a text change effect")
    return True, "resolved"


@effect_handler("recolor_target_from_text")
def recolor_target_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    symbol = str(instruction.payload.get("target_color", ""))
    # "Target spell or permanent becomes [color]" — a spell on the stack is a
    # legal target (the Lace cards). Recolor it via the stack item's color override.
    if context.stack_target is not None and symbol:
        context.stack_target.choices["new_color"] = symbol
        game.log.append(f"{context.stack_target.card.name} (on the stack) became {symbol}")
        return True, "resolved"
    target = context.target
    perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    changed = game._apply_color_override(target, symbol, target_permanent_index=perm_idx) if symbol else False
    game.log.append("Changed target color" if changed else "No valid permanent to recolor")
    return True, "resolved"


@effect_handler("change_target_land_type")
def change_target_land_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Honor a specifically chosen land (e.g. a player selected the target land
    # in the UI). Fall back to the first land the target player controls.
    target_land = resolve_target_permanent(
        context, predicate=lambda p: p.card.primary_type == "land"
    )
    if target_land is not None:
        land_type = str(instruction.payload.get("land_type", "forest"))
        # "...until this creature leaves the battlefield." The contribution is
        # keyed on the source, so the revert hook drops exactly this one and
        # whatever else says the land is something (an Evil Presence Swamp)
        # reasserts itself (CR 611.3).
        source = context.source_permanent
        change_land_type(
            target_land, land_type, source=source, label=context.card.name
        )
        game.log.append(f"{target_land.card.name} became a Forest")
        if source is not None:
            forested = source.metadata.setdefault("forested_lands", [])
            if not any(land is target_land for land in forested):
                forested.append(target_land)
        # Forest count just changed; recompute characteristic-defining P/T now so
        # Gaea's Liege reflects the new total immediately (not at the next step).
        game._refresh_dynamic_creatures()
    else:
        game.log.append("No target land for Forest effect")
    return True, "resolved"


def _is_swamp(perm: Permanent) -> bool:
    return perm.has_type("swamp")


@effect_handler("add_mire_counter_to_target_land")
def add_mire_counter_to_target_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Cyclopean Tomb: "Put a mire counter on target non-Swamp land. That land is
    a Swamp for as long as it has a mire counter on it."

    The mire counter both flags the land and overrides its type to Swamp (CR 305.7).
    The source artifact records each land it mires so its rest-of-game cleanup
    trigger (see ON_LEAVE_BATTLEFIELD) knows which lands to undo when it dies.
    """
    # Honor the explicitly chosen land when one was targeted.
    target_land = resolve_target_permanent(
        context, predicate=lambda p: p.card.primary_type == "land" and not _is_swamp(p)
    )
    if target_land is None:
        game.log.append("No valid non-Swamp land for mire counter")
        return True, "resolved"

    target_land.metadata["mire_counter"] = True
    # Keyed on the counter, not on the Tomb: "for as long as it has a mire
    # counter on it" outlives the artifact that put it there.
    change_land_type(
        target_land, "swamp", source=MIRE_COUNTER, label=context.card.name
    )
    game.log.append(f"{target_land.card.name} got a mire counter and became a Swamp")

    # Remember this land on the activating artifact so its death trigger can later
    # remove the mire counter "for the rest of the game".
    source = context.source_permanent
    if source is not None:
        mired = source.metadata.setdefault("mired_lands", [])
        if target_land not in mired:
            mired.append(target_land)
    return True, "resolved"


@effect_handler("animate_self_until_end_of_combat")
def animate_self_until_end_of_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    set_base_pt(
        source_permanent,
        int(instruction.payload.get("power", 0)),
        int(instruction.payload.get("toughness", 0)),
    )
    source_permanent.metadata["animate_until_end_of_combat"] = True
    game.log.append(f"{card.name} is animated until end of combat")
    return True, "resolved"


@effect_handler("create_token")
def create_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Generic token creation: payload carries name / P/T / type_line / colors /
    keywords / count ("x" resolves to the cast's X). Tokens are stamped
    ``is_token`` so they cease to exist instead of hitting the graveyard
    (CR 704.5d / 111.7)."""
    caster = context.caster
    card = context.card
    payload = instruction.payload
    controller_index = game.players.index(caster)
    token_card = make_token_card(
        str(payload.get("name", "Token")),
        int(payload.get("power", 1)),
        int(payload.get("toughness", 1)),
        str(payload.get("type_line", "Creature — Token")),
        colors=tuple(payload.get("colors") or ()),
        keywords=tuple(payload.get("keywords") or ()),
        image_source=card,
    )
    count = resolve_amount(payload.get("count", 1), context.x_value)
    for _ in range(count):
        game._put_permanent_onto_battlefield(
            controller_index, Permanent(card=token_card, metadata={"is_token": True}), None
        )
    if count == 1:
        game.log.append(f"{card.name} created a {token_card.name} token")
    elif count > 1:
        game.log.append(f"{card.name} created {count} {token_card.name} tokens")
    return True, "resolved"


@effect_handler("coin_flip_token_or_self_damage")
def coin_flip_token_or_self_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Bottle of Suleiman: "Flip a coin. If you win the flip, create a 5/5
    colorless Djinn artifact creature token with flying. If you lose the flip,
    this artifact deals 5 damage to you." (CR 705) The losing branch damages the
    ability's *controller*, not an opponent — "you" is the flipper."""
    caster = context.caster
    card = context.card
    payload = instruction.payload
    if flip_coin():
        game.log.append(f"{card.name}: won the coin flip")
        return create_token(game, OracleInstruction("create_token", "", dict(payload)), context)
    amount = int(payload.get("damage", 0))
    game.log.append(f"{card.name}: lost the coin flip")
    game._deal_damage_to_player(
        caster, amount, source=card,
        then=lambda dealt: game.log.append(
            f"{card.name} dealt {dealt} damage to {caster.name}"
        ),
    )
    return True, "resolved"


@effect_handler("cast_face_down_creature")
def cast_face_down_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Illusionary Mask: arm a pending choice for the controller to pick a creature
    card in hand whose mana cost X could pay (cmc <= X), to cast face down as a 2/2.
    The actual cast happens in confirm_face_down_cast; the choice is optional."""
    caster = context.caster
    card = context.card
    controller_index = game.players.index(caster)
    max_cmc = max(0, int(context.x_value or 0))
    eligible = [c for c in caster.hand if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc]
    if not eligible:
        game.log.append(f"{card.name}: no eligible creature in hand to cast face-down (X={max_cmc})")
        return True, "resolved"
    game.arm_pending_choice(
        "face_down_cast", controller_index, max_cmc=max_cmc, card_name=card.name
    )
    game.log.append(f"{card.name}: choose a creature (mana value <= {max_cmc}) to cast face down")
    return True, "resolved"


@effect_handler("remove_counter_from_self")
def remove_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Armageddon Clock: "Remove a doom counter from this artifact."

    The counter's name is payload, matching the accumulation side
    (phases/upkeep_effects.py), so the pair is one template rather than a card.
    Removing from zero is a no-op, not a negative count.
    """
    permanent = context.source_permanent
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "doom"))
    key = f"{counter}_counters"
    current = int(permanent.metadata.get(key, 0))
    if current <= 0:
        game.log.append(f"{permanent.card.name} has no {counter} counter to remove")
        return True, "resolved"
    permanent.metadata[key] = current - 1
    game.log.append(
        f"Removed a {counter} counter from {permanent.card.name} "
        f"({permanent.metadata[key]} left)"
    )
    return True, "resolved"
