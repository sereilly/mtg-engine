"""Handlers for the turn's own structure: phases, steps, and their choices.

End/advance the turn, the cleanup and untap selections, Time Vault's skip of
the turn beginning, the upkeep pay-or-consequence decisions, Island
Sanctuary's draw choice, and stepping an AI turn forward.
"""

from __future__ import annotations

from engine.untap_restrictions import permanent_in_limited_scope
from engine.phases.upkeep_step import upkeep_prompt_key
from fastapi import HTTPException

from .action_helpers import answered_permanent_id
from .action_registry import HUMAN_ONLY, action_handler
from .combat_prompts import _ai_declare_attackers, _banding_assignment_pending
from .game_flow import _advance_ai_turn, _advance_phase, _ai_step
from .seats import _ai_should_hold, _hold_priority_for_human, _seat_type
from .turn_steps import (
    _advance_after_upkeep_choices,
    _begin_turn,
    _can_pay_upkeep_choice,
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
    untap_candidates,
)


def _answered_upkeep_prompt(pending: list[dict], req) -> tuple:
    """The pending upkeep prompt *req* is answering, and the key to file it
    under — or an HTTP error naming which half of the address was wrong.

    **An address is required whenever the prompt has one.** A card name alone
    cannot say which of two Breeding Pits is being paid for, and a request that
    sends only the name would silently answer whichever prompt matched first —
    the defect this whole seam was rebuilt to remove, arriving back through the
    wire. So a prompt carrying ``permanent_id`` is answerable only by
    ``prompt_permanent_id``, and a prompt whose subject is not a permanent —
    Nether Shadow's graveyard return, a Nafs Asp obligation — only by
    ``prompt_subject_ordinal``, which says *which* of the same-named subjects
    it is. Both narrow to one pending entry; the bare name is left as the
    answer for a prompt carrying neither, where it can only mean the one.

    An address that names no *pending* prompt is a 400 rather than a
    fall-through: the client wrote this against the board it last polled, and
    if that permanent has gone the name beside it now points at a different
    decision.
    """
    if req.prompt_permanent_id is not None:
        match = next(
            (c for c in pending if c.get("permanent_id") == req.prompt_permanent_id),
            None,
        )
        if match is None:
            raise HTTPException(
                status_code=400,
                detail="that permanent is not awaiting an upkeep decision",
            )
        return match, upkeep_prompt_key(match)
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if req.prompt_subject_ordinal is not None:
        match = next(
            (
                c for c in pending
                if c["card_name"] == req.card_name
                and c.get("subject_ordinal") == req.prompt_subject_ordinal
            ),
            None,
        )
        if match is None:
            raise HTTPException(
                status_code=400,
                detail="that subject is not awaiting an upkeep decision",
            )
        return match, upkeep_prompt_key(match)
    match = next(
        (c for c in pending if c["card_name"] == req.card_name), None
    )
    if match is None:
        raise HTTPException(
            status_code=400, detail="card not awaiting an upkeep decision"
        )
    if match.get("permanent_id") is not None:
        raise HTTPException(
            status_code=400,
            detail="prompt_permanent_id is required to answer this decision",
        )
    if match.get("subject_ordinal") is not None:
        raise HTTPException(
            status_code=400,
            detail="prompt_subject_ordinal is required to answer this decision",
        )
    return match, upkeep_prompt_key(match)


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
        # False when the discard set something off that a person still owes
        # an answer to — a madness card discarded to hand size offers its cast
        # (CR 702.35a) — so the turn waits for it rather than beginning the
        # next one around an open prompt.
        if session.game.resolve_cleanup_step(
            session.current_turn, discard_hand_indices=selected,
        ):
            _start_next_turn(session)

@action_handler("time_vault_skip")
def _action_time_vault_skip(session, req, seat_type):
    # Time Vault: skip the turn you are beginning to untap the artifact.
    if req.seat != session.current_turn or not session.time_vault_pending:
        raise HTTPException(status_code=400, detail="no Time Vault skip is pending for you")
    name = req.card_name or (session.time_vault_pending[0] if session.time_vault_pending else None)
    if not name or not session.game.untap_for_skip(req.seat, name):
        raise HTTPException(status_code=400, detail="cannot skip to untap that permanent")
    session.time_vault_resolved_turn = session.game.turn
    session.time_vault_pending = []
    _start_next_turn(session)  # the skipped player's turn does not run

@action_handler("time_vault_decline")
def _action_time_vault_decline(session, req, seat_type):
    # Decline the skip and take the turn normally.
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    session.time_vault_resolved_turn = session.game.turn
    session.time_vault_pending = []
    _begin_turn(session, req.seat, defer_untap_selection=True)

@action_handler("untap_select", human_only=HUMAN_ONLY)
def _action_untap_select(session, req, seat_type):
    # One click of a "can't untap more than N" choice (Winter Orb, Smoke,
    # Static Orb, Damping Field): toggles the permanent named by
    # ``permanent_id`` — the ``candidate_ids`` entry clicked — in the
    # selection, which is kept by id across requests (``untap_selected_ids``).
    # It was kept by slot, and the offer beside it too, so anything leaving
    # the battlefield between two clicks moved both onto the neighbours.
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if session.game.current_step != "untap":
        raise HTTPException(status_code=400, detail="untap selection is only available during untap")
    if req.permanent_id is None and req.permanent_index is None:
        raise HTTPException(status_code=400, detail="permanent_id is required")

    required = _untap_land_selection_requirement(session)
    if required <= 0:
        raise HTTPException(status_code=400, detail="no untap land selection is required")

    chosen_id = answered_permanent_id(
        session.game, req, id_field="permanent_id", slot_field="permanent_index",
        seat=req.seat,
    )
    candidates = {perm.permanent_id: perm for perm in untap_candidates(session)}
    if chosen_id not in candidates:
        raise HTTPException(status_code=400, detail="permanent is not a valid untap land choice")

    selected = [pid for pid in session.untap_selected_ids if pid in candidates]
    if chosen_id in selected:
        selected = [pid for pid in selected if pid != chosen_id]
    else:
        # Enforce the per-type cap first (Winter Orb constrains lands, Smoke
        # constrains creatures) so the error names the constrained type
        # rather than the combined total.
        options = session.game.get_untap_land_selection_options(session.current_turn) or {}
        limits = options.get("limits") or {}

        def _ptype(permanent) -> str:
            # The first constrained type this permanent answers to — which is
            # the one whose cap the message should name. "" when it answers to
            # none, because then there is no cap to charge it against: the
            # printed ``card.primary_type`` stood here as the fallback and
            # could name a scope the permanent is **not** in, which is a Licid
            # that became an Aura being charged against Smoke's creature cap.
            return next(
                (t for t in sorted(limits) if permanent_in_limited_scope(permanent, t)),
                "",
            )

        new_type = _ptype(candidates[chosen_id])
        # The per-type cap, read from the limits map the engine reports rather
        # than from a pair of named fields — the message that names the type is
        # what tells a player *why* the click was refused, and it should not go
        # generic the moment a third type is constrained.
        type_max = limits.get(new_type)
        if type_max is not None:
            already = sum(1 for pid in selected if _ptype(candidates[pid]) == new_type)
            if already >= int(type_max):
                raise HTTPException(
                    status_code=400,
                    detail=f"already selected maximum untap {new_type}s",
                )
        if len(selected) >= required:
            raise HTTPException(status_code=400, detail="already selected maximum untap permanents")
        selected.append(chosen_id)

    session.untap_selected_ids = selected
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

    candidates = {perm.permanent_id: perm for perm in untap_candidates(session)}
    selected = [pid for pid in session.untap_selected_ids if pid in candidates]
    if len(selected) > required:
        raise HTTPException(status_code=400, detail="selected too many permanents to untap")

    # Split the chosen permanents by type and hand one list per constrained
    # type to the untap resolver — **by id**, which the engine turns into
    # slots after the phasing event (CR 702.26a takes permanents off the
    # battlefield list before anything untaps). Only a *constrained* type gets
    # a (possibly empty) selection; an unconstrained one stays absent so it
    # untaps freely. Generic over the limits map, so Damping Field's artifact
    # needed no branch of its own here.
    options = session.game.get_untap_land_selection_options(session.current_turn) or {}
    by_type = {
        card_type: [
            pid for pid in selected
            # The engine's own scope predicate, not a second spelling of it —
            # an artifact creature answers to both Damping Field's limit and
            # Smoke's, every permanent answers to Static Orb's, and a split that
            # disagreed would hand the resolver a selection it then rejected.
            if permanent_in_limited_scope(candidates[pid], card_type)
        ]
        for card_type in (options.get("limits") or {})
    }
    try:
        session.game.resolve_untap_step(
            session.current_turn, selected_ids_by_type=by_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _clear_untap_selection(session)
    _resolve_upkeep_step(session, session.current_turn)

@action_handler("optional_untap_confirm")
def _action_optional_untap_confirm(session, req, seat_type):
    # Old Man of the Sea: the player picked which "may choose not to untap"
    # permanents stay tapped — by id (``target_permanent_ids``, each offered
    # entry's ``id``; the preamble has 404'd a stale one), or by slot
    # (``creature_indices``, read as the permanents in those slots now).
    # Empty or omitted is untap them all.
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not session.optional_untap_pending:
        raise HTTPException(status_code=400, detail="no optional untap choice is pending")
    valid = {entry.get("id") for entry in session.optional_untap_pending}
    if req.target_permanent_ids is not None:
        keep = list(dict.fromkeys(req.target_permanent_ids))
    else:
        keep = []
        for slot in dict.fromkeys(req.creature_indices or []):
            named = session.game.permanent_at(req.seat, slot)
            if named is None:
                raise HTTPException(status_code=400, detail="invalid keep-tapped choice")
            keep.append(named.permanent_id)
    if any(pid not in valid for pid in keep):
        raise HTTPException(status_code=400, detail="invalid keep-tapped choice")
    session.optional_untap_pending = []
    session.game.resolve_untap_step(session.current_turn, keep_tapped_ids=keep)
    _clear_untap_selection(session)
    _resolve_upkeep_step(session, session.current_turn)

@action_handler("pay_upkeep")
def _action_pay_upkeep(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _upkeep_pay_pending(session):
        raise HTTPException(status_code=400, detail="no upkeep payment required")

    choice, key = _answered_upkeep_prompt(_upkeep_pay_pending(session), req)
    controller = session.game.players[req.seat]
    # The whole cost, not its mana half: an upkeep may print life or a
    # sacrifice beside the mana (CR 702.24a), and a gate that reads one part
    # lets a player pay a cost they cannot afford. And on top of every upkeep
    # cost this seat has already agreed to pay: they are paid afterwards off
    # one board, and an accept that board cannot honour used to be carried
    # out as a decline when its turn came (`_can_pay_upkeep_choice`).
    if not _can_pay_upkeep_choice(session, controller, choice):
        raise HTTPException(
            status_code=400,
            detail=f"cannot pay upkeep cost for {choice['card_name']}",
        )

    session.upkeep_resolved_choices[key] = True

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("sacrifice_upkeep")
def _action_sacrifice_upkeep(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _upkeep_pay_pending(session):
        raise HTTPException(status_code=400, detail="no upkeep payment required")

    _choice, key = _answered_upkeep_prompt(_upkeep_pay_pending(session), req)
    session.upkeep_resolved_choices[key] = False

    if not _upkeep_decisions_pending(session):
        _advance_after_upkeep_choices(session)

@action_handler("resolve_optional_trigger")
def _action_resolve_optional_trigger(session, req, seat_type):
    if req.seat != session.current_turn:
        raise HTTPException(status_code=400, detail="not your turn")
    if not _optional_trigger_pending(session):
        raise HTTPException(status_code=400, detail="no optional trigger pending")
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept (true/false) is required")

    # A target-bearing trigger (Vesuvan Doppelganger's re-copy, Erhnam
    # Djinn's forestwalk grant) requires the chosen creature alongside an
    # accept. Mandatory triggers can't be declined — only targeted.
    choice, key = _answered_upkeep_prompt(_optional_trigger_pending(session), req)
    if choice.get("mandatory") and not req.accept:
        raise HTTPException(status_code=400, detail="this trigger is mandatory and can't be declined")
    if choice.get("needs_target") and req.accept:
        # The answer is filed as the chosen permanent's **id** (CR 400.7) —
        # what each `valid_targets` entry carries and what the engine reads
        # (`UpkeepStepMixin._upkeep_target_pick`). It was the (seat, slot)
        # pair, which the step read again later: a permanent leaving in
        # between moved the slot onto its neighbour. `target_permanent_id` is
        # the address to send (a stale one is the preamble's 404); a seat and
        # slot are still accepted, and turned into the id of what is in that
        # slot now, while it still means what the client clicked.
        if req.target_permanent_id is not None:
            target_id = req.target_permanent_id
        elif req.target_seat is not None and req.target_permanent_index is not None:
            named = session.game.permanent_at(req.target_seat, req.target_permanent_index)
            if named is None:
                raise HTTPException(
                    status_code=404,
                    detail="that permanent is no longer on the battlefield",
                )
            target_id = named.permanent_id
        else:
            raise HTTPException(status_code=400, detail="this trigger requires a target choice")
        valid = {t.get("id") for t in choice.get("valid_targets", [])}
        if target_id not in valid:
            raise HTTPException(status_code=400, detail="invalid target for this trigger")
        session.optional_trigger_targets[key] = target_id

    session.optional_trigger_resolved[key] = bool(req.accept)

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
    choice, key = _answered_upkeep_prompt(
        _upkeep_mana_prevention_pending(session), req
    )
    amount = max(0, int(req.amount or 0))
    controller = session.game.players[req.seat]
    available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
    amount = min(amount, int(choice.get("damage", 0)), available)
    session.upkeep_mana_prevention_resolved[key] = amount

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
    session.game.enter_next_turn_phase("beginning")

@action_handler("ai_step")
def _action_ai_step(session, req, seat_type):
    if _seat_type(session, session.current_turn) != "ai":
        raise HTTPException(status_code=400, detail="current turn is not AI")
    # The turn this step belongs to. Everything below may advance *it* and no
    # other: `_advance_phase` from the AI's end step runs the cleanup and the
    # next player's whole beginning phase, and whatever turn that leaves is not
    # this request's to walk any further.
    stepped_turn = session.current_turn
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
            if session.current_turn == stepped_turn:
                _advance_ai_turn(session)
