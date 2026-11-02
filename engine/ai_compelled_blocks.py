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
damage (CR 702.2c), indestructible and a regeneration shield as survival, a
prevention shield as damage that may not arrive (``ai_combat._would_be_prevented``,
the attacker's own damage chooser's question) — because a provoke that sends
a 2/2 into a first-striking 2/2 is the provoke a seat must not take.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ai_rehearsal import permanent_worth
from .ai_weighed_cast import _effect_steps
from .combat_assignment import combat_damage_assigned_by

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
    lost (``ai_rehearsal.permanent_worth``, read as the board will be once
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
    resolving (``ai_rehearsal._detach``) and asked the engine's own question
    (``_can_block_attacker``) — so what it sheds is whatever its program
    says, never a keyword named here."""
    import random

    from .activation_prohibitions import activation_prohibition
    from .ai_rehearsal import _detach, scratch_copy
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
    destroys it — none where it is indestructible or has a regeneration
    shield, one point from deathtouch (CR 702.2c).

    The defender's blocks are its own to declare later, and a gang that
    kills the attacker is the block a defender makes; nothing here is a
    rehearsal, because the question is asked part-way through the provoke's
    resolution, where no copy can be run."""
    from .ai_combat import _would_be_prevented

    if game._has_keyword(attacker, "indestructible") or attacker.regeneration_shield:
        return False
    seat = game.controller_index_of(blocker)
    gang = [blocker] + [
        other for other in game.controlled_by(seat)
        if other is not blocker and other.is_creature and not other.tapped
        and game._can_block_attacker(other, attacker)
    ]
    if len(gang) < 2:
        return False
    needed = max(0, attacker.effective_toughness - attacker.damage_marked)
    dealt = 0
    for member in gang:
        amount = combat_damage_assigned_by(member)
        if not amount or _would_be_prevented(game, member, attacker, amount):
            continue
        if game._has_keyword(member, "deathtouch"):
            return True
        dealt += amount
    return needed > 0 and dealt >= needed


def _evasion_damage_worth(game: "Game", attacker: "Permanent", blocker: "Permanent") -> float:
    """What the combat damage *attacker* deals unblocked is worth to its seat
    against *blocker*'s controller (``ai_rehearsal.life_worth``) — the price
    of shedding the evasion that kept it unblocked."""
    from .ai_rehearsal import life_worth

    defender = game.players[game.controller_index_of(blocker)]
    damage = combat_damage_assigned_by(attacker)
    return life_worth(defender.life) - life_worth(defender.life - damage)


def fight_outcome(game: "Game", attacker: "Permanent", blocker: "Permanent") -> "tuple[bool, bool]":
    """``(attacker destroys blocker, blocker destroys attacker)`` if the two
    fight alone — the combat damage step's two steps (CR 510.4) estimated."""
    from .ai_combat import _would_be_prevented

    def dealt(source, recipient) -> int:
        amount = combat_damage_assigned_by(source)
        if amount and _would_be_prevented(game, source, recipient, amount):
            return 0
        return amount

    def lethal(source, recipient) -> int | None:
        """Damage from *source* that destroys *recipient*, or None if none
        does this combat."""
        if game._has_keyword(recipient, "indestructible") or recipient.regeneration_shield:
            return None
        remaining = max(0, recipient.effective_toughness - recipient.damage_marked)
        if remaining > 0 and game._has_keyword(source, "deathtouch"):
            return 1
        return remaining

    def strikes(perm) -> tuple[bool, bool]:
        double = game._has_keyword(perm, "double strike")
        first = double or game._has_keyword(perm, "first strike")
        return first, (not first) or double

    to_blocker, to_attacker = dealt(attacker, blocker), dealt(blocker, attacker)
    kill_blocker, kill_attacker = lethal(attacker, blocker), lethal(blocker, attacker)
    attacker_first, attacker_regular = strikes(attacker)
    blocker_first, blocker_regular = strikes(blocker)

    on_blocker = on_attacker = 0
    blocker_dead = attacker_dead = False

    def settle() -> None:
        nonlocal blocker_dead, attacker_dead
        if kill_blocker is not None and on_blocker > 0 and on_blocker >= kill_blocker:
            blocker_dead = True
        if kill_attacker is not None and on_attacker > 0 and on_attacker >= kill_attacker:
            attacker_dead = True

    if attacker_first or blocker_first:
        if attacker_first:
            on_blocker += to_blocker
        if blocker_first:
            on_attacker += to_attacker
        settle()
    if attacker_regular and not attacker_dead:
        on_blocker += to_blocker
    if blocker_regular and not blocker_dead:
        on_attacker += to_attacker
    settle()
    return blocker_dead, attacker_dead


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
    names no pair, and is left to that maximisation."""
    attacker_seat = game.active_player_index
    blocks: dict[int, int] = {}
    for requirement in game.block_requirements(defending_player_index):
        if requirement.blocker is None or requirement.attacker is None:
            continue
        if requirement.blocker in blocks:
            continue
        blocker = game.permanent_at(defending_player_index, requirement.blocker)
        attacker = game.permanent_at(attacker_seat, requirement.attacker)
        if blocker is None or attacker is None or blocker.tapped or not blocker.is_creature:
            continue
        if not game._can_block_attacker(blocker, attacker):
            continue
        blocks[requirement.blocker] = requirement.attacker
    return blocks


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
    "best_compelled_blocker",
    "compelled_block_declined",
    "compelled_blocks",
    "compelled_block_worth",
    "compels_a_block_on_source",
    "fight_outcome",
]
