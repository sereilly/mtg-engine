from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..models import Permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("draw_target_cards")
def draw_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    x_value = context.x_value
    amount = instruction.payload.get("amount", 0)
    count = max(0, x_value or 0) if amount == "x" else int(amount)
    drawn = target.draw(count)
    game.log.append(f"{target.name} drew {drawn} cards")
    return True, "resolved"


@effect_handler("draw_controller_cards")
def draw_controller_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    drawn = caster.draw(int(instruction.payload.get("amount", 0)))
    game.log.append(f"{card.name} drew {drawn} card")
    return True, "resolved"


@effect_handler("discard_hand_ante_then_draw_seven")
def discard_hand_ante_then_draw_seven(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    while caster.hand:
        caster.graveyard.append(caster.hand.pop(0))
    if caster.library:
        caster.graveyard.append(caster.library.pop(0))
    drawn = caster.draw(7)
    game.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
    return True, "resolved"


@effect_handler("each_player_antes_top_card")
def each_player_antes_top_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    anted = 0
    for player in game.players:
        if player.library:
            player.graveyard.append(player.library.pop(0))
            anted += 1
    game.log.append(f"{card.name} anted {anted} card(s) in simplified model")
    return True, "resolved"


@effect_handler("exchange_ante_with_top_library")
def exchange_ante_with_top_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    if caster.library:
        caster.graveyard.append(caster.library.pop(0))
        game.log.append(f"{card.name} exchanged top library card with simulated ante zone")
    else:
        game.log.append(f"{card.name} resolved with no library card to exchange")
    return True, "resolved"


@effect_handler("wheel_of_fortune")
def wheel_of_fortune(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        while player.hand:
            player.graveyard.append(player.hand.pop(0))
        player.draw(7)
    game.log.append("Wheel effect resolved for all players")
    return True, "resolved"


@effect_handler("timetwister")
def timetwister(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    for player in game.players:
        pool = player.library + player.hand + player.graveyard
        player.library = list(pool)
        player.hand = []
        player.graveyard = []
        player.draw(7)
    game.log.append("Timetwister effect resolved for all players")
    return True, "resolved"


@effect_handler("search_library")
def search_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    caster_index = game.players.index(caster)
    game.pending_search_library = {
        "caster_index": caster_index,
        "count": instruction.payload.get("count", 1),
        "card_type": instruction.payload.get("card_type", "any"),
    }
    game.log.append(f"{caster.name} is searching their library")
    return True, "pending_search_library"


@effect_handler("reorder_target_library_top")
def reorder_target_library_top(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    top_count = min(3, len(target.library))
    # "You may have that player shuffle" (Natural Selection) lets the caster
    # optionally shuffle the target's library after reordering.
    may_shuffle = "you may have that player shuffle" in context.card.oracle_text.lower()
    game.pending_reorder_library = {
        "caster_index": caster_index,
        "target_index": target_index,
        "top_count": top_count,
        "may_shuffle": may_shuffle,
    }
    game.log.append(f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library")
    return True, "pending_reorder_library"


@effect_handler("discard_target_cards")
def discard_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    actual = min(int(instruction.payload.get("amount", 0)), len(target.hand))
    if actual <= 0:
        game.log.append(f"{target.name} has no cards to discard")
        return True, "resolved"
    # This is a non-random discard ("discards a card"), so the discarding player
    # chooses which card. Defer to a pending choice; the UI prompts the human and
    # the AI auto-resolves it. Library of Leng lets them choose top-of-library.
    player_index = game.players.index(target)
    game.pending_discard = {
        "player_index": player_index,
        "count": actual,
        "allow_top_of_library": any(p.card.name == "Library of Leng" for p in target.battlefield),
    }
    game.log.append(f"{target.name} must choose {actual} card(s) to discard")
    return True, "pending_discard"


def _resolve_one_discard(game: Game, player_index: int, hand_index: int, to_library: bool) -> bool:
    """Move one chosen card from a player's hand to their graveyard (or, with
    Library of Leng, the top of their library). Returns False on a bad index."""
    if not (0 <= player_index < len(game.players)):
        return False
    player = game.players[player_index]
    if not (0 <= hand_index < len(player.hand)):
        return False
    card = player.hand.pop(hand_index)
    allow_top = bool(game.pending_discard and game.pending_discard.get("allow_top_of_library"))
    if to_library and allow_top:
        player.library.insert(0, card)
        game.log.append(f"{player.name} discarded {card.name} to the top of their library (Library of Leng)")
    else:
        player.graveyard.append(card)
        game.log.append(f"{player.name} discarded {card.name}")
    return True


@effect_handler("discard_x_target_cards")
def discard_x_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    x_value = context.x_value
    x = max(0, x_value or 0)
    actual = min(x, len(target.hand))
    indices = random.sample(range(len(target.hand)), actual)
    for i in sorted(indices, reverse=True):
        discarded = target.hand.pop(i)
        target.graveyard.append(discarded)
    game.log.append(f"{target.name} discarded {actual} cards at random")
    return True, "resolved"


@effect_handler("return_creature_from_graveyard_to_hand")
def return_creature_from_graveyard_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    returned = game._return_creature_from_graveyard(caster)
    game.log.append("Returned creature from graveyard" if returned else "No creature to return")
    return True, "resolved"


@effect_handler("reanimate_creature")
def reanimate_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Resurrection returns "target creature card from your graveyard", so the chosen
    # index is into the caster's own graveyard regardless of which seat the UI tags.
    idx = context.target_permanent_index
    idx = idx if isinstance(idx, int) else None
    reanimated = game._reanimate_creature_to_battlefield(caster, caster, idx)
    game.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
    return True, "resolved"


@effect_handler("bounce_target_creature")
def bounce_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    bounced = game._bounce_target_creature(target, context.target_permanent_index)
    game.log.append("Returned creature to hand" if bounced else "No creature to return")
    return True, "resolved"


@effect_handler("exile_target_creature_until_eot")
def exile_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # 610.3: zone-change one-shot "until" EOT; second one-shot returns at cleanup
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.card.primary_type == "creature":
            exiled_perm = candidate
            target.battlefield.pop(target_perm_idx)
    if exiled_perm is None:
        for idx, perm in enumerate(target.battlefield):
            if perm.card.primary_type == "creature":
                exiled_perm = perm
                target.battlefield.pop(idx)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        owner_idx = game.players.index(target)
        game.exile_until_eot.append((owner_idx, exiled_perm.card))
        game.log.append(f"{exiled_perm.card.name} exiled until end of turn by {card.name}")
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("exile_creature_gain_life_equal_to_power")
def exile_creature_gain_life_equal_to_power(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # Swords to Plowshares: exile target creature; its controller gains life = its power
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.card.primary_type == "creature":
            exiled_perm = candidate
            target.battlefield.pop(target_perm_idx)
    if exiled_perm is None:
        for idx, perm in enumerate(target.battlefield):
            if perm.card.primary_type == "creature":
                exiled_perm = perm
                target.battlefield.pop(idx)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        life_gain = exiled_perm.effective_power
        game.log.append(f"{exiled_perm.card.name} exiled by {card.name}")
        game._gain_life(target, life_gain, card.name)
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("peek_hand_and_force_play")
def peek_hand_and_force_play(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    seen = len(target.hand)
    if target.hand:
        played = target.hand.pop(0)
        target.graveyard.append(played)
        game.log.append(f"{card.name} forced {target.name} to play {played.name}")
    else:
        game.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
    return True, "resolved"


@effect_handler("look_at_target_hand")
def look_at_target_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    viewer = context.caster
    card = context.card
    # Record the reveal so the UI can show the viewer the actual cards in the
    # target player's hand (Glasses of Urza). The viewer is the ability's
    # controller; the target is the player whose hand is looked at.
    game.pending_hand_reveal = {
        "viewer_index": game.players.index(viewer),
        "target_index": game.players.index(target),
        "card_names": [c.name for c in target.hand],
    }
    seen = len(target.hand)
    game.log.append(f"{card.name}: {viewer.name} looked at {target.name}'s hand ({seen} cards)")
    return True, "resolved"
