"""``POST /api/sessions/{id}/action`` — one dispatch over ``ActionKind``.

Every game action a client can take arrives at :func:`do_action` and is routed
by the ``ActionKind`` literal in :mod:`web.schemas`. The chain is deliberately
in one place: the shared preamble (seat check, concede, pending-prompt refusal,
priority bookkeeping) and the shared tail (snapshot, AI response, serialize)
apply to *every* action, so splitting the branches across modules would mean
either duplicating that frame or handing each branch a different one.

The route itself is registered in :mod:`web.app`, which stays the one place a
path is declared.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from .prompts import blocking_prompt
from .schemas import GameActionRequest

from .runtime import CARD_BY_NAME, _require_session, _save_snapshot
from .events import _notify_session_change
from .seats import (
    _ai_should_hold,
    _first_opponent_seat,
    _hold_priority_for_human,
    _seat_type,
)
from .pregame import (
    _pregame_auto_advance,
    _pregame_confirm_bottom,
    _pregame_confirm_bottom_simultaneous,
    _pregame_enter_mulligan,
    _pregame_keep_player,
)
from .turn_steps import (
    _advance_after_upkeep_choices,
    _begin_turn,
    _cleanup_discard_requirement,
    _clear_untap_selection,
    _consume_draw_step_life_loss,
    _end_turn,
    _finish_beginning_phase,
    _optional_trigger_pending,
    _resolve_upkeep_step,
    _start_next_turn,
    _untap_land_selection_requirement,
    _upkeep_decisions_pending,
    _upkeep_mana_prevention_pending,
    _upkeep_pay_pending,
)
from .combat_prompts import (
    _ai_assign_combat_damage,
    _ai_declare_attackers,
    _banding_assignment_pending,
    _multiblock_split_pending,
)
from .game_flow import (
    _advance_ai_turn,
    _advance_phase,
    _ai_step,
    _auto_resolve_ai_pending,
    _run_priority_exchange,
)
from .state_view import build_state
from .debug_actions import (
    _DEBUG_ANYTIME_ACTIONS,
    _debug_move_permanent_off_battlefield,
    _debug_target_permanent,
)


def _resolve_permanent_ids(game, req: GameActionRequest) -> GameActionRequest:
    """Turn every ``*_permanent_id`` on the request into the index the rest of
    this module already speaks.

    **One place, at the top of the dispatch.** The alternative — teaching each
    branch to accept either spelling — is thirty places that have to agree about
    precedence and about what a stale id means, which is how the index reads
    spread through the engine in the first place.

    The id wins over any index sent beside it, and a seat sent beside it is
    *replaced* by the seat that actually controls the permanent: an id knows
    which battlefield it is on, so a request cannot name a permanent and the
    wrong player at once.

    An id that no longer resolves is a 404. That is the whole reason the field
    exists: the client wrote this request against the board it last polled, and
    if the permanent has left since, the index beside the id now names whichever
    permanent slid into that slot. Acting on it is the bug; refusing is the fix.
    """
    gone = "that permanent is no longer on the battlefield"
    update: dict = {}

    if req.permanent_id is not None:
        found = game.find_permanent_by_id(req.permanent_id)
        if found is None:
            raise HTTPException(status_code=404, detail=gone)
        seat, permanent = found
        # ``permanent_index`` is overloaded on this protocol: for ``tap`` /
        # ``activate`` it is a slot on the acting seat's own battlefield, and for
        # ``cast`` it is a slot on ``target_seat``. Both are "the slot on
        # whichever battlefield this permanent is on", which is the one thing an
        # id can always answer — so the index is derived from the *controller*,
        # and the seat is filled in when the request did not name one.
        update["permanent_index"] = game.battlefield_index_of(permanent)
        update["permanent_name"] = permanent.card.name
        if req.target_seat is None:
            update["target_seat"] = seat

    if req.target_permanent_id is not None:
        found = game.find_permanent_by_id(req.target_permanent_id)
        if found is None:
            raise HTTPException(status_code=404, detail=gone)
        seat, permanent = found
        update["target_permanent_index"] = game.battlefield_index_of(permanent)
        update["target_seat"] = seat

    if req.target_permanent_ids is not None:
        indices: list[int] = []
        seats = set()
        for permanent_id in req.target_permanent_ids:
            found = game.find_permanent_by_id(permanent_id)
            if found is None:
                raise HTTPException(status_code=404, detail=gone)
            seat, permanent = found
            indices.append(game.battlefield_index_of(permanent))
            seats.add(seat)
        update["target_permanent_indices"] = indices
        if len(seats) == 1:
            # A single-seat list is what ``target_permanent_indices`` means;
            # a spread across seats has to arrive as ``divided_targets``, which
            # carries a seat per entry.
            update["target_seat"] = seats.pop()

    if req.source_permanent_id is not None:
        found = game.find_permanent_by_id(req.source_permanent_id)
        if found is None:
            raise HTTPException(status_code=404, detail="that damage source is no longer on the battlefield")
        seat, permanent = found
        update["source_permanent_index"] = game.battlefield_index_of(permanent)
        update["source_seat"] = seat

    if req.divided_targets:
        resolved = []
        for entry in req.divided_targets:
            if entry.id is None:
                resolved.append(entry)
                continue
            found = game.find_permanent_by_id(entry.id)
            if found is None:
                raise HTTPException(status_code=404, detail=gone)
            seat, permanent = found
            resolved.append(entry.model_copy(update={
                "seat": seat, "index": game.battlefield_index_of(permanent),
            }))
        update["divided_targets"] = resolved

    return req.model_copy(update=update) if update else req


def _default_target(card_name: str, caster_index: int) -> int:
    if card_name in {"Ancestral Recall", "Healing Salve", "Stream of Life"}:
        return caster_index
    return 1 - caster_index


def _queue_spell_from_request(game, seat: int, card_name: str, req, *, x_value):
    """Queue a spell from ``seat``'s hand using every targeting field on the
    request, so the normal ``cast`` action and the debug free-cast paths share
    one code path and can never drift on which parameters they forward (colors
    for text-change spells, the chosen stack target, modal mode, X, multi-target
    lists). Callers prepare ``x_value`` and, for the free casts, inject the card
    into hand and toggle ``enforce_mana_costs`` around this call."""
    engine_stack_index = None
    if req.target_stack_index is not None:
        # The client sends a top-first stack index; the engine stack is bottom-first.
        engine_stack_index = len(game.stack) - 1 - req.target_stack_index
    # Fireball-style multi-target spells send a list; it wins over permanent_index.
    # ``target_permanent_index`` is accepted as the same thing: it is what
    # ``target_permanent_id`` normalizes to, and a cast's target has no reason to
    # be spelled differently from every other action's target.
    permanent_target = (
        req.target_permanent_indices
        if req.target_permanent_indices is not None
        else (req.permanent_index if req.permanent_index is not None else req.target_permanent_index)
    )
    target = req.target_seat if req.target_seat is not None else _default_target(card_name, seat)
    # Cross-seat divided targets (Fireball): (seat, index|None) pairs; an index
    # of None is that player's face.
    divided = (
        [(entry.seat, entry.index) for entry in req.divided_targets]
        if req.divided_targets
        else None
    )
    return game.queue_from_hand(
        seat,
        card_name,
        target_player_index=target,
        target_permanent_index=permanent_target,
        x_value=x_value,
        new_color=req.mana_color,
        target_stack_index=engine_stack_index,
        mode_index=req.mode_index,
        old_color=req.old_color,
        divided_targets=divided,
    )


def _find_card_in_hand(player: PlayerState, card_name: str):
    return next((card for card in player.hand if card.name == card_name), None)


def _find_controlled_permanent(
    player: PlayerState,
    permanent_name: str | None,
    permanent_index: int | None,
) -> tuple[int, Permanent] | None:
    if permanent_index is not None:
        if permanent_index < 0 or permanent_index >= len(player.battlefield):
            return None
        permanent = player.battlefield[permanent_index]
        if permanent_name and permanent.card.name != permanent_name:
            return None
        return permanent_index, permanent

    if permanent_name is None:
        return None

    for idx, permanent in enumerate(player.battlefield):
        if permanent.card.name == permanent_name:
            return idx, permanent
    return None


def do_action(session_id: str, req: GameActionRequest):
    session = _require_session(session_id)
    if session.status == "finished":
        raise HTTPException(status_code=400, detail="game already finished")

    if not session.game_started:
        raise HTTPException(status_code=400, detail="waiting for players to join and start the game")

    if req.seat not in session.joined_seats:
        raise HTTPException(status_code=400, detail="seat has not joined")

    # Stable ids in, battlefield indices out — before any branch reads a target,
    # so every action below sees one spelling. See _resolve_permanent_ids.
    req = _resolve_permanent_ids(session.game, req)

    # Concede (Rule 104.3a) is always available — it bypasses every pending-decision
    # guard below and any pregame gating, since a player can leave at any time.
    if req.action == "concede":
        session.game.concede(req.seat)
        # Setting the seat as lost decides the game in a duel; build_state's
        # settle step flips status to "finished" once a winner exists (and
        # settles the ante with it).
        state = build_state(session, viewer_seat=req.seat)
        _notify_session_change(session.id, "concede")
        return state

    _pregame_actions = {
        "coin_flip_choose",
        "mulligan_take",
        "mulligan_keep",
        "mulligan_bottom_select",
        "mulligan_bottom_confirm",
    }
    if session.pregame_phase is not None and req.action not in _pregame_actions | _DEBUG_ANYTIME_ACTIONS:
        raise HTTPException(status_code=400, detail="pregame not complete")

    if session.pregame_phase is None:
        _save_snapshot(session)

    seat_type = _seat_type(session, req.seat)

    # Keep the engine's set of human-controlled seats current, so forced-sacrifice
    # effects (Lich) dealt to a human during this action defer to an interactive
    # prompt instead of auto-resolving.
    session.game.interactive_seats = {
        s for s in range(len(session.game.players)) if _seat_type(session, s) == "human"
    }

    # Remember the human's phase-rail hold-priority preferences so the AI can stop
    # at them even on steps (turn start, end step) it would otherwise resolve itself.
    if req.stop_steps is not None:
        session.opponent_stop_steps = set(req.stop_steps)
    if req.self_stop_steps is not None:
        session.self_stop_steps = set(req.self_stop_steps)

    cleanup_required = _cleanup_discard_requirement(session)
    untap_required = _untap_land_selection_requirement(session)
    if (
        cleanup_required > 0
        and req.action == "cast"
        and req.seat == session.current_turn
        and session.game.current_phase == "cleanup"
        and req.card_name
    ):
        active_hand = session.game.players[session.current_turn].hand
        selected = set(session.cleanup_selected_indices)
        matching_indices = [idx for idx, card in enumerate(active_hand) if card.name == req.card_name]
        preferred_index = next((idx for idx in matching_indices if idx not in selected), None)
        if preferred_index is None and matching_indices:
            preferred_index = matching_indices[0]
        if preferred_index is not None:
            req = req.model_copy(update={"action": "cleanup_select", "hand_index": preferred_index})

    if cleanup_required > 0 and req.action not in {"cleanup_select"} | _DEBUG_ANYTIME_ACTIONS:
        raise HTTPException(status_code=400, detail="select cleanup discards before other actions")

    if untap_required > 0 and req.action not in {"untap_select", "untap_confirm"} | _DEBUG_ANYTIME_ACTIONS:
        raise HTTPException(status_code=400, detail="select untap lands before other actions")

    if session.optional_untap_pending and req.action not in {"optional_untap_confirm"} | _DEBUG_ANYTIME_ACTIONS:
        raise HTTPException(status_code=400, detail="choose which permanents stay tapped before other actions")

    _UPKEEP_DECISION_ACTIONS = {"pay_upkeep", "sacrifice_upkeep", "resolve_optional_trigger", "pay_upkeep_prevention", "tap", "activate"} | _DEBUG_ANYTIME_ACTIONS
    if _upkeep_pay_pending(session) and req.action not in _UPKEEP_DECISION_ACTIONS:
        raise HTTPException(status_code=400, detail="resolve upkeep payment before other actions")

    if _optional_trigger_pending(session) and req.action not in _UPKEEP_DECISION_ACTIONS:
        raise HTTPException(status_code=400, detail="resolve optional trigger before other actions")

    if _upkeep_mana_prevention_pending(session) and req.action not in _UPKEEP_DECISION_ACTIONS:
        raise HTTPException(status_code=400, detail="resolve upkeep prevention before other actions")

    if session.island_sanctuary_pending and req.action not in {"island_sanctuary_skip", "island_sanctuary_draw"} | _DEBUG_ANYTIME_ACTIONS:
        raise HTTPException(status_code=400, detail="choose Island Sanctuary draw option before other actions")

    _auto_resolve_ai_pending(session)
    # A prompt the acting seat owes refuses every action but the one that
    # answers it. Driven by the registry, so a new prompt cannot ship able to be
    # played around — the failure the eighteen hand-written checks this replaces
    # had no protection against.
    blocking = blocking_prompt(session.game, req.seat, req.action, frozenset(_DEBUG_ANYTIME_ACTIONS))
    if blocking is not None:
        raise HTTPException(status_code=400, detail=blocking[0].blocked_detail)

    if req.action in {
        "cast",
        "activate",
        "pass_priority",
        "end_turn",
        "next_phase",
        "declare_attackers",
        "declare_blockers",
        "assign_combat_damage",
        "assign_banding_damage",
        "assign_multiblock_damage",
        "untap_select",
        "untap_confirm",
    } and seat_type != "human":
        raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")

    if req.action == "cast":
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")

        caster = session.game.players[req.seat]
        card = _find_card_in_hand(caster, req.card_name)
        if card is None:
            raise HTTPException(status_code=400, detail="card not in hand")

        # CR 702.8b: a card with flash casts any time an instant could be cast,
        # so the two sorcery-speed gates below ask instant-or-flash, not the
        # type line alone. A land is never cast and keeps sorcery timing.
        instant_speed = card.primary_type == "instant" or card.has_flash
        if req.seat != session.current_turn and not instant_speed:
            raise HTTPException(status_code=400, detail="non-instant spells can only be cast on your turn")

        if card.primary_type in {"land", "sorcery", "creature", "artifact", "enchantment"} and not instant_speed:
            if req.seat != session.current_turn:
                raise HTTPException(status_code=400, detail="can only cast this card on your turn")
            if session.game.current_phase != "main":
                raise HTTPException(status_code=400, detail="can only cast this card during main phase")
            if session.game.stack:
                raise HTTPException(status_code=400, detail="can only cast this card when stack is empty")

        result = _queue_spell_from_request(
            session.game, req.seat, req.card_name, req, x_value=req.x_value,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)

    elif req.action == "tap":
        if req.permanent_name is None and req.permanent_index is None:
            raise HTTPException(status_code=400, detail="permanent_name or permanent_index is required")
        controller = session.game.players[req.seat]
        resolved = _find_controlled_permanent(controller, req.permanent_name, req.permanent_index)
        if resolved is None:
            raise HTTPException(status_code=400, detail="permanent not found")
        permanent_index, permanent = resolved

        if permanent.card.primary_type == "land":
            tapped = session.game.tap_land_for_mana(
                req.seat,
                permanent.card.name,
                chosen_color=req.mana_color or "G",
                permanent_index=permanent_index,
                defer_kudzu_choice=_seat_type(session, req.seat) != "ai",
            )
        else:
            tapped = session.game.tap_permanent(
                req.seat,
                permanent.card.name,
                permanent_index=permanent_index,
            )
        if not tapped:
            raise HTTPException(status_code=400, detail="failed to tap permanent")

    elif req.action == "activate":
        if req.permanent_name is None and req.permanent_index is None:
            raise HTTPException(status_code=400, detail="permanent_name or permanent_index is required")
        controller = session.game.players[req.seat]
        resolved = _find_controlled_permanent(controller, req.permanent_name, req.permanent_index)
        # Ifh-Bíff Efreet: "Any player may activate this ability." — the
        # permanent may sit on another player's battlefield; the activator
        # still pays the cost and controls the ability.
        source_controller_seat = None
        if resolved is None:
            for other_seat, other in enumerate(session.game.players):
                if other_seat == req.seat:
                    continue
                candidate = _find_controlled_permanent(other, req.permanent_name, req.permanent_index)
                if candidate is not None and (
                    "any player may activate this ability"
                    in candidate[1].card.oracle_text.lower()
                ):
                    resolved = candidate
                    source_controller_seat = other_seat
                    break
        if resolved is None:
            raise HTTPException(status_code=400, detail="permanent not found")
        permanent_index, permanent = resolved

        # A land activation is a mana tap ONLY when the chosen ability is a mana
        # ability. Non-mana land abilities (Island of Wak-Wak's power-set,
        # Library of Alexandria's draw) go through the normal ability path —
        # previously every land activation fell into tap_land_for_mana, which
        # invented a green mana for mana-less lands and made Library's draw
        # unreachable.
        land_as_mana_tap = permanent.card.primary_type == "land"
        if land_as_mana_tap:
            usable = usable_activated_abilities(compile_card_oracle(permanent.effective_card))
            mana_kinds = {"add_mana_from_text", "sacrifice_self_for_mana", "sacrifice_creature_for_mana"}
            chosen_ability = None
            if req.ability_index is not None and 0 <= req.ability_index < len(usable):
                chosen_ability = usable[req.ability_index]
            elif usable and not permanent.effective_produced_mana:
                # No explicit choice on a land that makes no mana: its only
                # meaningful activation is the non-mana ability.
                chosen_ability = usable[0]
            if chosen_ability is not None and chosen_ability.instruction.kind not in mana_kinds:
                land_as_mana_tap = False

        if land_as_mana_tap:
            tapped = session.game.tap_land_for_mana(
                req.seat,
                permanent.card.name,
                chosen_color=req.mana_color or "G",
                permanent_index=permanent_index,
                defer_kudzu_choice=_seat_type(session, req.seat) != "ai",
            )
            if not tapped:
                raise HTTPException(status_code=400, detail="failed to tap land for mana")
        else:
            if not session.game.has_priority(req.seat):
                raise HTTPException(status_code=400, detail="you do not currently have priority")
            if req.target_seat is not None:
                target = req.target_seat
            elif len(session.game.players) == 2:
                target = 1 - req.seat
            else:
                raise HTTPException(status_code=400, detail="target_seat is required in a 3+ player game")
            # The client sends a top-first stack index; convert to the engine's
            # bottom-first indexing (Deathgrip: "Counter target green spell").
            engine_stack_index = None
            if req.target_stack_index is not None:
                engine_stack_index = len(session.game.stack) - 1 - req.target_stack_index
            # "A source of your choice" (Jade Monolith): a chosen stack spell's
            # index arrives top-first; convert like target_stack_index.
            engine_source_stack_index = None
            if req.source_stack_index is not None:
                engine_source_stack_index = len(session.game.stack) - 1 - req.source_stack_index
            result = session.game.queue_permanent_ability(
                req.seat,
                permanent.card.name,
                target_player_index=target,
                permanent_index=permanent_index,
                mana_color=req.mana_color,
                target_permanent_index=req.target_permanent_index,
                target_stack_index=engine_stack_index,
                ability_index=req.ability_index,
                x_value=req.x_value,
                source_seat=req.source_seat,
                source_permanent_index=req.source_permanent_index,
                source_stack_index=engine_source_stack_index,
                source_controller_index=source_controller_seat,
            )
            if not result.supported:
                raise HTTPException(status_code=400, detail=result.details)
            session.game.note_priority_action_taken(req.seat)

    elif req.action == "activate_emblem":
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        result = session.game.activate_prevent_one_emblem(
            req.seat,
            emblem_index=req.emblem_index if req.emblem_index is not None else 0,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)

    elif req.action == "channel_mana":
        # Channel emblem: "any time you could activate a mana ability, you may pay 1
        # life. If you do, add {C}." Pay `x_value` life (default 1) for that many {C}.
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        amount = req.x_value if req.x_value is not None else 1
        result = session.game.use_channel_mana(req.seat, amount)
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)

    elif req.action == "pass_priority":
        try:
            _run_priority_exchange(session, req.seat)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    elif req.action == "end_turn":
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

    elif req.action == "next_phase":
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

    elif req.action == "declare_attackers":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        # Declaring attackers is the active player's turn-based action (CR 508.1),
        # taken before any player has priority — so no spells may be cast during
        # the assignment and a priority window is *not* required here. The engine
        # grants the active player priority once attackers are declared (CR 508.4).
        ok, details = session.game.declare_attackers(
            req.seat,
            req.attacker_indices or [],
            defending_player_index=req.target_seat,
            bands=req.bands,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "declare_blockers":
        # CR 802.4: with attack-multiple-players (FFA), 2+ defending players may
        # each declare blocks in the same combat — any of them may act here, not
        # just a single pre-picked defender. With zero attackers this turn nobody
        # is formally "a defending player" yet, but any non-active seat may still
        # submit a trivial no-op declaration (mirrors the engine's own check).
        defending_players = session.game.combat_defending_players()
        if defending_players:
            if req.seat not in defending_players:
                raise HTTPException(status_code=400, detail="only a defending player may declare blockers")
        elif req.seat == session.game.active_player_index or not (0 <= req.seat < len(session.game.players)):
            raise HTTPException(status_code=400, detail="only a defending player may declare blockers")
        # Declaring blockers is the defending player's turn-based action (CR 509.1),
        # not a priority action: no spells may be cast during the assignment, and the
        # defender declares even while no priority window is open. The engine grants
        # the active player priority once blockers are declared (CR 509.4), so the
        # AI's turn can resume / the attacker may respond.
        raw_pairs = req.blocker_pairs or {}
        # A value may be a single attacker index or a list (one creature blocking
        # several attackers — Two-Headed Giant of Foriys). Normalize to lists.
        blocker_pairs = {
            int(k): [int(a) for a in (v if isinstance(v, list) else [v])]
            for k, v in raw_pairs.items()
        }
        ok, details = session.game.declare_blockers(req.seat, blocker_pairs)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "assign_combat_damage":
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        # CR 702.22j: the defender pre-commits banding-blocked attackers' damage
        # before the active player resolves; block resolution until they have.
        if _banding_assignment_pending(session):
            raise HTTPException(
                status_code=400,
                detail="waiting for the defending player to assign banding combat damage",
            )
        # CR 510.1d: likewise a defender's multi-block division (Two-Headed Giant
        # of Foriys) is pre-committed before combat damage resolves.
        if _multiblock_split_pending(session):
            raise HTTPException(
                status_code=400,
                detail="waiting for the defending player to divide blocker combat damage",
            )
        # Distinguish "no assignment given" (None -> engine default/auto) from an
        # explicit empty assignment ({} -> deal nothing). This lets a caller supply
        # only blocker_damage (banding, CR 702.22k) and have attackers deal normally.
        if req.attacker_damage is None:
            attacker_damage = None
        else:
            attacker_damage = {
                int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
                for attacker_idx, blockers in req.attacker_damage.items()
            }
        blocker_damage = (
            {int(b): int(a) for b, a in req.blocker_damage.items()}
            if req.blocker_damage
            else None
        )
        blocker_damage_split = (
            {
                int(b): {int(m): int(v) for m, v in split.items()}
                for b, split in req.blocker_damage_split.items()
            }
            if req.blocker_damage_split
            else None
        )
        ok, details = session.game.resolve_combat_damage(
            req.seat,
            attacker_damage=attacker_damage,
            blocker_damage=blocker_damage,
            blocker_damage_split=blocker_damage_split,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        session.game.note_priority_action_taken(req.seat)

    elif req.action == "assign_banding_damage":
        # CR 702.22j: the defending player pre-commits how attackers blocked by a
        # creature with banding split their combat damage.
        banding_raw = req.banding_damage or {}
        banding_damage = {
            int(attacker_idx): {int(blocker_idx): int(value) for blocker_idx, value in blockers.items()}
            for attacker_idx, blockers in banding_raw.items()
        }
        ok, details = session.game.assign_banding_combat_damage(req.seat, banding_damage)
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        # The defender has pre-committed their CR 702.22j split. If the attacker is
        # the AI, it was paused waiting for this — resolve its combat damage now.
        if (
            not _banding_assignment_pending(session)
            and _seat_type(session, session.game.active_player_index) == "ai"
        ):
            _ai_assign_combat_damage(session)

    elif req.action == "assign_multiblock_damage":
        # CR 510.1d: the defending player pre-commits how each of their creatures
        # blocking multiple attackers (Two-Headed Giant of Foriys) divides its
        # combat damage among them.
        split_raw = req.blocker_damage_split or {}
        blocker_split = {
            int(b): {int(a): int(v) for a, v in split.items()}
            for b, split in split_raw.items()
        }
        ok, details = session.game.assign_multiblock_blocker_damage(req.seat, blocker_split)
        if not ok:
            raise HTTPException(status_code=400, detail=details)
        # If the attacker is the AI, it was paused waiting for this division —
        # resolve its combat damage now.
        if (
            not _multiblock_split_pending(session)
            and not _banding_assignment_pending(session)
            and _seat_type(session, session.game.active_player_index) == "ai"
        ):
            _ai_assign_combat_damage(session)

    elif req.action == "cleanup_select":
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

    elif req.action == "untap_select":
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

    elif req.action == "untap_confirm":
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

    elif req.action == "optional_untap_confirm":
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

    elif req.action == "pay_upkeep":
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

    elif req.action == "sacrifice_upkeep":
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

    elif req.action == "resolve_optional_trigger":
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

    elif req.action == "pay_upkeep_prevention":
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

    elif req.action in {"island_sanctuary_skip", "island_sanctuary_draw"}:
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

    elif req.action == "search_library_confirm":
        pending = session.game.pending_search_library
        if pending is None:
            raise HTTPException(status_code=400, detail="no library search pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your library search")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index (library card index) is required")
        # Which zone the index addresses. The engine checks it against the zones
        # the search was armed with, so naming the graveyard on a library-only
        # search is a rejected answer rather than a widened effect.
        zone = req.search_zone or "library"
        if zone not in {"library", "graveyard"}:
            raise HTTPException(status_code=400, detail="unknown search zone")
        ok = session.game.confirm_search_library(req.seat, req.hand_index, zone)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid library card index")

    elif req.action == "search_library_decline":
        pending = session.game.pending_search_library
        if pending is None:
            raise HTTPException(status_code=400, detail="no library search pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your library search")
        # Failing to find is legal (CR 701.19b) and is the only answer available
        # when nothing in the searched zones matches the restriction.
        session.game.decline_search_library(req.seat)

    elif req.action == "reorder_library_confirm":
        pending = session.game.pending_reorder_library
        if pending is None:
            raise HTTPException(status_code=400, detail="no library reorder pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your library reorder")
        if req.card_order is None:
            raise HTTPException(status_code=400, detail="card_order is required")
        ok = session.game.confirm_reorder_library(req.seat, req.card_order, shuffle=bool(req.shuffle))
        if not ok:
            raise HTTPException(status_code=400, detail="invalid card order")

    elif req.action == "scry_confirm":
        pending = session.game.pending_scry
        if pending is None:
            raise HTTPException(status_code=400, detail="no scry pending")
        if req.seat != pending["caster_index"]:
            raise HTTPException(status_code=400, detail="not your scry")
        if req.card_order is None or req.bottom_count is None:
            raise HTTPException(status_code=400, detail="card_order and bottom_count are required")
        ok = session.game.confirm_scry(req.seat, req.card_order, req.bottom_count)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid scry arrangement")

    elif req.action == "discard_confirm":
        pending = session.game.pending_discard
        if pending is None:
            raise HTTPException(status_code=400, detail="no discard pending")
        if req.seat != pending["player_index"]:
            raise HTTPException(status_code=400, detail="not your discard")
        if not req.discard_indices:
            raise HTTPException(status_code=400, detail="discard_indices is required")
        ok = session.game.confirm_discard(
            req.seat, list(req.discard_indices), to_library=bool(req.to_library)
        )
        if not ok:
            raise HTTPException(status_code=400, detail="invalid discard selection")

    elif req.action == "leng_discard_confirm":
        # Library of Leng: choose where an already-discarded card goes — top of
        # library (the optional replacement) or graveyard.
        if not any(
            e["player_index"] == req.seat for e in session.game.pending_leng_discards
        ):
            raise HTTPException(status_code=400, detail="no Library of Leng choice pending for you")
        ok = session.game.confirm_leng_discard(req.seat, to_library=bool(req.to_library))
        if not ok:
            raise HTTPException(status_code=400, detail="invalid Library of Leng choice")

    elif req.action == "resolve_optional_pay":
        # Color rods (Wooden Sphere, …): "you may pay {1}. If you do, gain life."
        if not any(
            e["player_index"] == req.seat for e in session.game.pending_optional_pays
        ):
            raise HTTPException(status_code=400, detail="no optional pay pending for you")
        if req.accept is None:
            raise HTTPException(status_code=400, detail="accept (true/false) is required")
        session.game.confirm_optional_pay(req.seat, card_name=req.card_name, accept=bool(req.accept))

    elif req.action == "land_type_confirm":
        # Phantasmal Terrain: the controller picks the enchanted land's basic type.
        if not req.land_type:
            raise HTTPException(status_code=400, detail="land_type is required")
        ok = session.game.confirm_land_type(req.seat, req.land_type)
        if not ok:
            raise HTTPException(status_code=400, detail="no land-type choice pending for you")

    elif req.action == "confirm_mana_payment":
        # Power Sink: the targeted spell's controller pays {X} to keep their spell,
        # or declines and it is countered. They tap lands to fill their pool first.
        if req.accept is None:
            raise HTTPException(status_code=400, detail="accept (true/false) is required")
        ok = session.game.confirm_mana_payment(req.seat, bool(req.accept))
        if not ok:
            raise HTTPException(status_code=400, detail="no mana payment pending for you")

    elif req.action == "kudzu_reattach_confirm":
        # Kudzu: the controller picks which land to re-enchant (battlefield index).
        if req.target_permanent_index is None:
            raise HTTPException(status_code=400, detail="target_permanent_index is required")
        ok = session.game.confirm_kudzu_reattach(req.seat, req.target_permanent_index)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid Kudzu reattach selection")

    elif req.action == "face_down_cast_confirm":
        # Illusionary Mask: the controller picks a hand creature to cast face down,
        # or declines (accept=False / no hand_index).
        if req.accept is False:
            hand_index = -1
        elif req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")
        else:
            hand_index = req.hand_index
        ok = session.game.confirm_face_down_cast(req.seat, hand_index)
        if not ok:
            raise HTTPException(status_code=400, detail="invalid face-down cast selection")

    elif req.action == "time_vault_skip":
        # Time Vault: skip the turn you are beginning to untap the artifact.
        if req.seat != session.current_turn or not session.time_vault_pending:
            raise HTTPException(status_code=400, detail="no Time Vault skip is pending for you")
        name = req.card_name or (session.time_vault_pending[0] if session.time_vault_pending else None)
        if not name or not session.game.untap_for_skip(req.seat, name):
            raise HTTPException(status_code=400, detail="cannot skip to untap that permanent")
        session.time_vault_resolved_turn = session.game.turn
        session.time_vault_pending = []
        _start_next_turn(session)  # the skipped player's turn does not run

    elif req.action == "time_vault_decline":
        # Decline the skip and take the turn normally.
        if req.seat != session.current_turn:
            raise HTTPException(status_code=400, detail="not your turn")
        session.time_vault_resolved_turn = session.game.turn
        session.time_vault_pending = []
        _begin_turn(session, req.seat, defer_untap_selection=True)

    elif req.action == "lamp_draw_confirm":
        # Aladdin's Lamp: the player picks which of the revealed top cards to
        # draw (hand_index = position in the revealed list).
        pending = session.game.pending_lamp_draw
        if pending is None or pending.get("player_index") != req.seat:
            raise HTTPException(status_code=400, detail="no Aladdin's Lamp draw is pending for you")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")
        if not session.game.confirm_lamp_draw(req.seat, req.hand_index):
            raise HTTPException(status_code=400, detail="invalid card choice")

    elif req.action == "outside_game_draw_confirm":
        # Ring of Ma'rûf: the player picks which card they own from outside the
        # game to put into their hand (hand_index = position in the sideboard).
        pending = session.game.pending_outside_game_draw
        if pending is None or pending.get("player_index") != req.seat:
            raise HTTPException(status_code=400, detail="no outside-the-game choice is pending for you")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")
        if not session.game.confirm_outside_game_draw(req.seat, req.hand_index):
            raise HTTPException(status_code=400, detail="invalid card choice")

    elif req.action == "opponent_damage_choose":
        # Cuombajj Witches: the opposing chooser picks any target for the second
        # damage packet — a player face (target_permanent_index omitted) or a
        # creature on target_seat's battlefield.
        pending = session.game.pending_opponent_damage
        if pending is None or pending.get("chooser_index") != req.seat:
            raise HTTPException(status_code=400, detail="no opponent damage choice is pending for you")
        if req.target_seat is None or not (0 <= req.target_seat < len(session.game.players)):
            raise HTTPException(status_code=400, detail="target_seat is required")
        if not session.game.confirm_opponent_damage_choice(
            req.seat, req.target_seat, req.target_permanent_index
        ):
            raise HTTPException(status_code=400, detail="failed to resolve the damage choice")

    elif req.action == "enter_choice_confirm":
        # Black Vise / Jihad: the controller confirms the "as this enters"
        # choice — an opponent (target_seat) and, for Jihad, a color (mana_color).
        pending = session.game.pending_enter_choice
        if pending is None or pending.get("controller_index") != req.seat:
            raise HTTPException(status_code=400, detail="no enter choice is pending for you")
        if req.target_seat is None:
            raise HTTPException(status_code=400, detail="target_seat is required")
        if not session.game.confirm_enter_choice(req.seat, req.target_seat, req.mana_color):
            raise HTTPException(status_code=400, detail="invalid enter choice")

    elif req.action == "body_choice_confirm":
        # Primal Clay: the controller picks which printed body the creature
        # entered as (hand_index = position in the offered options).
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index (body option index) is required")
        if not session.game.confirm_enter_body_choice(req.seat, req.hand_index):
            raise HTTPException(status_code=400, detail="no body choice is pending for you")

    elif req.action == "least_power_choice_confirm":
        # Drop of Honey: the controller picks which of the creatures tied for
        # least power is destroyed (target_seat + target_permanent_index).
        pending = session.game.pending_least_power_choice
        if pending is None or pending.get("controller_index") != req.seat:
            raise HTTPException(status_code=400, detail="no least-power choice is pending for you")
        if req.target_seat is None or req.target_permanent_index is None:
            raise HTTPException(status_code=400, detail="target_seat and target_permanent_index are required")
        if not session.game.confirm_least_power_choice(
            req.seat, req.target_seat, req.target_permanent_index
        ):
            raise HTTPException(status_code=400, detail="invalid creature choice")

    elif req.action == "word_of_command_confirm":
        # Word of Command: the caster records the card the target must play
        # (accept=False / no hand_index declines). The spell stays on the stack
        # and finishes resolving when priority is next released.
        if req.accept is False:
            hand_index = -1
        elif req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")
        else:
            hand_index = req.hand_index
        ok = session.game.confirm_word_of_command(req.seat, hand_index, defer_resolution=True)
        if not ok:
            raise HTTPException(status_code=400, detail="no Word of Command pending for you")

    elif req.action == "assign_defender_piles":
        piles = {int(k): str(v) for k, v in (req.piles or {}).items()}
        ok, details = session.game.assign_defender_piles(req.seat, piles)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "assign_attacker_piles":
        piles = {int(k): str(v) for k, v in (req.piles or {}).items()}
        ok, details = session.game.assign_attacker_piles(req.seat, piles)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "assign_camouflage_piles":
        # Camouflage: the defending player's chosen division of their creatures
        # into piles (0-based pile numbers, one pile per attacker). Piles are then
        # matched to attackers at random by the engine.
        camo_piles: dict[int, int | list[int]] = {
            int(k): ([int(p) for p in v] if isinstance(v, list) else int(v))
            for k, v in (req.camouflage_piles or {}).items()
        }
        ok, details = session.game.assign_camouflage_piles(req.seat, camo_piles)
        if not ok:
            raise HTTPException(status_code=400, detail=details)

    elif req.action == "balance_confirm":
        pending = session.game.pending_balance
        if pending is None or req.seat not in pending["plans"]:
            raise HTTPException(status_code=400, detail="no balance choice pending for you")
        ok = session.game.confirm_balance(
            req.seat,
            land_indices=req.land_indices or [],
            creature_indices=req.creature_indices or [],
            hand_indices=req.discard_indices or [],
        )
        if not ok:
            raise HTTPException(status_code=400, detail="invalid balance selection (wrong number of cards)")

    elif req.action == "sacrifice_confirm":
        pending = session.game.pending_sacrifice
        if pending is None or req.seat != pending["player_index"]:
            raise HTTPException(status_code=400, detail="no sacrifice pending for you")
        ok = session.game.confirm_sacrifice(req.seat, list(req.sacrifice_indices or []))
        if not ok:
            raise HTTPException(status_code=400, detail="invalid sacrifice selection")
        # Lord of the Pit: if this sacrifice paused the beginning phase, resume it
        # (draw step + main phase) now that the choice is made.
        if session.pending_post_sacrifice is not None and session.game.pending_sacrifice is None:
            marker, pidx = session.pending_post_sacrifice
            session.pending_post_sacrifice = None
            if marker == "begin_turn":
                _finish_beginning_phase(session, pidx)

    elif req.action == "effect_order_confirm":
        # CR 616.1e: the affected player picks which of the effects contending
        # over one event applies first. Answering re-runs the event, so this
        # returns with the draw made or the damage dealt.
        if not session.game.resolve_pending_choice(
            "effect_order", req.seat, option_index=int(req.option_index or 0)
        ):
            raise HTTPException(status_code=400, detail="no effect order pending for you")

    elif req.action == "dismiss_hand_reveal":
        session.game.dismiss_hand_reveal(req.seat)

    elif req.action == "ai_step":
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

    elif req.action == "debug_add_to_hand":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        player = session.game.players[req.seat]
        player.hand.append(card)
        session.game.log.append(f"[Debug] {player.name} added {card.name} to hand.")

    elif req.action == "debug_add_to_sideboard":
        # Cards owned from outside the game (CR 100.4). Only a deck with an
        # explicit sideboard starts with any, so this is the only way to give a
        # random-deck game something for Ring of Ma'rûf's replaced draw to find.
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        player = session.game.players[req.seat]
        player.sideboard.append(card)
        session.game.log.append(
            f"[Debug] {player.name} added {card.name} to their cards outside the game."
        )

    elif req.action == "debug_cast_free":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")

        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        player = session.game.players[req.seat]
        player.hand.append(card)
        x_value = req.x_value if req.x_value is not None else (0 if "{X}" in (card.mana_cost or "") else None)

        # Cast through the shared cast plumbing (same targeting/colors/mode as a
        # real hand cast); the only difference is mana isn't enforced for a free cast.
        original_enforce_mana_costs = session.game.enforce_mana_costs
        try:
            session.game.enforce_mana_costs = False
            result = _queue_spell_from_request(session.game, req.seat, card.name, req, x_value=x_value)
        finally:
            session.game.enforce_mana_costs = original_enforce_mana_costs

        if not result.supported:
            # Roll back the injected card if the cast did not complete.
            for idx in range(len(player.hand) - 1, -1, -1):
                if player.hand[idx].name == card.name:
                    del player.hand[idx]
                    break
            raise HTTPException(status_code=400, detail=result.details)

        session.game.note_priority_action_taken(req.seat)
        session.game.log.append(f"[Debug] {player.name} cast {card.name} for free.")

    elif req.action == "debug_cast_free_opponent":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        if not req.card_name:
            raise HTTPException(status_code=400, detail="card_name is required")

        # The caster is an opposing seat, NOT req.target_seat — that field carries
        # the spell's *target* (frequently the acting human's own seat, e.g. for a
        # burn spell aimed back at them), so deriving the caster from it would cast
        # the card as the wrong player. An explicit caster_seat overrides (lets FFA
        # pick which opponent); otherwise fall back to the first living opponent.
        if req.caster_seat is not None:
            opponent_seat = req.caster_seat
        else:
            opponent_seat = _first_opponent_seat(session.game, req.seat)
        if opponent_seat is None or not (0 <= opponent_seat < len(session.game.players)):
            raise HTTPException(status_code=400, detail="no opposing seat to cast for")
        card = CARD_BY_NAME.get(req.card_name.strip().casefold())
        if card is None:
            raise HTTPException(status_code=404, detail="card not found")

        opponent = session.game.players[opponent_seat]
        opponent.hand.append(card)
        x_value = req.x_value if req.x_value is not None else (0 if "{X}" in (card.mana_cost or "") else None)

        # Debug exception: casting for the opponent is allowed even on your own turn,
        # when priority belongs to you. Hand the opponent a priority window so the cast
        # is accepted and the resulting game state (caster holds priority) is correct.
        saved_priority_player_index = session.game.priority_player_index
        session.game.start_priority_window(opponent_seat)

        original_enforce_mana_costs = session.game.enforce_mana_costs
        try:
            session.game.enforce_mana_costs = False
            result = _queue_spell_from_request(session.game, opponent_seat, card.name, req, x_value=x_value)
        finally:
            session.game.enforce_mana_costs = original_enforce_mana_costs

        if not result.supported:
            # Roll back the injected card and priority window if the cast did not complete.
            session.game.priority_player_index = saved_priority_player_index
            for idx in range(len(opponent.hand) - 1, -1, -1):
                if opponent.hand[idx].name == card.name:
                    del opponent.hand[idx]
                    break
            raise HTTPException(status_code=400, detail=result.details)

        # The spell is now on the stack under a temporary priority window we handed
        # the opponent so the cast would be accepted. Hand priority back to the acting
        # (human) player: it's their turn, so the AI opponent would never get a turn to
        # pass and the spell would strand on the stack. With priority restored the human
        # resolves it by passing, exactly like a spell they cast themselves.
        session.game.start_priority_window(req.seat)
        session.game.log.append(f"[Debug] {opponent.name} cast {card.name} for free.")

    elif req.action == "debug_add_mana":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        color = (req.mana_color or "").strip().upper()
        if color not in {"W", "U", "B", "R", "G", "C"}:
            raise HTTPException(status_code=400, detail="invalid mana color")

        # target_seat selects whose pool to add to; default to the acting seat.
        target = req.target_seat if req.target_seat is not None else req.seat
        player = session.game.players[target]
        player.mana_pool[color] += 1
        session.game.log.append(f"[Debug] Added {{{color}}} to {player.name}'s mana pool.")

    elif req.action == "debug_force_ai_attack_all":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        session.force_ai_attack_all = bool(req.force_attack_all)
        state = "ON" if session.force_ai_attack_all else "OFF"
        session.game.log.append(f"[Debug] Force AI to attack with all creatures: {state}.")

    elif req.action == "debug_clear_summoning_sickness":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        _, permanent = _debug_target_permanent(session, req)
        if not session.game._is_creature(permanent):
            raise HTTPException(status_code=400, detail="only a creature can have summoning sickness")
        # Drop the marker entirely rather than back-dating it: _advance_summoning_sickness
        # re-stamps a marker that still matches the current turn, so a stale value
        # would come back as sickness on the next opponent's untap step.
        permanent.metadata.pop("summoning_sickness_turn", None)
        session.game.log.append(f"[Debug] {permanent.card.name} loses summoning sickness.")

    elif req.action in {"debug_tap_permanent", "debug_untap_permanent"}:
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        controller_seat, permanent = _debug_target_permanent(session, req)
        make_tapped = req.action == "debug_tap_permanent"
        # Same write path Twiddle uses: a raw state flip that also turns a
        # face-down creature (Illusionary Mask) face up when it becomes tapped.
        # City of Brass's "whenever this land becomes tapped" deliberately does
        # not fire — the engine scopes that trigger to the tap-for-mana path.
        session.game._tap_or_untap_target(
            session.game.players[controller_seat], make_tapped, req.target_permanent_index
        )
        session.game.log.append(
            f"[Debug] {permanent.card.name} {'tapped' if make_tapped else 'untapped'}."
        )

    elif req.action in {"debug_return_to_hand", "debug_exile_permanent"}:
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        controller_seat, permanent = _debug_target_permanent(session, req)
        zone = "hand" if req.action == "debug_return_to_hand" else "exile"
        name = permanent.card.name
        _debug_move_permanent_off_battlefield(
            session.game, controller_seat, req.target_permanent_index, zone
        )
        session.game.check_state_based_actions()
        moved = "returned to its owner's hand" if zone == "hand" else "exiled"
        session.game.log.append(f"[Debug] {name} {moved}.")

    elif req.action == "debug_destroy_permanent":
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue debug action for AI seat")
        controller_seat, permanent = _debug_target_permanent(session, req)
        controller = session.game.players[controller_seat]
        name = permanent.card.name
        # A debug destroy is unconditional — regeneration shields, indestructibility
        # and destruction-replacement shields are all skipped so the tester can
        # always clear the board. It still routes through _permanent_to_graveyard,
        # so dies-triggers and Aura cleanup fire exactly as in a real destruction.
        session.game.remove_from_battlefield(permanent)
        session.game._permanent_to_graveyard(controller, permanent)
        session.game._trigger_aura_death_effects(permanent, controller)
        if permanent.card.primary_type == "land":
            session.game._process_land_dies(controller_seat)
        session.game._recompute_continuous_effects()
        session.game.check_state_based_actions()
        session.game.log.append(f"[Debug] {name} destroyed.")

    elif req.action == "coin_flip_choose":
        if session.pregame_phase != "coin_flip":
            raise HTTPException(status_code=400, detail="not in coin flip phase")
        if req.seat != session.coin_flip_winner:
            raise HTTPException(status_code=400, detail="only the coin flip winner can choose")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        choice = req.hand_index  # 0 = go first, 1 = go second
        if choice not in (0, 1):
            raise HTTPException(status_code=400, detail="hand_index must be 0 (go first) or 1 (go second)")
        if choice == 1 and len(session.game.players) != 2:
            # "Go second" only maps unambiguously to "the other player" in a
            # 2-player game; FFA doesn't offer this choice (not in MVP scope).
            raise HTTPException(status_code=400, detail="go second is only available in a 2-player game")
        starting_player = req.seat if choice == 0 else (1 - req.seat)
        session.game.log.append(
            f"{session.game.players[req.seat].name} chooses to go {'first' if choice == 0 else 'second'}"
        )
        _pregame_enter_mulligan(session, starting_player)
        _pregame_auto_advance(session)

    elif req.action == "mulligan_take":
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in mulligan phase")
        if session.simultaneous_mulligan:
            if req.seat in session.mulligan_kept_seats:
                raise HTTPException(status_code=400, detail="you already kept your hand")
        elif req.seat != session.mulligan_offer_seat:
            raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        if not session.game.pregame_mulligan_draw(req.seat):
            raise HTTPException(status_code=400, detail="cannot take another mulligan (7 mulligans taken)")

    elif req.action == "mulligan_keep":
        if session.pregame_phase != "mulligan":
            raise HTTPException(status_code=400, detail="not in mulligan phase")
        if session.simultaneous_mulligan:
            if req.seat in session.mulligan_kept_seats:
                raise HTTPException(status_code=400, detail="you already kept your hand")
        elif req.seat != session.mulligan_offer_seat:
            raise HTTPException(status_code=400, detail="not your turn to decide on mulligan")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        _pregame_keep_player(session, req.seat)
        _pregame_auto_advance(session)

    elif req.action == "mulligan_bottom_select":
        if session.simultaneous_mulligan:
            # Bottom selection runs inside the shared "mulligan" phase, one
            # concurrent selection per seat that kept after mulliganing.
            if session.pregame_phase != "mulligan":
                raise HTTPException(status_code=400, detail="not in bottom card selection phase")
            if req.seat not in session.mulligan_bottom_required_by_seat:
                raise HTTPException(status_code=400, detail="you have no bottom cards to select")
        else:
            if session.pregame_phase != "bottom_select":
                raise HTTPException(status_code=400, detail="not in bottom card selection phase")
            if req.seat != session.mulligan_bottom_seat:
                raise HTTPException(status_code=400, detail="not your turn to select bottom cards")
        if seat_type != "human":
            raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
        if req.hand_index is None:
            raise HTTPException(status_code=400, detail="hand_index is required")
        player = session.game.players[req.seat]
        if req.hand_index >= len(player.hand):
            raise HTTPException(status_code=400, detail="invalid hand index")
        selected = (
            session.mulligan_bottom_selected_by_seat[req.seat]
            if session.simultaneous_mulligan
            else session.mulligan_bottom_selected
        )
        if req.hand_index in selected:
            selected.remove(req.hand_index)
        else:
            selected.append(req.hand_index)

    elif req.action == "mulligan_bottom_confirm":
        if session.simultaneous_mulligan:
            if session.pregame_phase != "mulligan":
                raise HTTPException(status_code=400, detail="not in bottom card selection phase")
            if req.seat not in session.mulligan_bottom_required_by_seat:
                raise HTTPException(status_code=400, detail="you have no bottom cards to select")
            if seat_type != "human":
                raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
            required = session.mulligan_bottom_required_by_seat[req.seat]
            if len(session.mulligan_bottom_selected_by_seat.get(req.seat, [])) != required:
                raise HTTPException(
                    status_code=400,
                    detail=f"must select exactly {required} card(s)",
                )
            _pregame_confirm_bottom_simultaneous(session, req.seat)
            _pregame_auto_advance(session)
        else:
            if session.pregame_phase != "bottom_select":
                raise HTTPException(status_code=400, detail="not in bottom card selection phase")
            if req.seat != session.mulligan_bottom_seat:
                raise HTTPException(status_code=400, detail="not your turn to select bottom cards")
            if seat_type != "human":
                raise HTTPException(status_code=400, detail="cannot issue human action for AI seat")
            if len(session.mulligan_bottom_selected) != session.mulligan_bottom_required:
                raise HTTPException(
                    status_code=400,
                    detail=f"must select exactly {session.mulligan_bottom_required} card(s)",
                )
            _pregame_confirm_bottom(session)
            _pregame_auto_advance(session)

    else:
        raise HTTPException(status_code=400, detail="unknown action")

    _notify_session_change(session.id, "action")
    return build_state(session, viewer_seat=req.seat)
