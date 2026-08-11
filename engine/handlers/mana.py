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
    for perm in game.controlled_by(target):
        if perm.card.primary_type != "land" or perm.tapped:
            continue
        game.become_tapped(perm)
        if perm.card.produced_mana:
            sym = perm.card.produced_mana[0].upper()
        else:
            symbols = perm.basic_land_mana
            sym = symbols[0] if symbols else "C"
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


_COLOR_WORDS = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


@effect_handler("sacrifice_creature_for_mana")
def sacrifice_creature_for_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"As an additional cost to cast this spell, sacrifice a creature." plus
    the mana that cost buys.

    Two cards print it and they differ in three ways, so all three are payload:

    ``color``       the mana symbol produced, or None when the card says "of any
                    one color" and the caster picks (the pick rides
                    ``context.choices["new_color"]``, like the laces' colour).
    ``bonus``       added to the sacrificed creature's mana value — Sacrifice
                    adds 0, Metamorphosis's "1 plus …" adds 1.
    ``spend_only``  the spell type the mana is locked to, or None for unrestricted
                    pool mana. Metamorphosis's "Spend this mana only to cast
                    creature spells" is ``"creature"``.

    All three used to be decided by ``in`` probes against the resolving card's
    own oracle text inside this handler, which made the card's *name* the only
    thing keeping Metamorphosis off Sacrifice's effect — a second parser living
    in a handler, and the exact shape ``engine/parsing/`` was deleted to remove.
    """
    caster = context.caster
    chosen = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    sacrificed_perm = game._sacrifice_creature_for_mana(caster, chosen_index=chosen)
    if sacrificed_perm is None:
        game.log.append(f"{caster.name} had no creature to sacrifice")
        return True, "resolved"
    sacrificed = sacrificed_perm.card
    amount = int(sacrificed.cmc) + int(instruction.payload.get("bonus", 0))
    payload_color = instruction.payload.get("color")
    if payload_color:
        symbol = str(payload_color)
    else:
        # "of any one color": the caster's pick, defaulting to the card's own
        # colour when no choice reached the stack (AI seats, headless scripts).
        symbol = game._normalize_mana_color(context.choices.get("new_color")) or "G"
    color_word = _COLOR_WORDS.get(symbol, symbol)
    spend_only = instruction.payload.get("spend_only")
    if spend_only == "creature":
        # The mana goes into the creature-spells-only bucket, merged into
        # payments by _pay_mana_cost only for creature spells.
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
    """Black Lotus: "{T}, Sacrifice this artifact: Add three mana of any one
    color." The sacrifice is a *cost*, paid by queue_permanent_ability's
    ``sacrifice_self`` branch before this runs — this only adds the mana."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    caster.mana_pool[str(instruction.payload.get("color", "G"))] += int(instruction.payload.get("amount", 0))
    # Belt and braces for callers that reach this handler without going through
    # the cost path (direct handler invocation in tests/scripts).
    if game.controls(caster, source_permanent):
        game.remove_from_battlefield(source_permanent)
        caster.graveyard.append(source_permanent.card)
    game.log.append(f"{card.name} sacrificed for mana")
    return True, "resolved"


@effect_handler("add_mana_from_text")
def add_mana_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Add mana to the controller's pool.

    Prefers a structured ``pips`` payload — ``(("G", 1), ("C", 2))`` — over
    re-reading the clause text. The text path remains for instructions the
    legacy rules produce, which carry the clause rather than what it means; it
    is one of the engine's inline oracle-text probes and goes away with them.
    """
    caster = context.caster
    card = context.card

    pips = instruction.payload.get("pips")
    if pips:
        added: list[str] = []
        for symbol, count in pips:
            if symbol not in caster.mana_pool:
                continue
            caster.mana_pool[symbol] += int(count)
            added.append(f"{{{symbol}}}" * int(count))
        game.log.append(f"{card.name} produced {''.join(added)}")
        return True, "resolved"

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
