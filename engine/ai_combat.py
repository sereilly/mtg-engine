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

What is *not* shared is the surrounding turn structure. The web layer walks
combat one client request at a time, pausing wherever a human has flagged a step
on the phase rail; the simulator has no humans and walks the whole phase in one
call. Those are genuinely different loops over the same engine seam
(`Game.advance_combat_phase`), not two copies of one.
"""

from dataclasses import dataclass, field

from .ai_policy import (
    choose_attack_target,
    choose_attackers,
    choose_combat_blockers,
    legal_attackers,
)


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


def declare_ai_attackers(
    game, seat: int, *, attacker_indices: list[int] | None = None,
    outcome: CombatOutcome | None = None,
) -> tuple[bool, str]:
    """Declare *seat*'s attackers, falling back when the engine refuses.

    *attacker_indices* overrides the policy's choice (the web Debug Menu's
    "attack with everything"); None asks `choose_attackers`.

    The fallback chain, and why each rung is there:

    1. The chosen set. If the engine takes it, done.
    2. **Every legal attacker.** A superset fixes exactly one class of refusal —
       a declaration that omitted a creature which must attack if able — because
       it contains every forced creature, and a forced creature that cannot
       legally attack is never required.
    3. **Nobody.** A superset cannot satisfy a *restriction* — a cap, an
       Errantry, an Orcish Conscripts — so for those, rung 2 is refused for the
       same reason rung 1 was and the seat ends up attacking with nothing.

    Rung 3 is the silent one, and it is logged rather than swallowed. It is not
    hypothetical: it is what both attack caps did to every AI seat that met one,
    for the life of this engine, until `attack_declaration_refusal` learned to
    carry them.
    """
    target = choose_attack_target(game, seat)
    if attacker_indices is None:
        attacker_indices = choose_attackers(game, seat)

    ok, why = game.declare_attackers(
        seat, attacker_indices, defending_player_index=target
    )
    if ok:
        return True, why

    if outcome is not None:
        outcome.refused_attacks.append((game.players[seat].name, why))
    game.log.append(
        f"AI attack declaration refused ({why}); falling back to every legal attacker"
    )
    fallback = legal_attackers(game, seat, against=target)
    ok, why = game.declare_attackers(
        seat, fallback, defending_player_index=target
    )
    if ok:
        return True, why

    if outcome is not None:
        outcome.silent_attacks.append((game.players[seat].name, why))
    game.log.append(
        f"AI fallback attack declaration also refused ({why}); "
        "this seat attacks with nobody"
    )
    return game.declare_attackers(seat, [], defending_player_index=target)


def declare_ai_blockers(game, defender_index: int) -> bool:
    """Declare *defender_index*'s blocks, with the same shape of fallback.

    CR 509.1a's chooser may be someone else ("You choose which creatures block
    this combat", Melee), and the *declaration* is still taken under the
    defender's seat — so only who is asked changes. The engine is asked which
    seat that is rather than this deciding, because the two answers disagreeing
    is a block declared by a seat the rules did not ask.
    """
    chooser_index = game.block_chooser_index(defender_index)

    if game.is_camouflage_active() and game.combat_attackers:
        # Camouflage replaces the declaration entirely: the defender divides
        # their creatures into piles and the engine matches piles to attackers
        # at random (CR 509.1 is not what happens here at all).
        ok, _ = game.resolve_camouflage_blocking(defender_index)
        return ok

    pairs = choose_combat_blockers(game, defender_index)
    ok, _ = game.declare_blockers(defender_index, pairs, acting_index=chooser_index)
    if ok:
        return True

    if pairs:
        # The chosen blocks were illegal; declaring none is legal unless a
        # requirement compels a block.
        ok, _ = game.declare_blockers(defender_index, {}, acting_index=chooser_index)
        if ok:
            return True

    # Either the empty declaration is itself illegal (Lure compels a block), or
    # it was what we tried first because a substituted chooser preferred it. Ask
    # the defender's own scoring, ignoring the substitution.
    ok, _ = game.declare_blockers(
        defender_index,
        choose_combat_blockers(game, defender_index, ignore_substitution=True),
        acting_index=chooser_index,
    )
    return ok


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
            continue
        if step == "declare_blockers" and not game.combat_blockers_locked:
            pending = game._pending_block_declarer()
            if pending is None:
                game.combat_blockers_locked = True
                game._prune_combat_state()
                continue
            declare_ai_blockers(game, pending)
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
                game.active_player_index,
                attacker_damage=game._build_auto_damage_assignment(),
            )
            outcome.manual_damage_splits += 1
            continue

        # Nothing moved and nothing is owed that this driver knows how to
        # answer — a prompt is outstanding, or a resolution is suspended
        # (CR 608.2). Neither is this loop's to force, and spinning here is the
        # bare-stack-drain hang one phase up, so leave the phase where it is.
        return outcome

    return outcome
