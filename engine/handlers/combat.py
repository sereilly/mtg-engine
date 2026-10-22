"""A combat under way: who is in it, who is blocked, and how its damage is
assigned (CR 506.4, CR 509.1h, CR 510).

Removing a creature from combat (outright, on a lost coin flip, or False
Orders' re-block), making an attacker blocked, swapping or reassigning
blockers, random and divided blocking, the player who chooses this combat's
blocks (Melee), the combat-damage blankets, the
assignment overrides ("as though it weren't blocked", "assigns no combat
damage"), rampage, banding granted, and the delayed destruction of a block
pair at end of combat.

What a *declaration* must, may not, or must pay to include — every
restriction, requirement, permission and toll an effect arms for the declare
attackers and declare blockers steps — is ``combat_declarations.py``'s, split
out at the 2,000-line cap's split round.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ._common import flip_coin, flip_coin_for
from ._targets import (recorded_permanent_ids, attached_host,
                       block_pair_permanents, resolve_own_combatant,
                       resolve_role_permanent, resolve_target_permanent,
                       resolve_target_permanents, roles_still_legal)
from .registry import effect_handler
from ..keywords import grant_keyword
from ..destruction_events import mark_delayed_destruction
from ..combat_assignment import (ASSIGNS_NO_COMBAT_DAMAGE,
                                MUST_ASSIGN_AS_UNBLOCKED,
                                 BLOCKED_WITHOUT_BLOCKERS)
from ..oracle_types import REMOVED_FROM_COMBAT_PERMANENTS
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
    if flip_coin_for(game, controller, flip=flip_coin):
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
    if flip_coin_for(game, controller, flip=flip_coin):
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
        mark_delayed_destruction(game, victim, "destroy_at_end_of_combat")
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
#: name, for ``combat_declarations.UNBLOCKABLE_PERMANENTS``' reason: the handler writes it and
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
    ``engine/prevention/shields.py`` re-matches it when damage would be dealt
    — so a red creature that enters after this resolves is exempt too, which is
    what the sentence says.

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

    The *set* is deliberately not captured: `engine/prevention/shields.py`
    re-matches the phrase when damage would be dealt, so a Dog that enters after
    this resolves is covered. Handing a shield to each Dog present would have
    made the card narrower than it prints.
    """
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(context.caster)
    game.combat_damage_prevented_for.append({"filter": described, "seat": seat})
    game.log.append(
        f"{context.card.name}: combat damage to matching permanents is prevented this turn"
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

    if instruction.payload.get("subject") == "source":
        # "You may have **this creature** assign its combat damage this turn
        # as though it weren't blocked." (Gurzigost, the offer answered yes.)
        # The ability's own source, while it is still on the battlefield: a
        # creature that left and came back is a new object (CR 400.7) and
        # this ability is not about it.
        source = context.source_permanent
        if source is None or not game.is_on_battlefield(source):
            game.log.append(f"{context.card.name}: nothing left to mark")
            return True, "resolved"
        source.metadata[MUST_ASSIGN_AS_UNBLOCKED] = True
        game.log.append(
            f"{source.card.name} assigns combat damage as though unblocked "
            f"this turn ({context.card.name})"
        )
        return True, "resolved"
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
