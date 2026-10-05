from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ._common import (recorded_permanent_ids, 
    attached_host,
    bound_permanent,
    block_pair_permanents,
    flip_coin,
    resolve_own_combatant,
    resolve_role_permanent,
    resolve_target_permanent,
    names_a_target_list as _names_a_list,
    resolve_target_permanents,
    roles_still_legal,
)
from .registry import effect_handler
from ..keywords import grant_keyword
from ..mana_payment import mana_cost_label
from ..combat_assignment import (ASSIGNS_NO_COMBAT_DAMAGE,
                                MUST_ASSIGN_AS_UNBLOCKED,
                                 BLOCKED_WITHOUT_BLOCKERS)
from ..combat_permissions import (ADDITIONAL_BLOCKS_UNTIL_EOT,
                                  CAN_BLOCK_ANY_NUMBER_UNTIL_EOT,
                                  MUST_BLOCK_ALL_UNTIL_EOT,
                                  MUST_BLOCK_ATTACKERS_UNTIL_EOT,
                                  ATTACK_AS_THOUGH_NO_DEFENDER,
                                  CANT_ATTACK_UNTIL_EOT,
                                  CANT_BLOCK_ATTACKERS_UNTIL_EOT,
                                  MUST_BLOCK_UNTIL_EOT,
                                  CANT_BLOCK_UNTIL_EOT)
from ..oracle_types import REMOVED_FROM_COMBAT_PERMANENTS
from ..pt import add_pt_modifier
from ..rampage import rampage_bonus
from ..turn_state import (CANT_ATTACK_ON_SEAT_TURN_KEY,
                          THAT_PLAYERS_NEXT_TURN,
                          DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY,
                          MUST_ATTACK_ON_SEAT_TURN_KEY,
                          seats_next_turn_window)

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
    # Through the one transition rather than by popping the attacker map.
    # CR 506.4: "a creature that's removed from combat stops being an attacking,
    # blocking, blocked, and/or unblocked creature" — and popping the map alone
    # left `permanent.attacking` stamped True, its `defending_player_index` set
    # and any blocker still holding its slot. Every filter asking "attacking"
    # went on admitting it for the rest of the turn.
    _take_permanent_out_of_combat(game, permanent)
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
    # Ydwen Efreet prints ", …creatures it was blocking that had become blocked
    # by only this creature this combat become unblocked" — the clause that
    # overrides CR 509.1h, which is why it is asked for here rather than
    # inherited from the removal.
    game._remove_blocker_from_combat(
        controller_index, idx, frees_blocked_attackers=True
    )
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
    # Through ``attached_host`` so an Aura that left before its block trigger
    # resolved still names the creature it was on (CR 608.2h last-known
    # information). Reading the live record answered "the Aura itself" —
    # Infinite Authority's "put a +1/+1 counter on enchanted creature" then
    # looked for the counter's recipient among permanents that had left.
    host = attached_host(game, source)
    if host is not None:
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
        perm.metadata[CANT_ATTACK_ON_SEAT_TURN_KEY] = seats_next_turn_window(
            game, seat
        )
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
        blocker.metadata[CAN_BLOCK_ANY_NUMBER_UNTIL_EOT] = True
        blocker.metadata[MUST_BLOCK_ALL_UNTIL_EOT] = True
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


def _take_permanent_out_of_combat(
    game: Game, perm: Permanent, *, frees_blocked_attackers: bool = False,
) -> bool:
    """Remove *perm* from combat, whichever role it holds (CR 506.4c).

    Combat state is index-keyed (see the control-seam notes), so the slot is
    derived once through the seam (``battlefield_index_of``) and every map
    that carries it is pruned together — an attacker's entry, its
    planeswalker assignment, its band, and any blocker's record of blocking
    it. A blocker goes through ``_remove_blocker_from_combat``, which keeps
    each attacker blocked (CR 509.1h) unless the card printed the sentence
    that says otherwise — ``frees_blocked_attackers``, which is Imprison's
    clause and not something removal does.
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
        game._remove_blocker_from_combat(
            seat, idx, frees_blocked_attackers=frees_blocked_attackers
        )
        game.log.append(f"{perm.card.name} was removed from combat")
        return True
    return False


def _blocked_attacker_indices(game: Game, defender_seat: int, blocker_index: int) -> list[int]:
    """Which attacker slots *blocker_index* is blocking for *defender_seat*."""
    return list(game.combat_blockers.get(defender_seat, {}).get(blocker_index, []))


def _could_block_all(game: Game, blocker: Permanent, attacker_indices: list[int]) -> bool:
    """CR 509.1b asked of a block that has not happened.

    "If each of those creatures **could block** all creatures that the other is
    blocking" (Sorrow's Path) is a hypothetical, so it is asked of exactly the
    gate a real declaration passes — ``_can_block_attacker``, per pair, plus
    ``_max_blocks_for`` for how many at once. Two questions would be two
    answers: a card that reads flying, protection and "can't be blocked by
    Walls" for the swap but not for the declaration would let a creature end up
    blocking something it could never have been declared against.

    Menace is deliberately not here. CR 702.111b restricts the *declaration as
    a whole* (CR 509.1c) rather than any one pairing, and this sentence asks
    about one creature at a time — the same reading ``declare_blockers``' own
    Lure and "must be blocked" loops make when they ask ``_can_block_attacker``
    per pair.
    """
    if len(attacker_indices) > game._max_blocks_for(blocker):
        return False
    attacker_controller = (
        game.players[game.active_player_index]
        if 0 <= game.active_player_index < len(game.players)
        else None
    )
    if attacker_controller is None:
        return False
    for attacker_index in attacker_indices:
        attacker = game.permanent_at(attacker_controller, attacker_index)
        if attacker is None or not game._can_block_attacker(blocker, attacker):
            return False
    return True


@effect_handler("swap_block_assignments")
def swap_block_assignments(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sorrow's Path: "Choose two target blocking creatures controlled by the
    same opponent. If each of those creatures could block all creatures that the
    other is blocking, remove both of them from combat. Each one then blocks all
    creatures the other was blocking."

    **Removing and re-blocking is not the same as swapping two map entries**,
    and the card says the former. Three things fall out of it that a swap would
    get wrong:

    * CR 509.1h keeps each *attacker* blocked the whole way through — "a
      creature remains blocked even if all the creatures blocking it are removed
      from combat" — so nothing becomes unblocked in between and no damage goes
      to the face.
    * CR 506.4 makes each blocker stop being a blocking creature, so CR 509.3a's
      "whenever this creature blocks" fires **again** when the effect blocks it
      (it "wasn't a blocking creature at that time"), and the division of its
      combat damage among what it used to block goes with the block.
    * CR 509.3c's "whenever this creature becomes blocked" does *not* fire, for
      the first reason: the attacker never stopped being blocked. Its
      per-blocker sibling CR 509.3d does, which is the ``already_blocked`` flag.

    The whole reassignment is refused unless the hypothetical holds for **both**
    creatures — one clause, checked before anything moves, because "if each of
    those creatures could block all creatures that the other is blocking" is a
    single condition over the pair rather than a filter applied to each.
    """
    observer = game.players.index(context.caster)
    payload = instruction.payload
    # CR 608.2b, through the same table the picker narrowed with: both roles
    # still on the battlefield, still blocking, still an opponent's, and still
    # each other's — a creature that left and returned is a new object (CR
    # 400.7) and is not the one that was chosen.
    if not roles_still_legal(game, context, payload, observer=observer):
        game.log.append(f"{context.card.name}: its chosen creatures are no longer legal targets")
        return True, "targets illegal"
    first = resolve_role_permanent(game, context, payload, "first")
    second = resolve_role_permanent(game, context, payload, "second")
    if first is None or second is None or first is second:
        return True, "no targets"

    defender_seat = game.controller_index_of(first)
    first_index = game.battlefield_index_of(first)
    second_index = game.battlefield_index_of(second)
    if defender_seat is None or first_index is None or second_index is None:
        return True, "no targets"

    first_blocks = _blocked_attacker_indices(game, defender_seat, first_index)
    second_blocks = _blocked_attacker_indices(game, defender_seat, second_index)
    if not first_blocks or not second_blocks:
        return True, "not blocking"

    if not (
        _could_block_all(game, first, second_blocks)
        and _could_block_all(game, second, first_blocks)
    ):
        game.log.append(
            f"{context.card.name}: {first.card.name} and {second.card.name} "
            "could not block each other's creatures — nothing happens"
        )
        return True, "swap illegal"

    game._remove_blocker_from_combat(defender_seat, first_index)
    game._remove_blocker_from_combat(defender_seat, second_index)
    swapped = {first_index: second_blocks, second_index: first_blocks}
    blocks = game.combat_blockers.setdefault(defender_seat, {})
    blocks.update(swapped)
    # The per-permanent combat flags and the band propagation are the
    # projection of these maps, exactly as they are after a declaration — the
    # attackers whose only blocker was removed a line ago become blocked again
    # here, which is CR 509.1h's "remains blocked" arriving by the shortest
    # route the engine has.
    game._prune_combat_state()
    game._record_block_history(defender_seat, swapped)
    game._fire_creature_blocks_triggers(defender_seat, swapped)
    game._fire_becomes_blocked_triggers(defender_seat, swapped, already_blocked=True)
    game.log.append(
        f"{context.card.name}: {first.card.name} and {second.card.name} "
        "swapped the creatures they were blocking"
    )
    return True, "resolved"


#: The scratchpad key the becomes-blocked step records its creatures under. One
#: name, for ``UNBLOCKABLE_PERMANENTS``' reason below: the handler writes it and
#: ``lowering/_records._PRODUCES`` declares it, and a second spelling would make
#: the lowering's gate vacuous while the record sat unread.
BLOCKED_PERMANENTS = "blocked_permanents"


@effect_handler("become_blocked")
def become_blocked(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target unblocked attacking creature becomes blocked." (Dazzling Beauty.)

    CR 509.1h: a creature can be blocked by *no* creatures, which is exactly the
    state an attacker is left in when its blockers leave combat — so nothing is
    added to any block map and no creature is put in front of this one. The
    consequence is the whole card: an attacker that is blocked and has no
    blockers assigns its combat damage to nothing at all unless it has trample,
    which is a branch the combat damage step has had since it was written.

    Two writes, and they are not a duplicate. ``blocked`` is the live flag every
    combat reader already asks, and the mark is what makes it *survive* — the
    combat phase rebuilds ``blocked`` from the block maps every time it prunes
    combat state, and this creature is in none of them.

    The printed narrowing is re-asked here (CR 608.2b): a creature that stopped
    attacking, or that something else blocked, between announcement and
    resolution is no longer a legal target, and the spell does nothing rather
    than marking a bystander.
    """
    from ..subject_filters import subject_matches

    described = instruction.payload.get("targets") or {}
    filters = described.get("filter") or {}
    observer = game.players.index(context.caster)

    def eligible(perm) -> bool:
        return subject_matches(
            game, perm, filters, observer=observer,
            source=context.source_permanent,
        )

    sweep = instruction.payload.get("subject")
    if sweep is not None and not described:
        # "**Attacking creatures** become blocked." (Fog Patch.) No target: the
        # set is every creature the printed phrase describes as the effect is
        # applied (CR 608.2h), found through the one matcher the targeted
        # spelling re-asks its choice through.
        chosen = [
            perm for perm in game.all_permanents()
            if perm.is_creature and subject_matches(
                game, perm, dict(sweep), observer=observer,
                source=context.source_permanent,
            )
        ]
        if not chosen:
            game.log.append(f"{context.card.name}: no attacking creatures")
    # "**X target attacking creatures** become blocked." (Choking Vines.) The
    # several-targets description says a list was collected, and each slot is
    # resolved strictly: a creature that left or stopped attacking is dropped
    # (CR 608.2b) and the rest still become blocked. No fallback scan, because a
    # fallback per slot would mark whichever attacker the scan reached first for
    # a choice the player made once.
    elif isinstance(described.get("count"), (int, str)) and described.get("count") != 1:
        chosen = resolve_target_permanents(game, context, predicate=eligible)
    else:
        found = resolve_target_permanent(
            game, context, predicate=eligible, fallback_on_invalid_choice=False,
        )
        chosen = [found] if found is not None else []
    if not chosen and sweep is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    # CR 509.3c: "Whenever [a creature] becomes blocked" triggers when an
    # effect blocks it "but only if the attacking creature was an unblocked
    # creature at that time". Read *before* the flag is written, because after
    # it every one of them is blocked — and a creature that already had a
    # blocker (Fog Patch blocks the blocked attackers too) is not announced a
    # second time.
    newly_blocked = [
        creature for creature in chosen
        if not creature.blocked and not game.creatures_blocking(creature)
    ]
    for creature in chosen:
        creature.blocked = True
        creature.metadata[BLOCKED_WITHOUT_BLOCKERS] = True
        game.log.append(
            f"{creature.card.name} becomes blocked ({context.card.name})"
        )
    game.fire_becomes_blocked_by_effect(newly_blocked)
    # What the *next* sentence means. "Each of those creatures" names every
    # creature this instruction blocked (CR 611.2c fixes the set when the effect
    # begins), by id and never by slot: the next instruction runs after this one
    # and a permanent may have left in between (CR 400.7).
    context.results[BLOCKED_PERMANENTS] = tuple(
        perm.permanent_id for perm in chosen
    )
    return True, "resolved"


@effect_handler("remove_from_combat")
def remove_from_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Disharmony: "Untap target attacking creature and **remove it from
    combat**." Reads the permanents the previous step of this resolution
    recorded (CR 611.2c fixed the set when the effect began) — nothing is
    chosen here, and an empty record is a legal outcome, not an error."""
    key = instruction.payload.get("permanents_from")
    # CR 509.1h is the default; the printed ", and creatures it was blocking …
    # become unblocked" (Imprison) is what overrides it, so the card decides
    # rather than the removal.
    frees = bool(instruction.payload.get("frees_blocked_attackers"))
    if key:
        removed_ids = list(recorded_permanent_ids(context, key))
    else:
        # "Remove **target attacking creature you control** from combat and
        # untap it." (Reconnaissance.) The other printing, where the removal is
        # the step that chooses — the ``targets`` description on the payload is
        # what says so, and the picker is derived from it. The printed noun
        # phrase is re-checked here as well as at announcement (idiom 9: the
        # picker's enumeration is a hint), through ``subject_matches`` because
        # "you control" and "attacking" are what the phrase is made of.
        from ..subject_filters import subject_matches

        described = {
            name: value for name, value in instruction.payload.items()
            if name not in ("targets", "frees_blocked_attackers")
        }
        observer = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        chosen = resolve_target_permanent(
            game, context,
            predicate=lambda p: subject_matches(
                game, p, described, observer=observer,
                source=context.source_permanent,
            ),
        )
        removed_ids = [chosen.permanent_id] if chosen is not None else []
    removed: list[int] = []
    for permanent_id in removed_ids:
        perm = game.permanent_by_id(permanent_id)
        if perm is None:
            continue
        _take_permanent_out_of_combat(game, perm, frees_blocked_attackers=frees)
        removed.append(permanent_id)
    # What a sentence behind this one means by "it" (Reconnaissance's untap).
    # By id, never by object or slot (CR 400.7), and written whichever branch
    # above ran: which printing chose the permanent is not something the step
    # behind it can see, so it must not be something it has to know.
    context.results[REMOVED_FROM_COMBAT_PERMANENTS] = tuple(removed)
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
    # False Orders prints the same overriding clause Ydwen Efreet does.
    game._remove_blocker_from_combat(
        target_player_index, removed_index, frees_blocked_attackers=True
    )

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


@effect_handler("double_combat_damage_until_eot")
def double_combat_damage_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Blind Fury: "If a creature would deal combat damage to a creature this
    turn, it deals double that damage to that creature instead."

    A CR 614 replacement armed by a resolving *spell*, so there is no permanent
    for the interceptor to read and the record goes on the game — the same shape
    the Fog flag below it takes, and appended rather than set for
    ``_damage_multiplier``'s reason: two copies are two effects and the doubling
    squares.

    The name is recorded rather than a bare count, so the log names the card
    that did it.
    """
    game.combat_damage_doubled_between_creatures.append(context.card.name)
    game.log.append(
        f"{context.card.name}: combat damage between creatures is doubled this turn"
    )
    return True, "resolved"


@effect_handler("prevent_all_combat_damage")
def prevent_all_combat_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    game.combat_damage_prevented_until_eot = True
    game.log.append("Combat damage prevented until end of turn")
    return True, "resolved"


@effect_handler("prevent_all_combat_damage_except_from")
def prevent_all_combat_damage_except_from(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all combat damage that would be dealt this turn. If this
    spell's additional cost was paid, this effect doesn't affect combat damage
    that would be dealt by red creatures." (Undergrowth, cost paid.)

    :func:`prevent_all_combat_damage`'s narrowed twin: the same turn-wide
    blanket with a hole in it, described by the damage's *source*. A record
    rather than a second flag because the hole is a printed noun phrase, and
    ``engine/prevention.py`` re-matches it when damage would be dealt — so a red
    creature that enters after this resolves is exempt too, which is what the
    sentence says.

    The seat is captured for the matcher's sake (a "you control" narrowing would
    need one), exactly as the recipient-scoped record beside it captures it, and
    for the same reason: the effect is the ability's controller's (CR 109.5)
    even if the board changes hands afterwards.
    """
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(context.caster)
    game.combat_damage_prevented_except_from.append(
        {"filter": described, "seat": seat}
    )
    game.log.append(
        f"{context.card.name}: combat damage is prevented this turn except from "
        f"matching sources"
    )
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


def forced_attacker_is_legal(game: Game, permanent: Permanent) -> bool:
    """Whether *permanent* is the creature this template may name: "target
    non-Wall creature **the active player has controlled continuously since the
    beginning of the turn**" (Nettling Imp, Norritt, Arcum's Whistle).

    Every clause narrows, and each was being dropped. The seat is the active
    player's, because the card exists to make somebody attack on *their* turn;
    the continuity is what keeps a creature that arrived this turn out, which is
    the difference between this and Siren's Call. Read off
    ``summoning_sickness_turn`` — the same record ``Game.can_attack`` asks —
    rather than a second one, because a permanent that entered this turn is
    exactly a permanent its controller has not had since the turn began.

    One reader, asked by the handler that marks the creature and by the legality
    gate that offers the picker its candidates, so the list a player is shown
    and the list the engine accepts cannot differ.
    """
    if not permanent.is_creature or permanent.has_type("wall"):
        return False
    if game.controller_index_of(permanent) != game.active_player_index:
        return False
    return permanent.metadata.get("summoning_sickness_turn") != game.turn


@effect_handler("mark_non_wall_target_to_attack")
def mark_non_wall_target_to_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose target non-Wall creature the active player has controlled
    continuously since the beginning of the turn. That creature attacks this
    turn if able. Destroy it at the beginning of the next end step if it didn't
    attack this turn."

    **The chosen creature**, which this used to ignore: it scanned the target
    player's battlefield and marked the first non-Wall creature it found, so a
    player who picked the Hill Giant got the Grizzly Bears marked instead. The
    card said "choose target" and the engine chose for them.
    """
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: forced_attacker_is_legal(game, perm),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: no legal creature to force into combat")
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    chosen.metadata["destroy_if_did_not_attack_eot"] = True
    game.log.append(f"{chosen.card.name} marked to attack this turn")
    return True, "resolved"


@effect_handler("force_target_to_attack_until_eot")
def force_target_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature attacks this turn if able." (Boiling Blood.)

    CR 508.1a's requirement for one turn on the creature the caster chose
    (CR 601.2c), through the same ``must_attack_until_eot`` mark
    ``declare_attackers_step`` already reads — so "if able" keeps meaning what
    it means everywhere else and a creature that cannot legally attack simply
    does not.

    No destroy rider. The sibling kind one function up (Nettling Imp's) carries
    one because *its* card prints one, and folding the two would have made this
    spell kill a creature that stayed home.

    The printed noun phrase is re-asked here, not only at announcement: a target
    that stopped being a creature between the two is no longer the thing the
    card names (CR 608.2b), and asking it through ``subject_matches`` is what
    keeps the picker's list and this resolution's one list.
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(
            f"{context.card.name}: its target is gone (608.2b)"
        )
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    game.log.append(f"{chosen.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("force_bound_to_attack_until_eot")
def force_bound_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This artifact deals 1 damage to target creature. **That creature**
    attacks this turn if able." (Bullwhip.)

    The same CR 508.1a requirement as the targeted kind above, on the object an
    earlier step of this resolution already acted on rather than on a second
    choice. ``bound_permanent`` is the reader every "that creature" goes
    through, so a requirement inside a loop names the iteration's object and one
    outside it names the ability's own target (CR 601.2c) -- and no picker is
    involved either way, which is the whole difference from the kind above.

    No noun phrase is re-tested: the sentence in front of this one already found
    the creature, and asking again would be a second reading of one choice.
    Whether it is still a creature is the requirement's own business -- the mark
    means nothing on a permanent that cannot attack, and "if able" is what makes
    that harmless.
    """
    chosen = bound_permanent(game, context)
    if chosen is None:
        game.log.append(
            f"{context.card.name}: nothing left for the attack requirement"
        )
        return True, "resolved"
    chosen.metadata["must_attack_until_eot"] = True
    game.log.append(f"{chosen.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("force_bound_to_block_until_eot")
def force_bound_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Untap target creature you don't control. **That creature blocks this
    turn if able.**" (Provoke.)

    CR 509.1c's weakest requirement, for one turn, on the creature the sentence
    in front of this one untapped: block *something* it legally can. The
    narrowed kind below records **which** attacker is owed; this one records
    only that a block is, which is why it is a flag rather than a list -- there
    is no pair here, and an empty list would compel nobody.

    ``bound_permanent`` is the reader every "that creature" goes through, so
    the pronoun means the ability's own target outside a loop and the
    iteration's object inside one, and no picker is involved either way.

    Nothing is re-tested: the untap in front of it already found the creature,
    and "if able" is what makes the mark harmless on one that cannot block.
    """
    chosen = bound_permanent(game, context)
    if chosen is None:
        game.log.append(
            f"{context.card.name}: nothing left for the block requirement"
        )
        return True, "resolved"
    chosen.metadata[MUST_BLOCK_UNTIL_EOT] = True
    game.log.append(f"{chosen.card.name} blocks this turn if able")
    return True, "resolved"


@effect_handler("force_target_to_block_until_eot")
def force_target_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature blocks this creature this turn if able." (Trumpeting
    Armodon.)

    CR 509.1c's requirement for one turn on the creature the caster chose
    (CR 601.2c), aimed at **one named attacker** — the ability's own source.
    Recorded on the compelled creature as that attacker's ``permanent_id``,
    which the declare-blockers step reads and the cleanup sweep clears.

    By id, and appended rather than assigned: two activations name two
    attackers and the creature owes both blocks as far as the rules allow, and
    an attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old requirement no longer names.

    The printed noun phrase is re-asked here, not only at announcement, for the
    reason the attack twin gives: a target that stopped being a creature
    between the two is no longer the thing the card names (CR 608.2b).

    With no source on the battlefield there is no attacker for the requirement
    to be about, so nothing is recorded — a mark with no id in it would be a
    "block anything" requirement the card never prints.
    """
    from ..subject_filters import subject_matches

    attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: its own attacker has left, so nothing is "
            "compelled to block"
        )
        return True, "resolved"
    # "Defending player chooses an untapped creature they control. **That
    # creature** blocks this creature this turn if able." (Crashing Boars.) The
    # creature an earlier step of this same resolution chose, read out of the
    # scratchpad by id — nothing was targeted, so there is no announcement to
    # resolve and nothing to re-check: the prompt's own candidate rule already
    # enforced the printed noun phrase, and re-asking it here would be a second
    # reading of a set the card only ever describes once.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key:
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            perm = game.permanent_by_id(permanent_id)
            if perm is None:
                continue
            _owe_block(game, perm, attacker, context)
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=attacker,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    _owe_block(game, chosen, attacker, context)
    return True, "resolved"


def _owe_block(game: Game, blocker, attacker, context) -> None:
    """Record that *blocker* owes *attacker* a block this turn (CR 509.1c).

    One body for both ways the creature is named — a target the caster chose
    (Trumpeting Armodon) and one an earlier step of the resolution recorded
    (Crashing Boars) — because what is recorded does not depend on which. By
    id, and appended rather than assigned: two activations name two attackers
    and the creature owes both blocks as far as the rules allow, and an
    attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old requirement no longer names.
    """
    owed = list(blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ())
    if attacker.permanent_id not in owed:
        owed.append(attacker.permanent_id)
    blocker.metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] = owed
    game.log.append(
        f"{blocker.card.name} blocks {attacker.card.name} this turn if able"
    )


@effect_handler("force_subject_to_block_until_eot")
def force_subject_to_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…all creatures with magnet counters on them block **that creature** this
    turn if able." (Magnetic Web.)

    The unnarrowed twin of the requirement above: every creature the printed
    noun phrase describes, on every battlefield, rather than one the caster
    chose. Same record and same enforcement — the attacker's ``permanent_id``
    on each compelled creature — so nothing new decides what "if able" means.

    ``attacker: "bound"`` is the creature the trigger's event was about, read
    out of the frozen trigger context by id (CR 400.7). The lowering refuses
    the pronoun under an event that records no attacker, so a missing id here
    is an attacker that has already left rather than a sentence nobody read.

    Through ``subject_matches`` with the ability's controller as CR 109.5's
    "you", the one reader of a printed noun phrase — and over
    ``all_permanents``, because the sentence scopes to no seat: a Magnetic Web
    attacker is on the *active* player's battlefield and the creatures compelled
    to block it are on everybody else's.
    """
    from ..subject_filters import subject_matches

    if instruction.payload.get("attacker") == "bound":
        bound = (context.trigger_context or {}).get("event_subject_permanent_id")
        attacker = game.permanent_by_id(bound) if isinstance(bound, int) else None
    else:
        attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: the attacker has left, so nothing is "
            "compelled to block"
        )
        return True, "resolved"
    described = instruction.payload.get("subject") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    compelled = 0
    for perm in game.all_permanents():
        if perm is attacker or not perm.is_creature:
            continue
        if not subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ):
            continue
        owed = list(perm.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ())
        if attacker.permanent_id not in owed:
            owed.append(attacker.permanent_id)
        perm.metadata[MUST_BLOCK_ATTACKERS_UNTIL_EOT] = owed
        compelled += 1
    game.log.append(
        f"{compelled} creature(s) block {attacker.card.name} this turn if able "
        f"({context.card.name})"
    )
    return True, "resolved"


def _windowed_seat(game, context, window) -> int | None:
    """The seat a payload ``window`` names, or None when nothing recorded one.

    One name today (``turn_state.THAT_PLAYERS_NEXT_TURN``) and one record: the
    player an earlier step of this same resolution asked to choose. Read here
    rather than at each of the three call sites so the requirement, the
    restriction and the end-step destruction cannot come to disagree about
    which turn "that turn" is — they are three sentences about one window,
    computed from one record inside one resolution, so they agree by
    construction rather than by comparison.
    """
    if window != THAT_PLAYERS_NEXT_TURN:
        return None
    seat = (context.results or {}).get("chosen_player")
    if isinstance(seat, int) and 0 <= seat < len(game.players):
        return seat
    return None


def _recorded_subject_permanents(game, context, payload):
    """The permanents a named step of this resolution recorded, still on the
    battlefield.

    ``subject_from`` is the plural of ``binds_recorded`` one file over: the
    sentence names "**the chosen creatures**" rather than a class, so the set is
    the answer an earlier step wrote and not something re-read off the board.
    Survivors only, by the same ``permanent_id`` resolution every other reader
    of a recorded set uses — a creature that has left is not there to be
    required to attack.
    """
    recorded = (context.results or {}).get(str(payload.get("subject_from"))) or ()
    found = []
    for entry in recorded:
        permanent = (
            entry if hasattr(entry, "permanent_id")
            else game.permanent_by_id(entry) if isinstance(entry, int) else None
        )
        if permanent is not None and game.is_on_battlefield(permanent):
            found.append(permanent)
    return found


@effect_handler("force_subject_to_attack_until_eot")
def force_subject_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Non-Wall creatures the active player controls attack this turn if able.
    At the beginning of the next end step, destroy each of those creatures that
    didn't attack this turn." (Maddening Imp.)

    The unnarrowed twin of ``force_target_to_attack_until_eot`` and the exact
    mirror of ``force_subject_to_block_until_eot`` beside it: every creature the
    printed noun phrase describes, on every battlefield, rather than one the
    caster chose. Same ``must_attack_until_eot`` mark the declare-attackers step
    already reads, so nothing new decides what "if able" means.

    Over ``all_permanents`` rather than one seat's battlefield, because the
    phrase scopes itself: "the active player controls" is a filter word
    (CR 102.1) that ``subject_matches`` answers, and reading the seat here as
    well would be a second opinion about which creatures the card names. That
    second opinion is what this replaces: ``force_active_player_creatures_to_attack``
    had ``active_player_index`` written into it and was reachable only by
    Siren's Call's name, so Maddening Imp — printing the identical sentence
    with one extra narrowing — got nothing from it.

    ``destroy_if_absent`` is the printed tail, and it is the same
    ``destroy_if_did_not_attack_eot`` mark Nettling Imp's fused handler sets and
    the end step already sweeps (``engine/phases/end_step.py``). Set at
    resolution rather than looked up at the end step, which is what makes
    "those creatures" mean the set that was marked and not whatever the noun
    phrase would describe a turn later.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    described = payload.get("subject") or {}
    destroy = bool(payload.get("destroy_if_absent"))
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    # "**During that player's next turn**, the chosen creatures attack if able."
    # (Oracle en-Vec.) Two payload keys over the same requirement: which turn it
    # holds for, and where the set came from. A window nobody recorded a seat
    # for does nothing rather than compelling the set on this turn, which is a
    # requirement a turn early and in the wrong player's favour.
    window = payload.get("window")
    seat = _windowed_seat(game, context, window) if window else None
    if window and seat is None:
        game.log.append(f"{context.card.name}: no player's turn to name")
        return True, "resolved"
    stamp = seats_next_turn_window(game, seat) if seat is not None else None
    if payload.get("subject_from"):
        subjects = _recorded_subject_permanents(game, context, payload)
    else:
        subjects = [
            perm for perm in game.all_permanents()
            if perm.is_creature and subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            )
        ]
    marked: list[str] = []
    for perm in subjects:
        if stamp is not None:
            perm.metadata[MUST_ATTACK_ON_SEAT_TURN_KEY] = dict(stamp)
            if destroy:
                perm.metadata[
                    DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY
                ] = dict(stamp)
        else:
            perm.metadata["must_attack_until_eot"] = True
            if destroy:
                perm.metadata["destroy_if_did_not_attack_eot"] = True
        marked.append(perm.card.name)
    if marked:
        when = (
            f"during {game.players[seat].name}'s next turn"
            if stamp is not None else "this turn"
        )
        game.log.append(
            f"{context.card.name} forces {', '.join(marked)} to attack {when}"
        )
    else:
        game.log.append(
            f"{context.card.name} resolved with no creatures to force into combat"
        )
    return True, "resolved"


@effect_handler("force_self_to_attack_until_eot")
def force_self_to_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…this creature deals 3 damage to you **and attacks this turn if able**."
    (Kookus.)

    CR 508.1a's requirement for one turn, on the ability's own source. The mark
    is the one ``declare_attackers`` already reads, so nothing new decides what
    "if able" means: a creature that cannot legally attack simply does not, and
    the requirement is met as far as the rules allow.

    Not the printed static ``engine/combat_restrictions.py`` reads for "attacks
    **each combat** if able" — that one lasts as long as the permanent is on the
    battlefield, and this ends with the turn (CR 611.2a), which is why the mark
    is the until-end-of-turn one and not a text claim.

    A source that has left the battlefield marks nothing: there is no permanent
    to require anything of, and CR 608.2 does as much as it can.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to make attack")
        return True, "resolved"
    source.metadata["must_attack_until_eot"] = True
    game.log.append(f"{source.card.name} must attack this turn if able")
    return True, "resolved"


@effect_handler("destroy_subject_at_end_step_if_it_didnt_attack")
def destroy_subject_at_end_step_if_it_didnt_attack(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of the next end step, destroy each of those creatures
    that didn't attack this turn." (Maddening Imp.) "…destroy all non-Wall
    creatures that player controls that didn't attack this turn. Ignore this
    effect for each creature the player didn't control continuously since the
    beginning of the turn." (Siren's Call.)

    The delayed half of the attack requirement, over the set a printed noun
    phrase describes. It arms the ``destroy_if_did_not_attack_eot`` mark the end
    step already sweeps (``engine/phases/end_step.py``) — the same mark Nettling
    Imp's fused handler sets for one creature — so nothing new decides when the
    destruction happens or whether regeneration is offered.

    **Marked now, swept later**, which is what makes the words mean what they
    say: "those creatures" is the set as it stood when the ability resolved, and
    a creature that arrives afterwards is not one of them however well it
    matches the phrase. Re-reading the noun phrase at the end step would be a
    second, later answer to a question CR 608.2 asked once.

    The two cards' sets differ from their own requirements' and from each
    other's — Siren's Call compels *every* creature the active player controls
    and destroys only the non-Walls it has controlled since the turn began — so
    the description travels in the payload rather than being inherited from the
    requirement beside it.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    described = payload.get("subject") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    # "At the beginning of **that turn's** end step, destroy each of **the
    # chosen creatures** that didn't attack this turn." (Oracle en-Vec.) The
    # same two keys the requirement above reads, and the same window computed
    # the same way from the same record — "that turn" is the turn the sentence
    # in front of it named, and both resolve inside one resolution, so the two
    # arithmetics cannot disagree.
    window = payload.get("window")
    seat = _windowed_seat(game, context, window) if window else None
    if window and seat is None:
        game.log.append(f"{context.card.name}: no player's turn to name")
        return True, "resolved"
    stamp = seats_next_turn_window(game, seat) if seat is not None else None
    if payload.get("subject_from"):
        subjects = _recorded_subject_permanents(game, context, payload)
    else:
        subjects = [
            perm for perm in game.all_permanents()
            if perm.is_creature and subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            )
        ]
    marked: list[str] = []
    for perm in subjects:
        if stamp is not None:
            perm.metadata[DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY] = dict(stamp)
        else:
            perm.metadata["destroy_if_did_not_attack_eot"] = True
        marked.append(perm.card.name)
    if marked:
        game.log.append(
            f"{context.card.name}: {', '.join(marked)} will be destroyed at end "
            "step if they didn't attack"
        )
    else:
        game.log.append(
            f"{context.card.name} resolved with no creatures to mark for the "
            "end-step destruction"
        )
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


#: The scratchpad key the unblockable grant records its creatures under. One
#: name, because the handler writes it and ``lowering/_records._PRODUCES``
#: declares it, and a second spelling would make the lowering's gate vacuous
#: while the record sat unread.
UNBLOCKABLE_PERMANENTS = "unblockable_permanents"


@effect_handler("grant_unblockable_to_target")
def grant_unblockable_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked this turn." (Teleport) / "…with
    **power 2 or less**…" (Dwarven Warriors) / "**X target creatures** with
    power 2 or less…" (Runed Arch) / "…**you control**…" (Goblin Sappers).

    One handler for all four, because the only difference between them is the
    noun phrase, and a noun phrase is something ``subject_matches`` answers.
    Dwarven Warriors used to have a handler of its own with "power 2 or less"
    written into its source — and again into ``legality.py``'s enumerator — so
    every other printing of the template refused.

    The filter is re-tested **here** and not only by the picker: CR 608.2b's
    check at resolution is what stops a creature that has been pumped past the
    bound since activation from being made unblockable, and a target the picker
    offered is not a target the effect still applies to.
    """
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items()
        if key != "targets"
    }
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )

    def _legal(perm: Permanent) -> bool:
        return perm.is_creature and subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        )

    # "X target creatures" resolves a *list*, and strictly: a per-slot fallback
    # would silently make one creature unblockable twice where the player chose
    # two (`resolve_target_permanents`).
    if _names_a_list(instruction):
        chosen = resolve_target_permanents(game, context, predicate=_legal)
    else:
        one = resolve_target_permanent(game, context, predicate=_legal)
        chosen = [one] if one is not None else []
    if not chosen:
        game.log.append(f"{context.card.name}: no creature to make unblockable")
        return True, "resolved"
    for target_creature in chosen:
        target_creature.metadata["cant_be_blocked_until_eot"] = True
        game.log.append(f"{target_creature.card.name} can't be blocked this turn")
    # "…can't be blocked this turn. **Destroy it** … at end of combat." (Goblin
    # Sappers.) The sentence after this one names what this one chose, and the
    # scratchpad is where it reads it — the same record a tap or an untap
    # writes, under the same shape (ids, never indices), so the lowering that
    # gates on "did an earlier step of this effect name a permanent?" asks one
    # question of all three.
    context.results[UNBLOCKABLE_PERMANENTS] = [
        perm.permanent_id for perm in chosen
    ]
    return True, "resolved"


@effect_handler("target_cant_block_until_eot")
def target_cant_block_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't block this turn." (Panic.)

    The mirror of ``grant_unblockable_to_target`` above — that one stops a
    creature *being* blocked, this one stops it blocking — and the same shape:
    a mark on the one permanent the spell chose, swept with the turn by
    ``_EOT_METADATA_KEYS``, read by the blocker gate.

    Not the blanket ``cant_block_until_eot`` beside it: that arms a board-wide
    filter, and a targeted restriction routed through it would reach every
    creature its noun phrase describes.

    "**Up to three target creatures** can't block this turn." (Panic Attack.)
    The same mark on each creature of a chosen list, resolved strictly — a
    per-slot fallback would mark one creature twice where the player chose
    two, and a slot whose creature left is simply not affected (CR 608.2b).
    """
    if _names_a_list(instruction):
        chosen = resolve_target_permanents(
            game, context, predicate=lambda p: p.is_creature
        )
        if not chosen:
            game.log.append(f"{context.card.name}: no creature to stop blocking")
        for each in chosen:
            each.metadata[CANT_BLOCK_UNTIL_EOT] = True
            game.log.append(f"{each.card.name} can't block this turn")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to stop blocking")
        return True, "resolved"
    target_creature.metadata[CANT_BLOCK_UNTIL_EOT] = True
    game.log.append(f"{target_creature.card.name} can't block this turn")
    return True, "resolved"


@effect_handler("target_cant_attack_until_eot")
def target_cant_attack_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't attack this turn." (Change of Heart.)

    The attacking twin of ``target_cant_block_until_eot`` above, and the same
    shape: a mark on the one permanent the spell chose, swept with the turn by
    ``_EOT_METADATA_KEYS``, read by ``declare_attackers_step.can_attack``.

    Not the blanket ``cant_attack_until_eot`` beside it -- that arms a
    board-wide filter, and a targeted restriction routed through it would
    ground every creature its noun phrase describes.

    The printed noun phrase is re-asked here, not only at announcement, for the
    reason every other targeted combat mark gives: a target that stopped being
    a creature between the two is no longer what the card names (CR 608.2b).
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    target_creature = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    target_creature.metadata[CANT_ATTACK_UNTIL_EOT] = True
    game.log.append(f"{target_creature.card.name} can't attack this turn")
    return True, "resolved"


@effect_handler("target_cant_block_source_until_eot")
def target_cant_block_source_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't block this creature this turn." (Duct Crawler.)

    CR 509.1b's denial narrowed to one named attacker — the ability's own
    source — and the exact mirror of ``force_target_to_block_until_eot`` above,
    down to why it is recorded the way it is: the forbidden attacker's
    ``permanent_id`` appended to a list on the restricted creature, because two
    activations name two attackers and both denials hold, and because an
    attacker that leaves and returns is a new object (CR 400.7) whose new id
    the old denial does not name.

    With no source on the battlefield there is no attacker for the denial to be
    about, so nothing is recorded — a mark with no id in it would be a "can't
    block at all" this card never prints.
    """
    from ..subject_filters import subject_matches

    attacker = context.source_permanent
    if attacker is None or not game.is_on_battlefield(attacker):
        game.log.append(
            f"{context.card.name}: its own attacker has left, so nothing is "
            "denied a block"
        )
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    chosen = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=attacker,
        ),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    denied = list(chosen.metadata.get(CANT_BLOCK_ATTACKERS_UNTIL_EOT) or ())
    if attacker.permanent_id not in denied:
        denied.append(attacker.permanent_id)
    chosen.metadata[CANT_BLOCK_ATTACKERS_UNTIL_EOT] = denied
    game.log.append(
        f"{chosen.card.name} can't block {attacker.card.name} this turn"
    )
    return True, "resolved"


@effect_handler("grant_additional_blocks_until_eot")
def grant_additional_blocks_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That creature can block up to two additional creatures this turn."
    (Yare.)

    CR 509.1b's block-count ceiling raised on one permanent for one turn. A
    record on the creature, read by ``_max_blocks_for`` beside the printed
    static it already counts and swept with the turn by ``_EOT_METADATA_KEYS``
    -- the arrangement every other granted combat permission here uses.

    It **adds**, because CR 509.1b's restrictions are cumulative in both
    directions: two grants on one creature are two more attackers, and a
    creature that already blocks an additional one by its own printed line
    keeps that too. Assignment rather than addition would have made the second
    copy of the spell do nothing.

    ``subject: "source"`` is the ability's own permanent ("{W}: This creature
    can block an additional creature this turn.", Mounted Archers). Resolved
    explicitly rather than through ``resolve_target_permanent``, whose
    no-target fallback scans the battlefield -- an activated ability names no
    target, so the fallback would grant the permission to whichever creature
    the scan reached first.
    """
    if instruction.payload.get("subject") == "source":
        blocker = context.source_permanent
    else:
        blocker = resolve_target_permanent(
            game, context, predicate=lambda p: p.is_creature
        )
    if blocker is None:
        game.log.append(
            f"{context.card.name}: no creature to grant extra blocks to"
        )
        return True, "resolved"
    extra = max(0, int(instruction.payload.get("count", 1)))
    blocker.metadata[ADDITIONAL_BLOCKS_UNTIL_EOT] = (
        int(blocker.metadata.get(ADDITIONAL_BLOCKS_UNTIL_EOT, 0)) + extra
    )
    game.log.append(
        f"{blocker.card.name} can block {extra} additional creature(s) this turn"
    )
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


@effect_handler("grant_cant_be_blocked_except_by_until_eot")
def grant_cant_be_blocked_except_by_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature can't be blocked this turn except by Walls." (Joven's
    Tools.)

    The granted twin of ``cant_be_blocked_except_by``, the static
    `engine/combat_restrictions.py` derives — and the **inverse** of
    ``grant_cant_be_blocked_by_until_eot`` beside it, not a flag on it: that one
    names blockers the creature is safe from and leaves the rest of the board
    able to block, this one names the only blockers there are. A record read as
    the other would turn one card into the other's opposite.

    An empty union would allow nothing at all rather than everything, which is
    a strictly larger effect than the card prints — so it refuses to arm rather
    than arming a whitelist nobody can satisfy. The lowering already declines
    the phrase; this is the second half of that rule, where a payload built by
    anything else arrives.
    """
    from ..combat_restrictions import grant_blocker_whitelist

    allowed = [
        described
        for described in (instruction.payload.get("allowed_blockers") or ())
        if described
    ]
    if not allowed:
        game.log.append(f"{context.card.name}: no blocker class to allow")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no creature to restrict")
        return True, "resolved"
    grant_blocker_whitelist(target_creature, allowed)
    game.log.append(
        f"{target_creature.card.name} can't be blocked this turn except by "
        f"matching creatures ({context.card.name})"
    )
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
    from .pump import DURATION_WORDS, grant_lifetime

    lifetime = grant_lifetime(game, instruction, context)
    grant_keyword(target_creature, "banding", **lifetime)
    # The duration the *card* printed, not the one this handler was written for.
    # Nature's Blessing's grant has none at all (CR 611.2a: it lasts as long as
    # the creature does), and a log line that says "until end of turn" over an
    # indefinite grant is the kind of second copy of a fact that survives long
    # after the fact stops being true.
    game.log.append(
        f"{target_creature.card.name} gains banding"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
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
    payload = instruction.payload
    entry = {
        "filter": dict(payload.get("filter") or {}),
        "source_name": context.card.name,
        # How many cleanups the window survives — 1 for every printed "this
        # turn", 2 for "this turn and next turn" (Peace Talks). Carried from
        # the payload rather than assumed, because the sweep is subtraction and
        # an assumed 1 ends the longer window a whole turn early.
        "remaining_turns": int(payload.get("remaining_turns", 1)),
    }
    # "**During that player's next turn**, … other creatures can't attack."
    # (Oracle en-Vec.) A turn that has not started, so the entry carries a
    # window stamp instead of a countdown — see ``phases/cleanup_step``, where
    # subtracting this turn's cleanup from it would end the restriction the turn
    # before it applied.
    window = payload.get("window")
    if window:
        seat = _windowed_seat(game, context, window)
        if seat is None:
            game.log.append(f"{context.card.name}: no player's turn to name")
            return True, "resolved"
        entry["on_seat_turn"] = seats_next_turn_window(game, seat)
    # "**Other** creatures can't attack" — other than the set an earlier step of
    # this resolution chose. Frozen now because that is when the choice was made
    # (CR 608.2), and by id because the entry outlives the resolution that wrote
    # it and a creature that leaves and returns is a new object the sentence
    # never named (CR 400.7). The restriction itself is deliberately *not*
    # frozen: CR 611.2c gives a rules-modifying effect the objects that arrive
    # later too, which is what the game-level entry is for.
    excepted = payload.get("except_from")
    if excepted:
        entry["except_permanent_ids"] = [
            permanent.permanent_id
            for permanent in _recorded_subject_permanents(
                game, context, {"subject_from": excepted}
            )
        ]
    game.attack_restrictions_until_eot.append(entry)
    game.log.append(f"{context.card.name}: the named creatures can't attack")
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


#: The two turn-scoped declaration tolls, mapped to the list each is filed in
#: and the word a log line uses. One table because the two handlers below differ
#: in nothing else: CR 508.1h and CR 509.1d are the same rule on two sides of
#: combat, and the *readers* are what tell them apart.
_PAY_TOLL_LISTS: dict[str, tuple[str, str]] = {
    "creatures_cant_attack_unless_pay_until_eot": (
        "attack_restrictions_until_eot", "attack",
    ),
    "creatures_cant_block_unless_pay_until_eot": (
        "blocking_restrictions_until_eot", "block",
    ),
}


def _arm_declaration_toll(game, instruction, context, kind: str):
    """File a "creatures can't <verb> unless their controller pays <cost>" toll.

    It goes in the very list the blanket prohibitions use, and that is the
    decision worth writing down: CR 508.1c and CR 509.1b make "can't attack"
    and "can't attack **unless some condition is met**" one rule, so one list is
    "what this turn forbids" and the cost is what the condition asks for. The
    two gates skip an entry carrying ``mana`` — a toll is not a ban, and a
    payable one forbids nothing — and the two *cost* readers pick it up
    instead. Cleanup already sweeps the list, so the window needs nothing new.

    **The cost is resolved here and stored concrete.** The ability announced X
    as it was activated (CR 601.2b, reached through CR 602.2b) and that number
    is fixed while the ability is on the stack (CR 107.3a) and so, once it has
    resolved, for the life of the effect; the declaration readers charge
    ``int()`` off the entry
    and would raise on a string, and a toll re-resolved at the declaration would
    read whichever X the *next* activation announced. A toll announced at X=0 is
    filed all the same and costs nothing, which is what the card says.
    """
    list_name, verb = _PAY_TOLL_LISTS[kind]
    cost = {
        symbol: max(0, int(context.x_value or 0)) if amount == "x" else int(amount)
        for symbol, amount in (instruction.payload.get("mana") or {}).items()
    }
    entry = {
        "filter": dict(instruction.payload.get("subject") or {}),
        # **The flag, not the cost, is what says this is a toll.** An entry
        # announced at X=0 owes {0}, which is a real and legal answer
        # (CR 107.3a: the choice is the activator's, and 0 is one of them) —
        # and a gate that told a toll from a ban by "does it carry
        # a price" would read that entry as a prohibition and ground every
        # creature the noun phrase names. The two readers key on this instead.
        "toll": True,
        "mana": {symbol: amount for symbol, amount in cost.items() if amount},
        "source_name": context.card.name,
    }
    getattr(game, list_name).append(entry)
    game.log.append(
        f"{context.card.name}: the named creatures can't {verb} this turn "
        f"unless their controller pays {mana_cost_label(entry['mana']) or '{0}'} "
        f"for each"
    )
    return True, "resolved"


@effect_handler("creatures_cant_attack_unless_pay_until_eot")
def creatures_cant_attack_unless_pay_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This turn, creatures can't attack unless their controller pays {X} for
    each attacking creature they control." (War Tax.) CR 508.1h."""
    return _arm_declaration_toll(
        game, instruction, context, "creatures_cant_attack_unless_pay_until_eot"
    )


@effect_handler("creatures_cant_block_unless_pay_until_eot")
def creatures_cant_block_unless_pay_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This turn, creatures can't block unless their controller pays {X} for
    each blocking creature they control." (War Cadence.) CR 509.1d."""
    return _arm_declaration_toll(
        game, instruction, context, "creatures_cant_block_unless_pay_until_eot"
    )


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


@effect_handler("assign_as_unblocked_until_eot")
def assign_as_unblocked_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"X target blocked creatures assign their combat damage this turn as
    though they weren't blocked." (Outmaneuver.)

    One mark per chosen creature, read by the combat damage step and ended by
    the cleanup sweep — the same shape ``assign_no_combat_damage_until_eot``
    below uses, over chosen permanents rather than over the source.

    Every named target still legal is marked and the rest of the effect still
    happens (CR 608.2b), which is what ``resolve_target_permanents`` gives; a
    target that has left is simply not marked. "Blocked" is re-checked here
    because it is the printed noun phrase and CR 608.2b asks a target's
    legality again at resolution — a creature whose blocker died to first-strike
    damage is no longer blocked, and marking it would be the spell reaching a
    creature it could not have named.
    """
    from ..subject_filters import subject_matches

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )

    def _legal(perm) -> bool:
        return perm.is_creature and subject_matches(
            game, perm, filters, observer=observer,
            source=context.source_permanent,
        )

    chosen = resolve_target_permanents(game, context, predicate=_legal)
    if not chosen:
        game.log.append(f"{context.card.name}: no blocked creature to redirect")
        return True, "resolved"
    for creature in chosen:
        creature.metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
    game.log.append(
        ", ".join(perm.card.name for perm in chosen)
        + " assign combat damage as though unblocked this turn "
        + f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("assign_no_combat_damage_until_eot")
def assign_no_combat_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"This creature assigns no combat damage this turn." (Floral Spuzzem.)

    Marks the effect's own source; ``engine/combat_assignment.py`` is what the
    combat damage step reads and the cleanup sweep is what ends it.

    ``subject: "attached"`` marks the permanent the source is attached to
    instead (Cloak of Confusion). One mark on one permanent either way — which
    permanent is payload, because the Aura's own assignment is not what the
    sentence is about and marking it would be the card doing nothing.

    With no permanent on the battlefield there is nothing the sentence is about,
    and the effect refuses rather than reporting a mark it did not make — the
    rider is the whole reason the card's first half is worth doing, so a
    silently dropped one is the card doing strictly more than it prints.
    """
    source = context.source_permanent
    subject = instruction.payload.get("subject")
    if subject == "attached":
        source = attached_host(game, source)
    elif subject == "bound":
        # "…when target creature you control attacks and isn't blocked, **it**
        # assigns no combat damage" (Delif's Cone, Delif's Cube). CR 603.7c's
        # object: the creature the delay's opener targeted, carried by id
        # because a permanent that left and came back is a different one
        # (CR 400.7) and must not inherit the mark.
        bound = (context.trigger_context or {}).get("bound_permanent_id")
        source = (
            game.permanent_by_id(bound) if isinstance(bound, int) else None
        )
    if source is None:
        return False, "ability not implemented"
    source.metadata[ASSIGNS_NO_COMBAT_DAMAGE] = True
    game.log.append(
        f"{source.card.name} assigns no combat damage this turn"
    )
    return True, "resolved"


@effect_handler("choose_blocks_for_defenders")
def choose_blocks_for_defenders(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Melee: "You choose which creatures block this combat and how those
    creatures block." CR 509.1a's chooser, substituted for the rest of this
    combat.

    One assignment, because that is the whole of what the card changes. The
    declaration stays the defending player's turn-based action, their creatures
    are the ones that block, every restriction and requirement is still checked
    against their board and CR 509.1d-f still charges them the cost — only the
    decisions inside CR 509.1a move. ``Game.block_chooser_index`` is the one
    place that is read, by the declaration's own gate, by the AI stepper and by
    the web layer, so "who is asked?" cannot come to have three answers.

    Set from the *resolving* seat rather than from the card's controller field:
    a copied Melee (Fork) is controlled by whoever copied it, and "you" on a
    spell is CR 109.5's controller of the spell.
    """
    seat = game.players.index(context.caster)
    game.combat_block_chooser = seat
    game.log.append(
        f"{context.card.name}: {context.caster.name} chooses this combat's blocks"
    )
    return True, "resolved"


def _blockers_of_attacker(game: Game, attacker_index: int) -> list[tuple[int, int]]:
    """``(defending seat, blocker index)`` for every creature blocking
    *attacker_index*.

    CR 802 means one attacker can only be blocked by the seat it is attacking,
    but ``combat_blockers`` is nested by defender and this reads it whole — the
    same shape ``_remove_blocker_from_combat``'s "still blocked" scan takes, and
    for the same reason: the question is about the attacker, not about a seat.
    """
    return [
        (seat, blocker_idx)
        for seat, blocker_map in game.combat_blockers.items()
        for blocker_idx, attackers in blocker_map.items()
        if attacker_index in attackers
    ]


@effect_handler("reassign_blockers_between_attackers")
def reassign_blockers_between_attackers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """General Jarkeld: "Choose two target blocked attacking creatures. If each
    of those creatures could be blocked by all creatures that the other is
    blocked by, each creature that's blocking exactly one of those attacking
    creatures stops blocking it and is blocking the other attacking creature."

    The **mirror** of Sorrow's Path's ``swap_block_assignments``: that card
    chooses the two blockers and swaps what each blocks, this one chooses the
    two attackers and swaps who blocks each. The hypothetical is the same
    question asked from the other end, and it is answered by the same helper —
    ``_could_block_all``, which asks exactly the gate a real declaration passes
    (CR 509.1b), because two questions would be two answers.

    Three things this handler does *not* do, each because the card does not say
    it:

    * **Nothing is removed from combat.** "Stops blocking it and is blocking the
      other" leaves every creature a blocking creature throughout, so
      ``_remove_blocker_from_combat`` is not the route — it unblocks an attacker
      whose only blocker left, which CR 509.1h forbids and which the words here
      never ask for.
    * **Each chosen attacker stays blocked**, for that same rule, even where the
      trade leaves one with no blockers at all: it was blocked, nothing removed
      it from combat and no effect says it becomes unblocked, so it stays a
      blocked creature and assigns no combat damage (CR 510.1a).
    * **"Blocks" does not trigger again.** CR 509.3a fires only if the creature
      "wasn't a blocking creature at that time" and CR 509.3c only if the
      attacker "was an unblocked creature at that time" — neither is true here.
      The per-pair halves (CR 509.3b, CR 509.3d) do fire, because no creature
      was already blocking the attacker it moves to.

    "Blocking **exactly one** of those attacking creatures" is the clause that
    keeps this from being a plain swap: a creature blocking both chosen
    attackers is blocking neither of them exactly once and does not move.
    """
    if not (0 <= game.active_player_index < len(game.players)):
        return True, "no combat"
    active = game.players[game.active_player_index]
    # The attackers are the active player's, whoever activated the ability, so
    # the targets are resolved against that battlefield rather than against
    # ``context.target`` — a defending player's ability names its opponent's
    # creatures.
    chosen = resolve_target_permanents(game, context, player=active)
    if len(chosen) != 2 or chosen[0] is chosen[1]:
        return True, "no targets"
    first, second = chosen
    first_idx = game.battlefield_index_of(first)
    second_idx = game.battlefield_index_of(second)
    if first_idx is None or second_idx is None:
        return True, "no targets"
    # CR 608.2b at resolution: both must still be attacking and still blocked —
    # the same two words the picker narrowed on. An attacker removed from combat
    # since is no longer one of the creatures this sentence is about.
    if not (
        first_idx in game.combat_attackers and second_idx in game.combat_attackers
    ):
        game.log.append(
            f"{context.card.name}: its chosen creatures are no longer attacking"
        )
        return True, "targets illegal"

    blockers_of_first = _blockers_of_attacker(game, first_idx)
    blockers_of_second = _blockers_of_attacker(game, second_idx)
    if not blockers_of_first or not blockers_of_second:
        game.log.append(
            f"{context.card.name}: its chosen creatures are no longer blocked"
        )
        return True, "targets illegal"

    # "If each of those creatures could be blocked by all creatures that the
    # other is blocked by" — one condition over the pair, checked before
    # anything moves, exactly as Sorrow's Path checks its mirror of it.
    def _blocker_at(seat: int, blocker_index: int):
        return game.permanent_at(game.players[seat], blocker_index)

    hypothetical_holds = all(
        _blocker_at(seat, b_idx) is not None
        and _could_block_all(game, _blocker_at(seat, b_idx), [first_idx])
        for seat, b_idx in blockers_of_second
    ) and all(
        _blocker_at(seat, b_idx) is not None
        and _could_block_all(game, _blocker_at(seat, b_idx), [second_idx])
        for seat, b_idx in blockers_of_first
    )
    if not hypothetical_holds:
        game.log.append(
            f"{context.card.name}: {first.card.name} and {second.card.name} "
            "could not be blocked by each other's blockers — nothing happens"
        )
        return True, "reassignment illegal"

    moved: dict[int, dict[int, list[int]]] = {}
    for from_idx, to_idx, blockers in (
        (first_idx, second_idx, blockers_of_first),
        (second_idx, first_idx, blockers_of_second),
    ):
        for seat, b_idx in blockers:
            assigned = game.combat_blockers.get(seat, {}).get(b_idx)
            if assigned is None or to_idx in assigned:
                # Blocking **both** chosen attackers, so not "exactly one": it
                # stays where it is.
                continue
            assigned[assigned.index(from_idx)] = to_idx
            # CR 510.1d's pre-committed division is keyed by the attacker it was
            # declared against, so it travels with the block — left behind it
            # would divide this blocker's damage among a creature it no longer
            # blocks.
            division = game.combat_multiblock_damage.get(b_idx)
            if division is not None and from_idx in division:
                division[to_idx] = division.pop(from_idx)
            moved.setdefault(seat, {}).setdefault(b_idx, []).append(to_idx)

    if not moved:
        game.log.append(
            f"{context.card.name}: every blocker was blocking both creatures — "
            "nothing moves"
        )
        return True, "resolved"

    # The per-permanent combat flags and the band propagation are the projection
    # of the maps just rewritten, exactly as they are after a declaration.
    # Neither attacker stops being blocked, because nothing left combat
    # (CR 509.1h).
    game._prune_combat_state()
    for seat, assignments in moved.items():
        game._record_block_history(seat, assignments)
        game._fire_creature_blocks_triggers(seat, assignments, already_blocking=True)
        game._fire_becomes_blocked_triggers(seat, assignments, already_blocked=True)
    game.log.append(
        f"{context.card.name}: the creatures blocking {first.card.name} and "
        f"{second.card.name} traded places"
    )
    return True, "resolved"
