"""The beginning phase and the turn's boundaries (CR 500-514).

The web layer cannot simply call the engine's step logic and return: untap
choices, upkeep payments and cleanup discards are *decisions a seat owes*, and
an interactive seat has to be asked between one step and the next. So a turn is
a sequence of resumable pieces here — begin, resolve upkeep (possibly deferring
it), finish the beginning phase, end the turn — each able to stop and be picked
up when the answer arrives.
"""

from __future__ import annotations

from engine.upkeep_costs import cost_from_payload

from .session_store import Session

from .prompts import auto_resolve_ai_prompts
from .seats import (
    _ai_should_hold,
    _hold_priority_for_human,
    _seat_type,
    _self_should_hold,
)


def _cleanup_discard_requirement(session: Session) -> int:
    if session.game.current_phase != "cleanup":
        return 0
    active = session.game.players[session.current_turn]
    if active.has_no_max_hand_size:
        return 0
    return max(0, len(active.hand) - 7)


def _clear_cleanup_selection(session: Session) -> None:
    session.cleanup_required_discards = 0
    session.cleanup_selected_indices = []


def _clear_untap_selection(session: Session) -> None:
    session.untap_required_lands = 0
    session.untap_candidate_indices = []
    session.untap_selected_indices = []
    session.optional_untap_pending = []


def _clear_upkeep_pay_choices(session: Session) -> None:
    session.upkeep_pay_choices = []
    session.upkeep_mana_prevention_choices = []
    session.upkeep_mana_prevention_resolved = {}
    session.upkeep_resolved_choices = {}
    session.optional_trigger_choices = []
    session.optional_trigger_resolved = {}
    session.optional_trigger_targets = {}
    session.upkeep_decisions_deferred = False


def _consume_draw_step_life_loss(session: Session) -> dict[str, bool] | None:
    """Pop the Nafs Asp pay-or-lose-life answers gathered at upkeep. Returns None
    when nothing was decided, which is resolve_draw_step's "no human input"
    signal (it pays when able)."""
    choices = session.draw_step_life_loss_choices
    session.draw_step_life_loss_choices = {}
    return choices or None


def _has_island_sanctuary(game, player_index: int) -> bool:
    return any(
        p.card.name == "Island Sanctuary" for p in game.controlled_by(player_index)
    )


def _upkeep_pay_pending(session: Session) -> list[dict]:
    """Return pay-or-sacrifice choices that still need a player decision."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.upkeep_pay_choices
        if c["card_name"] not in session.upkeep_resolved_choices
    ]


def _optional_trigger_pending(session: Session) -> list[dict]:
    """Return optional ('you may') upkeep triggers still awaiting a yes/no answer."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.optional_trigger_choices
        if c["card_name"] not in session.optional_trigger_resolved
    ]


def _upkeep_mana_prevention_pending(session: Session) -> list[dict]:
    """Return 'pay mana to prevent damage' upkeep triggers (Power Leak) still
    awaiting the player's chosen amount."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.upkeep_mana_prevention_choices
        if c["card_name"] not in session.upkeep_mana_prevention_resolved
    ]


def _upkeep_decisions_pending(session: Session) -> bool:
    """True while any upkeep decision (pay-or-sacrifice, optional trigger, or
    pay-to-prevent) is open."""
    return bool(
        _upkeep_pay_pending(session)
        or _optional_trigger_pending(session)
        or _upkeep_mana_prevention_pending(session)
    )


def _collect_upkeep_decisions(game, player_index: int) -> tuple[list[dict], list[dict], list[dict]]:
    """Every interactive upkeep decision this player owes right now, as
    (pay-or-consequence, optional/targeted, pay-to-prevent) lists. Read-only, so
    callers can also use it just to ask "does this upkeep need a prompt at all?"."""
    pay_choices = game.get_upkeep_pay_triggers(player_index)
    # Nafs Asp: "unless they pay {1} before that draw step" — decided here, at
    # upkeep, then handed to resolve_draw_step. Shares the pay-or-else channel.
    pay_choices += game.get_draw_step_life_loss_choices(player_index)
    # Optional ("you may") triggers and mandatory targeted triggers (Erhnam
    # Djinn) share one decision channel — both are answered by
    # resolve_optional_trigger, the mandatory ones with a target and no decline.
    optional_choices = game.get_optional_upkeep_triggers(player_index)
    optional_choices += game.get_upkeep_target_triggers(player_index)
    prevention_choices = game.get_upkeep_mana_prevention_triggers(player_index)
    return pay_choices, optional_choices, prevention_choices


def _gather_upkeep_decisions(session: Session, player_index: int) -> bool:
    """Populate pending upkeep decisions for a human player and pause at upkeep.

    Returns True if a decision is pending (caller should stop and prompt), False
    if the player has nothing to decide and the upkeep can resolve immediately.
    """
    game = session.game
    pay_choices, optional_choices, prevention_choices = _collect_upkeep_decisions(game, player_index)
    if not pay_choices and not optional_choices and not prevention_choices:
        return False
    session.upkeep_pay_choices = pay_choices
    session.upkeep_resolved_choices = {}
    session.optional_trigger_choices = optional_choices
    session.optional_trigger_resolved = {}
    session.optional_trigger_targets = {}
    session.upkeep_mana_prevention_choices = prevention_choices
    session.upkeep_mana_prevention_resolved = {}
    game._set_phase_and_step("beginning", "upkeep")
    return True


#: Backstop on the answer/resolve alternation below. Each round either empties
#: the stack or stops on a prompt, so a real turn needs a handful; a run of this
#: many means a default that fails to clear its own prompt.
_MAX_PROMPT_ROUNDS = 64


def _pause_beginning_phase(session: Session, marker: str, player_index: int) -> bool:
    """Whether the beginning phase must stop here, owing somebody a decision.

    CR 117.3b: nobody receives priority — and no step advances — while a spell
    or ability is still resolving, and a resolution that armed a prompt is. The
    engine holds the ability on the stack for it; this is the turn structure's
    half, because the step's own priority window has already been drained by
    ``_resolve_priority_window`` and the *next* step is what would run.

    Only a human's prompt stops anything: an AI seat answers its own here and
    the drain carries on, which is also what re-enters the window a held object
    stopped — the rest of the step's triggers are still on the stack behind it.

    This asked about Lord of the Pit's sacrifice and nothing else, the one card
    anyone had been bitten by. Sanctum of All's "you may search your library" is
    the same fact with a different prompt in it, and used to run the draw step
    and land in the main phase with its offer still unanswered.
    """
    game = session.game
    for _ in range(_MAX_PROMPT_ROUNDS):
        auto_resolve_ai_prompts(game, lambda seat: _seat_type(session, seat))
        if game.waiting_prompt() is not None:
            session.paused_beginning_phase = (marker, player_index)
            return True
        if not game.stack:
            return False
        game._resolve_priority_window()
    # A default that fails to clear its own prompt would loop here forever; the
    # cap breaks it, and the log says so rather than carrying on silently (the
    # same precedent as resolution.py's _settle abort).
    game.log.append(
        f"_pause_beginning_phase aborted after {_MAX_PROMPT_ROUNDS} rounds at {marker} "
        "(a prompt default is not clearing itself)"
    )
    return False


def _resume_paused_beginning_phase(session: Session) -> None:
    """Pick a beginning phase back up once nothing is owed.

    Called from ``web/actions.py``'s tail after every action rather than from
    the handler that answers the prompt: *which* prompt paused the phase is not
    something the answering handler knows, and the sacrifice confirm carrying
    this alone is why only that one prompt could ever pause it.
    """
    if session.paused_beginning_phase is None:
        return
    marker, player_index = session.paused_beginning_phase
    if _pause_beginning_phase(session, marker, player_index):
        return
    session.paused_beginning_phase = None
    if marker == "begin_turn":
        _finish_beginning_phase(session, player_index)
    elif marker == "main_phase":
        session.game.enter_next_turn_phase("beginning")


def _advance_after_upkeep_choices(session: Session) -> None:
    """Called once all upkeep decisions (pay-or-sacrifice and optional) are resolved."""
    choices = dict(session.upkeep_resolved_choices)
    optional = dict(session.optional_trigger_resolved)
    trigger_targets = dict(session.optional_trigger_targets)
    mana_prevention = dict(session.upkeep_mana_prevention_resolved)
    # Split the Nafs Asp answers back out — resolve_upkeep knows nothing about
    # them; they belong to the draw step that _finish_beginning_phase runs next.
    life_loss_names = {
        c["card_name"] for c in session.upkeep_pay_choices
        if c.get("kind") == "draw_step_life_loss_unless_pay"
    }
    session.draw_step_life_loss_choices = {
        name: paid for name, paid in choices.items() if name in life_loss_names
    }
    choices = {name: paid for name, paid in choices.items() if name not in life_loss_names}
    _clear_upkeep_pay_choices(session)
    session.game.resolve_upkeep(
        session.current_turn,
        human_choices=choices,
        optional_choices=optional,
        mana_prevention=mana_prevention,
        trigger_targets=trigger_targets,
    )
    if _pause_beginning_phase(session, "begin_turn", session.current_turn):
        return
    _finish_beginning_phase(session, session.current_turn)


def _build_upkeep_pay_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Serialize pending upkeep pay state for the game-state response."""
    if not session.upkeep_pay_choices:
        return None
    if viewer_seat != session.current_turn:
        return None
    pending = _upkeep_pay_pending(session)
    # Per-card affordability so the UI can disable the pay button instead of
    # offering a payment that would be rejected. The whole cost, not its mana
    # half: CR 702.24a admits life and a sacrifice beside the mana, and a
    # button greyed out on one part is the same lie either way round.
    can_pay: dict[str, bool] = {}
    if 0 <= session.current_turn < len(session.game.players):
        payer = session.game.players[session.current_turn]
        can_pay = {
            c["card_name"]: session.game.can_pay_upkeep_cost(
                payer, cost_from_payload(c.get("cost") or {})
            )
            for c in session.upkeep_pay_choices
        }
    return {
        "choices": session.upkeep_pay_choices,
        "resolved": session.upkeep_resolved_choices,
        "pending": pending,
        "can_pay": can_pay,
    }


def _build_optional_trigger_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Serialize pending optional ('you may') trigger prompts for the response."""
    if not session.optional_trigger_choices:
        return None
    if viewer_seat != session.current_turn:
        return None
    return {
        "choices": session.optional_trigger_choices,
        "resolved": session.optional_trigger_resolved,
        "pending": _optional_trigger_pending(session),
    }


def _build_upkeep_mana_prevention_info(session: Session, viewer_seat: int | None) -> dict | None:
    """Serialize 'pay mana to prevent that much damage' upkeep prompts (Power Leak).

    The viewer chooses an amount (0..damage, capped by available mana); it is sent
    back via the ``pay_upkeep_prevention`` action."""
    if not session.upkeep_mana_prevention_choices:
        return None
    if viewer_seat != session.current_turn:
        return None
    pending = _upkeep_mana_prevention_pending(session)
    available = 0
    if 0 <= session.current_turn < len(session.game.players):
        pool = session.game.players[session.current_turn].mana_pool
        available = sum(pool.get(s, 0) for s in pool)
    return {
        "choices": session.upkeep_mana_prevention_choices,
        "resolved": session.upkeep_mana_prevention_resolved,
        "pending": pending,
        "available_mana": available,
    }


def _untap_land_selection_requirement(session: Session) -> int:
    if session.game.current_step != "untap":
        return 0
    if session.current_turn < 0 or session.current_turn >= len(session.game.players):
        return 0
    options = session.game.get_untap_land_selection_options(session.current_turn)
    if not options:
        return 0
    max_count = int(options.get("max_count", 0))
    return max(0, max_count)


def _begin_turn(session: Session, player_index: int, defer_untap_selection: bool) -> bool:
    game = session.game
    # Reset the per-turn counters (creatures died, damage taken, lands played)
    # exactly as the headless start_turn flow does — without this, Scavenging
    # Ghoul's end-step trigger fires on deaths from previous turns.
    game.begin_turn_bookkeeping(player_index)

    # Time Vault: "If you would begin your turn while this is tapped, you may skip
    # that turn instead. If you do, untap it." Prompt a human controller at the very
    # start of their turn (once); the AI never skips. Resolved via the
    # time_vault_skip / time_vault_decline actions.
    if (
        defer_untap_selection
        and session.time_vault_resolved_turn != game.turn
        and _seat_type(session, player_index) == "human"
    ):
        options = game.get_begin_turn_untap_options(player_index)
        if options:
            game._set_phase_and_step("beginning", "untap")
            session.time_vault_pending = list(options)
            return False
    session.time_vault_pending = []

    if defer_untap_selection:
        options = game.get_untap_land_selection_options(player_index)
        if options:
            game._set_phase_and_step("beginning", "untap")
            session.untap_required_lands = int(options["max_count"])
            session.untap_candidate_indices = [int(idx) for idx in options["candidate_indices"]]
            session.untap_selected_indices = []
            return False

        # Old Man of the Sea: "You may choose not to untap this creature during
        # your untap step." Pause for the human's keep-tapped choice; answered
        # by the optional_untap_confirm action.
        optional = game.get_optional_untap_permanents(player_index)
        if optional:
            game._set_phase_and_step("beginning", "untap")
            session.optional_untap_pending = list(optional)
            return False

    _clear_untap_selection(session)
    game.resolve_untap_step(player_index)

    return _resolve_upkeep_step(session, player_index)


def _resolve_upkeep_step(session: Session, player_index: int) -> bool:
    """Run the upkeep step once the untap step is done, honoring the phase-rail
    holds and any interactive upkeep-trigger prompts.

    Returns True when the beginning phase ran through (or deliberately stopped at
    a priority window), False when it paused waiting on human input. Shared by
    _begin_turn and the untap-selection actions that resume a turn mid-untap.
    """
    game = session.game

    # CR 503.1/503.1a: the upkeep step opens with a priority window — triggers go
    # on the stack and the active player acts BEFORE any of them resolve, so an
    # "unless you pay" choice is made at resolution, not on the way in. When the
    # human flagged the upkeep stop on the phase rail, give them that window first
    # and hold the trigger prompts back until they pass priority (_advance_phase
    # picks the deferral back up) instead of prompting them out of the gate.
    if (
        _self_should_hold(session, "upkeep")
        and _seat_type(session, player_index) == "human"
        and any(_collect_upkeep_decisions(game, player_index))
    ):
        _clear_upkeep_pay_choices(session)
        session.upkeep_decisions_deferred = True
        game._set_phase_and_step("beginning", "upkeep")
        game._on_step_or_phase_begin("beginning", "upkeep")
        game.start_priority_window(player_index)
        return True

    if _seat_type(session, player_index) == "human":
        if _gather_upkeep_decisions(session, player_index):
            return False

    _clear_upkeep_pay_choices(session)

    # On the AI's turn, pause to hand a human priority at the upkeep step if flagged.
    if _ai_should_hold(session, "upkeep"):
        game.resolve_upkeep(player_index, defer_priority=True)
        _hold_priority_for_human(session)
        return True

    # On the human's own turn, open a priority window at upkeep if flagged on the
    # phase rail, instead of resolving straight through to the main phase.
    if _self_should_hold(session, "upkeep"):
        game.resolve_upkeep(player_index, defer_priority=True)
        return True

    game.resolve_upkeep(player_index)
    if _pause_beginning_phase(session, "begin_turn", player_index):
        return False
    return _finish_beginning_phase(session, player_index)


def _resume_deferred_upkeep(session: Session, player_index: int) -> None:
    """Resolve an upkeep whose trigger prompts were held back for the phase-rail
    upkeep priority window, now that the window has closed. Any prompts are
    gathered against the CURRENT board — the player may have sacrificed, killed or
    bounced a trigger source during the window — and answering them resumes the
    beginning phase through _advance_after_upkeep_choices."""
    game = session.game
    session.upkeep_decisions_deferred = False
    if _gather_upkeep_decisions(session, player_index):
        return
    _clear_upkeep_pay_choices(session)
    game.resolve_upkeep(player_index)
    if _pause_beginning_phase(session, "begin_turn", player_index):
        return
    _finish_beginning_phase(session, player_index)


def _finish_beginning_phase(session: Session, player_index: int) -> bool:
    """Run the draw step and enter the main phase after upkeep has resolved,
    honoring Island Sanctuary and the phase-rail draw-step holds. Shared by
    _begin_turn and the post-sacrifice (Lord of the Pit) resume."""
    game = session.game
    if _seat_type(session, player_index) == "human" and _has_island_sanctuary(game, player_index):
        session.island_sanctuary_pending = True
        return False

    # Nafs Asp answers collected during upkeep; consumed exactly once here.
    pay_life_loss = _consume_draw_step_life_loss(session)

    if _ai_should_hold(session, "draw"):
        game.resolve_draw_step(player_index, defer_priority=True, pay_life_loss=pay_life_loss)
        _hold_priority_for_human(session)
        return True

    if _self_should_hold(session, "draw"):
        game.resolve_draw_step(player_index, defer_priority=True, pay_life_loss=pay_life_loss)
        return True

    game.resolve_draw_step(player_index, pay_life_loss=pay_life_loss)
    # The draw step asks too — a draw trigger's prompt is owed before the main
    # phase begins, exactly as the upkeep's is before the draw step.
    if _pause_beginning_phase(session, "main_phase", player_index):
        return False
    game.enter_next_turn_phase("beginning")
    return True


def _start_next_turn(session: Session) -> None:
    _clear_cleanup_selection(session)
    _clear_untap_selection(session)
    _clear_upkeep_pay_choices(session)
    session.draw_step_life_loss_choices = {}
    session.island_sanctuary_pending = False
    session.game.active_player_index = session.current_turn
    session.game.turn += 1
    session.current_turn = session.game._compute_next_active_player()
    should_defer_untap = _seat_type(session, session.current_turn) == "human"
    _begin_turn(session, session.current_turn, defer_untap_selection=should_defer_untap)


#: How a phase name reads in the log. Only the two CR 500.8 can add are
#: spelled out; anything else falls back to its own name.
_PHASE_LABELS = {
    "combat": "combat phase",
    "precombat_main": "main phase",
    "postcombat_main": "main phase",
    "beginning": "beginning phase",
    "ending": "ending phase",
}


def _end_turn(session: Session, allow_manual_cleanup_selection: bool = False) -> bool:
    """The End Turn button: jump from wherever the active player is standing to
    the end step, then the cleanup step, then the next turn.

    **It jumps, deliberately, and it always has** — pressing it in a precombat
    main phase skips that turn's own combat. The two turn controls are already
    different things: ``next_phase`` walks CR 500.1's order one phase at a time
    and honours the turn's plan, and this one is the "I am finished" shortcut.
    Making it walk the phases instead would leave no way to decline a combat
    phase, and would make the button a synonym for holding down the other one.

    What CR 500.8 changed is that the plan can now hold a phase *no rule put
    there* — Relentless Assault's "After this main phase, there is an additional
    combat phase followed by an additional main phase" (CR 500.8) — and jumping
    over one of those loses something the player paid a card for rather than
    something the turn structure was always going to offer. That stays a jump
    too, for the reason above, but it stops being **silent**:
    ``Game.extra_phases_remaining`` is the plan minus CR 500.1's ordinary
    remainder, which is exactly what an effect added, and it is named in the log
    where every other thing the turn did to itself is named.
    """
    added = session.game.extra_phases_remaining()
    if added:
        session.game.log.append(
            f"{session.game.players[session.current_turn].name} ended the turn, "
            "skipping the extra "
            + ", ".join(_PHASE_LABELS.get(phase, phase) for phase in added)
            + " (CR 500.8)"
        )
    if session.game.current_turn_phase in {"precombat_main", "postcombat_main"}:
        session.game._close_current_priority_step()
    if session.game.current_turn_phase == "combat":
        session.game.end_combat()
    if session.game.current_step != "end":
        session.game.resolve_end_step(session.current_turn)
    session.game.close_end_step()
    should_defer_cleanup = allow_manual_cleanup_selection and _seat_type(session, session.current_turn) == "human"
    cleanup_completed = session.game.resolve_cleanup_step(
        session.current_turn,
        defer_discard_selection=should_defer_cleanup,
    )
    if not cleanup_completed:
        session.cleanup_required_discards = _cleanup_discard_requirement(session)
        session.cleanup_selected_indices = []
        return False
    _start_next_turn(session)
    return True
