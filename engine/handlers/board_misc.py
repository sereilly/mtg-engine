from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import CardDefinition, Permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _token_image_uris(source_card: CardDefinition, token_name: str) -> dict[str, str] | None:
    """Resolve a token's Scryfall image URLs from its creating card's ``all_parts``.

    Scryfall image URLs are derivable from a card's id, so we only need the id
    that ``all_parts`` records for the token component — no network call. Returns
    None when the source card has no matching token part (e.g. minimal raw data).
    """
    raw = source_card.raw
    if not isinstance(raw, dict):
        return None
    for part in raw.get("all_parts") or ():
        if not isinstance(part, dict):
            continue
        if part.get("component") == "token" and part.get("name") == token_name:
            card_id = part.get("id")
            if not isinstance(card_id, str) or len(card_id) < 2:
                continue
            base = f"{card_id[0]}/{card_id[1]}/{card_id}.jpg"
            return {
                size: f"https://cards.scryfall.io/{size}/front/{base}"
                for size in ("small", "normal", "large", "art_crop", "border_crop")
            }
    return None


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

    symbol = (context.new_color or "").upper()
    # Magical Hack on a land swaps one basic land type for another, changing the
    # mana it produces (Forest → Island taps for blue). This replaces the land's
    # type, not its color, so set a land-type override rather than a color override.
    if target_perm is not None and target_perm.card.primary_type == "land" and symbol in _SYMBOL_TO_LAND_TYPE:
        new_type = _SYMBOL_TO_LAND_TYPE[symbol]
        target_perm.metadata["land_type_override"] = new_type
        game.log.append(f"{card.name} changed {target_perm.card.name} into a {new_type.title()}")
        return True, "resolved"

    # Otherwise (spell or non-land permanent) apply a color override when one was chosen.
    if symbol:
        game._apply_color_override(target, symbol, target_permanent_index=perm_idx)
        game.log.append(f"{card.name} changed target's color to {symbol}")
    else:
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
    target = context.target
    target_land = None
    # Honor a specifically chosen land (e.g. a player selected the target land
    # in the UI). Fall back to the first land the target player controls.
    chosen_index = context.target_permanent_index
    if isinstance(chosen_index, int) and 0 <= chosen_index < len(target.battlefield):
        candidate = target.battlefield[chosen_index]
        if candidate.card.primary_type == "land":
            target_land = candidate
    if target_land is None:
        target_land = next((perm for perm in target.battlefield if perm.card.primary_type == "land"), None)
    if target_land is not None:
        target_land.metadata["land_type_override"] = str(instruction.payload.get("land_type", "forest"))
        game.log.append(f"{target_land.card.name} became a Forest")
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
    target = context.target
    target_land = None
    chosen_index = context.target_permanent_index
    # Honor the explicitly chosen land when one was targeted.
    if isinstance(chosen_index, int) and 0 <= chosen_index < len(target.battlefield):
        candidate = target.battlefield[chosen_index]
        if candidate.card.primary_type == "land" and not _is_swamp(candidate):
            target_land = candidate
    if target_land is None:
        target_land = next(
            (
                perm
                for perm in target.battlefield
                if perm.card.primary_type == "land" and not _is_swamp(perm)
            ),
            None,
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
    source_permanent.metadata["absolute_power"] = int(instruction.payload.get("power", 0))
    source_permanent.metadata["absolute_toughness"] = int(instruction.payload.get("toughness", 0))
    source_permanent.metadata["animate_until_end_of_combat"] = True
    game.log.append(f"{card.name} is animated until end of combat")
    return True, "resolved"


@effect_handler("create_wasp_token")
def create_wasp_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    controller_index = game.players.index(caster)
    raw = {"name": "Wasp", "type_line": "Artifact Creature — Insect", "power": "1", "toughness": "1"}
    image_uris = _token_image_uris(card, "Wasp")
    if image_uris is not None:
        raw["image_uris"] = image_uris
    wasp = CardDefinition(
        name="Wasp",
        mana_cost="",
        cmc=0.0,
        type_line="Artifact Creature — Insect",
        oracle_text="Flying",
        colors=(),
        color_identity=(),
        keywords=("Flying",),
        produced_mana=(),
        raw=raw,
    )
    game._put_permanent_onto_battlefield(controller_index, Permanent(card=wasp), None)
    game.log.append(f"{card.name} created a Wasp token")
    return True, "resolved"


@effect_handler("cast_face_down_creature")
def cast_face_down_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    controller_index = game.players.index(caster)
    creature_card = next(
        (c for c in caster.hand if c.primary_type == "creature"),
        None,
    )
    if creature_card is None:
        game.log.append(f"{card.name}: no creature in hand to cast face-down")
        return True, "resolved"
    caster.hand.remove(creature_card)
    face_down = CardDefinition(
        name=creature_card.name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": creature_card.name, "type_line": "Creature", "power": "2", "toughness": "2"},
    )
    perm = Permanent(card=face_down)
    perm.metadata["face_down"] = True
    game._put_permanent_onto_battlefield(controller_index, perm, None)
    game.log.append(f"{card.name} cast {creature_card.name} face-down as a 2/2 creature")
    return True, "resolved"
