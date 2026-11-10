"""The beginning phase and the turn's boundaries (CR 500-514).

The web layer cannot simply call the engine's step logic and return: untap
choices, upkeep payments and cleanup discards are *decisions a seat owes*, and
an interactive seat has to be asked between one step and the next. So a turn is
a sequence of resumable pieces here — begin, resolve upkeep (possibly deferring
it), finish the beginning phase, end the turn — each able to stop and be picked
up when the answer arrives.
"""

from __future__ import annotations

from engine.ai_graveyard_activations import graveyard_abilities
from engine.hand_size import maximum_hand_size
from engine.phases.upkeep_step import upkeep_prompt_key
from engine.upkeep_costs import cost_from_payload

from .session_store import Session

from .prompts import auto_resolve_ai_prompts
from .seats import (
    _ai_should_hold,
    _hold_priority_for_human,
    _mark_interactive_seats,
    _seat_type,
    _self_should_hold,
)
from .pregame import _pregame_auto_advance


def _cleanup_discard_requirement(session: Session) -> int:
    """How many cards the active seat still owes CR 514.1's discard.

    Asked of ``engine.hand_size.maximum_hand_size`` — the reader the cleanup
    step itself enforces with. This kept its own copy (the player flag and a
    literal seven), so the engine deferred a human seat's discard under Cursed
    Rack or Recycle and this then reported that nothing was owed: no prompt
    was drawn, and advancing started the next turn with the cards still in
    hand. The engine and the prompt must count against one number.
    """
    if session.game.current_phase != "cleanup":
        return 0
    active = session.game.players[session.current_turn]
    limit = maximum_hand_size(session.game, session.current_turn)
    if limit is None:
        return 0
    return max(0, len(active.hand) - limit)


def _clear_cleanup_selection(session: Session) -> None:
    session.cleanup_required_discards = 0
    session.cleanup_selected_indices = []


def _clear_untap_selection(session: Session) -> None:
    session.untap_required_lands = 0
    session.untap_selected_ids = []
    session.optional_untap_pending = []


def untap_candidates(session: Session) -> list:
    """The permanents the active seat may choose to untap under a "can't
    untap more than N" restriction (Winter Orb, Smoke, Static Orb, Damping
    Field), in battlefield order — the engine's own offer
    (``get_untap_land_selection_options``), read **now**.

    Read live rather than kept on the session: the list the step offered was
    stored as battlefield slots across requests, so a permanent leaving
    between two clicks moved every later slot onto its neighbour and the
    stored offer named permanents nobody was offered. The selection is kept by
    ``permanent_id`` (``Session.untap_selected_ids``) for the same reason.
    """
    game = session.game
    seat = session.current_turn
    options = game.get_untap_land_selection_options(seat) or {}
    return [
        permanent
        for idx in sorted(int(i) for i in options.get("candidate_indices") or ())
        if (permanent := game.permanent_at(seat, idx)) is not None
    ]


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
    """Whether this seat is owed the "skip your draw for protection" question.

    Asked of the engine's own reader of its draw-step hook rather than answered
    here by the card's name: the engine decides whether the skip exists, and a
    second answer in this package is one the two could come to disagree about.
    """
    return game.may_skip_draw_for_protection(player_index)


def _upkeep_pay_pending(session: Session) -> list[dict]:
    """Return pay-or-sacrifice choices that still need a player decision.

    Filtered by ``upkeep_prompt_key`` — the permanent id, for all but the two
    prompts that have none. This read the printed card name, so two copies of
    one upkeep card were one entry as far as "still pending" was concerned:
    answering either cleared both, and the second permanent's decision was
    never asked. The engine's half of that is
    ``upkeep_effects.upkeep_answer``.
    """
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.upkeep_pay_choices
        if upkeep_prompt_key(c) not in session.upkeep_resolved_choices
    ]


def _optional_trigger_pending(session: Session) -> list[dict]:
    """Return optional ('you may') upkeep triggers still awaiting a yes/no answer."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.optional_trigger_choices
        if upkeep_prompt_key(c) not in session.optional_trigger_resolved
    ]


def _upkeep_mana_prevention_pending(session: Session) -> list[dict]:
    """Return 'pay mana to prevent damage' upkeep triggers (Power Leak) still
    awaiting the player's chosen amount."""
    if session.game.current_step != "upkeep":
        return []
    return [
        c for c in session.upkeep_mana_prevention_choices
        if upkeep_prompt_key(c) not in session.upkeep_mana_prevention_resolved
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
            # The step the window stopped in was held open rather than ended
            # (``Game.window_left_unfinished``): now that nothing is owed, it
            # ends — its mana pools empty (CR 500.5) *after* the trigger that
            # stopped it has resolved, not before.
            if game.step_held_open() and not game._close_current_priority_step():
                continue
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


def _leave_step(session: Session, leave) -> bool:
    """Leave the current step through *leave*, answering what AI seats owe on
    the way; True once the step has been left.

    *leave* is the engine's own way out of the step (``advance_combat_phase``,
    ``_close_current_priority_step``, ``end_combat``). It drains the step's
    priority window, and at a table with a human at it the window stops for
    **every** seat's prompt (CR 608.2: a resolution that asks is not finished)
    — so the engine holds the step open (``Game.step_held_open``) rather than
    ending it around the question. An AI seat's question is this layer's to
    answer, with the kind's default, and the step's leaving then resumes at
    its window: the rest of the step's triggers resolve *in* the step, Brood
    Sliver's second token offer included. A human's question stops here and
    the step waits for the answer; the next advance resumes it.

    Before this, the engine walked past the AI's question and this layer
    answered it one step late: an AI's provoke resolved in the declare
    blockers step, Essence Sliver's life gain in the AI's end step.
    """
    game = session.game
    for _ in range(_MAX_PROMPT_ROUNDS):
        leave()
        if not game.step_held_open():
            return True
        auto_resolve_ai_prompts(game, lambda seat: _seat_type(session, seat))
        if game.waiting_prompt() is not None:
            return False
    game.log.append(
        f"_leave_step gave up after {_MAX_PROMPT_ROUNDS} rounds in "
        f"{game.current_step} (a prompt default is not clearing itself)"
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
    elif marker == "untap_type_choice":
        # The untap step stopped *inside* CR 502.3's turn-based action, before
        # it untapped anything, so the resume re-enters the step rather than the
        # phase behind it — the type the seat just named is what the step is
        # about to spend.
        _finish_untap_step(session, player_index)
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
    # Split on the prompt *key*, not on the card name: an upkeep answer is
    # filed under a permanent id now and a Nafs Asp obligation under its source
    # name (it has no permanent — the source may have left), so the two
    # channels no longer share a key space at all.
    life_loss_keys = {
        upkeep_prompt_key(c) for c in session.upkeep_pay_choices
        if c.get("kind") == "draw_step_life_loss_unless_pay"
    }
    session.draw_step_life_loss_choices = {
        key: paid for key, paid in choices.items() if key in life_loss_keys
    }
    choices = {key: paid for key, paid in choices.items() if key not in life_loss_keys}
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


def _can_pay_upkeep_choice(session: Session, payer, choice: dict) -> bool:
    """Whether *payer* can pay *choice*'s upkeep cost **on top of** every
    upkeep cost they have already said they will pay.

    The upkeep's prices are answered as a batch and paid afterwards, one
    trigger at a time, off one board. Each used to be asked on its own, so
    two Force of Nature and four Forests read "can pay" twice, both were
    accepted, the first was paid — and the second, found unpayable when its
    turn came, dealt its 8 damage: a "Pay" carried out as a "don't". An
    accept the board cannot honour beside the ones already given is refused
    while it is still an answer (CR 118.3, CR 608.2d).

    The mana halves are what share a board, so those are what is summed; the
    life and sacrifice halves are asked of this cost alone, as before.
    """
    cost = cost_from_payload(choice.get("cost") or {})
    if not session.game.can_pay_upkeep_cost(payer, cost):
        return False
    key = upkeep_prompt_key(choice)
    total = dict(cost.mana)
    committed = False
    for other in session.upkeep_pay_choices:
        other_key = upkeep_prompt_key(other)
        if other_key == key or session.upkeep_resolved_choices.get(other_key) is not True:
            continue
        for symbol, amount in cost_from_payload(other.get("cost") or {}).mana.items():
            if amount:
                total[symbol] = total.get(symbol, 0) + amount
                committed = True
    if not committed or not cost.mana:
        return True
    return session.game.can_pay_upkeep_mana(payer, total)


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
        # Keyed by the prompt key, which JSON renders as a string for the
        # permanent ids — ``app.js`` indexes it with the same value it sends
        # back, and JavaScript stringifies a numeric index for free.
        # …and on top of what the seat has already agreed to pay this upkeep
        # (`_can_pay_upkeep_choice`), which is the question the pay action
        # asks: the button and the answer read one board.
        can_pay = {
            upkeep_prompt_key(c): _can_pay_upkeep_choice(session, payer, c)
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


def _begin_turn(
    session: Session, player_index: int, defer_untap_selection: bool | None = None,
) -> bool:
    game = session.game
    # Reset the per-turn counters (creatures died, damage taken, lands played)
    # exactly as the headless start_turn flow does — without this, Scavenging
    # Ghoul's end-step trigger fires on deaths from previous turns.
    game.begin_turn_bookkeeping(player_index)
    # Whether a person is asked this turn's untap decisions is read *after*
    # the bookkeeping, because a control over this seat's turn starts there
    # (CR 723.1, Mindslaver): the person controlling an AI seat's turn is
    # asked, and a person an AI controls is not.
    if defer_untap_selection is None:
        defer_untap_selection = _seat_type(session, player_index) == "human"

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
        # Storage Matrix: "each player chooses artifact, creature, or land
        # during their untap step." A decision inside CR 502.3's turn-based
        # action, and the *first* one in this file that is a registered pending
        # choice rather than a session field — so it is asked through the
        # registry and paused on through `_pause_beginning_phase`, which is
        # already the generic "somebody owes something" stop. It comes before
        # the two below because it decides what they can even offer.
        if game.arm_untap_type_choices(player_index):
            game._set_phase_and_step("beginning", "untap")
            if _pause_beginning_phase(session, "untap_type_choice", player_index):
                return False
        return _finish_untap_step(session, player_index)

    _clear_untap_selection(session)
    game.resolve_untap_step(player_index)

    return _resolve_upkeep_step(session, player_index)


def _finish_untap_step(session: Session, player_index: int) -> bool:
    """The untap step's remaining decisions, and the step itself.

    Split out of ``_begin_turn`` so a type choice can be resumed into without
    re-running ``begin_turn_bookkeeping``: the resume enters *here*, at the
    point the choice interrupted, rather than at the top of the turn.
    """
    game = session.game
    options = game.get_untap_land_selection_options(player_index)
    if options:
        game._set_phase_and_step("beginning", "untap")
        session.untap_required_lands = int(options["max_count"])
        session.untap_selected_ids = []
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

    # **The AI's own upkeep is a window it answers** when it holds an ability
    # of a card in its graveyard — the simulator's ``"upkeep"`` window
    # (`engine.ai_priority.instant_speed_window`): most of those print
    # "Activate only during your upkeep", and an upkeep resolved straight
    # through is one no web AI seat ever used. The step stops with the AI's
    # priority open; the next `ai_step` answers it and leaves the step
    # (`game_flow._ai_step`). Asked of any graveyard ability rather than one
    # activatable now: "only during your upkeep" is not yet true of a step
    # that has not begun, and the answer asks CR 602.5 itself.
    #
    # **Before the person's hold, not after it**: the active player receives
    # priority first (CR 117.3a). The hold below passed the AI's priority on
    # unasked, so a person flagging the AI's upkeep cost it its Necrosavant;
    # now the AI answers first and the person's hold follows from that same
    # `ai_step` (`action_turn._action_ai_step`, `game_flow._hold_at_flagged_step`).
    if _seat_type(session, player_index) == "ai" and any(
        True for _ability in graveyard_abilities(game, player_index)
    ):
        game.resolve_upkeep(player_index, defer_priority=True)
        return True

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
    # CR 104.1: a game the upkeep ended (Sulfuric Vortex's 2 damage to a
    # player at 2) has no draw step and no main phase. The engine's stepping
    # refuses both (``engine/game_over_guard.py``); this stops the web half —
    # Island Sanctuary's question — from being asked of an ended game.
    if game.is_game_over():
        return True
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
    # CR 104.1: no next turn after the game has ended — the turn counter and
    # the active seat are this function's own writes, not the engine's.
    if session.game.is_game_over():
        return
    _clear_cleanup_selection(session)
    _clear_untap_selection(session)
    _clear_upkeep_pay_choices(session)
    session.draw_step_life_loss_choices = {}
    session.island_sanctuary_pending = False
    session.game.active_player_index = session.current_turn
    session.game.turn += 1
    session.current_turn = session.game._compute_next_active_player()
    _begin_turn(session, session.current_turn)


def _begin_first_turn(session: Session) -> None:
    """Turn 1's beginning phase, once the pregame is over (CR 103.8: "The
    starting player takes their first turn").

    The same pieces as every later turn — ``_begin_turn``'s untap step, the
    upkeep and the draw step, each able to stop on a decision a person owes —
    without :func:`_start_next_turn`'s ``turn += 1``: ``Game.turn`` is already
    1, which is what the draw step reads for CR 103.8a's skip in a two-player
    game. In a multiplayer game nobody skips it (CR 103.8c), so the starting
    player draws. Idempotent: it runs once per game, when
    ``Session.first_turn_owed`` says the pregame has just ended.

    Until the kg3 round no web game ran this — every one opened in turn 1's
    precombat main phase, so a Free-For-All's starting player kept seven
    cards, and an upkeep trigger on a permanent already on the battlefield
    (a Debug-Menu board set up during the pregame) never fired on turn 1.
    """
    if not session.first_turn_owed or session.pregame_phase is not None:
        return
    if not session.game_started or session.game.is_game_over():
        return
    session.first_turn_owed = False
    # A route may run this before any action has told the engine who is a
    # person; a decision this phase owes a human is asked, not defaulted.
    _mark_interactive_seats(session)
    starting_player = session.current_turn
    _begin_turn(session, starting_player)


def _settle_pregame(session: Session) -> None:
    """Everything a route or a pregame action owes the table once it has
    moved the pregame: the AI seats' declarations (``pregame._pregame_auto_advance``)
    and, if that ended the pregame, turn 1's beginning phase
    (:func:`_begin_first_turn`). The one call every caller makes, so none can
    end a pregame and leave its first turn unbegun."""
    _pregame_auto_advance(session)
    _begin_first_turn(session)


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
    # Each step jumped through is still left the engine's way: a window that
    # stops on a question holds the step (CR 608.2), and the jump waits there
    # for a human's answer rather than carrying the question into the end step.
    if session.game.current_turn_phase in {"precombat_main", "postcombat_main"}:
        if not _leave_step(session, session.game._close_current_priority_step):
            return False
    if session.game.current_turn_phase == "combat":
        if not _leave_step(session, session.game.end_combat):
            return False
    if session.game.current_step != "end":
        session.game.resolve_end_step(session.current_turn)
    if not _leave_step(session, session.game.close_end_step):
        return False
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
