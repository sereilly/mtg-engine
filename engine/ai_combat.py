from __future__ import annotations

"""Driving a combat phase for seats nobody is going to prompt.

`ai_policy` decides *what* an AI seat would like to do in combat —
`choose_attackers`, `choose_combat_blockers`. This module is the other half:
taking those answers and actually making the declarations, including what to do
when the engine refuses one. That is a small amount of code and it had exactly
one home (`web/combat_prompts._ai_declare_attackers`), tangled up with a
`Session` — so the AI simulator, which has no session and no human seats, could
not reach it.

**The declaration fallbacks are the part worth sharing, not the walking.** A
refused declaration is silent: nothing is spent, no rule is broken, and the seat
simply does not attack — this combat and every later one. That silence is why
both attack caps went unnoticed for the life of this engine, and a second copy
of the fallback chain in the simulator would be a second place for it to hide.
So the chain lives here once and both drivers call it.

**Both chains, as of the round that drained the blocking half of the
declaration-legality gap.** `web/game_flow` carried its own copy of the block
fallback and its own `{}` rung, which is how CR 509.1b's declaration-wide
restrictions stayed invisible to the AI's chooser for as long as the attack caps
did: a refused block declaration is silent in exactly the same way, and the web
copy's safety valve wipes *every* seat's blocks rather than one seat's.

What is *not* shared is the surrounding turn structure. The web layer walks
combat one client request at a time, pausing wherever a human has flagged a step
on the phase rail; the simulator has no humans and walks the whole phase in one
call. Those are genuinely different loops over the same engine seam
(`Game.advance_combat_phase`), not two copies of one.
"""

from dataclasses import dataclass, field

from .combat_assignment import combat_damage_assigned_by
from .ai_scoring import _permanent_value, choose_attack_target
from .ai_declarations import choose_attackers, choose_combat_blockers, legal_attackers


@dataclass
class CombatOutcome:
    """What one combat phase actually did, for a caller that has to report it.

    The simulator's honesty numbers, and the reason `refused_attacks` exists at
    all: a declaration the engine refuses costs nothing and breaks no rule, so
    it cannot fail an assertion — but the seat attacks with nobody, and it will
    keep proposing the same illegal set every turn. That is the attack-side twin
    of `SimulationReport.refused_casts`, and it could not be measured before
    this module because no simulated seat had ever declared an attack.
    """

    attacks_declared: int = 0
    attackers: int = 0
    blockers: int = 0
    #: Combats where the engine could not auto-resolve damage and this driver
    #: supplied the split. **Not** "combats that dealt damage" — almost all of
    #: those never reach this driver at all, because `advance_combat_phase`
    #: resolves them itself with the same `_build_auto_damage_assignment`. This
    #: counts the multi-blocked and banding cases (CR 510.1a / 702.22j), which
    #: is the interesting number: it is the path a simulated game exercises
    #: least and the one a manual assignment can get wrong.
    manual_damage_splits: int = 0
    #: `(seat name, engine's refusal)` for each declaration that was refused and
    #: had to fall back. Non-empty means the AI proposed something illegal.
    refused_attacks: list[tuple[str, str]] = field(default_factory=list)
    #: Declarations where even the fallback was refused, so the seat attacked
    #: with nobody. This is the one that means a restriction the AI cannot see.
    silent_attacks: list[tuple[str, str]] = field(default_factory=list)
    #: The block-side twins, and they exist for the reason the attack pair does
    #: rather than for symmetry: `declare_ai_blockers` fell back **in silence**
    #: in exactly the way `declare_ai_attackers` did before W2G4 counted it, and
    #: every one of CR 509.1b's declaration-wide restrictions was invisible to
    #: the AI's chooser. A refused block costs nothing and breaks no rule, so it
    #: fails no assertion — the defender simply blocks with nobody, and proposes
    #: the same illegal map again next combat.
    refused_blocks: list[tuple[str, str]] = field(default_factory=list)
    #: Declarations where even the empty one was refused, so no legal block
    #: existed for this seat to make. A requirement (Lure) compels a block the
    #: restrictions forbid; the web layer's answer is a safety valve that wipes
    #: **every** seat's blocks, so this is the one worth an issue rather than a
    #: count.
    silent_blocks: list[tuple[str, str]] = field(default_factory=list)
    #: ``(blocker permanent_id, attacker permanent_id)`` for every block this
    #: driver declared. What a rehearsal compares between two copies of one
    #: combat (``ai_rehearsal.Rehearsal.blocks_added``): an action taken before
    #: the blocks is taken for a block it adds.
    blocks_declared: set[tuple[int, int]] = field(default_factory=set)
    #: ``permanent_id`` of every attacker this driver declared — the attack
    #: side's twin, compared the same way (``Rehearsal.declarations_changed``):
    #: an action taken before the attack is taken for an attack or a block it
    #: changes, and one that changes neither can wait for the blocks.
    attackers_declared: set[int] = field(default_factory=set)


def declared_block_pairs(game, defender_index: int) -> set[tuple[int, int]]:
    """``(blocker permanent_id, attacker permanent_id)`` for each block
    *defender_index* has declared this combat (``Game.combat_blockers``)."""
    active = game.active_player_index
    pairs: set[tuple[int, int]] = set()
    for blocker_slot, attacker_slots in (game.combat_blockers.get(defender_index) or {}).items():
        blocker = game.permanent_at(defender_index, blocker_slot)
        if blocker is None:
            continue
        for attacker_slot in (
            attacker_slots if isinstance(attacker_slots, list) else [attacker_slots]
        ):
            attacker = game.permanent_at(active, attacker_slot)
            if attacker is not None:
                pairs.add((blocker.permanent_id, attacker.permanent_id))
    return pairs


#: The log line for an offer turned down, after the creature's name. The
#: offer *taken* is the engine's own line (`combat_assignment.AS_THOUGH_UNBLOCKED_LOG`).
KEEPS_DAMAGE_ON_BLOCKERS_LOG = "keeps its combat damage on the creatures blocking it"


def choose_combat_damage_assignment(game) -> tuple[dict, list[int]]:
    """How the active player's attackers assign combat damage when nobody is
    asked: ``(attacker_damage, as_though_unblocked)`` for
    ``Game.resolve_all_combat_damage``.

    The division among blockers is the engine's default
    (`_build_auto_damage_assignment`). What this adds is the answer to **"You
    may have this creature assign its combat damage as though it weren't
    blocked"** (Lone Wolf, Thorn Elemental, Rhox, Pride of Lions; Garruk,
    Savage Herald's −7), which every default took, always — so a 7/7 walked
    past the 2/2 in front of it for seven of a healthy opponent's twenty life
    and the 2/2 lived to block again. Declined (`_offer_is_better_declined`)
    where the creature in front of it would die and the player would not, or
    where the damage would not reach the player at all; taken otherwise, and
    then **named** by id, so the announcement says which answer it is rather
    than leaving it to an absence.

    One function for the three places a default is supplied — the simulator's
    driver below, the web layer's AI seat (`_ai_assign_combat_damage`) and
    the engine's own auto-resolve (`advance_combat_phase`) — so an offer
    cannot be answered three ways.
    """
    active = game.active_player_index
    offered = [
        slot for slot in sorted(game.combat_attackers)
        if game.unblocked_assignment_chooser(slot) == active
        and game._attacker_all_blockers(slot)
        and combat_damage_assigned_by(game.permanent_at(active, slot)) > 0
    ]
    if not offered:
        return game._build_auto_damage_assignment(), []
    # Every offered attacker as it would divide among its blockers, to weigh.
    divided = game._build_auto_damage_assignment(declining=offered)
    declined = [
        slot for slot in offered
        if _offer_is_better_declined(game, slot, divided.get(slot) or {})
    ]
    for slot in declined:
        game.log.append(
            f"{game.permanent_at(active, slot).card.name} {KEEPS_DAMAGE_ON_BLOCKERS_LOG}"
        )
    return (
        game._build_auto_damage_assignment(declining=declined),
        [
            game.permanent_at(active, slot).permanent_id
            for slot in offered if slot not in declined
        ],
    )


def choose_combat_damage_announcement(game) -> dict:
    """Everything the active player's attackers announce about their combat
    damage when nobody is asked, as the keywords
    ``Game.resolve_all_combat_damage`` / ``resolve_combat_damage`` take:
    `choose_combat_damage_assignment`'s division and "as though it weren't
    blocked" answers, and **Butcher Orgg's offer** — "You may assign this
    creature's combat damage divided as you choose among defending player
    and/or any number of creatures they control" — where taking it is better
    (`choose_divided_assignments`). An attacker whose damage is divided that
    way is taken out of the other two answers (CR 510.1: one creature's
    combat damage is assigned one way, `divided_announcement_refusal`).

    The one function the three places that supply a default ask — the
    simulator's driver (`run_ai_combat_phase`), the engine's own auto-resolve
    (``phases/combat_phase``) and the web layer's AI seat — so the offer is
    answered one way.
    """
    attacker_damage, as_though_unblocked = choose_combat_damage_assignment(game)
    divided = choose_divided_assignments(game)
    if divided:
        slots = {
            game.battlefield_index_of(game.permanent_by_id(permanent_id))
            for permanent_id in divided
        }
        attacker_damage = {
            slot: split for slot, split in attacker_damage.items() if slot not in slots
        }
        as_though_unblocked = [
            permanent_id for permanent_id in as_though_unblocked
            if permanent_id not in divided
        ]
    return {
        "attacker_damage": attacker_damage,
        "as_though_unblocked": as_though_unblocked,
        "divided_among_defenders": divided or None,
    }


def choose_divided_assignments(game) -> "dict[int, dict]":
    """``{attacker permanent_id: division}`` for each of the active player's
    attackers that may divide its combat damage among the defending player and
    the creatures they control (Butcher Orgg) and is better off doing so —
    for a seat nobody asks. A person is asked (``divided_assignments_to_ask``
    where the client has the dialog); an AI seat took the default, which is
    the offer declined, for the life of the card (ONS W1G9).

    Each division is `_division_among_defenders`', and only one the engine's
    gate accepts (`combat_assignment.divided_among_defenders_refusal`) is
    named — so the announcement is never the reason combat damage is refused.
    """
    from .combat_assignment import (divided_among_defenders_refusal,
                                    may_divide_among_defenders)

    active = game.active_player_index
    if active in game.interactive_seats:
        return {}
    divided: dict[int, dict] = {}
    for slot in sorted(game.combat_attackers):
        attacker = game.permanent_at(active, slot)
        if attacker is None or not may_divide_among_defenders(attacker):
            continue
        division = _division_among_defenders(game, slot, attacker)
        if division is None:
            continue
        if divided_among_defenders_refusal(game, slot, attacker, division) is not None:
            continue
        divided[attacker.permanent_id] = division
    return divided


def _division_among_defenders(game, attacker_slot: int, attacker) -> "dict | None":
    """How *attacker* divides its combat damage among the defending player and
    their creatures, or None to leave it as it would otherwise be assigned.

    **All of it to the player when that ends the game** (with what the
    unblocked attackers beside it deal). Otherwise each creature the damage
    can kill — blocking or not, which is the offer's whole point ("You can use
    the ability to divide damage even if it is not blocked", ruling
    2004-10-04) — is taken, most worth per point of lethal damage first, while
    what it is worth (``ai_standing.permanent_worth``) is more than the same
    damage to the player's face (``ai_standing.life_worth``, which makes the
    last points dear); whatever is left goes to the player. A creature the
    damage would not reach (protection, a shield) and a player it would not
    reach are never named. None where the division is what the attacker would
    do anyway (an unblocked attacker sending everything to the player), and
    for an attack on a planeswalker, whose loyalty this has no price for.
    """
    from .ai_standing import life_worth, permanent_worth
    from .combat_assignment import DEFENDING_PLAYER_SHARE

    if game.combat_attacked_planeswalkers.get(attacker_slot) is not None:
        return None
    defending = game.combat_attackers.get(attacker_slot)
    if defending is None or not 0 <= defending < len(game.players):
        return None
    damage = combat_damage_assigned_by(attacker)
    if damage <= 0:
        return None
    defender = game.players[defending]
    active = game.active_player_index
    face = not _would_be_prevented(game, attacker, defender, damage)
    beside = sum(
        combat_damage_assigned_by(other)
        for slot, seat in game.combat_attackers.items()
        if slot != attacker_slot and seat == defending
        and game.combat_attacked_planeswalkers.get(slot) is None
        and (other := game.permanent_at(active, slot)) is not None
        and not other.blocked and not game._attacker_all_blockers(slot)
    )
    life = defender.life - beside
    if face and damage >= life:
        # Unblocked, that is where its damage goes anyway.
        return {DEFENDING_PLAYER_SHARE: damage} if attacker.blocked else None
    killable = []
    for creature in game.controlled_by(defending):
        if not creature.is_creature:
            continue
        lethal = _lethal_from(game, attacker, creature)
        if lethal <= 0 or _would_be_prevented(game, attacker, creature, lethal):
            continue
        killable.append((permanent_worth(creature), lethal, creature))
    killable.sort(key=lambda entry: (-entry[0] / entry[1], -entry[0]))
    division: dict = {}
    left = damage
    for worth, lethal, creature in killable:
        if lethal > left:
            continue
        to_face = life_worth(life) - life_worth(life - lethal) if face else 0.0
        if worth <= to_face:
            continue
        division[creature.permanent_id] = lethal
        left -= lethal
    if left:
        if face:
            division[DEFENDING_PLAYER_SHARE] = left
        elif division:
            heaviest = max(division, key=lambda key: division[key])
            division[heaviest] += left
        else:
            return None
    if not attacker.blocked and set(division) == {DEFENDING_PLAYER_SHARE}:
        return None
    return division


def _would_be_prevented(game, source, recipient, amount: int) -> bool:
    """Whether a prevention or redirection effect applies to *amount* combat
    damage from *source* to *recipient* (CR 615, CR 614.9) — a Circle of
    Protection's shield, protection from the attacker's colour, a Fog.

    Asked of the damage event's own contention set (`damage_candidates`),
    whose ``applies`` predicates are pure by the registry's contract — nothing
    is spent by asking. "Applies" is not "prevents all of it": a one-point
    shield answers yes. The chooser reads that as damage that may not arrive,
    which is the cautious reading of it.
    """
    from .damage_events import (damage_candidates, damage_source_seat,
                                mark_turn_unpreventable)

    event = {"recipient": recipient, "amount": amount, "source": source, "combat": True}
    event["source_seat"] = damage_source_seat(game, source)
    # The event as `deal_damage` would see it: under Flaring Pain's "Damage
    # can't be prevented this turn" no shield stops it.
    mark_turn_unpreventable(game, event)
    return any(
        candidate.prevents_or_redirects and candidate.applies(game, dict(event))
        for candidate in damage_candidates(recipient, event)
    )


def _offer_is_better_declined(game, attacker_slot: int, division: dict) -> bool:
    """Whether a blocked attacker with the offer should assign its combat
    damage to the creatures blocking it (*division*, the default one) rather
    than as though it weren't blocked.

    * **Taken when it ends the game**: the damage reaches the defending
      player and, with what the unblocked attackers beside it deal, is at
      least that player's life.
    * **Declined when it kills** — some blocker is assigned lethal damage
      that would reach it — because a creature removed is worth more than
      damage that does not finish anybody.
    * **Declined when the damage would not reach the player** and would reach
      a blocker: damage a Circle of Protection eats does nothing, and damage
      marked on a blocker is at least something for the next attacker.
    * Taken otherwise — the stated default, and the only answer an attack on
      a **planeswalker** gets: what its loyalty is worth against a creature
      is a valuation this does not have.
    """
    active = game.active_player_index
    attacker = game.permanent_at(active, attacker_slot)
    if attacker is None or game.combat_attacked_planeswalkers.get(attacker_slot) is not None:
        return False
    defending = game.combat_attackers[attacker_slot]
    if not 0 <= defending < len(game.players):
        return False
    defender = game.players[defending]
    damage = combat_damage_assigned_by(attacker)
    reaches_player = not _would_be_prevented(game, attacker, defender, damage)
    if reaches_player:
        beside = sum(
            combat_damage_assigned_by(other)
            for slot, seat in game.combat_attackers.items()
            if slot != attacker_slot and seat == defending
            and game.combat_attacked_planeswalkers.get(slot) is None
            and (other := game.permanent_at(active, slot)) is not None
            and not other.blocked and not game._attacker_all_blockers(slot)
        )
        if damage + beside >= defender.life:
            return False
    deathtouch = game._has_keyword(attacker, "deathtouch")
    reaches_a_blocker = False
    for blocker_slot, assigned in division.items():
        blocker = game.permanent_at(defending, blocker_slot)
        if blocker is None or assigned <= 0:
            continue
        if _would_be_prevented(game, attacker, blocker, assigned):
            continue
        reaches_a_blocker = True
        lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
        if deathtouch and lethal > 0:
            lethal = 1
        if assigned >= lethal:
            return True
    return reaches_a_blocker and not reaches_player


# --- The defending player's chair (CR 702.22j) -------------------------------
#
# Where the defending player assigns an attacker's combat damage — a creature
# with banding is blocking it, or "rather than the attacking player, you
# assign the combat damage of each creature attacking you" (Defensive
# Formation) — the two answers above are that player's: how the damage is
# divided among the creatures blocking, and, for an attacker that "may …
# assign its combat damage as though it weren't blocked", whether it is.
# An attacking AI seat has weighed its half since `choose_combat_damage_
# assignment` existed. A *defending* one was given the engine's defaults: the
# division that kills as many of its own creatures as the power allows
# (`_default_attacker_division`, "the attacker's rather than the defender's"),
# and the offer always declined — so its blocker died in front of a Thorn
# Elemental at twenty life.

def _lethal_from(game, attacker, blocker) -> int:
    """How much of *attacker*'s combat damage destroys *blocker* (CR 702.2c:
    any amount from a source with deathtouch) — the damage step's own count."""
    lethal = max(0, blocker.effective_toughness - blocker.damage_marked)
    if lethal > 0 and game._has_keyword(attacker, "deathtouch"):
        return 1
    return lethal


def _division_costing_least(game, attacker, blockers: dict, damage: int) -> tuple[dict, list]:
    """How a defending player divides *damage* among the creatures blocking
    *attacker* so as to lose least: ``(division, the creatures it kills)``.

    All of it has to be assigned (CR 510.1c), and any division of it among
    the blockers is legal — so the question is only which of them die.

    * **None**, where the damage fits under what each can take: each is
      assigned less than lethal damage, the first in slot order filled first.
      A blocker the damage would not reach at all (protection from the
      attacker's colour, a shield — ``_would_be_prevented``) takes everything.
    * Otherwise **one**: a creature already assigned lethal damage can be
      assigned the rest as well, so all of it goes on the one worth least
      (``ai_standing.permanent_worth``) and every other blocker lives. The
      engine's default walked the blockers in slot order assigning lethal
      damage to each — the most deaths the power allows, which is what an
      *attacker* wants.
    """
    from .ai_standing import permanent_worth

    division = {slot: 0 for slot in blockers}
    if damage <= 0 or not blockers:
        return division, []
    for slot, blocker in blockers.items():
        if _would_be_prevented(game, attacker, blocker, damage):
            division[slot] = damage
            return division, []
    room = {slot: max(0, _lethal_from(game, attacker, blocker) - 1)
            for slot, blocker in blockers.items()}
    if damage <= sum(room.values()):
        left = damage
        for slot in sorted(blockers):
            division[slot] = min(left, room[slot])
            left -= division[slot]
        return division, []
    cheapest = min(sorted(blockers), key=lambda slot: permanent_worth(blockers[slot]))
    division[cheapest] = damage
    return division, [blockers[cheapest]]


def _defender_takes_the_damage_itself(
    game, attacker, attacker_slot: int, defending: int, damage: int, dying: list,
) -> bool:
    """Whether a defending player who assigns an offered attacker's damage
    has it assigned "as though it weren't blocked" — to themself — rather
    than to the creatures blocking it.

    The attacker's own question (`_offer_is_better_declined`) from the other
    chair, in the valuation's own units: taken when keeping the damage on the
    blockers would cost a creature (*dying*) worth more than the life it
    costs to take it (``ai_standing.life_worth``, which makes the last
    points dear and a loss of the game unaffordable) — or costs nothing to
    take at all, because it would not reach the player. Kept on the blockers
    when none of them dies of it, and for an attack on a planeswalker, whose
    loyalty this has no price for.
    """
    from .ai_standing import life_worth, permanent_worth

    if not dying or game.combat_attacked_planeswalkers.get(attacker_slot) is not None:
        return False
    defender = game.players[defending]
    if _would_be_prevented(game, attacker, defender, damage):
        return True
    active = game.active_player_index
    # What is coming at this player beside it: the attackers nothing blocks.
    beside = sum(
        combat_damage_assigned_by(other)
        for slot, seat in game.combat_attackers.items()
        if slot != attacker_slot and seat == defending
        and game.combat_attacked_planeswalkers.get(slot) is None
        and (other := game.permanent_at(active, slot)) is not None
        and not other.blocked and not game._attacker_all_blockers(slot)
    )
    life_after_the_rest = defender.life - beside
    cost_in_life = life_worth(life_after_the_rest) - life_worth(life_after_the_rest - damage)
    return cost_in_life < sum(permanent_worth(creature) for creature in dying)


def choose_defender_damage_assignment(game, defender_index: int) -> tuple[dict, list[int]]:
    """How *defender_index* assigns the combat damage of each attacker it
    assigns, has a decision about and has not yet announced for this step
    (``Game.defender_assignments_owed``): ``(divisions, as_though_unblocked)``
    for ``Game.assign_banding_combat_damage``.

    A division for each such attacker that keeps its damage on the creatures
    blocking it (`_division_costing_least`), and the ``permanent_id`` of each
    whose "as though it weren't blocked" the defending player takes
    (`_defender_takes_the_damage_itself`) — one answer per attacker, never
    some of each.

    **A trampler is kept on its blockers too.** All of its damage to the
    creatures blocking it is legal for the seat that assigns it (CR 510.1c;
    CR 702.19b's excess is "assigned as its controller chooses among those
    blocking creatures and the player"), and in front of one blocker with
    more than lethal damage to assign, that blocker dies either way — so the
    excess is the whole decision, and none of it to this seat is the least
    it can cost. The engine's default sent it here: the attacker's split.
    """
    active = game.active_player_index
    divisions: dict[int, dict[int, int]] = {}
    taken: list[int] = []
    for slot in game.defender_assignments_owed(defender_index):
        attacker = game.permanent_at(active, slot)
        if attacker is None:
            continue
        damage = combat_damage_assigned_by(attacker)
        blockers = {
            blocker_slot: blocker
            for blocker_slot in game._attacker_all_blockers(slot)
            if (blocker := game.permanent_at(defender_index, blocker_slot)) is not None
        }
        division, dying = _division_costing_least(game, attacker, blockers, damage)
        if (
            game.unblocked_assignment_chooser(slot) == defender_index
            and _defender_takes_the_damage_itself(
                game, attacker, slot, defender_index, damage, dying
            )
        ):
            taken.append(attacker.permanent_id)
        elif blockers:
            divisions[slot] = division
    return divisions, taken


def announce_defender_assignments(game) -> int:
    """Have every defending seat **nobody is sitting at** announce how the
    attackers it assigns the combat damage of assign it (CR 510.1, CR
    702.22j), for the combat damage step about to be dealt. Returns how many
    attackers were answered for.

    Called by the damage step itself (``Game.resolve_combat_damage``), which
    is the one line every way of dealing combat damage passes through — an AI
    attacker's assignment, a person's, the engine's own auto-resolve, the
    second step of a double strike — so the defending seat's answer cannot be
    there for some of them. A person is not answered for: their dialog asks
    (``Game.unblocked_assignments_to_ask``, ``web/combat_prompts``).

    An announcement the engine refuses is dropped and the default stands, as
    it did before this existed; the chooser builds only divisions
    ``_attacker_division_refusal`` accepts. Nothing is logged for a division
    (the damage lines say where it went); an offer taken is the engine's own
    line, as it is for an attacker's.
    """
    answered = 0
    for defender_index in sorted(game.combat_defending_players()):
        if defender_index in game.interactive_seats:
            continue
        if not 0 <= defender_index < len(game.players):
            continue
        divisions, taken = choose_defender_damage_assignment(game, defender_index)
        if not divisions and not taken:
            continue
        ok, _why = game.assign_banding_combat_damage(
            defender_index, divisions, as_though_unblocked=taken,
        )
        if not ok:
            continue
        answered += len(divisions) + len(taken)
    return answered


def declare_ai_attackers(
    game, seat: int, *, attacker_indices: list[int] | None = None,
    outcome: CombatOutcome | None = None,
) -> tuple[bool, str]:
    """Declare *seat*'s attackers, falling back when the engine refuses.

    *attacker_indices* overrides the policy's choice (the web Debug Menu's
    "attack with everything"); None asks `choose_attackers`.

    Every rung is declared as the engine's CR 508.1d maximisation hands it back
    (`Game.obeying_attack_declaration`): unchanged when it already obeys the
    most requirements it can, otherwise the nearest declaration that does —
    which may aim a creature somewhere other than the chosen opponent (a
    Juggernaut beside a Propaganda that can attack only the planeswalker
    without paying), so the declaration carries each creature's aim.

    The fallback chain, and why each rung is there:

    1. The chosen set. If the engine takes it, done.
    2. **Every legal attacker.** A superset of every compelled creature — the
       rung that once fixed a declaration omitting one, kept for whatever the
       chooser's prune and the maximisation together still miss.
    3. **The cost-free maximum nearest to nobody.** "Nobody" was this rung,
       and it is no longer always legal: under Dueling Grounds beside an
       "attacks each combat if able" creature, declaring nobody obeys fewer
       requirements than declaring that creature alone (CR 508.1d's own
       example). The engine's answer from an empty preference is legal by
       construction.

    Rung 3 is the silent one, and it is logged rather than swallowed. It is not
    hypothetical: it is what both attack caps did to every AI seat that met one,
    for the life of this engine, until `attack_declaration_refusal` learned to
    carry them.
    """
    target = choose_attack_target(game, seat)
    if attacker_indices is None:
        attacker_indices = choose_attackers(game, seat)

    ok, why = _declare_obeying(game, seat, attacker_indices, target)
    if ok:
        return True, why

    if outcome is not None:
        outcome.refused_attacks.append((game.players[seat].name, why))
    game.log.append(
        f"AI attack declaration refused ({why}); falling back to every legal attacker"
    )
    fallback = legal_attackers(game, seat, against=target)
    ok, why = _declare_obeying(game, seat, fallback, target)
    if ok:
        return True, why

    if outcome is not None:
        outcome.silent_attacks.append((game.players[seat].name, why))
    game.log.append(
        f"AI fallback attack declaration also refused ({why}); "
        "this seat attacks with the fewest the requirements allow"
    )
    return _declare_obeying(game, seat, [], target)


def _declare_obeying(game, seat: int, indices: list[int], target: int):
    """Declare *indices* at *target*, as the CR 508.1d maximisation hands the
    declaration back — each creature with the seat or planeswalker it aims
    at."""
    declaration = game.obeying_attack_declaration(
        seat, list(indices), against=target, rank=_permanent_value,
    )
    return game.declare_attackers(
        seat, declaration.attackers, defending_player_index=target,
        attacker_targets=declaration.seats or None,
        attacker_planeswalker_ids=declaration.walkers or None,
    )


def declare_ai_blockers(
    game, defender_index: int, *, outcome: CombatOutcome | None = None
) -> bool:
    """Declare *defender_index*'s blocks, with the same shape of fallback.

    CR 509.1a's chooser may be someone else ("You choose which creatures block
    this combat", Melee), and the *declaration* is still taken under the
    defender's seat — so only who is asked changes. The engine is asked which
    seat that is rather than this deciding, because the two answers disagreeing
    is a block declared by a seat the rules did not ask.

    **The fallbacks are counted, for the attack side's reason.** A refused
    block is silent — nothing spent, no rule broken, and the defender simply
    blocks with nobody, this combat and every later one, because the chooser
    proposes the same map again. That silence is what hid every one of
    CR 509.1b's declaration-wide restrictions from `choose_combat_blockers`,
    which pruned against nothing at all until `block_declaration_refusal`
    existed for it to ask.
    """
    chooser_index = game.block_chooser_index(defender_index)
    name = game.players[defender_index].name

    if game.is_camouflage_active() and game.combat_attackers:
        # Camouflage replaces the declaration entirely: the defender divides
        # their creatures into piles and the engine matches piles to attackers
        # at random (CR 509.1 is not what happens here at all).
        ok, _ = game.resolve_camouflage_blocking(defender_index)
        return ok

    pairs = choose_combat_blockers(game, defender_index)
    ok, why = game.declare_blockers(defender_index, pairs, acting_index=chooser_index)
    if ok:
        return True

    if outcome is not None:
        outcome.refused_blocks.append((name, why))
    game.log.append(
        f"AI block declaration refused ({why}); falling back"
    )

    if pairs:
        # The chosen blocks were illegal; declaring none is legal unless a
        # requirement compels a block.
        ok, why = game.declare_blockers(defender_index, {}, acting_index=chooser_index)
        if ok:
            return True

    # Either the empty declaration is itself illegal (Lure compels a block), or
    # it was what we tried first because a substituted chooser preferred it. Ask
    # the defender's own scoring, ignoring the substitution.
    ok, why = game.declare_blockers(
        defender_index,
        choose_combat_blockers(game, defender_index, ignore_substitution=True),
        acting_index=chooser_index,
    )
    if ok:
        return True

    if outcome is not None:
        outcome.silent_blocks.append((name, why))
    game.log.append(
        f"AI fallback block declaration also refused ({why}); "
        "this seat blocks with nobody"
    )
    return False


def run_ai_combat_phase(game, seat: int, *, outcome: CombatOutcome | None = None,
                        max_steps: int = 40) -> CombatOutcome:
    """Walk one whole combat phase for a table of AI seats (CR 506–511).

    `Game.advance_combat_phase` is the engine's own step walker and it already
    does almost all of this: it enters the phase, auto-skips a declaration step
    with nothing to declare, fires the unblocked-attack triggers, opens and
    drains each step's priority window, and hands off to whatever phase comes
    after combat. It **returns without moving** at exactly the points where a
    player owes a turn-based action — attackers, blockers, the damage
    assignment — which is what makes this a loop rather than a reimplementation:
    advance, and if nothing moved, supply the declaration it is waiting for.

    That "if nothing moved" is the whole design. Naming the three wait states
    here instead would be a second copy of the engine's own step logic, and it
    would go stale the moment a fourth is added; a step that stops advancing is
    observable without knowing why it stopped.

    Returns when the phase is no longer combat — the engine enters the postcombat
    main phase itself (CR 500.1, and Relentless Assault's extra phase is entered
    rather than skipped, because `advance_combat_phase` asks what comes next
    rather than naming it).
    """
    outcome = outcome if outcome is not None else CombatOutcome()

    for _ in range(max_steps):
        if game.is_game_over():
            return outcome
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        if game.current_turn_phase != "combat":
            return outcome
        if (game.current_turn_phase, game.current_step) != before:
            continue

        # The phase did not move, so something is owed. Which thing is decided
        # by what is unlocked, not by the step name — a step can be reached with
        # its declaration already made (the engine locks an auto-skipped one).
        step = game.current_step
        if step == "declare_attackers" and not game.combat_attackers_locked:
            declare_ai_attackers(game, seat, outcome=outcome)
            outcome.attacks_declared += 1
            outcome.attackers += len(game.combat_attackers)
            outcome.attackers_declared |= {
                attacker.permanent_id
                for slot in game.combat_attackers
                if (attacker := game.permanent_at(game.active_player_index, slot)) is not None
            }
            continue
        if step == "declare_blockers" and not game.combat_blockers_locked:
            pending = game._pending_block_declarer()
            if pending is None:
                game.combat_blockers_locked = True
                game._prune_combat_state()
                continue
            declare_ai_blockers(game, pending, outcome=outcome)
            outcome.blocks_declared |= declared_block_pairs(game, pending)
            # `+=`, not `=`: this runs once per defending player per combat and
            # the outcome spans a whole phase, so assigning would report only
            # whichever defender declared last.
            outcome.blockers += sum(len(m) for m in game.combat_blockers.values())
            continue
        if step == "combat_damage" and not game.combat_damage_resolved:
            # CR 510.1a/702.22j: whoever divides a multi-blocked attacker's
            # damage, the *default* division is the engine's own — the same one
            # the web layer's auto-resolve path uses, so an AI-vs-AI game and an
            # unattended human game split damage the same way.
            game.resolve_all_combat_damage(
                game.active_player_index, **choose_combat_damage_announcement(game),
            )
            outcome.manual_damage_splits += 1
            continue

        # Nothing moved and nothing is owed that this driver knows how to
        # answer — a prompt is outstanding, or a resolution is suspended
        # (CR 608.2). Neither is this loop's to force, and spinning here is the
        # bare-stack-drain hang one phase up, so leave the phase where it is.
        return outcome

    return outcome
