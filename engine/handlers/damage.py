from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..resumption import run_resumable
from ._common import apply_damage_to_creature, resolve_amount, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _damage_reporter(game: Game, card, permanent):
    """What a divided-damage site does once one creature's share is dealt: log
    it and fire "dealt damage" triggers.

    Handed to `_mark_damage_on_permanent` as its `then` rather than run after
    it, because a damage event can stop to ask the affected player which effect
    applies first — and while it waits, nothing has been dealt to report."""

    def report(dealt: int) -> None:
        game.log.append(f"{card.name} dealt {dealt} damage to {permanent.card.name}")
        if dealt > 0 and permanent.damage_marked < permanent.effective_toughness:
            game._fire_dealt_damage_triggers(permanent)

    return report


@effect_handler("deal_damage")
def deal_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    x_value = context.x_value

    # Rocket Launcher: "Destroy this artifact at the beginning of the next end
    # step." A consequence of having activated, so it is marked here rather
    # than sequenced — the end step's existing delayed-destruction sweep does
    # the rest (phases/end_step.py:_delayed_eot_removal).
    if instruction.payload.get("destroys_source_at_end_step") and source_permanent is not None:
        source_permanent.metadata["destroy_at_next_end_step"] = True

    damage = resolve_amount(instruction.payload.get("amount", 0), x_value)
    target_perm_idx = context.target_permanent_index
    # "…and N damage to you": a second damage instruction in the same sequence
    # aimed at the source's controller rather than the spell's target. Reads the
    # same "recipient" key target_gains_life has always used. Without it, "deal
    # damage and also damage yourself" would need its own fused instruction kind
    # (which is exactly what deal_damage_and_self_damage was).
    if instruction.payload.get("recipient") == "caster":
        def _report(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            game.log.append(f"{card.name} dealt {dealt} damage to {caster.name}")

        game._deal_damage_to_player(
            caster, damage, source=source_permanent or card, then=_report, asks=True
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "each_opponent":
        # "…deals N damage to each opponent": one player-damage event per
        # living opponent, in seat order, resumable so a shield or replacement
        # that stops to ask carries the rest of the loop with it.
        def _hit_opponent(opponent_index: int) -> None:
            face = game.players[opponent_index]
            game._deal_damage_to_player(
                face, damage, source=source_permanent or card, asks=True,
                then=lambda dealt, face=face: game.log.append(
                    f"{card.name} dealt {dealt} damage to {face.name}"
                ),
            )

        run_resumable(game, game.opponents_of(game.players.index(caster)), _hit_opponent)
        return True, "resolved"
    # Fireball's cross-seat divided list: any mix of creatures and player faces
    # on both sides, each dealt damage // n ("divided evenly, rounded down").
    divided = context.choices.get("divided_targets")
    if divided:
        entries = [
            (seat, index)
            for seat, index in divided
            if 0 <= seat < len(game.players)
            and (index is None or 0 <= index < len(game.players[seat].battlefield))
        ]
        n = len(entries)
        if n == 0:
            game.log.append(f"{card.name} had no remaining targets")
            return True, "resolved"
        per_target = damage // n
        # Creatures first (highest index first so removals can't shift earlier
        # indices), then faces. One resumable list rather than two loops: a
        # target that stops to ask the player something has to take the targets
        # behind it with it, and "behind it" spans both groups.
        ordered = sorted(
            (e for e in entries if e[1] is not None), key=lambda e: e[1], reverse=True
        ) + [e for e in entries if e[1] is None]

        def hit(entry) -> None:
            seat, index = entry
            if index is None:
                face = game.players[seat]
                game._deal_damage_to_player(
                    face, per_target, source=card, asks=True,
                    then=lambda dealt: game.log.append(
                        f"{card.name} dealt {dealt} damage to {face.name}"
                    ),
                )
                return
            target_perm = game.players[seat].battlefield[index]
            game._mark_damage_on_permanent(
                target_perm, per_target, source=source_permanent or card, asks=True,
                then=_damage_reporter(game, card, target_perm),
            )

        run_resumable(game, ordered, hit)
        return True, "resolved"
    # Support multiple target indices for spells like Fireball
    if isinstance(target_perm_idx, list):
        # `_stack_push` stamped an id per chosen index, positionally and
        # None-padded, so the two lists pair up. Resolving each through the seam
        # means a target that survived is still hit even if an earlier one died
        # and shifted every later slot — which is precisely what a multi-target
        # spell waiting on the stack is exposed to.
        ids = context.target_permanent_id
        if not isinstance(ids, list):
            ids = [None] * len(target_perm_idx)
        chosen = []
        for position, idx in enumerate(target_perm_idx):
            permanent_id = ids[position] if position < len(ids) else None
            found = game.chosen_permanent(target, idx, permanent_id)
            if found is not None:
                chosen.append(found)
        n = len(chosen)
        if n == 0:
            # CR 608.2b: every chosen creature target is gone, so the spell
            # does nothing — it must not fall back to damaging the player.
            game.log.append(f"{card.name}: no remaining legal targets (CR 608.2b)")
            return True, "resolved"
        per_target = damage // n if n > 0 else 0
        # Highest slot first, so a death here cannot shift a target this loop
        # has not reached yet. Kept even though each target is now resolved up
        # front: `_mark_damage_on_permanent` reads the battlefield itself.
        for target_perm in sorted(
            chosen, key=lambda perm: game.battlefield_index_of(perm) or 0, reverse=True
        ):
            game._mark_damage_on_permanent(
                target_perm, per_target, source=source_permanent or card,
                then=_damage_reporter(game, card, target_perm),
            )
        return True, "resolved"
    if isinstance(target_perm_idx, int):
        # Damage targets a creature permanent, not the player.
        #
        # The id is asked *first*, and the CR 608.2b refusal below is what the
        # bounds check became. Order matters here and it is easy to get wrong:
        # a standalone `not 0 <= idx < len(battlefield)` guard in front of this
        # returned "target is gone" for a target that had merely been
        # *renumbered* — every creature below it dying shortens the list — so
        # the id lookup behind it could never run. Resolving first and refusing
        # on None means the spell fizzles when the target is genuinely gone and
        # finds it when it only moved.
        target_perm = game.chosen_permanent(
            target, target_perm_idx, context.target_permanent_id
        )
        if target_perm is None:
            # CR 608.2b: a creature was targeted but is no longer on the
            # battlefield — the spell does nothing rather than hitting the player.
            game.log.append(f"{card.name}: target creature is gone, no effect (CR 608.2b)")
            return True, "resolved"
        # 115.4: "any target" is limited to creatures, players, planeswalkers, and battles.
        # Noncreature artifacts (and other noncreature non-planeswalker permanents) are not
        # valid "any target" targets — the spell fizzles against them.
        if "any target" in card.oracle_text.lower():
            # is_creature / has_type (not the printed type line) so animated
            # lands — Kormus Bell swamps, Living Lands forests — count as
            # creatures here, and a layer-4 type change is honored.
            if not target_perm.is_creature and not target_perm.has_type("planeswalker"):
                game.log.append(
                    f"{card.name}: '{target_perm.card.name}' is not a valid 'any target' target (115.4)"
                )
                return True, "resolved"
        # A Jade Monolith redirect (source-aware) is handled inside
        # _mark_damage_on_permanent so combat and spell damage share one path.
        # Disintegrate-style riders: the damaged creature can't be regenerated
        # this turn, and if it would die this turn it is exiled instead (a
        # replacement effect honored by _destroy_marked_creatures / _permanent_to_graveyard).
        if target_perm.is_creature:
            if instruction.payload.get("no_regen"):
                target_perm.metadata["cant_be_regenerated_this_turn"] = True
            if instruction.payload.get("exile_if_dies"):
                target_perm.metadata["exile_if_dies_this_turn"] = True
        apply_damage_to_creature(
            game, target_perm, damage, source_permanent or card,
            log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {target_perm.card.name}",
            # Recorded so a later instruction in the same resolution can read it
            # ("You gain life equal to the damage dealt").
            then=lambda dealt: context.results.__setitem__("damage_dealt", dealt),
            asks=True,
        )
    else:
        def _report(damage: int) -> None:
            context.results["damage_dealt"] = damage
            if source_permanent is not None:
                game.log.append(f"{card.name} dealt {damage} damage")
            else:
                game.log.append(f"{target.name} took {damage} damage")

        game._deal_damage_to_player(
            target, damage, source=source_permanent or card, then=_report, asks=True
        )
    return True, "resolved"


@effect_handler("deal_damage_to_player")
def deal_damage_to_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A triggered ability that deals a fixed amount of damage to a player, resolving
    off the stack. Used by triggers that previously dealt damage inline at fire time:
    Dingus Egg (land dies), the land-enters 2-damage trigger, and Aura death damage.
    The victim and amount are carried in ``trigger_context`` so a synthetic instruction
    (no parsed payload) is enough."""
    tctx = context.trigger_context or {}
    victim_idx = tctx.get("victim_player_index")
    amount = int(tctx.get("amount", 0))
    if victim_idx is None or not (0 <= victim_idx < len(game.players)) or amount <= 0:
        return True, "resolved"
    victim = game.players[victim_idx]
    game._deal_damage_to_player(
        victim, amount, source=context.source_permanent,
        then=lambda dealt: game.log.append(
            f"{context.card.name} dealt {dealt} damage to {victim.name}"
        ),
    )
    return True, "resolved"


@effect_handler("simulacrum_redirect")
def simulacrum_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Simulacrum: caster gains life equal to the damage dealt to them this turn,
    # then deals that much damage to a target creature they control.
    caster = context.caster
    card = context.card
    amount = max(0, caster.damage_taken_this_turn)

    if amount > 0:
        game._gain_life(caster, amount, card.name)

    target_perm = resolve_target_permanent(game, context, player=caster)
    if target_perm is None:
        game.log.append(f"{card.name}: no creature to deal damage to")
        return True, "resolved"

    apply_damage_to_creature(
        game, target_perm, amount, card,
        log_message=lambda dealt: (
            f"{card.name} dealt {dealt} damage to {target_perm.card.name} and {caster.name} gained {amount} life"
        ),
    )
    return True, "resolved"


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = int(instruction.payload.get("amount", 1))
    _mass_damage_players_and_creatures(game, card, amount, lambda perm: True)
    game.log.append(f"{card.name} dealt {amount} damage to each creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_and_self_damage")
def deal_damage_and_self_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    amount = int(instruction.payload.get("amount", 0))
    self_damage = int(instruction.payload.get("self_damage", 0))
    target_perm_idx = context.target_permanent_index
    target_perm = game.chosen_permanent(
        target, target_perm_idx, context.target_permanent_id
    )
    if target_perm is not None:
        game._mark_damage_on_permanent(
            target_perm, amount, source=card,
            then=lambda dealt: game.log.append(
                f"{card.name} dealt {dealt} damage to {target_perm.card.name}"
            ),
        )
    else:
        game._deal_damage_to_player(
            target, amount, source=card,
            then=lambda damage: game.log.append(
                f"{card.name} dealt {damage} damage to {target.name}"
            ),
        )
    game._deal_damage_to_player(
        caster, self_damage, source=card,
        then=lambda dealt: game.log.append(
            f"{card.name} dealt {dealt} damage to {caster.name} (self-damage)"
        ),
    )
    return True, "resolved"


@effect_handler("deal_damage_and_gain_life")
def deal_damage_and_gain_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    target_perm_idx = context.target_permanent_index
    # Drain Life is an "any target" spell — it may hit a creature. Deal to the
    # chosen creature and gain life equal to the damage actually dealt (capped by
    # its toughness, mirroring the card's life-gain limit).
    target_perm = game.chosen_permanent(
        target, target_perm_idx, context.target_permanent_id
    )
    if target_perm is not None:
        if target_perm.is_creature:
            apply_damage_to_creature(
                game, target_perm, damage, card,
                log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {target_perm.card.name}",
                then=lambda dealt: game._gain_life(caster, dealt, card.name),
                asks=True,
            )
            return True, "resolved"
    def _report(damage: int) -> None:
        game.log.append(f"{card.name} dealt {damage} damage to {target.name}")
        # "You gain life equal to the damage dealt" is part of this damage
        # event's consequences, so it has to be inside it: a suspended event
        # would otherwise gain life equal to nothing and never come back to it.
        game._gain_life(caster, damage, card.name)

    game._deal_damage_to_player(target, damage, source=card, then=_report, asks=True)
    return True, "resolved"


def _has_flying(perm: Permanent) -> bool:
    """Flying from any source — printed, granted, or granted then removed.
    Reading the grant flags directly would miss whichever route a future card
    uses and would get grant-after-removal backwards (CR 613.9)."""
    return perm.has_keyword("flying")


def _mass_damage_players_and_creatures(game: Game, card, damage: int, creature_predicate) -> None:
    """Earthquake/Hurricane sweep: damage every player, then every creature
    passing the predicate, then destroy the lethally damaged as one SBA batch."""
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=card)
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and creature_predicate(perm):
                game._mark_damage_on_permanent(perm, damage, source=card)


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    _mass_damage_players_and_creatures(game, card, damage, lambda perm: not _has_flying(perm))
    game.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    _mass_damage_players_and_creatures(game, card, damage, _has_flying)
    game.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_each_attacking_creature")
def deal_damage_each_attacking_creature(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sandstorm: "deals 1 damage to each attacking creature." Creature-only
    sweep across every battlefield — no player damage — resolved as one SBA
    batch so simultaneous lethal damage kills together."""
    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    struck = 0
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and perm.attacking:
                game._mark_damage_on_permanent(perm, damage, source=card)
                struck += 1
    game.log.append(f"{card.name} dealt {damage} damage to each of {struck} attacking creatures")
    return True, "resolved"


@effect_handler("self_damage_unless_pay")
def self_damage_unless_pay(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hasran Ogress: "Whenever this creature attacks, it deals 3 damage to
    you unless you pay {2}." Arms a pending optional-pay entry for the
    controller (the same prompt flow as the color rods); declining — or being
    unable to pay — deals the damage. Headless/AI paths resolve it via
    auto_resolve_pending_optional_pays."""
    caster = context.caster
    card = context.card
    amount = int(instruction.payload.get("amount", 0))
    cost = int(instruction.payload.get("cost", 0))
    game.arm_pending_choice(
        "optional_pay", game.players.index(caster),
        card_name=card.name, cost=cost, life=0, damage=amount,
        _source_permanent=context.source_permanent,
    )
    game.log.append(
        f"{caster.name} may pay {{{cost}}} or {card.name} deals {amount} damage to them"
    )
    return True, "resolved"


@effect_handler("deal_damage_and_opponent_choice")
def deal_damage_and_opponent_choice(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Cuombajj Witches: "{T}: This creature deals 1 damage to any target and
    1 damage to any target of an opponent's choice." The controller's chosen
    target rides the normal context targeting (handled by deal_damage); the
    opposing choice becomes a pending prompt for a human chooser, or a
    deterministic pick (kill a creature of the activator's if able, else the
    activator's face) for AI/headless play."""
    deal_damage(game, instruction, context)

    caster_index = game.players.index(context.caster)
    chooser_index = next(
        (i for i, p in enumerate(game.players) if i != caster_index and not p.lost), None
    )
    if chooser_index is None:
        return True, "resolved"
    amount = int(instruction.payload.get("opponent_amount", instruction.payload.get("amount", 0)))
    # An interactive chooser is prompted; every other seat takes the kind's
    # deterministic default the moment this is armed.
    if game.arm_pending_choice(
        "opponent_damage", chooser_index,
        caster_index=caster_index, amount=amount, card_name=context.card.name,
        _source_permanent=context.source_permanent,
    ) is not None:
        game.log.append(
            f"{game.players[chooser_index].name} chooses any target for {context.card.name}'s {amount} damage"
        )
    return True, "resolved"


@effect_handler("target_bites_target")
def target_bites_target(game, instruction, context):
    """"Target creature you control deals damage equal to its power to another
    target creature." (Garruk, Savage Herald's -2.) Two chosen targets resolved
    positionally: the biter first, the bitten second. Both are resolved by id
    without an owner constraint - the biter must be the caster's, the bitten
    anyone's, and the two must differ (the printed "another")."""
    ids = context.target_permanent_id
    if not isinstance(ids, list):
        ids = [ids, None]
    resolved = [game.permanent_by_id(pid) if isinstance(pid, int) else None for pid in ids]
    biter = resolved[0] if resolved else None
    bitten = resolved[1] if len(resolved) > 1 else None
    caster_index = game.players.index(context.caster)
    if biter is None or not biter.is_creature or not game.controls(caster_index, biter):
        game.log.append(f"{context.card.name}: no creature you control to deal the damage")
        return True, "resolved"
    if bitten is None or not bitten.is_creature or bitten is biter:
        game.log.append(f"{context.card.name}: no other target creature to damage")
        return True, "resolved"
    amount = biter.effective_power
    apply_damage_to_creature(
        game, bitten, amount, biter,
        log_message=lambda dealt: (
            f"{biter.card.name} deals {dealt} damage to {bitten.card.name}"
        ),
        asks=True,
    )
    return True, "resolved"
