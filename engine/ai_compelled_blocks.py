"""What a block an attacker compels is worth to the attacker's seat.

Provoke (CR 702.39a): "Whenever this creature attacks, you may choose to have
target creature defending player controls block this creature this combat if
able. If you do, untap that creature." Two decisions a seat nobody asks makes,
both about the same pair:

* **which creature** — CR 603.3d chooses the target as the ability is put on
  the stack (``choices/triggers._default_trigger_target``), and the target is
  mandatory while one exists, so the answer is the candidate the attacker gains
  most from fighting;
* **whether to use it** — the "may" is answered on resolution
  (``choices/optional_pay._default_optional_pay``), and an offer whose block
  the attacker gains nothing from is declined: taking it untaps a defending
  creature for nothing, or hands the defender a block it wanted.

Both are read off the **compiled program** (:func:`compels_a_block_on_source`)
rather than off the keyword, so a printed "target creature blocks this
creature this turn if able" trigger is weighed by the same answer.

The fight is estimated the way the combat damage step deals it — first strike
and double strike in two steps (CR 510.4), deathtouch as one point of lethal
damage (CR 702.2c), indestructible and a regeneration as survival
(:func:`survives_destruction`), a prevention shield as damage that may not
arrive (``ai_combat._would_be_prevented``, the attacker's own damage chooser's
question) — because a provoke that sends a 2/2 into a first-striking 2/2 is
the provoke a seat must not take.

**A regeneration is not indestructible.** A creature that regenerates is
removed from combat (CR 701.19a, CR 506.4), so a shielded creature that
first-strike damage would destroy deals no regular damage, and the creature
it was fighting assigns none to it either (CR 510.1c-d). Read as
indestructible, a shielded River Boa blocking a first striker "killed" it,
and a first striker blocking a shielded attacker "died" to damage it was
never dealt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ai_standing import permanent_worth
from .ai_weighed_cast import _effect_steps
from .combat_assignment import ASSIGNS_NO_COMBAT_DAMAGE, combat_damage_assigned_by

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent
    from .oracle_types import OracleInstruction


#: The steps that compel a creature to block one named attacker
#: (``handlers/combat_declarations``). Only the payloads naming the ability's
#: **source** as that attacker are read: the attacker is the creature whose
#: controller is choosing.
_COMPELLING_KINDS = frozenset({
    "force_bound_to_block_until_eot",
    "force_target_to_block_until_eot",
})

#: What a compelled block that kills nothing and loses nothing is worth: below
#: zero, because the attacker's damage that would have reached the player is
#: absorbed (trample aside) and a tapped target was untapped for nothing.
_STALEMATE = -0.5

#: The share of a creature's worth an untap hands the defender when the
#: creature then cannot block the attacker at all: it is free to block a
#: different one.
_UNTAPPED_FOR_NOTHING_SHARE = 0.25

#: How a creature survives damage that would destroy it
#: (:func:`survives_destruction`): **indestructible** (CR 702.12b) — the
#: damage stays marked and it fights on…
STAYS = "stays"
#: …or **regenerated** (CR 701.19a-b): tapped, its damage removed, and
#: removed from combat (CR 506.4), so it deals no combat damage in a later
#: step and is dealt none.
REGENERATES = "regenerates"


def survives_destruction(game: "Game", permanent: "Permanent", dealt_by=()) -> "str | None":
    """How *permanent* survives combat damage from *dealt_by* that would
    destroy it — :data:`STAYS`, :data:`REGENERATES` — or None when it does not.

    The engine's own questions (``engine/regeneration.py``): a shield spent
    on the next destruction (CR 701.19a) or the static "If this creature would
    be destroyed, regenerate it" (CR 701.19b), neither while "can't be
    regenerated" holds (CR 701.19c) — set already, or set by the damage
    itself when a dealer denies it (Bone Shaman's grant)."""
    from .regeneration import cant_be_regenerated, denies_regeneration, regenerates_itself

    if game._has_keyword(permanent, "indestructible"):
        return STAYS
    if cant_be_regenerated(permanent) or any(
        denies_regeneration(source) and combat_damage_assigned_by(source) > 0
        for source in dealt_by
    ):
        return None
    if permanent.regeneration_shield > 0 or regenerates_itself(permanent):
        return REGENERATES
    return None


def compels_a_block_on_source(instruction: "OracleInstruction | None") -> bool:
    """Whether a step of *instruction* compels a creature to block the
    ability's own source (provoke, Trumpeting Armodon)."""
    if instruction is None:
        return False
    return any(
        step.kind in _COMPELLING_KINDS
        and (step.payload or {}).get("attacker") == "source"
        for step in _effect_steps(instruction)
    )


def compelled_block_worth(game: "Game", attacker: "Permanent", blocker: "Permanent") -> float:
    """What *blocker* blocking *attacker* is worth to *attacker*'s seat.

    A creature killed is its worth gained; the attacker killed is its worth
    lost (``ai_standing.permanent_worth``, read as the board will be once
    the turn is over). A block that kills neither is :data:`_STALEMATE`, and a
    blocker that cannot block the attacker at all (no flying against a flier)
    is a creature untapped to block somebody else — **unless the attacker can
    shed what stops the block** with an ability of its own its controller can
    activate now (Swooping Talon's "{1}: This creature loses flying until end
    of turn", :func:`_shed_for_the_block`): then it is the fight with that
    shed, less the damage the evasion would have dealt. The shedding itself
    is the controller's later decision, rehearsed through the fight before
    the blocks (``ai_policy.choose_instant_speed_activation``).

    **A grounded attacker is open to every blocker, not only the one it
    compelled** (:func:`_ganged_on`): where the defender's other creatures
    that could then block it would kill it alongside the compelled one, the
    fight is the attacker lost. Three Grizzly Bears against a 2/6 Talon is
    six damage — the window then rightly declined to shed, and the provoke
    had untapped a Bears for nothing (kg3).
    """
    if not game._can_block_attacker(blocker, attacker):
        shed = _shed_for_the_block(game, attacker, blocker)
        if shed is not None:
            table, shed_attacker, shed_blocker = shed
            worth = compelled_block_worth(table, shed_attacker, shed_blocker)
            if _ganged_on(table, shed_attacker, shed_blocker):
                kills, _dies = fight_outcome(table, shed_attacker, shed_blocker)
                worth = min(worth, (
                    permanent_worth(shed_blocker, now=False) if kills else 0.0
                ) - permanent_worth(shed_attacker, now=False))
            return worth - _evasion_damage_worth(game, attacker, blocker)
        return -permanent_worth(blocker, now=False) * _UNTAPPED_FOR_NOTHING_SHARE
    kills, dies = fight_outcome(game, attacker, blocker)
    worth = 0.0
    if kills:
        worth += permanent_worth(blocker, now=False)
    if dies:
        worth -= permanent_worth(attacker, now=False)
    if not kills and not dies:
        return _STALEMATE
    return worth


def _shed_for_the_block(game: "Game", attacker: "Permanent", blocker: "Permanent"):
    """``(table, attacker, blocker)`` on a copy of *game* on which *attacker*'s
    controller has activated an ability of *attacker*'s own that hampers it
    (``ai_valuation.hampers_its_own_source``: a keyword lost, never the
    creature itself) and after which *blocker* can block it — or None.

    Only an ability the controller could activate **now**: no {T} on a
    tapped attacker, nothing the activation prohibitions refuse, a cost the
    engine's gate and the board can pay. The ability is the engine's own,
    activated and resolved on a scratch copy cut loose from whatever is
    resolving (``ai_scratch_copy._detach``) and asked the engine's own question
    (``_can_block_attacker``) — so what it sheds is whatever its program
    says, never a keyword named here."""
    import random

    from .activation_prohibitions import activation_prohibition
    from .ai_scratch_copy import _detach, scratch_copy
    from .ai_valuation import hampers_its_own_source, is_mana_ability
    from .board_payment import board_can_pay

    seat = game.controller_index_of(attacker)
    for index, ability in enumerate(game.usable_abilities_of(attacker)):
        if ability.instruction is None or is_mana_ability(ability.instruction):
            continue
        if not hampers_its_own_source(ability.instruction):
            continue
        if ability.cost.requires_tap and (attacker.tapped or game._is_summoning_sick(attacker)):
            continue
        if activation_prohibition(game, seat, attacker, ability) is not None:
            continue
        if game.unpayable_activation_cost(seat, attacker, ability) is not None:
            continue
        if game.enforce_mana_costs and not board_can_pay(game, seat, dict(ability.cost.mana)):
            continue
        state = random.getstate()
        try:
            table = scratch_copy(game)
            _detach(table, owing_nothing=True)
            table.enforce_mana_costs = False
            shed = table.permanent_by_id(attacker.permanent_id)
            held = table.permanent_by_id(blocker.permanent_id)
            if shed is None or held is None:
                continue
            result = table.queue_permanent_ability(
                seat, shed.card.name, permanent_index=table.battlefield_index_of(shed),
                ability_index=index,
            )
            if not getattr(result, "supported", False):
                continue
            table.resolve_top_of_stack()
        finally:
            random.setstate(state)
        if table._can_block_attacker(held, shed):
            return table, shed, held
    return None


def _ganged_on(game: "Game", attacker: "Permanent", blocker: "Permanent") -> bool:
    """Whether *attacker*, blocked by *blocker* and by every other untapped
    creature *blocker*'s controller has that could block it too, would be
    destroyed: their combat damage together (each as the damage step deals
    it, a prevention shield read as damage that may not arrive) against what
    destroys it — none where it survives destruction
    (:func:`survives_destruction`), one point from deathtouch (CR 702.2c).

    The defender's blocks are its own to declare later, and a gang that
    kills the attacker is the block a defender makes; nothing here is a
    rehearsal, because the question is asked part-way through the provoke's
    resolution, where no copy can be run."""
    from .ai_combat import _would_be_prevented

    seat = game.controller_index_of(blocker)
    gang = [blocker] + [
        other for other in game.controlled_by(seat)
        if other is not blocker and other.is_creature and not other.tapped
        and game._can_block_attacker(other, attacker)
    ]
    if len(gang) < 2:
        return False
    # The block's own triggers first (:func:`gang_block_pumps`), as
    # `ai_declarations._gang_kills` reads the gang the defender will make.
    pumps = gang_block_pumps(game, attacker, gang)
    if pumped_toughness(attacker, pumps) <= 0:
        return True
    if survives_destruction(game, attacker, dealt_by=gang) is not None:
        return False
    needed = max(0, pumped_toughness(attacker, pumps) - attacker.damage_marked)
    dealt = 0
    for member in gang:
        if pumped_toughness(member, pumps) <= 0:
            continue
        amount = pumped_combat_damage(member, pumps)
        if not amount or _would_be_prevented(game, member, attacker, amount):
            continue
        if game._has_keyword(member, "deathtouch"):
            return True
        dealt += amount
    return needed > 0 and dealt >= needed


def _evasion_damage_worth(game: "Game", attacker: "Permanent", blocker: "Permanent") -> float:
    """What the combat damage *attacker* deals unblocked is worth to its seat
    against *blocker*'s controller (``ai_standing.life_worth``) — the price
    of shedding the evasion that kept it unblocked."""
    from .ai_standing import life_worth

    defender = game.players[game.controller_index_of(blocker)]
    damage = combat_damage_assigned_by(attacker)
    return life_worth(defender.life) - life_worth(defender.life - damage)


def fight_outcome(game: "Game", attacker: "Permanent", blocker: "Permanent") -> "tuple[bool, bool]":
    """``(attacker destroys blocker, blocker destroys attacker)`` if the two
    fight alone — the combat damage step's two steps (CR 510.4) estimated.

    Each is fighting, destroyed, or **out** — regenerated, so removed from
    combat (:data:`REGENERATES`): neither deals the other damage in a later
    step (CR 510.1c-d). An indestructible one (:data:`STAYS`) fights on.

    **And a creature that leaves the fight as the blocks are made**
    (``ai_combat_triggers.leaves_the_fight``: Goblin Cadets' "Whenever this
    creature blocks or becomes blocked, target opponent gains control of
    it") deals and is dealt nothing, and is lost to its side — read as
    destroyed, the reading every caller here weighs it by."""
    from .ai_combat import _would_be_prevented
    from .ai_combat_triggers import leaves_the_fight

    attacker_leaves = leaves_the_fight(game, attacker, blocking=False)
    blocker_leaves = leaves_the_fight(game, blocker, blocking=True)
    if attacker_leaves or blocker_leaves:
        return blocker_leaves, attacker_leaves
    pumped = block_pair_pumps(game, attacker, blocker)

    def dealt(source, recipient) -> int:
        amount = pumped_combat_damage(source, pumped)
        if amount and _would_be_prevented(game, source, recipient, amount):
            return 0
        return amount

    def lethal(source, recipient) -> int:
        """Damage from *source* that would destroy *recipient*."""
        remaining = max(0, pumped_toughness(recipient, pumped) - recipient.damage_marked)
        if remaining > 0 and game._has_keyword(source, "deathtouch"):
            return 1
        return remaining

    def strikes(perm) -> tuple[bool, bool]:
        double = game._has_keyword(perm, "double strike")
        first = double or game._has_keyword(perm, "first strike")
        return first, (not first) or double

    to_blocker, to_attacker = dealt(attacker, blocker), dealt(blocker, attacker)
    kill_blocker, kill_attacker = lethal(attacker, blocker), lethal(blocker, attacker)
    blocker_saved = survives_destruction(game, blocker, dealt_by=(attacker,))
    attacker_saved = survives_destruction(game, attacker, dealt_by=(blocker,))
    attacker_first, attacker_regular = strikes(attacker)
    blocker_first, blocker_regular = strikes(blocker)

    on_blocker = on_attacker = 0
    fighting, dead, out = "fighting", "dead", "out"
    blocker_state = attacker_state = fighting
    # A pump that leaves no toughness puts the creature in the graveyard
    # before any damage (CR 704.5f): a 2/1 blocking a flanker.
    if pumped_toughness(blocker, pumped) <= 0:
        blocker_state = dead
    if pumped_toughness(attacker, pumped) <= 0:
        attacker_state = dead

    def destroyed(saved: "str | None") -> str:
        if saved == STAYS:
            return fighting
        return out if saved == REGENERATES else dead

    def settle() -> None:
        nonlocal blocker_state, attacker_state
        if blocker_state == fighting and on_blocker > 0 and on_blocker >= kill_blocker:
            blocker_state = destroyed(blocker_saved)
        if attacker_state == fighting and on_attacker > 0 and on_attacker >= kill_attacker:
            attacker_state = destroyed(attacker_saved)

    if attacker_first or blocker_first:
        if attacker_first:
            on_blocker += to_blocker
        if blocker_first:
            on_attacker += to_attacker
        settle()
    both = attacker_state == fighting and blocker_state == fighting
    if attacker_regular and both:
        on_blocker += to_blocker
    if blocker_regular and both:
        on_attacker += to_attacker
    settle()
    return blocker_state == dead, attacker_state == dead


#: The trigger conditions on each side of a block whose P/T changes the fight
#: before its damage: the attacker's "becomes blocked" (flanking's -1/-1 on
#: the blocker, Pygmy Troll's +1/+1) and the blocker's "blocks".
_BLOCKED_PUMP_CONDITIONS = frozenset({"creature_becomes_blocked", "creature_blocks_or_blocked_by"})
_BLOCKS_PUMP_CONDITIONS = frozenset({
    "creature_blocks", "creature_blocks_or_blocked_by", "creature_attacks_or_blocks",
})


def block_pair_pumps(game: "Game", attacker: "Permanent", blocker: "Permanent") -> dict:
    """``{id(creature): (power, toughness)}`` for the two — what their own
    triggers on this block add before combat damage: "Whenever this creature
    becomes blocked by a creature without flanking, the blocking creature
    gets -1/-1" (flanking, CR 702.25a: ``pump_block_pair``), "…becomes
    blocked by a creature, this creature gets +1/+1" (Pygmy Troll:
    ``pump_self``), and the blocker's own "Whenever this creature blocks"
    pumps. The one-blocker case of :func:`gang_block_pumps`."""
    return gang_block_pumps(game, attacker, [blocker])


def gang_block_pumps(game: "Game", attacker: "Permanent", members) -> dict:
    """``{id(creature): (power, toughness)}`` for *attacker* and each of
    *members* blocking it together — what their own triggers on this block
    add before combat damage, each fired as ``phases/block_triggers`` fires
    it: the attacker's bare "becomes blocked" once for the creature (CR
    509.3c), its "becomes blocked **by** a creature …" once for each member
    the phrase admits (CR 509.3d: flanking shrinks every blocker in a gang,
    Pygmy Troll grows once per blocker) or once for the declaration where it
    prints "one or more" (CR 509.3e), and each member's own "Whenever this
    creature blocks" — "…blocks **a creature with flying**" (Snarespinner)
    only where the attacker is one (CR 509.3b). "…for each creature blocking
    it" (Elvish Berserker) is the gang's size, "…beyond the first" (Johtull
    Wurm) one less. Which blocker a trigger fires for is the engine's own
    question (``events.trigger_subject_matches`` on its ``blocker`` subject,
    and on ``blocked`` for the blocker's own trigger).
    Steps behind a condition or a choice are left out; nothing is added once
    the attacker is blocked — the triggers have fired."""
    from .events import trigger_subject_matches
    from .phases.block_triggers import _threshold_blockers
    from .trigger_utils import matching_triggers

    members = list(members)
    found = {id(attacker): [0, 0], **{id(member): [0, 0] for member in members}}
    if not members or getattr(attacker, "blocked", False):
        return {key: tuple(value) for key, value in found.items()}
    seat = game.controller_index_of(attacker)
    for trigger in matching_triggers(
        attacker.effective_card, condition_kinds=_BLOCKED_PUMP_CONDITIONS,
    ):
        if trigger.condition.payload.get("blocker_filter"):
            firings = _threshold_blockers(trigger, [
                member for member in members
                if trigger_subject_matches(
                    game, trigger, "blocker", member, observer=seat, source=attacker,
                )
            ])
        else:
            firings = members[:1]
        for blocker in firings:
            _add_block_pumps(found, trigger, attacker, blocker, len(members))
    for member in members:
        member_seat = game.controller_index_of(member)
        for trigger in matching_triggers(
            member.effective_card, condition_kinds=_BLOCKS_PUMP_CONDITIONS,
        ):
            if trigger.condition.payload.get("blocked_filter") and not _threshold_blockers(
                trigger, [attacker] if trigger_subject_matches(
                    game, trigger, "blocked", attacker, observer=member_seat, source=member,
                ) else [],
            ):
                continue
            _add_block_pumps(found, trigger, member, attacker, 1)
    return {key: tuple(value) for key, value in found.items()}


def _add_block_pumps(found: dict, trigger, source, other, blockers: int) -> None:
    """Add one firing of *trigger* (printed on *source*, about *other*) to
    *found*: ``pump_self`` on *source*, ``pump_block_pair`` on *other*."""
    for step in _plain_steps(trigger.instruction):
        payload = step.payload or {}
        if step.kind == "pump_self":
            receiver = source
        elif step.kind == "pump_block_pair":
            receiver = other
        else:
            continue
        power = _one_on_one(payload.get("power"), payload, blockers)
        toughness = _one_on_one(payload.get("toughness"), payload, blockers)
        if power is not None and toughness is not None:
            found[id(receiver)][0] += power
            found[id(receiver)][1] += toughness


def pumped_combat_damage(source: "Permanent", pumps: dict) -> int:
    """The combat damage *source* assigns once its block pumps (*pumps*,
    :func:`gang_block_pumps`) have resolved: its power with theirs added,
    unless it assigns none (``ASSIGNS_NO_COMBAT_DAMAGE``)."""
    amount = combat_damage_assigned_by(source)
    power = pumps.get(id(source), (0, 0))[0]
    if power and not source.metadata.get(ASSIGNS_NO_COMBAT_DAMAGE):
        amount = max(0, source.effective_power + power)
    return amount


def pumped_toughness(creature: "Permanent", pumps: dict) -> int:
    """*creature*'s toughness once its block pumps (*pumps*) have resolved; a
    creature left with none is put into its graveyard before any damage
    (CR 704.5f)."""
    return creature.effective_toughness + pumps.get(id(creature), (0, 0))[1]


def _one_on_one(amount, payload: dict, blockers: int = 1) -> "int | None":
    """A pump's printed amount, or "+1/+1 … for each creature blocking it"
    (Elvish Berserker: ``times_x`` over a ``blocking_source`` count) with the
    *blockers* the fight has — "…beyond the first" (Johtull Wurm) the count's
    ``offset`` less, never below none. None for any other amount."""
    if isinstance(amount, int) and not isinstance(amount, bool):
        return amount
    count = payload.get("x_from_count") or {}
    if isinstance(amount, dict) and isinstance(amount.get("times_x"), int) and count.get(
        "blocking_source"
    ):
        return amount["times_x"] * max(0, blockers + int(count.get("offset") or 0))
    return None


def _plain_steps(instruction) -> list:
    """*instruction*'s steps, a ``sequence`` opened and nothing else — what
    happens whenever the ability resolves."""
    if instruction is None:
        return []
    if instruction.kind == "sequence":
        return [
            leaf for child in (instruction.payload or {}).get("steps") or ()
            for leaf in _plain_steps(child)
        ]
    return [instruction]


def compelled_blocks(game: "Game", defending_player_index: int) -> "dict[int, int]":
    """``{blocker slot: attacker slot}`` — the blocks CR 509.1c already
    requires of *defending_player_index*'s creatures, one attacker by name
    (provoke's mark, Trumpeting Armodon's, "blocks this creature this turn if
    able"), read off ``Game.block_requirements``: the first such requirement
    on each untapped creature that can block the attacker it names.

    The defending seat's chooser starts from these (``ai_declarations.
    choose_combat_blockers``), because the engine will make them whatever it
    chooses (``Game.obeying_block_declaration``) — so the fight a compelled
    creature wins alone is a fight nobody else need join. A requirement to
    block *something* (Watchdog) or for an attacker to be blocked by *someone*
    names no pair, and is left to that maximisation.

    **Of a creature's requirements, the attacker that holds the most of
    them**, the first such on a tie. CR 509.1c counts requirements obeyed,
    and a creature provoked twice by one attacker (two instances of provoke,
    CR 702.39b — every Sliver under two Hunter Slivers) obeys two by blocking
    it and one by blocking another provoker: the engine's maximisation moves
    it there whatever this seat declared. Read as "the first requirement",
    the seat planned Goblin Turncoat onto Goblin Grappler and traded its
    Hunter Sliver with the twice-provoking Crypt Sliver — and the engine then
    put the Turncoat on the Crypt Sliver too, two blockers on a 1/1 the
    Turncoat killed alone and Grappler unblocked (SCG Phase 5, the LGN
    block-commitment census)."""
    attacker_seat = game.active_player_index
    held: dict[int, dict[int, int]] = {}
    for requirement in game.block_requirements(defending_player_index):
        if requirement.blocker is None or requirement.attacker is None:
            continue
        blocker = game.permanent_at(defending_player_index, requirement.blocker)
        attacker = game.permanent_at(attacker_seat, requirement.attacker)
        if blocker is None or attacker is None or blocker.tapped or not blocker.is_creature:
            continue
        if not game._can_block_attacker(blocker, attacker):
            continue
        counts = held.setdefault(requirement.blocker, {})
        counts[requirement.attacker] = counts.get(requirement.attacker, 0) + 1
    # `max` keeps the first of equals in the order the requirements came, so
    # a creature each of whose attackers holds one requirement is planned
    # where it always was.
    return {blocker: max(counts, key=counts.get) for blocker, counts in held.items()}


def best_compelled_blocker(
    game: "Game", attacker: "Permanent", candidates: "list[Permanent]",
) -> "Permanent | None":
    """The candidate *attacker* gains most from fighting, first among equals
    in the order offered, or None when there is none."""
    best = None
    best_worth = None
    for candidate in candidates:
        worth = compelled_block_worth(game, attacker, candidate)
        if best_worth is None or worth > best_worth:
            best, best_worth = candidate, worth
    return best


def compelled_block_declined(game: "Game", player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asks declines an offer whose accept branch
    compels the announced target to block the offer's source — the provoke
    "may" — because the block is worth nothing to it (or less)."""
    from .ai_prompt_readers import _offer_target_permanent

    accept = entry.get("_on_accept") or ()
    if not any(compels_a_block_on_source(step) for step in accept):
        return False
    attacker = entry.get("_source_permanent")
    if attacker is None or not game.is_on_battlefield(attacker):
        # Nothing left for the block to be about: taking the offer would only
        # untap the defender's creature.
        return True
    target = _offer_target_permanent(game, entry.get("_context"))
    if target is None or game.controller_index_of(attacker) != player_index:
        return False
    return compelled_block_worth(game, attacker, target) <= 0


__all__ = [
    "REGENERATES",
    "STAYS",
    "best_compelled_blocker",
    "block_pair_pumps",
    "gang_block_pumps",
    "pumped_combat_damage",
    "pumped_toughness",
    "compelled_block_declined",
    "compelled_blocks",
    "compelled_block_worth",
    "compels_a_block_on_source",
    "fight_outcome",
    "survives_destruction",
]
