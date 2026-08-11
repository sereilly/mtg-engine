from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..models import Permanent
from ._common import resolve_amount, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("draw_target_cards")
def draw_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    count = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    drawn = game._draw_with_replacements(target, count)
    game.log.append(f"{target.name} drew {drawn} cards")
    return True, "resolved"


@effect_handler("draw_controller_cards")
def draw_controller_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    drawn = game._draw_with_replacements(caster, int(instruction.payload.get("amount", 0)))
    game.log.append(f"{card.name} drew {drawn} card")
    return True, "resolved"


@effect_handler("arm_lamp_draw_replacement")
def arm_lamp_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Aladdin's Lamp: arm the controller's next draw this turn to become
    "look at the top X, choose one to draw, bottom the rest in a random
    order". Consumed by Game._draw_with_replacements at the next draw."""
    caster = context.caster
    x = max(1, int(context.x_value or 0))
    game.lamp_draw_replacements[game.players.index(caster)] = x
    game.log.append(
        f"{context.card.name}: {caster.name}'s next draw this turn looks at the top {x} card(s) instead"
    )
    return True, "resolved"


@effect_handler("arm_outside_game_draw_replacement")
def arm_outside_game_draw_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ring of Ma'rûf: arm the controller's next draw this turn to become "put a
    card you own from outside the game into your hand" instead. Consumed by
    Game._draw_with_replacements at the next draw."""
    caster = context.caster
    game.outside_game_draw_replacements.add(game.players.index(caster))
    game.log.append(
        f"{context.card.name}: instead of {caster.name}'s next draw this turn, they put "
        "a card they own from outside the game into their hand"
    )
    return True, "resolved"


@effect_handler("draw_reveal_discard_unless_land")
def draw_reveal_discard_unless_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sindbad: "Draw a card and reveal it. If it isn't a land card, discard
    it." The reveal is public (logged); a non-land is discarded through
    _discard_card so Library of Leng's replacement still applies."""
    caster = context.caster
    card = context.card
    if not caster.library:
        # 120.3: the draw is still attempted; drawing from an empty library
        # marks the loss the same way every other draw does.
        caster.draw(1)
        game.log.append(f"{card.name}: {caster.name} has no cards to draw")
        return True, "resolved"
    drawn = caster.library[0]
    caster.draw(1)
    game.log.append(f"{card.name}: {caster.name} drew and revealed {drawn.name}")
    if drawn.primary_type != "land":
        caster.hand.remove(drawn)
        game._discard_card(caster, drawn)
        game.log.append(f"{caster.name} discarded {drawn.name} (not a land card)")
    return True, "resolved"


@effect_handler("draw_then_discard_self")
def draw_then_discard_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Bazaar of Baghdad: "Draw two cards, then discard three cards." Affects
    the ability's own controller; the discard is non-random, so it becomes a
    pending choice (the same flow discard_target_cards uses)."""
    caster = context.caster
    card = context.card
    draw_count = int(instruction.payload.get("draw", 0))
    discard_count = int(instruction.payload.get("discard", 0))
    drawn = caster.draw(draw_count)
    game.log.append(f"{card.name}: {caster.name} drew {drawn} card(s)")

    actual_discard = min(discard_count, len(caster.hand))
    if actual_discard <= 0:
        return True, "resolved"
    player_index = game.players.index(caster)
    game.arm_pending_choice(
        "discard", player_index,
        count=actual_discard,
        allow_top_of_library=game._controls_top_of_library_discard(caster),
    )
    game.log.append(f"{caster.name} must choose {actual_discard} card(s) to discard")
    return True, "pending_discard"


@effect_handler("discard_hand_ante_then_draw_seven")
def discard_hand_ante_then_draw_seven(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Contract from Below: "Discard your hand, ante the top card of your
    library, then draw seven cards." The anted card goes to the ante zone
    (CR 407), not the graveyard."""
    caster = context.caster
    card = context.card
    while caster.hand:
        caster.graveyard.append(caster.hand.pop(0))
    if caster.library:
        # CR 407.4: the caster owns the cards in their own library, so they are
        # the player who can ante the top one.
        game.ante_object(game.players.index(caster), caster.library.pop(0))
    drawn = caster.draw(7)
    game.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
    return True, "resolved"


@effect_handler("each_player_antes_top_card")
def each_player_antes_top_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    anted = 0
    # CR 407.4: each player antes their own top card, so every ante is made by
    # that card's owner.
    for index, player in enumerate(game.players):
        if player.library:
            game.ante_object(index, player.library.pop(0))
            anted += 1
    game.log.append(f"{card.name} anted {anted} card(s)")
    return True, "resolved"


@effect_handler("exchange_ante_with_top_library")
def exchange_ante_with_top_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Darkpact: "You own target card in the ante. Exchange that card with the
    top card of your library." With nothing of yours in the ante there is
    nothing to exchange (CR 608.2b: the effect does as much as it can)."""
    caster = context.caster
    card = context.card
    if not caster.ante:
        game.log.append(f"{card.name}: {caster.name} owns no card in the ante to exchange")
        return True, "resolved"
    if not caster.library:
        game.log.append(f"{card.name} resolved with no library card to exchange")
        return True, "resolved"
    chosen = context.target_permanent_index if isinstance(context.target_permanent_index, int) else 0
    if not (0 <= chosen < len(caster.ante)):
        chosen = 0
    anted = caster.ante.pop(chosen)
    # CR 407.4: the replacement card comes off the caster's own library, so the
    # caster is the player anting it.
    game.ante_object(game.players.index(caster), caster.library.pop(0))
    caster.hand.append(anted)
    game.log.append(
        f"{card.name}: {caster.name} exchanged {anted.name} in the ante "
        f"for the top card of their library"
    )
    return True, "resolved"


@effect_handler("ante_self_then_clear_ante_and_draw")
def ante_self_then_clear_ante_and_draw(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Jeweled Bird: "{T}: Ante this artifact. If you do, put all other cards
    you own from the ante into your graveyard, then draw a card."

    The ante is the *effect*, not part of the cost, so the Bird moves from the
    battlefield to the ante zone (CR 407) on resolution. The "if you do" rider
    only happens when it actually got anted — a Bird that has already left the
    battlefield antes nothing and the rest of the ability does nothing, and
    neither does one activated by a player who doesn't own it: CR 407.4 makes
    the owner the only player who can ante an object."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    owner_index = game.owner_index_of(source_permanent)
    controller_seat = game.controller_index_of(source_permanent)
    controller = game.players[controller_seat] if controller_seat is not None else None
    if controller is None:
        game.log.append(f"{card.name} is no longer on the battlefield to ante")
        return True, "resolved"
    # CR 407.4: only the owner can ante it. A stolen Bird (Control Magic, Old Man
    # of the Sea) can be activated by its new controller, but the ante — and so
    # the whole "if you do" rider — simply doesn't happen.
    if not game.can_ante(game.players.index(caster), owner_index):
        game.log.append(
            f"{caster.name} doesn't own {card.name} and can't ante it (CR 407.4)"
        )
        return True, "resolved"
    # "All other cards you own from the ante" is everything the *ability's
    # controller* owns there before the Bird arrives — captured first, since a
    # CardDefinition is shared per name and identity alone couldn't tell a
    # previously anted copy apart from this one.
    others = list(caster.ante)
    game.remove_from_battlefield(source_permanent)
    game.ante_object(owner_index, source_permanent.card)
    game.log.append(f"{caster.name} anted {card.name}")

    # `others` is the exact prefix of caster.ante taken before the append, so
    # slicing it off leaves only the newly anted Bird.
    caster.ante = caster.ante[len(others):]
    caster.graveyard.extend(others)
    if others:
        game.log.append(
            f"{card.name} put {len(others)} other card(s) {caster.name} owns "
            "from the ante into their graveyard"
        )
    drawn = game._draw_with_replacements(caster, 1)
    game.log.append(f"{card.name} drew {drawn} card")
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
    game.arm_pending_choice(
        "search_library", caster_index,
        count=instruction.payload.get("count", 1),
        card_type=instruction.payload.get("card_type", "any"),
    )
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
    game.arm_pending_choice(
        "reorder_library", caster_index,
        target_index=target_index, top_count=top_count, may_shuffle=may_shuffle,
    )
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
    game.arm_pending_choice(
        "discard", player_index,
        count=actual,
        allow_top_of_library=game._controls_top_of_library_discard(target),
    )
    game.log.append(f"{target.name} must choose {actual} card(s) to discard")
    return True, "pending_discard"


@effect_handler("opponent_discards_random_card_on_damage")
def opponent_discards_random_card_on_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hypnotic Specter: "Whenever this creature deals damage to a player, that
    player discards a card at random." Resolves off the stack; the player who took
    the damage is carried in ``trigger_context``."""
    tctx = context.trigger_context or {}
    idx = tctx.get("defending_player_index")
    if idx is None or not (0 <= idx < len(game.players)):
        return True, "resolved"
    defending = game.players[idx]
    if defending.hand:
        discarded = defending.hand.pop(random.randrange(len(defending.hand)))
        game._discard_card(defending, discarded)
        game.log.append(f"{context.card.name}: {defending.name} discards {discarded.name} at random")
    return True, "resolved"


def _resolve_one_discard(game: Game, player_index: int, hand_index: int, to_library: bool) -> bool:
    """Move one chosen card from a player's hand to their graveyard (or, with
    Library of Leng, the top of their library). Returns False on a bad index."""
    if not (0 <= player_index < len(game.players)):
        return False
    player = game.players[player_index]
    if not (0 <= hand_index < len(player.hand)):
        return False
    card = player.hand.pop(hand_index)
    choice = game.pending_choice_of("discard", player_index)
    allow_top = bool(choice is not None and choice.data.get("allow_top_of_library"))
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
        game._discard_card(target, discarded)  # Library of Leng -> top of library
    game.log.append(f"{target.name} discarded {actual} cards at random")
    return True, "resolved"


@effect_handler("return_creature_from_graveyard_to_hand")
def return_creature_from_graveyard_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    any_card = bool(instruction.payload.get("any_card"))
    card_type = instruction.payload.get("card_type")

    def _eligible(card) -> bool:
        if any_card:
            return True
        return card_type is not None and card_type in card.type_line.lower()
    # Honor the caster's chosen graveyard card (Rule 601.2c). Regrowth
    # (any_card) accepts any type; Raise Dead only a creature card.
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(caster.graveyard) and _eligible(
        caster.graveyard[idx]
    ):
        chosen = caster.graveyard.pop(idx)
        caster.hand.append(chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_type is not None and card_type != "creature":
        chosen_index = next(
            (i for i, c in enumerate(caster.graveyard) if _eligible(c)), None
        )
        if chosen_index is None:
            game.log.append(f"No {card_type} card in graveyard to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        caster.hand.append(chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"

    returned = game._return_creature_from_graveyard(caster)
    if not returned and any_card and caster.graveyard:
        chosen = caster.graveyard.pop(0)
        caster.hand.append(chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
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
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        owner_idx = game.players.index(target)
        game.exile_until_eot.append((owner_idx, exiled_perm.card))
        game.log.append(f"{exiled_perm.card.name} exiled until end of turn by {card.name}")
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("phase_out_target_creature_until_source_leaves")
def phase_out_target_creature_until_source_leaves(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    target_perm = resolve_target_permanent(game, context, predicate=lambda p: p.is_creature)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    owner_index = game.controller_index_of(target_perm)
    if owner_index is None:
        return True, "resolved"
    # By identity throughout: ``list.remove`` compares by value, and Permanent is
    # a dataclass with generated __eq__, so it takes the first *equal* permanent
    # — an opponent's identically-stated copy of the same card — rather than the
    # one that was chosen.
    owner_player = game.players[owner_index]
    game.remove_from_battlefield(target_perm)
    # Auras/Equipment attached to the phased creature phase out with it (CR 702.26h).
    attachments: list[tuple[int, Permanent]] = []
    for seat, player in enumerate(game.players):
        leaving = [
            perm for perm in game.controlled_by(seat)
            if perm.metadata.get("attached_to") is target_perm
        ]
        if leaving:
            game.remove_all_from_battlefield(leaving)
            attachments.extend((seat, perm) for perm in leaving)
    source_permanent.metadata["phased_out_permanent"] = target_perm
    source_permanent.metadata["phased_out_owner_index"] = owner_index
    source_permanent.metadata["phased_out_attachments"] = attachments
    game.log.append(f"{card.name} phases {target_perm.card.name} out")
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
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
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
    """Word of Command: the caster looks at the target's hand and chooses a card
    for that player to play. Arms a pending choice resolved by
    confirm_word_of_command (which plays the chosen card as the target). Also
    surfaces the revealed hand so the UI can show it to the caster."""
    target = context.target
    caster = context.caster
    card = context.card
    if not target.hand:
        game.log.append(f"{card.name}: {target.name} has no cards to play")
        return True, "resolved"
    caster_index = game.players.index(caster)
    target_index = game.players.index(target)
    game.arm_pending_choice(
        "word_of_command", caster_index,
        target_index=target_index, card_name=card.name,
        hand=[c.name for c in target.hand],
    )
    game.log.append(f"{card.name}: {caster.name} looks at {target.name}'s hand to choose a card to force")
    return True, "resolved"


@effect_handler("look_at_target_hand")
def look_at_target_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    viewer = context.caster
    card = context.card
    # Record the reveal so the UI can show the viewer the actual cards in the
    # target player's hand (Glasses of Urza). The viewer is the ability's
    # controller; the target is the player whose hand is looked at.
    viewer_index = game.players.index(viewer)
    # Only the most recent reveal is shown, so a second look replaces the first
    # rather than queueing behind it.
    game.clear_pending_choices("hand_reveal", viewer_index)
    game.arm_pending_choice(
        "hand_reveal", viewer_index,
        target_index=game.players.index(target),
        card_names=[c.name for c in target.hand],
    )
    seen = len(target.hand)
    game.log.append(f"{card.name}: {viewer.name} looked at {target.name}'s hand ({seen} cards)")
    return True, "resolved"


@effect_handler("mill_target_player")
def mill_target_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """CR 701.13a: put the top N cards of a player's library into their
    graveyard.

    Milling fewer than N because the library ran out is not a loss — CR 704.5b
    only fires when a player actually *attempts to draw* from an empty library,
    so this stops at whatever is there.
    """
    target = context.target
    amount = int(instruction.payload.get("amount", 1) or 1)
    milled = 0
    for _ in range(amount):
        if not target.library:
            break
        target.graveyard.append(target.library.pop(0))
        milled += 1
    game.log.append(f"{target.name} milled {milled} card(s)")
    return True, "resolved"


@effect_handler("return_all_owned_artifacts_to_hand")
def return_all_owned_artifacts_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hurkyl's Recall: "Return all artifacts target player owns to their hand."

    Owns, not controls. An artifact the target player owns but an opponent has
    stolen still returns, and to the *owner's* hand (CR 400.3) — which is why
    this asks ``owner_index_of`` rather than reading the battlefield it happens
    to be sitting on.
    """
    owner_index = game.players.index(context.target)
    returned = 0
    for player in game.players:
        for permanent in list(player.battlefield):
            if not permanent.has_type("artifact"):
                continue
            if game.owner_index_of(permanent) != owner_index:
                continue
            # Identity, not value: two untapped Moxen of the same name are ``==``.
            game.remove_from_battlefield(permanent)
            game.players[owner_index].hand.append(permanent.card)
            game._remove_aura_effects(permanent)
            returned += 1
    game.log.append(f"Returned {returned} artifact(s) to {context.target.name}'s hand")
    return True, "resolved"
