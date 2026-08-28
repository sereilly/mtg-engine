from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ._common import (
    block_pair_permanents,
    flip_coin,
    resolve_own_combatant,
    resolve_target_permanent,
)
from .registry import effect_handler
from ..keywords import grant_keyword
from ..combat_assignment import ASSIGNS_NO_COMBAT_DAMAGE
from ..combat_permissions import ATTACK_AS_THOUGH_NO_DEFENDER
from ..pt import add_pt_modifier
from ..rampage import rampage_bonus

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


@effect_handler("coin_flip_remove_attacker_and_tap")
def coin_flip_remove_attacker_and_tap(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Mijae Djinn: "Whenever this creature attacks, flip a coin. If you lose
    the flip, remove this creature from combat and tap it." Fired per-attacker
    by _fire_creature_attacks_triggers, which threads the attacker's own
    controller/index through target_player_index/target_permanent_index."""
    combatant = resolve_own_combatant(game, context)
    if combatant is None:
        return True, "resolved"
    controller, idx, permanent = combatant
    if flip_coin():
        game.log.append(f"{context.card.name} won the coin flip")
        return True, "resolved"
    game.combat_attackers.pop(idx, None)
    game.combat_bands = [band for band in game.combat_bands if idx not in band]
    game.become_tapped(permanent)
    game.log.append(f"{context.card.name} lost the coin flip: removed from combat and tapped")
    return True, "resolved"


@effect_handler("coin_flip_remove_blocker")
def coin_flip_remove_blocker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ydwen Efreet: "Whenever this creature blocks, flip a coin. If you lose
    the flip, remove this creature from combat and it can't block this turn.
    Creatures it was blocking that had become blocked by only this creature
    this combat become unblocked." Fired per-blocker by
    _fire_creature_blocks_triggers. "Can't block this turn" needs no extra
    flag: this engine only declares blockers once per combat, so removal
    already prevents it from blocking again."""
    combatant = resolve_own_combatant(game, context)
    if combatant is None:
        return True, "resolved"
    controller, idx, _permanent = combatant
    if flip_coin():
        game.log.append(f"{context.card.name} won the coin flip")
        return True, "resolved"
    controller_index = game.players.index(controller)
    game._remove_blocker_from_combat(controller_index, idx)
    game.log.append(f"{context.card.name} lost the coin flip: removed from combat")
    return True, "resolved"


@effect_handler("delayed_destroy_blocked_or_blocker")
def delayed_destroy_blocked_or_blocker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Resolve Cockatrice / Thicket Basilisk's block trigger (Rule 509.2a).

    The trigger was put on the stack when blockers were declared; on resolution
    it marks the creature it blocked / that blocked it for destruction at end of
    combat.

    Which half fired decides how the victim is named, and
    ``block_pair_permanents`` is the one place that difference is written down.
    """
    # "destroy that **Wall**" (Battering Ram). The trigger's own condition
    # already required one, so this re-states rather than narrows — and it is
    # tested anyway, because a payload key nothing reads is a printed word that
    # could be deleted with no change to what the card does.
    subtype = instruction.payload.get("subtype_filter")
    victims = [
        perm
        for perm in block_pair_permanents(game, context)
        if not subtype or perm.has_type(str(subtype))
    ]
    # The pair, recorded before anything is marked. The sentence after this one
    # names *both* halves — "if **that creature** was destroyed this way, put a
    # +1/+1 counter on **the first creature**" (Infinite Authority) — and by the
    # time it is asked, a step later, the victim is a card in a graveyard and
    # combat is over. The scratchpad is where an effect's later steps read what
    # its earlier ones knew (CR 608.2h), and `_PRODUCES` is what lets the
    # grammar refuse the sentence when no step wrote it.
    context.results[END_OF_COMBAT_DESTRUCTION_RESULT_KEY] = {
        "own_id": _block_pair_own_creature_id(game, context),
        "victim_ids": [victim.permanent_id for victim in victims],
    }
    if not victims:
        game.log.append(f"{context.card.name} block trigger had no valid target")
        return True, "no target"
    for victim in victims:
        victim.metadata["destroy_at_end_of_combat"] = True
        game.log.append(
            f"{context.card.name} will destroy {victim.card.name} at end of combat"
        )
    return True, "resolved"


#: Where the delayed destroy above writes the pair it bound, and the one name
#: the grammar's ``_PRODUCES`` declares for it. One spelling, because a second
#: would make the grammar's refusal vacuous while the reader found nothing.
END_OF_COMBAT_DESTRUCTION_RESULT_KEY = "end_of_combat_destruction"


def _block_pair_own_creature_id(game: Game, context: OracleExecutionContext) -> int | None:
    """The creature a block trigger is *about* — the other half of the pair
    ``block_pair_permanents`` returns.

    Two spellings, one question. A creature watching its own block is the
    ability's source; an Aura watching the creature it enchants is not on that
    creature's ``effective_card`` at all (CR 113.7a), so the source is the Aura
    and the creature is what it is attached to. Derived here rather than
    stamped by the fire sites, because both of them already record the *other*
    half and this is the same pair read from the other end.
    """
    source = context.source_permanent
    if source is None:
        return None
    host = source.metadata.get("attached_to")
    if host is not None and game.is_on_battlefield(host):
        return host.permanent_id
    return source.permanent_id


@effect_handler("cant_attack_during_controllers_next_turn")
def cant_attack_during_controllers_next_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Wall of Dust: "Whenever this creature blocks a creature, that creature
    can't attack during its controller's next turn."

    "That creature" is the blocked attacker, resolved by the stable ids the
    blocks fire site recorded on the trigger (CR 509.3f fixed the set at
    declaration; an id that no longer resolves is a creature that left, and a
    creature that returns is a new object the sentence never named — CR 400.7).
    The stamp names the creature's controller *as the trigger resolves* and
    that seat's next turn ordinal; ``can_attack`` refuses exactly while that
    turn is the current one, and a later turn walks past the stamp with
    nothing to sweep.
    """
    stamped = []
    for permanent_id in (context.trigger_context or {}).get("blocked_permanent_ids") or ():
        perm = game.permanent_by_id(permanent_id)
        if perm is None:
            continue
        seat = game.controller_index_of(perm)
        if seat is None:
            continue
        perm.metadata["cant_attack_on_seat_turn"] = {
            "seat": seat,
            "seat_turn": game.seat_turn_counts.get(seat, 0) + 1,
        }
        stamped.append((perm, seat))
    if stamped:
        for perm, seat in stamped:
            game.log.append(
                f"{perm.card.name} can't attack during "
                f"{game.players[seat].name}'s next turn ({context.card.name})"
            )
    else:
        game.log.append(f"{context.card.name} block trigger found no blocked creature")
    return True, "resolved"


@effect_handler("rampage_pump")
def rampage_pump(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Rampage N (CR 702.23a): +N/+N until end of turn for each creature
    blocking this one beyond the first.

    The count is taken **here**, at resolution, which is the whole of CR
    702.23b — blockers added or removed after the ability triggered do not
    change the bonus, and a bonus applied back in the declare-blockers step
    could not have said that. `_attacker_all_blockers` is the same reader the
    damage step uses, so "how many creatures are blocking this attacker"
    (band-propagated blocks included, CR 702.22h) has one answer rather than
    two that can disagree.
    """
    attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        return True, "resolved"
    attacker_idx = game.battlefield_index_of(attacker)
    if attacker_idx is None or attacker_idx not in game.combat_attackers:
        # Removed from combat between the trigger and its resolution: it is no
        # longer blocked by anything, so the bonus is nothing.
        return True, "resolved"
    amount = int(instruction.payload.get("amount", 0))
    bonus = rampage_bonus(amount, len(game._attacker_all_blockers(attacker_idx)))
    if bonus:
        add_pt_modifier(attacker, bonus, bonus, until="end_of_turn")
        game.log.append(
            f"{attacker.card.name} gets +{bonus}/+{bonus} until end of turn (rampage {amount})"
        )
    return True, "resolved"


@effect_handler("grant_unlimited_blocking")
def grant_unlimited_blocking(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Blaze of Glory: "Target creature defending player controls can block any number
    # of creatures this turn. It blocks each attacking creature this turn if able."
    # Honor the chosen creature; fall back to the first only for AI/headless play.
    card = context.card
    blocker = resolve_target_permanent(game, context)
    if blocker is not None:
        # Lets it block any number of attackers (_max_blocks_for) and requires it to
        # block each attacker it can (enforced when blocks are declared).
        blocker.metadata["can_block_any_number_until_eot"] = True
        blocker.metadata["must_block_all_until_eot"] = True
        game.log.append(f"{card.name}: {blocker.card.name} can block any number of creatures this turn")
    else:
        game.log.append(f"{card.name} found no creature to grant unlimited blocking")
    return True, "resolved"


@effect_handler("randomize_blockers")
def randomize_blockers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    # Camouflage: mark this turn so the defending player's blocks are assigned by
    # random pile (resolve_camouflage_blocking) rather than chosen this combat.
    game.camouflage_active_turn = game.turn
    game.log.append(f"{card.name} set up random pile blocking this turn")
    return True, "resolved"


def _take_permanent_out_of_combat(game: Game, perm: Permanent) -> bool:
    """Remove *perm* from combat, whichever role it holds (CR 506.4c).

    Combat state is index-keyed (see the control-seam notes), so the slot is
    derived once through the seam (``battlefield_index_of``) and every map
    that carries it is pruned together — an attacker's entry, its
    planeswalker assignment, its band, and any blocker's record of blocking
    it. A blocker goes through ``_remove_blocker_from_combat``, which already
    unblocks attackers this creature was the only blocker of.
    """
    idx = game.battlefield_index_of(perm)
    if idx is None:
        return False
    seat = game.controller_index_of(perm)
    if seat == game.active_player_index and idx in game.combat_attackers:
        game.combat_attackers.pop(idx, None)
        game.combat_attacked_planeswalkers.pop(idx, None)
        game.combat_bands = [band for band in game.combat_bands if idx not in band]
        for blocker_map in game.combat_blockers.values():
            for blocked in blocker_map.values():
                if idx in blocked:
                    blocked.remove(idx)
        # CR 506.4c: it stops being an attacking creature — the per-permanent
        # state has to agree with the pruned maps, or a filter asking
        # "attacking" between now and end of combat gets a different answer
        # than the damage step does.
        perm.attacking = False
        perm.defending_player_index = None
        perm.blocked = False
        game.log.append(f"{perm.card.name} was removed from combat")
        return True
    if idx in game.combat_blockers.get(seat, {}):
        game._remove_blocker_from_combat(seat, idx)
        game.log.append(f"{perm.card.name} was removed from combat")
        return True
    return False


@effect_handler("remove_from_combat")
def remove_from_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Disharmony: "Untap target attacking creature and **remove it from
    combat**." Reads the permanents the previous step of this resolution
    recorded (CR 611.2c fixed the set when the effect began) — nothing is
    chosen here, and an empty record is a legal outcome, not an error."""
    key = instruction.payload.get("permanents_from")
    for permanent_id in context.results.get(key) or ():
        perm = game.permanent_by_id(permanent_id)
        if perm is None:
            continue
        _take_permanent_out_of_combat(game, perm)
    return True, "resolved"


@effect_handler("remove_creature_from_combat")
def remove_creature_from_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # False Orders: "Remove target creature defending player controls from combat.
    # Creatures it was blocking that had become blocked by only that creature this
    # combat become unblocked." Honor the chosen blocker; fall back to the first
    # creature only when no explicit target was supplied (AI/headless).
    target = context.target
    card = context.card
    idx = context.target_permanent_index
    removed_index: int | None = None
    if isinstance(idx, int) and 0 <= idx < len(target.battlefield):
        if target.battlefield[idx].is_creature:
            removed_index = idx
    if removed_index is None:
        removed_index = next(
            (i for i, perm in enumerate(target.battlefield) if perm.is_creature),
            None,
        )
    if removed_index is None:
        game.log.append(f"{card.name} had no creature to remove from combat")
        return True, "resolved"

    removed = target.battlefield[removed_index]
    removed.metadata["removed_from_combat"] = True

    # If this creature is currently blocking, take it out of combat: drop it as a
    # blocker and unblock any attacker whose only blocker it was. combat_blockers is
    # nested by defender (CR 802), so look up this defender's own blocker entries.
    target_player_index = game.players.index(target)
    game._remove_blocker_from_combat(target_player_index, removed_index)

    game.log.append(f"{card.name} removed {removed.card.name} from combat")
    return True, "resolved"


@effect_handler("left_right_combat_division")
def left_right_combat_division(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    # Record that the division was established this combat so the rest of the
    # engine (and tests) can observe that the attack trigger actually fired.
    if context.source_permanent is not None:
        context.source_permanent.metadata["left_right_division_turn"] = game.turn
    game.combat_left_right_active = True
    # TODO(FFA): Raging River's left/right split is only spec'd for a single
    # defending player; under attack-multiple-players (CR 802) with 2+ defenders
    # this combat, default to the first one rather than modeling a division per
    # defender.
    defender_index = next(iter(game.combat_defending_players()), None)
    game.combat_left_right_defender_index = defender_index
    # A fresh attack re-opens both players' pile decisions.
    game.combat_left_right_defender_locked = False
    game.combat_left_right_attacker_locked = False

    # Seed a sensible default division so AI/headless combat still resolves: the
    # defending player's non-flying creatures are split into left/right at random,
    # and every attacker defaults to "left". This doubles as the AI's actual choice
    # (an AI defender "chooses randomly"); a human overrides it via the UI before
    # blocks are declared (assign_defender_piles / assign_attacker_piles). The
    # module RNG is seeded in AI simulations, so a seeded run stays reproducible.
    if isinstance(defender_index, int) and 0 <= defender_index < len(game.players):
        defender = game.players[defender_index]
        game.combat_defender_piles = {}
        for idx, perm in enumerate(defender.battlefield):
            if not perm.is_creature:
                continue
            if game._has_keyword(perm, "flying"):
                continue  # flyers are in neither pile (they may block anything)
            game.combat_defender_piles[idx] = random.choice(("left", "right"))
    game.combat_attacker_piles = {idx: random.choice(("left", "right")) for idx in game.combat_attackers}
    game.log.append(f"{card.name} established left/right combat division")
    return True, "resolved"


@effect_handler("prevent_all_combat_damage")
def prevent_all_combat_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    game.combat_damage_prevented_until_eot = True
    game.log.append("Combat damage prevented until end of turn")
    return True, "resolved"


@effect_handler("prevent_all_combat_damage_to_matching")
def prevent_all_combat_damage_to_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all combat damage that would be dealt this turn to Dogs you
    control." (Pack Leader.)

    Arms a turn-wide record carrying the printed noun phrase and the seat "you
    control" resolves to — the ability's controller (CR 109.5), captured now
    because the effect is theirs even if the Dogs change hands later.

    The *set* is deliberately not captured: `engine/prevention.py` re-matches the
    phrase when damage would be dealt, so a Dog that enters after this resolves
    is covered. Handing a shield to each Dog present would have made the card
    narrower than it prints.
    """
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(context.caster)
    game.combat_damage_prevented_for.append({"filter": described, "seat": seat})
    game.log.append(
        f"{context.card.name}: combat damage to matching permanents is prevented this turn"
    )
    return True, "resolved"


@effect_handler("mark_non_wall_target_to_attack")
def mark_non_wall_target_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    target_creature = next(
        (
            perm
            for perm in game.controlled_by(target)
            if perm.is_creature and not perm.has_type("wall")
        ),
        None,
    )
    if target_creature is not None:
        target_creature.metadata["must_attack_until_eot"] = True
        target_creature.metadata["destroy_if_did_not_attack_eot"] = True
        game.log.append(f"{target_creature.card.name} marked to attack this turn")
    else:
        game.log.append("No non-Wall target for Nettling Imp effect")
    return True, "resolved"


@effect_handler("force_active_player_creatures_to_attack")
def force_active_player_creatures_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    marked: list[str] = []
    for permanent in game.controlled_by(game.active_player_index):
        if not permanent.is_creature:
            continue
        permanent.metadata["must_attack_until_eot"] = True
        is_wall = permanent.has_type("wall")
        # "Ignore this effect for each creature the player didn't control
        # continuously since the beginning of the turn."
        entered_this_turn = permanent.metadata.get("summoning_sickness_turn") == game.turn
        if not is_wall and not entered_this_turn:
            permanent.metadata["destroy_if_did_not_attack_eot"] = True
        marked.append(permanent.card.name)
    if marked:
        game.log.append(f"{context.card.name} forces {', '.join(marked)} to attack this turn")
    else:
        game.log.append(f"{context.card.name} resolved with no creatures to force into combat")
    return True, "resolved"


@effect_handler("grant_unblockable_to_self")
def grant_unblockable_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature can't be blocked this turn." (Ghostly Pilferer.)

    The ability's own source, so nothing is chosen and nothing is resolved. A
    source that has already left the battlefield grants nothing rather than
    falling back to a scan, which would make some other creature unblockable.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing to make unblockable")
        return True, "resolved"
    source.metadata["cant_be_blocked_until_eot"] = True
    game.log.append(f"{source.card.name} can't be blocked this turn")
    return True, "resolved"


@effect_handler("grant_unblockable_to_target")
def grant_unblockable_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked this turn." (Teleport.)

    The unrestricted printing: any creature is a legal target, so the only
    thing to honour is the choice itself. The sibling below is the one whose
    printed line narrows the target by power.
    """
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to make unblockable")
        return True, "resolved"
    target_creature.metadata["cant_be_blocked_until_eot"] = True
    game.log.append(f"{target_creature.card.name} can't be blocked this turn")
    return True, "resolved"


@effect_handler("grant_cant_be_blocked_by_until_eot")
def grant_cant_be_blocked_by_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked by Walls this turn." (Tower of
    Coireall.)

    The granted twin of the static restriction `engine/combat_restrictions.py`
    derives, and the *same* record the blockers step reads: the class of blocker
    is a filter payload either way, so a card printing another subtype, colour
    or card type needs no code here and no branch there.

    Not folded into ``grant_unblockable_to_target``: that one makes the creature
    unblockable by everything, and a narrowing this handler dropped would hand
    the card the larger effect silently.
    """
    from ..combat_restrictions import grant_blocker_restriction

    described = instruction.payload.get("blocker_filter") or {}
    if not described:
        # A restriction with no class behind it would be the unnarrowed one.
        game.log.append(f"{context.card.name}: no blocker class to restrict")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to restrict")
        return True, "resolved"
    grant_blocker_restriction(target_creature, described)
    game.log.append(
        f"{target_creature.card.name} can't be blocked by matching creatures "
        f"this turn ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("grant_unblockable_to_low_power_target")
def grant_unblockable_to_low_power_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Honor the specifically chosen creature (the player picked one in the UI);
    # fall back to the first eligible creature only for AI/headless casts with no
    # explicit target. Either way the "power 2 or less" restriction is enforced.
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature and p.effective_power <= 2
    )
    if target_creature is not None:
        target_creature.metadata["cant_be_blocked_until_eot"] = True
        game.log.append(f"{target_creature.card.name} can't be blocked this turn")
    else:
        game.log.append("No valid low-power creature for unblockable effect")
    return True, "resolved"


@effect_handler("grant_banding_to_target")
def grant_banding_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Helm of Chatzuk: "{1}, {T}: Target creature gains banding until end of turn."
    # Honor the chosen target (any creature, on either battlefield); fall back to
    # the first creature only when no explicit target was supplied (AI/headless).
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append("No valid creature target for banding effect")
        return False, "no valid creature target for banding effect"
    from .pump import grant_lifetime

    grant_keyword(
        target_creature, "banding", **grant_lifetime(game, instruction, context)
    )
    game.log.append(f"{target_creature.card.name} gains banding until end of turn")
    return True, "resolved"


@effect_handler("cant_attack_until_eot")
def cant_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures can't attack this turn." (Festival.)

    The attack twin of ``cant_block_until_eot`` below: a blanket restriction the
    attack gate (``declare_attackers_step.can_attack``) tests for the rest of
    the turn, swept at cleanup. State plus a reader, never a flag stamped per
    creature — a creature entering after this resolves cannot attack either,
    which per-permanent flags would miss.
    """
    game.attack_restrictions_until_eot.append({
        "filter": dict(instruction.payload.get("filter") or {}),
        "source_name": context.card.name,
    })
    game.log.append(f"{context.card.name}: the named creatures can't attack this turn")
    return True, "resolved"


@effect_handler("cant_block_until_eot")
def cant_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures without flying can't block this turn." (Destructive
    Tampering's second mode.) Arms a blanket restriction the blocker gate
    (``_can_block_attacker``) tests for the rest of the turn; cleanup sweeps
    it. State plus a reader, never a flag stamped per creature — a creature
    entering after this resolves is restricted too, which per-permanent flags
    would miss."""
    game.blocking_restrictions_until_eot.append({
        "filter": dict(instruction.payload.get("filter") or {}),
        "source_name": context.card.name,
    })
    game.log.append(f"{context.card.name}: the named creatures can't block this turn")
    return True, "resolved"


@effect_handler("attack_as_though_no_defender_until_eot")
def attack_as_though_no_defender_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"…can attack this turn as though it didn't have defender."
    (Wall of Wonder.)

    CR 609.4: the permission is stamped on the permanent rather than the
    keyword being removed, so the creature still *has* defender for everything
    that asks — what "creatures with defender" counts, what a defender-narrowed
    filter matches, what layer 6 reports to the web payload. The key is swept
    by the cleanup step (``_EOT_METADATA_KEYS``), which is the whole of "this
    turn".
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    source.metadata[ATTACK_AS_THOUGH_NO_DEFENDER] = True
    game.log.append(
        f"{source.card.name} can attack this turn as though it didn't have defender"
    )
    return True, "resolved"


@effect_handler("exempt_from_attack_tapping")
def exempt_from_attack_tapping(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Attacking doesn't cause creatures you control to tap this combat if
    Johan is untapped." (Johan; CR 508.1f.)

    Arms a standing exemption rather than doing anything now — nothing is
    tapped or untapped when this resolves, and the creatures it is about have
    not been declared yet. ``engine/attack_tapping.py`` holds it, the declare
    attackers step asks it, and the end of combat step ends it.

    The gate is bound to the **source permanent by id**: "if Johan is untapped"
    is about this Johan (CR 400.7), so a Johan that leaves and returns does not
    inherit the exemption his earlier self armed. With no source on the
    battlefield there is nothing for the gate to be about, and the effect
    refuses rather than arming an exemption that could never apply — or, worse,
    one whose gate is silently dropped.
    """
    from ..attack_tapping import AttackTapExemption, arm_attack_tap_exemption

    gate_filter = dict(instruction.payload.get("gate_filter") or {})
    source = context.source_permanent
    if gate_filter and source is None:
        return False, "ability not implemented"
    seat = game.players.index(context.caster)
    arm_attack_tap_exemption(game, AttackTapExemption(
        controller_index=seat,
        subject_filter=dict(instruction.payload.get("filter") or {}),
        gate_permanent_id=source.permanent_id if gate_filter else None,
        gate_filter=gate_filter,
        source_name=context.card.name if context.card is not None else "an effect",
    ))
    game.log.append(
        f"attacking doesn't cause those creatures to tap this combat "
        f"({context.card.name if context.card is not None else 'an effect'})"
    )
    return True, "resolved"


@effect_handler("assign_no_combat_damage_until_eot")
def assign_no_combat_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This creature assigns no combat damage this turn." (Floral Spuzzem.)

    Marks the effect's own source; ``engine/combat_assignment.py`` is what the
    combat damage step reads and the cleanup sweep is what ends it.

    With no source on the battlefield there is nothing the sentence is about,
    and the effect refuses rather than reporting a mark it did not make — the
    rider is the whole reason the card's first half is worth doing, so a
    silently dropped one is the card doing strictly more than it prints.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    source.metadata[ASSIGNS_NO_COMBAT_DAMAGE] = True
    game.log.append(
        f"{source.card.name} assigns no combat damage this turn"
    )
    return True, "resolved"
