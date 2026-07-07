from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("drain_target_lands_mana")
def drain_target_lands_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    # Tap each of target's untapped lands and collect the mana they would produce
    mana_gained: dict[str, int] = {}
    for perm in target.battlefield:
        if perm.card.primary_type != "land" or perm.tapped:
            continue
        perm.tapped = True
        if perm.card.produced_mana:
            sym = perm.card.produced_mana[0].upper()
        else:
            land_type = str(perm.metadata.get("land_type_override", "")).lower() or perm.card.type_line.lower()
            if "plains" in land_type:
                sym = "W"
            elif "island" in land_type:
                sym = "U"
            elif "swamp" in land_type:
                sym = "B"
            elif "mountain" in land_type:
                sym = "R"
            elif "forest" in land_type:
                sym = "G"
            else:
                sym = "C"
        mana_gained[sym] = mana_gained.get(sym, 0) + 1
    # Drain any existing unspent mana from target's pool too
    for sym in ("W", "U", "B", "R", "G", "C"):
        pool_amount = target.mana_pool.get(sym, 0)
        if pool_amount > 0:
            mana_gained[sym] = mana_gained.get(sym, 0) + pool_amount
            target.mana_pool[sym] = 0
    # Add all drained mana to caster
    for sym, amount_gained in mana_gained.items():
        caster.mana_pool[sym] = caster.mana_pool.get(sym, 0) + amount_gained
    total = sum(mana_gained.values())
    game.log.append(f"{card.name} drained {total} mana from {target.name}")
    return True, "resolved"


@effect_handler("sacrifice_creature_for_black_mana")
def sacrifice_creature_for_black_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sacrifice (LEA): "Add an amount of {B} equal to the sacrificed
    creature's mana value." Metamorphosis (ARN): "Add X mana of any one color,
    where X is 1 plus the sacrificed creature's mana value." Both share the
    additional-cost parse; the amount bump and the color choice are read from
    the card's own text (the chosen color rides context.new_color, like the
    laces' color choice)."""
    caster = context.caster
    chosen = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    sacrificed = game._sacrifice_creature_for_mana(caster, chosen_index=chosen)
    if sacrificed is None:
        game.log.append(f"{caster.name} had no creature to sacrifice")
        return True, "resolved"
    text = (context.card.oracle_text or "").lower()
    amount = int(sacrificed.cmc)
    if "1 plus the sacrificed creature's mana value" in text:
        amount += 1
    symbol = "B"
    color_word = "black"
    if "mana of any one color" in text:
        symbol = game._normalize_mana_color(context.new_color) or "G"
        color_word = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}.get(symbol, symbol)
    if "spend this mana only to cast creature spells" in text:
        # Metamorphosis: the mana goes into the creature-spells-only bucket,
        # merged into payments by _pay_mana_cost only for creature spells.
        caster.creature_only_mana[symbol] = caster.creature_only_mana.get(symbol, 0) + amount
        game.log.append(
            f"{caster.name} sacrificed {sacrificed.name} for {amount} {color_word} mana "
            "(spendable only on creature spells)"
        )
    else:
        caster.mana_pool[symbol] = caster.mana_pool.get(symbol, 0) + amount
        game.log.append(f"{caster.name} sacrificed {sacrificed.name} for {amount} {color_word} mana")
    return True, "resolved"


@effect_handler("sacrifice_self_for_mana")
def sacrifice_self_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    caster.mana_pool[str(instruction.payload.get("color", "G"))] += int(instruction.payload.get("amount", 0))
    caster.graveyard.append(source_permanent.card)
    caster.battlefield = [perm for perm in caster.battlefield if perm is not source_permanent]
    game.log.append(f"{card.name} sacrificed for mana")
    return True, "resolved"


@effect_handler("add_mana_from_text")
def add_mana_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    game._add_mana_from_text(
        caster,
        str(instruction.payload.get("oracle_text", card.oracle_text)),
        preferred_color=str(instruction.payload.get("color", "")) or None,
    )
    game.log.append(f"{card.name} produced mana")
    return True, "resolved"


@effect_handler("channel_life_for_mana")
def channel_life_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster.channel_active_until_eot = True
    game.log.append(f"{caster.name} may pay life for {{C}} mana until end of turn (Channel)")
    return True, "resolved"
