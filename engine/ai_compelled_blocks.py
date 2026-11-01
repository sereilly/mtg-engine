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
    is a creature untapped to block somebody else.
    """
    if not game._can_block_attacker(blocker, attacker):
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
