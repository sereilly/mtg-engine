"""Handlers for the turn's own structure: phases, steps, and their choices.

End/advance the turn, the cleanup and untap selections, the upkeep
pay-or-consequence decisions, Island Sanctuary's draw choice, and stepping
an AI turn forward.
"""

from __future__ import annotations

from fastapi import HTTPException
from .action_registry import HUMAN_ONLY, action_handler
from .combat_prompts import _ai_declare_attackers, _banding_assignment_pending
from .game_flow import _advance_ai_turn, _advance_phase, _ai_step
from .seats import _ai_should_hold, _hold_priority_for_human, _seat_type
from .turn_steps import (
    _advance_after_upkeep_choices,
    _cleanup_discard_requirement,
    _clear_untap_selection,
    _consume_draw_step_life_loss,
    _end_turn,
    _optional_trigger_pending,
    _resolve_upkeep_step,
    _start_next_turn,
    _untap_land_selection_requirement,
    _upkeep_decisions_pending,
    _upkeep_mana_prevention_pending,
    _upkeep_pay_pending,
)


@action_handler("end_turn", human_only=HUMAN_ONLY)
def _action_end_turn(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")
    if session.game.stack:
        raise HTTPException(status_code=400, detail="cannot end turn while stack is not empty")
    # The upkeep is still unresolved behind the phase-rail window the player is
    # standing in; ending the turn from here would skip its triggers outright.
    if session.upkeep_decisions_deferred:
        raise HTTPException(status_code=400, detail="resolve your upkeep before ending the turn")
    _end_turn(session, allow_manual_cleanup_selection=True)

@action_handler("next_phase", human_only=HUMAN_ONLY)
def _action_next_phase(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    # CR 702.22j: a defender's banding damage split is pre-committed before the
    # active player resolves combat damage — don't let them advance past it.
    if _banding_assignment_pending(session):
        raise HTTPException(
            status_code=400,
            detail="waiting for the defending player to assign banding combat damage",
        )
    # CR 508.1/509.1: during the declare attackers/blockers assignment no priority
    # window is open (declaring is a turn-based action). The active player may
    # still advance the turn structure to drive that declaration; outside the
    # assignment, advancing a phase requires holding priority with an empty stack.
    assignment_portion = (
        session.game.current_turn_phase == "combat"
        and session.game.current_step in ("declare_attackers", "declare_blockers")
        and session.game.priority_player_index is None
    )
    if (
        session.game.current_turn_phase in {"precombat_main", "combat", "postcombat_main"}
        and not assignment_portion
    ):
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        if session.game.stack:
            raise HTTPException(status_code=400, detail="cannot advance phase while stack is not empty")
    _advance_phase(session)

@action_handler("cleanup_select")
def _action_cleanup_select(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if session.game.current_phase != "cleanup":
        raise HTTPException(status_code=400, detail="cleanup selection is only available during cleanup")
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")

    active_hand = session.game.players[session.current_turn].hand
    if req.hand_index < 0 or req.hand_index >= len(active_hand):
        raise HTTPException(status_code=400, detail="hand_index out of range")

    required = _cleanup_discard_requirement(session)
    if required <= 0:
        raise HTTPException(status_code=400, detail="no cleanup discard is required")

    selected = sorted(set(session.cleanup_selected_indices))
    if req.hand_index in selected:
        selected = [idx for idx in selected if idx != req.hand_index]
    else:
        if len(selected) >= required:
            raise HTTPException(status_code=400, detail="already selected required cleanup discards")
        selected.append(req.hand_index)
        selected = sorted(set(selected))

    session.cleanup_selected_indices = selected
    session.cleanup_required_discards = required

    if len(selected) == required:
        session.game.resolve_cleanup_step(session.current_turn, discard_hand_indices=selected)
        _start_next_turn(session)

@action_handler("untap_select", human_only=HUMAN_ONLY)
def _action_untap_select(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if session.game.current_step != "untap":
        raise HTTPException(status_code=400, detail="untap selection is only available during untap")
    if req.permanent_index is None:
        raise HTTPException(status_code=400, detail="permanent_index is required")

    required = _untap_land_selection_requirement(session)
    if required <= 0:
        raise HTTPException(status_code=400, detail="no untap land selection is required")

    candidates = set(session.untap_candidate_indices)
    if req.permanent_index not in candidates:
        raise HTTPException(status_code=400, detail="permanent is not a valid untap land choice")

    selected = sorted(set(session.untap_selected_indices))
    if req.permanent_index in selected:
        selected = [idx for idx in selected if idx != req.permanent_index]
    else:
        # Enforce the per-type cap first (Winter Orb constrains lands, Smoke
        # constrains creatures) so the error names the constrained type
        # rather than the combined total.
        options = session.game.get_untap_land_selection_options(session.current_turn) or {}
        battlefield = session.game.players[session.current_turn].battlefield

        def _ptype(idx: int) -> str:
            return battlefield[idx].card.primary_type if 0 <= idx < len(battlefield) else ""

        new_type = _ptype(req.permanent_index)
        type_max = {"land": options.get("land_max"), "creature": options.get("creature_max")}.get(new_type)
        if type_max is not None:
            already = sum(1 for idx in selected if _ptype(idx) == new_type)
            if already >= int(type_max):
                raise HTTPException(
                    status_code=400,
                    detail=f"already selected maximum untap {new_type}s",
                )
        if len(selected) >= required:
            raise HTTPException(status_code=400, detail="already selected maximum untap permanents")
        selected.append(req.permanent_index)
        selected = sorted(set(selected))

    session.untap_selected_indices = selected
    session.untap_required_lands = required

@action_handler("untap_confirm", human_only=HUMAN_ONLY)
def _action_untap_confirm(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if session.game.current_step != "untap":
        raise HTTPException(status_code=400, detail="untap confirmation is only available during untap")

    required = _untap_land_selection_requirement(session)
    if required <= 0:
        raise HTTPException(status_code=400, detail="no untap land selection is required")

    selected = sorted(set(session.untap_selected_indices))
    if len(selected) > required:
        raise HTTPException(status_code=400, detail="selected too many permanents to untap")

    # Split the chosen battlefield indices by type — Winter Orb constrains lands,
    # Smoke constrains creatures — and hand each list to the untap resolver. Only
    # pass a (possibly empty) selection for a constrained type; an unconstrained
    # type stays None so it untaps freely.
    options = session.game.get_untap_land_selection_options(session.current_turn) or {}
    battlefield = session.game.players[session.current_turn].battlefield
    selected_lands = [i for i in selected if 0 <= i < len(battlefield) and battlefield[i].card.primary_type == "land"]
    selected_creatures = [i for i in selected if 0 <= i < len(battlefield) and battlefield[i].card.primary_type == "creature"]
    try:
        session.game.resolve_untap_step(
            session.current_turn,
            selected_land_indices=selected_lands if options.get("land_max") is not None else None,
            selected_creature_indices=selected_creatures if options.get("creature_max") is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _clear_untap_selection(session)
    _resolve_upkeep_step(session, session.current_turn)

@action_handler("optional_untap_confirm")
def _action_optional_untap_confirm(session, req, seat_type):
    # Old Man of the Sea: the player picked which "may choose not to untap"
    # permanents stay tapped (creature_indices; empty/omitted = untap all).
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not session.optional_untap_pending:
        raise HTTPException(status_code=400, detail="no optional untap choice is pending")
    valid = {int(entry["index"]) for entry in session.optional_untap_pending}
    keep = sorted(set(req.creature_indices or []))
    if any(idx not in valid for idx in keep):
        raise HTTPException(status_code=400, detail="invalid keep-tapped choice")
    session.optional_untap_pending = []
    session.game.resolve_untap_step(session.current_turn, keep_tapped_indices=keep)
    _clear_untap_selection(session)
    _resolve_upkeep_step(session, session.current_turn)

@action_handler("pay_upkeep")
def _action_pay_upkeep(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _upkeep_pay_pending(session):
        raise HTTPException(status_code=400, detail="no upkeep payment required")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")

    pending = {c["card_name"]: c for c in _upkeep_pay_pending(session)}
    if req.card_name not in pending:
        raise HTTPException(status_code=400, detail="card not awaiting upkeep payment")

    choice = pending[req.card_name]
    controller = session.game.players[req.seat]
    if not session.game.can_pay_upkeep_mana(controller, choice.get("mana") or {}):
        raise HTTPException(status_code=400, detail=f"not enough mana to pay upkeep for {req.card_name}")

    session.upkeep_resolved_choices[req.card_name] = True

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("sacrifice_upkeep")
def _action_sacrifice_upkeep(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _upkeep_pay_pending(session):
        raise HTTPException(status_code=400, detail="no upkeep payment required")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")

    pending = {c["card_name"]: c for c in _upkeep_pay_pending(session)}
    if req.card_name not in pending:
        raise HTTPException(status_code=400, detail="card not awaiting upkeep payment")

    session.upkeep_resolved_choices[req.card_name] = False

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("resolve_optional_trigger")
def _action_resolve_optional_trigger(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _optional_trigger_pending(session):
        raise HTTPException(status_code=400, detail="no optional trigger pending")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")

    pending = {c["card_name"]: c for c in _optional_trigger_pending(session)}
    if req.card_name not in pending:
        raise HTTPException(status_code=400, detail="card not awaiting an optional trigger decision")

    # A target-bearing trigger (Vesuvan Doppelganger's re-copy, Erhnam
    # Djinn's forestwalk grant) requires the chosen creature alongside an
    # accept. Mandatory triggers can't be declined — only targeted.
    choice = pending[req.card_name]
    if choice.get("mandatory") and not req.accept:
        raise HTTPException(status_code=400, detail="this trigger is mandatory and can't be declined")
    if choice.get("needs_target") and req.accept:
        if req.target_seat is None or req.target_permanent_index is None:
            raise HTTPException(status_code=400, detail="this trigger requires a target choice")
        valid = {
            (t.get("seat"), t.get("index"))
            for t in choice.get("valid_targets", [])
        }
        if (req.target_seat, req.target_permanent_index) not in valid:
            raise HTTPException(status_code=400, detail="invalid target for this trigger")
        session.optional_trigger_targets[req.card_name] = (req.target_seat, req.target_permanent_index)

    session.optional_trigger_resolved[req.card_name] = bool(req.accept)

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("pay_upkeep_prevention")
def _action_pay_upkeep_prevention(session, req, seat_type):
    # Power Leak: "that player may pay any amount of mana ... prevent X of that
    # damage." The player commits how much mana to pay (0..damage, capped by
    # available mana); the engine spends it and prevents that much.
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _upkeep_mana_prevention_pending(session):
        raise HTTPException(status_code=400, detail="no upkeep prevention pending")
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    pending = {c["card_name"]: c for c in _upkeep_mana_prevention_pending(session)}
    if req.card_name not in pending:
        raise HTTPException(status_code=400, detail="card not awaiting an upkeep prevention decision")
    amount = max(0, int(req.amount or 0))
    controller = session.game.players[req.seat]
    available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
    amount = min(amount, int(pending[req.card_name].get("damage", 0)), available)
    session.upkeep_mana_prevention_resolved[req.card_name] = amount

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("island_sanctuary_skip", "island_sanctuary_draw")
def _action_island_sanctuary_skip(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not session.island_sanctuary_pending:
        raise HTTPException(status_code=400, detail="no Island Sanctuary choice pending")
    session.island_sanctuary_pending = False
    skip = req.action == "island_sanctuary_skip"
    session.game.resolve_draw_step(
        session.current_turn,
        sanctuary_choice=skip,
        pay_life_loss=_consume_draw_step_life_loss(session),
    )
    session.game._enter_main_phase(precombat=True)

@action_handler("ai_step")
def _action_ai_step(session, req, seat_type):
    if _seat_type(session, session.current_turn) != "ai":
        raise HTTPException(status_code=400, detail="current turn is not AI")
    if _ai_step(session):
        # The AI finished acting in the current step. Hold here if the human
        # flagged this (main) step; otherwise leave it and advance the turn,
        # pausing at any later step they flagged.
        step = session.game.current_step
        if _ai_should_hold(session, step):
            if step == "declare_attackers":
                _ai_declare_attackers(session)
            _hold_priority_for_human(session)
        else:
            _advance_phase(session)
            _advance_ai_turn(session)
