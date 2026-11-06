"""What a creature's own attack or block trigger costs its controller — the
gamble a seat takes by declaring it.

Goblin Psychopath: "Whenever this creature attacks or blocks, flip a coin. If
you lose the flip, the next time it would deal combat damage this turn, it
deals that damage to you instead." The engine plays it correctly; the AI's
declarations (``ai_declarations.choose_attackers``, ``choose_combat_blockers``)
weighed the 5/5 as a 5/5, so it attacked into an empty board at even life —
half the time five damage to the opponent, half the time five to itself — and
attacked with everything at lethal as though its five were certain.

**Read off the compiled program, never off a name** (:func:`combat_gamble`):
the creature's triggered abilities that fire as it attacks (or blocks), walked
with the chance each step happens. A coin flip (CR 705) is the one source of
chance a trigger's text gives the walk — ``flip_coin`` and an ``if_then`` on
its result, or the fused kinds Mijae Djinn and Ydwen Efreet compile to — and
each branch behind it happens half the time. What the walk prices:

* **its combat damage turned on its controller** — a "deals that damage to
  you instead" redirect of its own next combat damage;
* **its combat damage not dealt at all** — removed from combat;
* **the creature given away or lost by chance** — Fickle Efreet's "if you
  lose the flip, an opponent gains control of it" at end of combat;
* **life its controller loses for certain** — Time Elemental's five.

**A creature certainly lost by attacking is not priced** (``spent``): Fog
Elemental, Keldon Battlewagon, Vebulid are one-shots by design, whose worth is
spent whenever they attack, and when to spend it is a timing question no
per-attack price answers — weighed against ``permanent_worth`` a Battlewagon
that cannot block would never attack at all. Nor is anything behind a ``may``
(a toll answered at resolution, ``ai_prompts.toll_decline_is_smaller_loss``)
or a condition the walk cannot price (Loafing Giant's milled land), or an
amount it cannot read (Ebonblade Reaper's "half your life"): each is left out
rather than guessed.

The price is set against what the declaration buys, on the rehearsal's own
scale (``ai_rehearsal.life_worth``, ``permanent_worth``): the damage that
reaches the defender (:func:`attack_is_worth_its_trigger`), or the damage a
block stops and the attacker it kills (:func:`block_is_worth_its_trigger`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ai_compelled_blocks import fight_outcome
from .ai_rehearsal import life_worth, permanent_worth
from .combat_assignment import combat_damage_assigned_by
from .trigger_utils import matching_triggers

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


#: The trigger conditions that fire as the creature itself attacks — the
#: declare-attackers step's own firing (``phases/declare_attackers_step``).
ATTACK_CONDITIONS = frozenset({"creature_attacks", "creature_attacks_or_blocks"})

#: …and as it blocks (``phases/block_triggers``): "blocks or becomes blocked"
#: fires on its block half too.
BLOCK_CONDITIONS = frozenset({
    "creature_blocks", "creature_attacks_or_blocks", "creature_blocks_or_blocked_by",
})

#: CR 705: a coin flip is won or lost with even chances.
FLIP_CHANCE = 0.5

#: The fused kinds whose losing flip removes the creature from combat (CR
#: 506.4), so its combat damage is not dealt: Mijae Djinn's attack, Ydwen
#: Efreet's block.
_REMOVED_ON_A_LOST_FLIP = frozenset({
    "coin_flip_remove_attacker_and_tap", "coin_flip_remove_blocker",
})

#: Its own next combat damage dealt to its controller instead.
_TURNED_ON_ITS_CONTROLLER = frozenset({"redirect_source_damage_to_you_until_eot"})

#: The creature leaves its controller's side.
_GIVEN_AWAY = frozenset({"give_control_of_source_to_player"})
_LOST = frozenset({"sacrifice_self", "destroy_self", "put_source_card_on_library_top"})

#: The wrappers whose steps all happen when they do.
_SEQUENTIAL = frozenset({"sequence"})


@dataclass
class CombatGamble:
    """What declaring a creature gambles, as expectations: ``delivered`` the
    chance its combat damage goes where it is assigned, ``turned`` the chance
    it is dealt to its controller instead, ``lost`` / ``given`` the chance
    the creature is lost / handed to an opponent by chance, ``life`` the life
    its controller loses, and ``spent`` whether the creature is certainly lost
    (a one-shot, left unpriced — see the module docstring)."""

    delivered: float = 1.0
    turned: float = 0.0
    lost: float = 0.0
    given: float = 0.0
    life: float = 0.0
    spent: bool = False

    @property
    def costs(self) -> bool:
        """Whether anything here is a price its controller pays."""
        return bool(self.turned or self.lost or self.given or self.life)


def combat_gamble(game: "Game", permanent: "Permanent", *, blocking: bool) -> CombatGamble:
    """The gamble *permanent* takes by attacking (or, *blocking*, by blocking),
    read off the triggered abilities it has now (``Permanent.effective_card``,
    so a face-down creature has none and a granted one counts)."""
    gamble = CombatGamble()
    conditions = BLOCK_CONDITIONS if blocking else ATTACK_CONDITIONS
    for trigger in matching_triggers(permanent.effective_card, condition_kinds=conditions):
        _walk(trigger.instruction, 1.0, gamble)
    gamble.delivered = max(0.0, gamble.delivered - gamble.turned)
    return gamble


def _walk(step, chance: float, gamble: CombatGamble) -> None:
    """Add what *step* does, happening with *chance*, to *gamble*."""
    kind = getattr(step, "kind", None)
    payload = getattr(step, "payload", None) or {}
    if kind is None:
        return
    if kind in _SEQUENTIAL:
        for child in payload.get("steps") or ():
            _walk(child, chance, gamble)
        return
    if kind == "create_delayed_trigger":
        # Later this turn (end of combat), but this turn: priced the same.
        _walk(payload.get("instruction"), chance, gamble)
        return
    if kind == "if_then":
        condition = payload.get("condition") or {}
        if condition.get("kind") != "coin_flip":
            return
        for branch in ("then", "else"):
            for child in payload.get(branch) or ():
                _walk(child, chance * FLIP_CHANCE, gamble)
        return
    if kind in _REMOVED_ON_A_LOST_FLIP:
        gamble.delivered -= chance * FLIP_CHANCE
        return
    if kind in _TURNED_ON_ITS_CONTROLLER:
        if payload.get("combat_only"):
            gamble.turned += chance
        return
    if kind in _GIVEN_AWAY or kind in _LOST:
        if chance >= 1.0:
            gamble.spent = True
        elif kind in _GIVEN_AWAY:
            gamble.given += chance
        else:
            gamble.lost += chance
        return
    if kind in ("deal_damage", "target_loses_life") and payload.get("recipient") == "caster":
        amount = payload.get("amount")
        if isinstance(amount, int) and not isinstance(amount, bool):
            gamble.life += chance * amount
        return


def _price(game: "Game", permanent: "Permanent", gamble: CombatGamble, seat: int) -> float:
    """What *gamble* costs *seat*, *permanent*'s controller."""
    life = game.players[seat].life
    hit = combat_damage_assigned_by(permanent)
    cost = gamble.turned * (life_worth(life) - life_worth(life - hit))
    worth = permanent_worth(permanent, now=False)
    # Handed to an opponent, it is lost here and gained there.
    cost += (gamble.lost + 2 * gamble.given) * worth
    if gamble.life:
        cost += life_worth(life) - life_worth(life - round(gamble.life))
    return cost


def attack_is_worth_its_trigger(game: "Game", attacker: "Permanent", defender: int) -> bool:
    """Whether *attacker*'s own attack trigger is a price its attack pays for:
    the combat damage expected to reach *defender* (``delivered``), worth
    more on the rehearsal's scale than what the trigger is expected to cost.
    Always True for a creature whose trigger costs nothing."""
    gamble = combat_gamble(game, attacker, blocking=False)
    if not gamble.costs:
        return True
    seat = game.controller_index_of(attacker)
    life = game.players[defender].life
    hit = combat_damage_assigned_by(attacker)
    gain = gamble.delivered * (life_worth(life) - life_worth(life - hit))
    return gain > _price(game, attacker, gamble, seat)


def expected_attack_damage(game: "Game", attacker: "Permanent") -> float:
    """The combat damage *attacker* is expected to deal where it is assigned
    — its power, as the lethal swing has always counted it, less what its own
    attack trigger may take of it."""
    delivered = combat_gamble(game, attacker, blocking=False).delivered
    power = attacker.effective_power
    return power if delivered >= 1.0 else power * delivered


def block_is_worth_its_trigger(
    game: "Game", blocker: "Permanent", attacker: "Permanent", prevented: int,
) -> bool:
    """Whether *blocker*'s own block trigger is a price the block pays for:
    the *prevented* damage it stops and the attacker it is expected to kill
    (``ai_compelled_blocks.fight_outcome``, at the chance its damage is
    dealt), against what the trigger is expected to cost. Always True for a
    creature whose trigger costs nothing."""
    gamble = combat_gamble(game, blocker, blocking=True)
    if not gamble.costs:
        return True
    seat = game.controller_index_of(blocker)
    life = game.players[seat].life
    gain = life_worth(life) - life_worth(life - max(0, prevented))
    _blocker_dies, attacker_dies = fight_outcome(game, attacker, blocker)
    if attacker_dies:
        gain += gamble.delivered * permanent_worth(attacker, now=False)
    return gain > _price(game, blocker, gamble, seat)


__all__ = [
    "ATTACK_CONDITIONS",
    "BLOCK_CONDITIONS",
    "CombatGamble",
    "attack_is_worth_its_trigger",
    "block_is_worth_its_trigger",
    "combat_gamble",
    "expected_attack_damage",
]
