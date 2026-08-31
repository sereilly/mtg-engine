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

from engine.activation_permissions import card_widens_activation
from engine.cast_permissions import permission_for
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from .action_registry import ACTION_HANDLERS, HUMAN_ONLY, action_handler
from .prompts import blocking_prompt
from .schemas import GameActionRequest

from .runtime import _require_session, _save_snapshot
from .events import _notify_session_change
from .seats import _seat_type
from .turn_steps import (
    _cleanup_discard_requirement,
    _optional_trigger_pending,
    _resume_paused_beginning_phase,
    _untap_land_selection_requirement,
    _upkeep_mana_prevention_pending,
    _upkeep_pay_pending,
)
from .game_flow import _auto_resolve_ai_pending, _run_priority_exchange
from .state_view import build_state
from .debug_actions import _DEBUG_ANYTIME_ACTIONS
from .action_helpers import (
    _find_card_in_hand,
    _find_controlled_permanent,
    _queue_spell_from_request,
)

# Imported for their registration side effects: each module's import fills
# ACTION_HANDLERS with its group's specs, and the exhaustiveness guard in
# tests/ui/test_action_registry.py is what notices a group left out.
from . import (  # noqa: F401
    action_combat,
    action_debug,
    action_pregame,
    action_prompt_answers,
    action_turn,
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

    if req.cost_permanent_id is not None:
        found = game.find_permanent_by_id(req.cost_permanent_id)
        if found is None:
            raise HTTPException(status_code=404, detail=gone)
        _, permanent = found
        # No seat is written back: only the payer's own permanents can pay
        # their cost, and the charger checks control itself.
        update["cost_permanent_index"] = game.battlefield_index_of(permanent)

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
        # Kept, not just converted. A pair of targets may sit on *two*
        # battlefields ("target creature you control … another target
        # creature", Garruk, Savage Herald's -2), and the engine re-derives
        # identities from one `target_seat` unless the caller supplies them —
        # so the ids resolved here are what the second slot's identity comes
        # from.
        update["target_permanent_ids"] = list(req.target_permanent_ids)
        if len(seats) == 1:
            # A single-seat list is what ``target_permanent_indices`` means;
            # a spread across seats has to arrive as ``divided_targets``, which
            # carries a seat per entry, or through the ids above.
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


# ---------------------------------------------------------------------------
# One handler per ActionKind (web/action_registry.py). Bodies are the former
# if/elif branches, verbatim; the shared preamble and tail stay in do_action.
# ---------------------------------------------------------------------------


@action_handler("cast", human_only=HUMAN_ONLY)
def _action_cast(session, req, seat_type):
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")

    caster = session.game.players[req.seat]
    if req.from_zone == "command":
        # CR 903.8: casting a commander from the command zone is a rule
        # rather than a permission, so the check here is ownership — which
        # is what the engine re-checks too; this turns "no" into a 400 with
        # the reason instead of a queue refusal.
        card = next(
            (
                entry for entry in caster.command_zone
                if entry.name == req.card_name
                and session.game.may_cast_from_command_zone(req.seat, entry)
            ),
            None,
        )
        if card is None:
            raise HTTPException(
                status_code=400,
                detail="that card is not your commander in the command zone (CR 903.8)",
            )
    elif req.from_zone in ("graveyard", "exile"):
        # Casting from outside the hand needs a permission grant
        # (engine/cast_permissions.py); the engine re-checks, this just
        # turns "no" into a 400 with the reason instead of a queue refusal.
        zone_cards = getattr(caster, req.from_zone)
        card = next(
            (
                entry for entry in zone_cards
                if entry.name == req.card_name
                and permission_for(
                    session.game, req.seat, entry, req.from_zone,
                    as_land=entry.primary_type == "land",
                ) is not None
            ),
            None,
        )
        if card is None:
            raise HTTPException(
                status_code=400,
                detail=f"no effect allows playing that card from your {req.from_zone}",
            )
    else:
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


@action_handler("tap")
def _action_tap(session, req, seat_type):
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
        )
    else:
        tapped = session.game.tap_permanent(
            req.seat,
            permanent.card.name,
            permanent_index=permanent_index,
        )
    if not tapped:
        raise HTTPException(status_code=400, detail="failed to tap permanent")


@action_handler("activate", human_only=HUMAN_ONLY)
def _action_activate(session, req, seat_type):
    if req.permanent_name is None and req.permanent_index is None:
        raise HTTPException(status_code=400, detail="permanent_name or permanent_index is required")
    controller = session.game.players[req.seat]
    resolved = _find_controlled_permanent(controller, req.permanent_name, req.permanent_index)
    # "Any player may activate this ability." (Ifh-Bíff Efreet), "Only your
    # opponents may activate this ability." (Clergy of the Holy Nimbus) — the
    # permanent may sit on another player's battlefield; the activator still
    # pays the cost and controls the ability. Asked of the one table the engine
    # enforces from, rather than of the substring this used to test, so a
    # permission added there is reachable through the API by construction.
    source_controller_seat = None
    if resolved is None:
        for other_seat, other in enumerate(session.game.players):
            if other_seat == req.seat:
                continue
            candidate = _find_controlled_permanent(other, req.permanent_name, req.permanent_index)
            if candidate is not None and card_widens_activation(
                candidate[1].effective_card
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
            # The "from" word of a text change activated as an ability
            # (Balduvian Shaman); the cast side already forwards the same
            # field, and the request schema has carried it all along.
            old_color=req.old_color,
            target_permanent_index=(
                req.target_permanent_indices
                if req.target_permanent_indices is not None
                else req.target_permanent_index
            ),
            target_permanent_ids=req.target_permanent_ids,
            target_stack_index=engine_stack_index,
            ability_index=req.ability_index,
            x_value=req.x_value,
            cost_permanent_index=req.cost_permanent_index,
            cost_permanent_ids=req.cost_permanent_ids,
            cost_hand_index=req.cost_hand_index,
            source_seat=req.source_seat,
            source_permanent_index=req.source_permanent_index,
            source_stack_index=engine_source_stack_index,
            source_controller_index=source_controller_seat,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)


@action_handler("activate_emblem")
def _action_activate_emblem(session, req, seat_type):
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")
    result = session.game.activate_prevent_one_emblem(
        req.seat,
        emblem_index=req.emblem_index if req.emblem_index is not None else 0,
    )
    if not result.supported:
        raise HTTPException(status_code=400, detail=result.details)
    session.game.note_priority_action_taken(req.seat)


@action_handler("channel_mana")
def _action_channel_mana(session, req, seat_type):
    # Channel emblem: "any time you could activate a mana ability, you may pay 1
    # life. If you do, add {C}." Pay `x_value` life (default 1) for that many {C}.
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")
    amount = req.x_value if req.x_value is not None else 1
    result = session.game.use_channel_mana(req.seat, amount)
    if not result.supported:
        raise HTTPException(status_code=400, detail=result.details)
    session.game.note_priority_action_taken(req.seat)


@action_handler("pass_priority", human_only=HUMAN_ONLY)
def _action_pass_priority(session, req, seat_type):
    try:
        _run_priority_exchange(session, req.seat)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    # Which actions may run during pregame is registry data (ActionSpec.pregame),
    # so the gate cannot drift from the handlers the way a hand-kept set could.
    spec = ACTION_HANDLERS.get(req.action)
    if session.pregame_phase is not None and not (
        (spec is not None and spec.pregame) or req.action in _DEBUG_ANYTIME_ACTIONS
    ):
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

    # The registry answers the rewritten action: the cleanup rewrite above may
    # have turned a "cast" into a "cleanup_select", and dispatching the spec
    # looked up before it would run the wrong handler.
    spec = ACTION_HANDLERS.get(req.action)
    if spec is None:
        raise HTTPException(status_code=400, detail="unknown action")
    if spec.human_only is not None and seat_type != "human":
        raise HTTPException(status_code=400, detail=spec.human_only)

    spec.handler(session, req, seat_type)

    # A turn step that stopped on a decision picks up here, once nothing is
    # owed. In the tail rather than in the handler that answers the prompt,
    # because *which* prompt paused the phase is not something the answering
    # handler knows — the sacrifice confirm used to carry that resume alone, so
    # a phase paused on any other decision would have stayed paused.
    _resume_paused_beginning_phase(session)

    _notify_session_change(session.id, "action")
    return build_state(session, viewer_seat=req.seat)
