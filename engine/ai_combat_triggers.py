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
with the chance each step happens. Three sources of chance a trigger's text
gives the walk: a coin flip (CR 705) — ``flip_coin`` and an ``if_then`` on its
result, or the fused kinds Mijae Djinn and Ydwen Efreet compile to — each
branch half the time; **a card milled** — "If a land card was milled this way"
(Loafing Giant), as often as its controller's library holds such cards, a
count every seat may make of its own library (CR 400.2 hides the order, not
the deck); and **being blocked** — an attack's "becomes blocked" trigger
(Goblin Cadets) as often as a defender has a creature that can block it. What
the walk prices:

* **its combat damage turned on its controller** — a "deals that damage to
  you instead" redirect of its own next combat damage;
* **its combat damage not dealt at all** — removed from combat, prevented
  (Loafing Giant), or the creature gone before damage (a toll unpaid, a
  creature given away as it becomes blocked);
* **the creature given away or lost by chance** — Fickle Efreet's "if you
  lose the flip, an opponent gains control of it" at end of combat;
* **life its controller loses** — Time Elemental's five, Ebonblade Reaper's
  "half your life, rounded up" (read off its count of the controller's life),
  Hasran Ogress's 3 when the {2} beside it cannot be paid.

**A toll** — "sacrifice it unless you exile a card from your graveyard"
(Rotting Giant, Treacherous Vampire), "it deals 3 damage to you unless you pay
{2}" (Hasran Ogress) — is paid by the standing policy whenever it can be
(``ai_prompts.toll_decline_is_smaller_loss``), so it is priced only where it
cannot: then its penalty happens, before the combat damage it was declared
for.

**A creature certainly lost by attacking is not priced** (``spent``): Fog
Elemental, Keldon Battlewagon, Vebulid are one-shots by design, whose worth is
spent whenever they attack, and when to spend it is a timing question no
per-attack price answers — weighed against ``permanent_worth`` a Battlewagon
that cannot block would never attack at all. A creature **handed to an
opponent** is not a one-shot, and is priced whatever its chance (Goblin
Cadets' block gives the attacker a creature and stops nothing but the
damage).

The price is set against what the declaration buys, on the rehearsal's own
scale (``ai_standing.life_worth``, ``permanent_worth``): the damage that
reaches the defender, and what the creature's own "deals combat damage to a
player" trigger takes from them where nothing can block it
(:func:`attack_is_worth_its_trigger`), or the damage a block stops and the
attacker it kills (:func:`block_is_worth_its_trigger`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ai_compelled_blocks import fight_outcome
from .ai_standing import life_worth, permanent_worth
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

#: …and as the attacker **becomes blocked** (``phases/block_triggers``): the
#: half of "blocks or becomes blocked" an attack sets off, whenever a
#: defender blocks it.
BLOCKED_CONDITIONS = frozenset({"creature_becomes_blocked", "creature_blocks_or_blocked_by"})

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

#: Its own combat damage prevented ("prevent all combat damage this creature
#: would deal this turn", Loafing Giant: the ``on_source`` reading).
_ITS_DAMAGE_PREVENTED = frozenset({"prevent_damage_by_target_until_eot"})

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


@dataclass(frozen=True)
class _Walk:
    """Where a step being walked happens: *game*, the creature's controller
    *seat*, whether it is after the combat damage (*later*: an end-of-combat
    delayed trigger), and whether a certain loss there is a one-shot's spent
    worth (*spendable*) or a price (a toll unpaid, a creature blocked)."""

    game: object
    seat: int
    later: bool = False
    spendable: bool = True


def combat_gamble(game: "Game", permanent: "Permanent", *, blocking: bool) -> CombatGamble:
    """The gamble *permanent* takes by attacking (or, *blocking*, by blocking),
    read off the triggered abilities it has now (``Permanent.effective_card``,
    so a face-down creature has none and a granted one counts)."""
    gamble = CombatGamble()
    seat = game.controller_index_of(permanent)
    reading = _Walk(game, seat)
    conditions = BLOCK_CONDITIONS if blocking else ATTACK_CONDITIONS
    for trigger in matching_triggers(permanent.effective_card, condition_kinds=conditions):
        _walk(trigger.instruction, 1.0, gamble, reading)
    if not blocking:
        on_blocked = matching_triggers(
            permanent.effective_card, condition_kinds=BLOCKED_CONDITIONS - conditions,
        )
        if on_blocked and can_be_blocked(game, permanent):
            priced = _Walk(game, seat, spendable=False)
            for trigger in on_blocked:
                _walk(trigger.instruction, 1.0, gamble, priced)
    gamble.delivered = max(0.0, gamble.delivered - gamble.turned)
    return gamble


def can_be_blocked(game: "Game", attacker: "Permanent") -> bool:
    """Whether an opponent of *attacker*'s controller has an untapped creature
    that could block it (``Game._can_block_attacker``) — the chance a "becomes
    blocked" trigger fires, read as certain where it can: the block that
    sets it off is the defender's to make."""
    seat = game.controller_index_of(attacker)
    return any(
        other.is_creature and not other.tapped and game._can_block_attacker(other, attacker)
        for opponent in game.opponents_of(seat)
        for other in game.controlled_by(opponent)
    )


def _walk(step, chance: float, gamble: CombatGamble, reading: _Walk) -> None:
    """Add what *step* does, happening with *chance*, to *gamble*."""
    kind = getattr(step, "kind", None)
    payload = getattr(step, "payload", None) or {}
    if kind is None:
        return
    if kind in _SEQUENTIAL:
        for child in payload.get("steps") or ():
            _walk(child, chance, gamble, reading)
        return
    if kind == "create_delayed_trigger":
        # Later this turn (end of combat), but this turn: priced the same —
        # and after the combat damage it would otherwise take away.
        later = _Walk(reading.game, reading.seat, True, reading.spendable)
        _walk(payload.get("instruction"), chance, gamble, later)
        return
    if kind == "if_then":
        condition = payload.get("condition") or {}
        then_chance = _condition_chance(condition, reading)
        if then_chance is None:
            return
        for branch, share in (("then", then_chance), ("else", 1.0 - then_chance)):
            for child in payload.get(branch) or ():
                _walk(child, chance * share, gamble, reading)
        return
    if kind == "may":
        _walk_toll(payload, chance, gamble, reading)
        return
    if kind == "self_damage_unless_pay":
        cost = payload.get("cost")
        if isinstance(cost, int) and not _can_pay_generic(reading, cost):
            gamble.life += chance * _amount(payload, reading)
        return
    if kind in _REMOVED_ON_A_LOST_FLIP:
        gamble.delivered -= chance * FLIP_CHANCE
        return
    if kind in _TURNED_ON_ITS_CONTROLLER:
        if payload.get("combat_only"):
            gamble.turned += chance
        return
    if kind in _ITS_DAMAGE_PREVENTED:
        if payload.get("on_source") and payload.get("combat_only"):
            gamble.delivered -= chance
        return
    if kind in _GIVEN_AWAY or kind in _LOST:
        if not reading.later:
            # Gone before the damage is dealt: none of it is.
            gamble.delivered -= chance
        if chance >= 1.0 and reading.spendable and kind in _LOST:
            gamble.spent = True
        elif kind in _GIVEN_AWAY:
            gamble.given += chance
        else:
            gamble.lost += chance
        return
    if kind in ("deal_damage", "target_loses_life") and payload.get("recipient") == "caster":
        gamble.life += chance * _amount(payload, reading)
        return


def _amount(payload: dict, reading: _Walk) -> int:
    """A step's printed amount, or the one count the walk reads: "half your
    life, rounded up" (Ebonblade Reaper's ``their_life`` of the controller).
    Anything else is 0 — left out rather than guessed."""
    amount = payload.get("amount")
    if isinstance(amount, int) and not isinstance(amount, bool):
        return amount
    count = payload.get("x_from_count") or {}
    if (
        amount == "x" and count.get("board_count") == "their_life"
        and count.get("owner") == "you" and count.get("half") in ("up", "down")
    ):
        life = max(0, int(reading.game.players[reading.seat].life))
        return (life + 1) // 2 if count["half"] == "up" else life // 2
    return 0


def _condition_chance(condition: dict, reading: _Walk) -> "float | None":
    """How often an ``if_then``'s condition holds: a lost or won flip half the
    time (CR 705), "if a land card was milled this way" as often as the
    controller's library holds such cards. None for a condition the walk
    cannot price — its branches are left out."""
    if condition.get("kind") == "coin_flip":
        return FLIP_CHANCE
    if condition.get("kind") == "milled_this_way" and condition.get("card_types"):
        types = tuple(str(each).lower() for each in condition["card_types"])
        library = reading.game.players[reading.seat].library
        if not library:
            return 0.0
        every = condition.get("type_match") == "all"

        def matches(card) -> bool:
            printed = set((card.type_line or "").lower().split("—")[0].split())
            held = [kind in printed for kind in types]
            return all(held) if every else any(held)

        return sum(1 for card in library if matches(card)) / len(library)
    return None


def _walk_toll(payload: dict, chance: float, gamble: CombatGamble, reading: _Walk) -> None:
    """A ``may`` with a printed penalty — "sacrifice it unless you exile a
    card from your graveyard" — priced where its controller cannot pay: its
    penalty walked as a price, not a one-shot spent. Paid (the standing
    policy), or a ``may`` with no penalty (a gift), it costs nothing here; a
    payment the walk cannot read leaves the toll out."""
    penalty = payload.get("otherwise") or ()
    if not penalty:
        return
    payable = _toll_payable(payload.get("action") or (), reading)
    if payable is None or payable:
        return
    priced = _Walk(reading.game, reading.seat, reading.later, spendable=False)
    for child in penalty:
        _walk(child, chance, gamble, priced)


def _toll_payable(action, reading: _Walk) -> "bool | None":
    """Whether a toll's payment can be made now: cards exiled from the
    controller's own graveyard, as many as it holds. None for any other
    payment."""
    player = reading.game.players[reading.seat]
    for step in action:
        payload = getattr(step, "payload", None) or {}
        if getattr(step, "kind", None) != "exile_cards_from_graveyard":
            return None
        if payload.get("graveyard_owner") != "you" or not payload.get("any_card"):
            return None
        count = payload.get("count")
        if not isinstance(count, int) or len(player.graveyard) < count:
            return False
    return True


def _can_pay_generic(reading: _Walk, cost: int) -> bool:
    """Whether the controller could pay {cost} now — the standing policy pays a
    mana toll out of its pool and untapped lands."""
    from .board_payment import board_can_pay

    game = reading.game
    if not getattr(game, "enforce_mana_costs", True):
        return True
    return board_can_pay(game, reading.seat, {"generic": cost})


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


#: The trigger of a creature's own that fires on its combat damage to a player
#: (``trigger_conditions``' ``damage_dealt`` with the source itself dealing).
_DAMAGE_TO_A_PLAYER = frozenset({"damage_dealt"})


def connecting_loss(game: "Game", attacker: "Permanent", defender: int) -> int:
    """The life *defender* loses to *attacker*'s own "Whenever this creature
    deals combat damage to a player, that player loses …" beside the damage —
    "half their life, rounded up" (Ebonblade Reaper), a printed number — read
    off the program, after the hit. 0 where there is none."""
    life = max(0, game.players[defender].life - combat_damage_assigned_by(attacker))
    loss = 0
    for trigger in matching_triggers(attacker.effective_card, condition_kinds=_DAMAGE_TO_A_PLAYER):
        payload = trigger.condition.payload or {}
        if not payload.get("damager_self") or payload.get("damage_combat") != "combat":
            continue
        if "player" not in str(payload.get("damage_recipient") or ""):
            continue
        for step in _steps_of(trigger.instruction):
            step_payload = step.payload or {}
            if step.kind != "target_loses_life" or step_payload.get("recipient") != (
                "damaged_permanent_controller"
            ):
                continue
            amount = step_payload.get("amount")
            count = step_payload.get("x_from_count") or {}
            if isinstance(amount, int) and not isinstance(amount, bool):
                loss += amount
            elif count.get("board_count") == "their_life" and count.get("half") == "up":
                loss += (life + 1) // 2
            elif count.get("board_count") == "their_life" and count.get("half") == "down":
                loss += life // 2
    return loss


def _steps_of(instruction) -> list:
    if instruction is None:
        return []
    if instruction.kind in _SEQUENTIAL:
        return [
            leaf for child in (instruction.payload or {}).get("steps") or ()
            for leaf in _steps_of(child)
        ]
    return [instruction]


def attack_is_worth_its_trigger(game: "Game", attacker: "Permanent", defender: int) -> bool:
    """Whether *attacker*'s own attack trigger is a price its attack pays for:
    the combat damage expected to reach *defender* (``delivered``) — and,
    where no creature of theirs can block it, what its own combat-damage
    trigger takes from them (:func:`connecting_loss`) — worth more on the
    rehearsal's scale than what the trigger is expected to cost. Always True
    for a creature whose trigger costs nothing."""
    gamble = combat_gamble(game, attacker, blocking=False)
    if not gamble.costs:
        return True
    seat = game.controller_index_of(attacker)
    life = game.players[defender].life
    hit = combat_damage_assigned_by(attacker)
    reached = hit
    if not can_be_blocked(game, attacker):
        reached += connecting_loss(game, attacker, defender)
    gain = gamble.delivered * (life_worth(life) - life_worth(life - reached))
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
        gain += max(0.0, gamble.delivered) * permanent_worth(attacker, now=False)
    return gain > _price(game, blocker, gamble, seat)


def leaves_the_fight(game: "Game", permanent: "Permanent", *, blocking: bool) -> bool:
    """Whether *permanent* certainly leaves the fight before combat damage
    once the blocks are made — as it blocks (*blocking*) or as it becomes
    blocked: its own trigger gives it away, sacrifices or destroys it
    (Goblin Cadets' "target opponent gains control of it"), with nothing
    left to chance. Read by the fight forecast
    (``ai_compelled_blocks.fight_outcome``): such a creature deals and is
    dealt no combat damage."""
    conditions = BLOCK_CONDITIONS if blocking else BLOCKED_CONDITIONS
    for trigger in matching_triggers(permanent.effective_card, condition_kinds=conditions):
        for step in _steps_of(trigger.instruction):
            if step.kind in _GIVEN_AWAY or step.kind in _LOST:
                return True
    return False


def turned_on_its_controller(game: "Game", attacker: "Permanent") -> bool:
    """Whether *attacker*'s next combat damage is armed to be dealt to its
    controller instead — Goblin Psychopath's lost flip, resolved: a record
    watching this source and no recipient (``damage_redirects.
    source_keyed_redirects``) whose live recipient is the attacker's own
    controller. A defender facing it takes none of that damage, blocked or
    not."""
    from .damage_redirects import live_recipient, source_keyed_redirects

    controller = game.players[game.controller_index_of(attacker)]
    return any(
        record.source is attacker
        and (record.uses is None or record.uses > 0)
        and live_recipient(game, record, attacker) is controller
        for record in source_keyed_redirects(game)
    )


__all__ = [
    "ATTACK_CONDITIONS",
    "BLOCKED_CONDITIONS",
    "BLOCK_CONDITIONS",
    "CombatGamble",
    "attack_is_worth_its_trigger",
    "block_is_worth_its_trigger",
    "can_be_blocked",
    "combat_gamble",
    "connecting_loss",
    "expected_attack_damage",
    "leaves_the_fight",
    "turned_on_its_controller",
]
