from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import CardDefinition, Permanent
from ..oracle_types import OracleInstruction
from ..pt import set_base_pt
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
    dealt = game._deal_damage_to_player(caster, amount, source=source)
    game.log.append(f"{source.card.name} dealt {dealt} damage to {caster.name}")
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

    game.pending_balance = {"plans": plans}
    game.log.append("Balance: each player chooses what to sacrifice and discard")
    return True, "pending_balance"


# Mana symbol → the basic land type Magical Hack swaps a land to (CR 305.7). The
# chosen replacement type is passed through as the cast's "new color".
_SYMBOL_TO_LAND_TYPE = {
    "W": "plains",
    "U": "island",
    "B": "swamp",
    "R": "mountain",
    "G": "forest",
}


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
    new_symbol = (context.new_color or "").upper()
    old_symbol = (context.old_color or "").upper()

    # Magical Hack: replace one basic land type with another. On a land this swaps
    # the land type (and the mana it makes); on a creature it remaps that landwalk
    # (swampwalk → islandwalk). It does NOT change the permanent's color.
    if mode == "land_type":
        new_type = _SYMBOL_TO_LAND_TYPE.get(new_symbol)
        old_type = _SYMBOL_TO_LAND_TYPE.get(old_symbol)
        if target_perm is not None and new_type:
            if target_perm.card.primary_type == "land":
                # The replaced word must actually appear in the land's current
                # type (its override, if one is already in effect, else the
                # printed type line) — replacing an absent word is a no-op.
                current_type = str(
                    target_perm.metadata.get("land_type_override") or target_perm.card.type_line
                ).lower()
                if old_type is not None and old_type not in current_type:
                    game.log.append(
                        f"{card.name} had no effect: {target_perm.card.name} has no {old_type.title()} land type"
                    )
                    return True, "resolved"
                target_perm.metadata["land_type_override"] = new_type
                game.log.append(f"{card.name} changed {target_perm.card.name} into a {new_type.title()}")
            elif target_perm.is_creature:
                # Magical Hack rewrites existing words: the old land type must
                # actually appear in the creature's printed text. That covers a
                # printed landwalk (Bog Wraith's "Swampwalk") AND a land word
                # inside a granted ability (Goblin King's "Other Goblins get
                # +1/+1 and have mountainwalk.") — but never grants islandwalk
                # from nothing (White Knight).
                printed_text = (target_perm.card.oracle_text or "").lower()
                if old_type and old_type in printed_text:
                    # Word-level remap: read wherever the engine interprets this
                    # card's text (lord walk grants) and shown by the UI as a
                    # struck-out/replacement text edit.
                    remap = target_perm.metadata.setdefault("land_word_remap", {})
                    remap[old_type] = new_type
                    # A landwalk the creature itself has also swaps as a keyword.
                    if game._has_keyword(target_perm, f"{old_type}walk"):
                        target_perm.metadata[f"has_{new_type}walk"] = True
                        target_perm.metadata[f"lost_{old_type}walk"] = True
                    game.log.append(f"{card.name} changed {old_type} to {new_type} in {target_perm.card.name}'s text")
                    game._recalculate_lord_buffs()
                else:
                    game.log.append(
                        f"{card.name} had no effect: {target_perm.card.name} has no"
                        f" {old_type.title() if old_type else 'matching'} land type in its text"
                    )
        return True, "resolved"

    # Sleight of Mind: replace one color word with another in the target's text.
    # Stored as a per-permanent remap consumed where the engine reads that text's
    # color (e.g. protection from <color>). It does NOT recolor the permanent.
    if mode == "color_word":
        if target_perm is not None and old_symbol and new_symbol:
            remap = target_perm.metadata.setdefault("color_word_remap", {})
            remap[old_symbol] = new_symbol
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
        context.stack_target.new_color = symbol
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
        target_land.metadata["land_type_override"] = str(instruction.payload.get("land_type", "forest"))
        game.log.append(f"{target_land.card.name} became a Forest")
        # "...until this creature leaves the battlefield." Track the lands this
        # source forested so the revert hook can undo them when it leaves (CR 611.3).
        source = context.source_permanent
        if source is not None:
            forested = source.metadata.setdefault("forested_lands", [])
            if target_land not in forested:
                forested.append(target_land)
        # Forest count just changed; recompute characteristic-defining P/T now so
        # Gaea's Liege reflects the new total immediately (not at the next step).
        game._refresh_dynamic_creatures()
    else:
        game.log.append("No target land for Forest effect")
    return True, "resolved"


def _is_swamp(perm: Permanent) -> bool:
    return (
        "swamp" in perm.card.type_line.lower()
        or perm.metadata.get("land_type_override") == "swamp"
    )


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
    target_land.metadata["land_type_override"] = "swamp"
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
    dealt = game._deal_damage_to_player(caster, amount, source=card)
    game.log.append(f"{card.name} dealt {dealt} damage to {caster.name}")
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
    game.pending_face_down_cast = {
        "player_index": controller_index,
        "max_cmc": max_cmc,
        "card_name": card.name,
    }
    game.log.append(f"{card.name}: choose a creature (mana value <= {max_cmc}) to cast face down")
    return True, "resolved"
