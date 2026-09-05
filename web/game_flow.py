"""Priority and phase advancement: the game moving forward between
HTTP requests.

:func:`_advance_phase` is the engine of the whole app. It runs the next step's
turn-based actions and keeps going until something has to stop it — a seat that
holds priority, a pending decision, an outstanding combat assignment. The AI
stepping functions sit here rather than in a module of their own because they
are the *same* loop seen from the other side: an AI seat is one that never
stops, so driving it is calling this until a human is owed something.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.ai_policy import (
    choose_activation_action,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
)

from .prompts import auto_resolve_ai_prompts
from .session_store import Session

from .seats import (
    _ai_should_hold,
    _hold_priority_for_human,
    _seat_type,
    _self_should_hold,
    _winner,
)
from .turn_steps import (
    _cleanup_discard_requirement,
    _clear_cleanup_selection,
    _has_island_sanctuary,
    _resume_deferred_upkeep,
    _start_next_turn,
)
from .combat_prompts import (
    _ai_assign_combat_damage,
    _ai_declare_attackers,
    _ai_resolve_raging_river,
    _band_blocker_assignment_pending,
    _banding_assignment_pending,
    _multiblock_split_pending,
)


def settle_before_observation(session: Session) -> None:
    """Take the decisions the game owes before any client can look at it.

    Both of these lived inside ``_serialize_state``, which meant the function
    named for turning the game into JSON was the function that moved cards
    between players — and so ``GET /state`` was not a read. They are here
    because they are the same family as everything else in this module: an AI
    seat's forced decision, and the game settling once it is over.

    They are *not* simply deletable, which is why this is a move rather than a
    removal. Both are lazy settlements of a transition the game has already
    entered, and the human's next action is gated on the result:

    * **Raging River** — the human's prompt sequencing runs defender-then-attacker,
      so an AI on either side must lock its division before the prompt renders.
      If this only ran on the action path, the prompt the human needs in order
      to act would be the thing waiting on the human to act.
    * **Ante (CR 407.2)** — the engine settles the ante zone itself when a
      state-based action or a concession decides the game. This covers the web
      layer's *own* (Lich-aware) reading of who has lost, which the engine does
      not make.

    Both are idempotent, so calling this on every observation costs nothing
    after the first. That is what lets it sit in front of the serializer rather
    than being threaded through every mutating path and forgotten on one.
    """
    win = _winner(session)
    if win is not None:
        session.status = "finished"
        if win >= 0:
            session.game.award_ante_to_winner(win)

    _ai_resolve_raging_river(session)


def _auto_resolve_ai_pending(session: Session) -> None:
    """Answer every prompt an AI seat owes, with that kind's recorded default.

    One loop over the queue, so a newly registered prompt is covered by
    construction. This was twelve near-identical functions — one per prompt,
    each re-deriving the seat and calling a bespoke resolver — and the two the
    list was missing (Aladdin's Lamp, Ring of Ma'rûf) would have stalled a seat
    handed from a human to the AI. A missing entry does not misbehave; it hangs
    the game on that seat forever.
    """
    auto_resolve_ai_prompts(session.game, lambda seat: _seat_type(session, seat))


def _ai_step(session: Session) -> bool:
    """Run one AI action for the current turn.

    Returns True when the AI has nothing more to do this turn (caller should end
    the turn).  Returns False when the AI queued a spell and passed priority to a
    human opponent — the turn must NOT be ended yet; the human must act first.
    """
    seat = session.current_turn
    game = session.game

    _auto_resolve_ai_pending(session)

    has_human_opponent = any(
        _seat_type(session, s) == "human"
        for s in range(len(game.players))
        if s != seat
    )

    if game.priority_player_index is not None and game.priority_player_index != seat:
        return False

    # choose_cast_action covers sorcery-speed plays (enchantments, sorceries,
    # creatures, artifacts, lands), which are legal only during the active player's
    # main phase with an empty stack. Without this guard the AI would, e.g., drop an
    # enchantment during the combat damage step. Instants are handled separately via
    # _ai_respond_to_priority / the declare-blockers window.
    sorcery_speed_ok = (
        game.active_player_index == seat
        and game.current_step in ("precombat_main", "postcombat_main")
        and not game.stack
    )
    cast_action = choose_cast_action(game, seat) if sorcery_speed_ok else None
    if cast_action is not None:
        # `hand_index` indexes the zone `from_zone` names — the command zone
        # for a commander cast (CR 903.8), the hand for everything else.
        cast_zone = (
            game.players[seat].command_zone
            if cast_action.from_zone == "command"
            else game.players[seat].hand
        )
        card_to_cast = cast_zone[cast_action.hand_index]
        for permanent_index in cast_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)

        if has_human_opponent:
            result = game.queue_from_hand(
                seat,
                card_to_cast.name,
                target_player_index=cast_action.target_player_index,
                target_permanent_index=cast_action.target_permanent_index,
                target_permanent_ids=cast_action.target_permanent_ids,
                x_value=cast_action.x_value,
                from_zone=cast_action.from_zone,
                # CR 118.9, forwarded whole: the policy only sets this when the
                # mana cost cannot be paid, so dropping it here would turn every
                # such cast into an "insufficient mana" refusal.
                alternative_cost=cast_action.alternative_cost,
                # CR 601.2d, forwarded for the same reason: the division is part
                # of the announcement, and a cast that drops it is refused.
                divided_targets=cast_action.divided_targets,
            )
            if result.supported:
                game.note_priority_action_taken(seat)
                # NOTE (frontend FFA pass): route through the priority-exchange
                # cascade rather than a bare engine pass. In a 3+ player (FFA)
                # game, the seat right after `seat` in turn order may be a
                # second AI player rather than the human — only this cascade
                # (already used by the "pass_priority" action handler) drives
                # that seat's response instead of stalling with priority stuck
                # on an AI seat no client action can ever advance.
                _run_priority_exchange(session, seat)
                return False  # paused — human has priority over the spell on the stack
        else:
            game.cast_from_hand(
                seat,
                card_to_cast.name,
                target_player_index=cast_action.target_player_index,
                target_permanent_index=cast_action.target_permanent_index,
                target_permanent_ids=cast_action.target_permanent_ids,
                x_value=cast_action.x_value,
                from_zone=cast_action.from_zone,
                # CR 118.9, forwarded whole: the policy only sets this when the
                # mana cost cannot be paid, so dropping it here would turn every
                # such cast into an "insufficient mana" refusal.
                alternative_cost=cast_action.alternative_cost,
                # CR 601.2d, forwarded for the same reason: the division is part
                # of the announcement, and a cast that drops it is refused.
                divided_targets=cast_action.divided_targets,
            )
            _auto_resolve_ai_pending(session)

    activation_action = choose_activation_action(game, seat)
    if activation_action is not None:
        for permanent_index in activation_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        game.activate_permanent_ability(
            seat,
            activation_action.permanent_name,
            target_player_index=activation_action.target_player_index,
            permanent_index=activation_action.permanent_index,
            target_permanent_index=activation_action.target_permanent_index,
        )
        _auto_resolve_ai_pending(session)

    return True


def _ai_respond_to_priority(session: Session, seat: int) -> str | None:
    game = session.game
    if not game.has_priority(seat):
        return None

    instant_action = choose_combat_instant_cast_action(game, seat)
    if instant_action is not None:
        card_to_cast = game.players[seat].hand[instant_action.hand_index]
        for permanent_index in instant_action.land_tap_indices:
            permanent = game.players[seat].battlefield[permanent_index]
            game.tap_land_for_mana(seat, permanent.card.name, permanent_index=permanent_index)
        result = game.queue_from_hand(
            seat,
            card_to_cast.name,
            target_player_index=instant_action.target_player_index,
            x_value=instant_action.x_value,
            # CR 601.2d. This executor forwards less of the announcement than
            # the main-phase one does (a chosen permanent never reaches it,
            # which is a gap of its own), but a divided spell dropped here is
            # not merely aimed badly — it is refused at announcement, so the
            # seat would offer the same instant every combat and do nothing.
            divided_targets=instant_action.divided_targets,
        )
        if result.supported:
            game.note_priority_action_taken(seat)

    if game.has_priority(seat):
        return game.pass_priority(seat)
    return None


def _auto_advance_after_all_passed(session: Session, pass_result: str | None) -> None:
    if pass_result != "all_passed_empty":
        return

    # A decision somebody still owes holds the turn where it is. An AI seat's
    # prompts were answered by _auto_resolve_ai_pending before this ran, so what
    # is left is a human's — and advancing the step past it would resolve it
    # into a board that has already moved on. This named Word of Command alone,
    # which was the only prompt anyone had been bitten by; the rest of the queue
    # is the same fact about a different card. A prompt that blocks nothing
    # (``hand_reveal``) is a notification and holds nothing, which is what
    # ``holds_priority`` says.
    if session.game.waiting_prompt() is not None:
        return

    # Advance turn structure automatically after both players pass with an empty stack.
    _advance_phase(session)


def _run_priority_exchange(session: Session, acting_seat: int) -> None:
    result = session.game.pass_priority(acting_seat)

    while True:
        _auto_resolve_ai_pending(session)
        _auto_advance_after_all_passed(session, result)

        if result == "awaiting_choice":
            # The resolution stopped to ask somebody something, so nobody has
            # priority until they answer (CR 117.3b) and the object stays on the
            # stack. An AI chooser's prompt was answered by
            # _auto_resolve_ai_pending above — the object has left the stack —
            # so priority can go round again on its behalf. A human's is still
            # owed: stop here and surface it. Asking the queue rather than the
            # optional-pay list is what makes that true of the search, the
            # discard and the mode choice as well.
            chooser = session.game.priority_player_index
            still_owed = chooser is not None and session.game.waiting_prompt(chooser)
            if not still_owed and chooser is not None and _seat_type(session, chooser) == "ai":
                result = session.game.pass_priority(chooser)
                continue
            break

        ai_priority_seat = session.game.priority_player_index
        if (
            result == "passed"
            and ai_priority_seat is not None
            and _seat_type(session, ai_priority_seat) == "ai"
            and (ai_priority_seat != session.current_turn or bool(session.game.stack))
        ):
            result = _ai_respond_to_priority(session, ai_priority_seat)
            continue

        break


def _advance_ai_turn(session: Session) -> None:
    """Advance the AI's turn through its non-main steps after it has finished acting
    in the current step.

    Pauses to hand a human priority at any step they flagged on the phase rail. Stops
    when a new main phase begins (so the AI can cast there on the next step), when the
    turn ends, or when human input is required (e.g. declaring blockers).
    """
    for _safety in range(20):
        game = session.game
        step = game.current_step

        if _ai_should_hold(session, step):
            # Resolve the active player's turn-based action (declaring attackers)
            # before handing priority to the human.
            if step == "declare_attackers":
                _ai_declare_attackers(session)
            if _hold_priority_for_human(session):
                return

        prev_turn = session.current_turn
        prev_phase = game.current_turn_phase
        prev_step = step
        _advance_phase(session)

        if session.current_turn != prev_turn:
            return  # the AI's turn has ended
        if (
            session.game.current_turn_phase == prev_phase
            and session.game.current_step == prev_step
        ):
            return  # stuck waiting for human input (e.g. declare blockers)
        # Stop at a main phase so the AI casts there (driven by the next ai_step).
        if session.game.current_step in ("precombat_main", "postcombat_main"):
            return


def _advance_phase(session: Session) -> None:
    game = session.game
    # A decision somebody still owes holds the turn structure where it is.
    # AI seats answer theirs with the kind's default first, so what is left is
    # a human's — and advancing past it would resolve it into a board that has
    # already moved on. This named Word of Command by hand while
    # _auto_advance_after_all_passed asked the queue, and the AI-turn path
    # (_advance_ai_turn) reaches here without passing through that function:
    # an AI's Mind Rot resolved, the human's discard was armed, and the turn
    # walked on. Word of Command's own ``is_open`` reproduces the old
    # "chosen, but not yet finished" distinction.
    _auto_resolve_ai_pending(session)
    if game.waiting_prompt() is not None:
        return
    phase = game.current_turn_phase
    step = game.current_step

    if phase == "beginning" and step in ("upkeep", "draw"):
        # The phase-rail upkeep window has closed — resolve the upkeep itself now,
        # prompting for the trigger decisions deliberately deferred past it. Runs
        # before close_beginning_step so the step's own end (which empties mana
        # pools, CR 500.4) doesn't strand mana the player floated to pay with.
        if step == "upkeep" and session.upkeep_decisions_deferred:
            _resume_deferred_upkeep(session, session.current_turn)
            return
        # Resume after a held upkeep/draw step on the AI's turn: close it and move on,
        # holding again at the draw step if the human flagged it.
        game.close_beginning_step()
        # Island Sanctuary: the human must choose whether to skip their draw before
        # the draw step resolves (CR 504 replacement choice). Pause for the prompt
        # instead of drawing through it.
        if (
            step == "upkeep"
            and _seat_type(session, session.current_turn) == "human"
            and _has_island_sanctuary(game, session.current_turn)
        ):
            session.island_sanctuary_pending = True
            return
        if step == "upkeep" and _ai_should_hold(session, "draw"):
            game.resolve_draw_step(session.current_turn, defer_priority=True)
            _hold_priority_for_human(session)
            return
        if step == "upkeep" and _self_should_hold(session, "draw"):
            game.resolve_draw_step(session.current_turn, defer_priority=True)
            return
        if step == "upkeep":
            game.resolve_draw_step(session.current_turn)
        game.enter_next_turn_phase("beginning")
        return

    if phase == "precombat_main":
        game._close_current_priority_step()
        # The turn's plan decides, not this line: normally the combat phase, but
        # an effect resolved during this main phase may have added one after it
        # (CR 500.8 - Relentless Assault).
        game.enter_next_turn_phase("precombat_main")
        _clear_cleanup_selection(session)
        return
    if phase == "combat":
        if (
            step == "combat_damage"
            and not game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) == "ai"
        ):
            # No human is assigning damage for the active AI. Resolve combat damage
            # with a sensible default assignment so a multi-blocked attacker (which
            # the engine defers for manual assignment) doesn't deadlock the step.
            _ai_assign_combat_damage(session)
        elif (
            step == "combat_damage"
            and not game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) == "human"
            and game._needs_manual_damage_assignment()
            and not game._manual_assignment_has_declared_multiblock()
            and not _banding_assignment_pending(session)
            and not _band_blocker_assignment_pending(session)
            and not _multiblock_split_pending(session)
        ):
            # A human attacker declared a band whose block propagated to a single
            # shared blocker (CR 702.22h), but no band member has banding to route
            # (so there is no CR 702.22k choice) — auto-resolve a sensible default
            # instead of looping forever waiting for an assignment that can't arrive.
            # When there IS a 702.22k choice, _band_blocker_assignment_pending keeps
            # this from firing so the active player's dialog can resolve it instead.
            auto = game._build_auto_damage_assignment()
            game.resolve_all_combat_damage(game.active_player_index, attacker_damage=auto)
        if step == "declare_attackers" and not game.combat_attackers_locked:
            _ai_declare_attackers(session)
        if step == "declare_blockers":
            combat_state = game.get_combat_state()
            # CR 802.4: with 2+ defending players (FFA), each declares in APNAP
            # order — _pending_block_declarer() names whichever one is up next,
            # not a single fixed defender.
            defender_index = game._pending_block_declarer()
            # CR 509.1a's chooser, which is the defending player unless "You
            # choose which creatures block this combat" (Melee) moved it. The
            # *declaration* is still the defender's — the engine keeps taking it
            # under their seat — so only the seat that has to be prompted
            # changes, and that is the seat whose kind decides whether the AI
            # answers here or the rail waits for a person.
            chooser_index = (
                game.block_chooser_index(defender_index)
                if isinstance(defender_index, int) else None
            )
            if isinstance(defender_index, int) and _seat_type(session, chooser_index) == "ai":
                if not combat_state.get("blockers_locked", False):
                    if game.is_camouflage_active() and combat_state.get("attackers"):
                        # Camouflage: the AI defender divides its creatures into
                        # random piles instead of declaring chosen blocks.
                        ok, _ = game.resolve_camouflage_blocking(defender_index)
                    else:
                        blocker_pairs = choose_combat_blockers(game, defender_index)
                        ok, _ = game.declare_blockers(
                            defender_index, blocker_pairs, acting_index=chooser_index
                        )
                        if not ok and blocker_pairs:
                            ok, _ = game.declare_blockers(
                                defender_index, {}, acting_index=chooser_index
                            )
                        elif not ok:
                            # The empty declaration a substituted chooser prefers
                            # can itself be illegal (Lure). Fall back to the
                            # defender's own scoring rather than to the safety
                            # valve below, which wipes every seat's blocks.
                            ok, _ = game.declare_blockers(
                                defender_index,
                                choose_combat_blockers(
                                    game, defender_index,
                                    ignore_substitution=True,
                                ),
                                acting_index=chooser_index,
                            )
                    if not ok:
                        # Safety valve: never let AI declaration failures deadlock combat progression.
                        game.combat_blockers = {}
                        game.combat_blockers_locked = True
                        game._prune_combat_state()
                    # The declaration may have been made *for* this seat by
                    # another (Melee). Casting an instant afterwards is the
                    # defender's own priority action, so it is offered only to
                    # an AI defender — reaching for a human's hand because an
                    # AI chose their blocks would be the substitution spilling
                    # past the one decision the card moves.
                    instant_action = (
                        choose_combat_instant_cast_action(game, defender_index)
                        if _seat_type(session, defender_index) == "ai" else None
                    )
                    if instant_action is not None:
                        card_to_cast = game.players[defender_index].hand[instant_action.hand_index]
                        for permanent_index in instant_action.land_tap_indices:
                            permanent = game.players[defender_index].battlefield[permanent_index]
                            game.tap_land_for_mana(defender_index, permanent.card.name, permanent_index=permanent_index)
                        game.cast_from_hand(
                            defender_index,
                            card_to_cast.name,
                            target_player_index=instant_action.target_player_index,
                            x_value=instant_action.x_value,
                        )
                        return
                    # CR 509.4: declaring blockers opened a priority window for the
                    # active player. When a human attacker flagged the declare-blockers
                    # stop on the phase rail, hold here so they can respond to the
                    # blocks (combat tricks, block triggers on the stack) instead of
                    # skipping straight to combat damage; the client advances again
                    # once they pass priority or hit Next Phase.
                    if (
                        game.combat_attackers
                        and game.priority_player_index is not None
                        and _self_should_hold(session, "declare_blockers")
                    ):
                        return
        # CR 510.4: the combat-damage step opens a priority window after damage is
        # dealt. The engine normally auto-resolves that window and skips straight to
        # end-of-combat when no manual damage assignment is needed — which silently
        # ignores a combat_damage stop flagged on the phase rail. When either the
        # active human (self) or a human opponent flagged it, tell the engine to hold
        # the step open instead of skipping.
        hold_damage = _self_should_hold(session, "combat_damage") or _ai_should_hold(
            session, "combat_damage"
        )
        game.advance_combat_phase(allow_damage_skip=not hold_damage)
        # On the AI's turn the engine leaves priority with the active AI; hand it to
        # the human so they can act at the step they flagged (mirrors the upkeep/draw
        # and declare-blockers holds). On the human's own turn the active player is
        # already the human, so this is a no-op.
        if (
            hold_damage
            and game.current_turn_phase == "combat"
            and game.current_step == "combat_damage"
            and game.combat_damage_resolved
            and _seat_type(session, game.active_player_index) != "human"
        ):
            _hold_priority_for_human(session)
        return
    if phase == "postcombat_main":
        game._close_current_priority_step()
        # Normally the ending phase; an extra combat phase added after this one
        # (CR 500.8) is entered here instead of being recorded and lost.
        game.enter_next_turn_phase("postcombat_main")
        _clear_cleanup_selection(session)
        return
    if step == "end":
        game.close_end_step()
        should_defer_cleanup = _seat_type(session, session.current_turn) == "human"
        cleanup_completed = game.resolve_cleanup_step(
            session.current_turn,
            defer_discard_selection=should_defer_cleanup,
        )
        if not cleanup_completed:
            session.cleanup_required_discards = _cleanup_discard_requirement(session)
            session.cleanup_selected_indices = []
            return
        _start_next_turn(session)
        return
    if step == "cleanup":
        if _cleanup_discard_requirement(session) > 0:
            raise HTTPException(status_code=400, detail="select cleanup discards before advancing")
        _start_next_turn(session)
        return
