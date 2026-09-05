"""Handlers for the Debug Menu's board manipulation. Human seats only
(``DEBUG_ONLY`` on every spec); each logs what it forged so a debugged game
reads honestly in the log.
"""

from __future__ import annotations

from fastapi import HTTPException
from .action_helpers import _queue_spell_from_request
from .action_registry import DEBUG_ONLY, action_handler
from .debug_actions import (
    _debug_move_permanent_off_battlefield,
    _debug_target_permanent,
)
from .runtime import CARD_BY_NAME
from .seats import _first_opponent_seat


@action_handler("debug_add_to_hand", human_only=DEBUG_ONLY)
def _action_debug_add_to_hand(session, req, seat_type):
    if not req.card_name:
        raise HTTPException(status_code=400, detail="card_name is required")

    card = CARD_BY_NAME.get(req.card_name.strip().casefold())
    if card is None:
        raise HTTPException(status_code=404, detail="card not found")

    player = session.game.players[req.seat]
    player.hand.append(card)
    session.game.log.append(f"[Debug] {player.name} added {card.name} to hand.")

@action_handler("debug_add_to_sideboard")
def _action_debug_add_to_sideboard(session, req, seat_type):
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

@action_handler("debug_cast_free", human_only=DEBUG_ONLY)
def _action_debug_cast_free(session, req, seat_type):
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

@action_handler("debug_cast_free_opponent", human_only=DEBUG_ONLY)
def _action_debug_cast_free_opponent(session, req, seat_type):
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

@action_handler("debug_add_mana", human_only=DEBUG_ONLY)
def _action_debug_add_mana(session, req, seat_type):
    color = (req.mana_color or "").strip().upper()
    if color not in {"W", "U", "B", "R", "G", "C"}:
        raise HTTPException(status_code=400, detail="invalid mana color")

    # target_seat selects whose pool to add to; default to the acting seat.
    target = req.target_seat if req.target_seat is not None else req.seat
    player = session.game.players[target]
    player.mana_pool[color] += 1
    session.game.log.append(f"[Debug] Added {{{color}}} to {player.name}'s mana pool.")

@action_handler("debug_force_ai_attack_all", human_only=DEBUG_ONLY)
def _action_debug_force_ai_attack_all(session, req, seat_type):
    session.force_ai_attack_all = bool(req.force_attack_all)
    state = "ON" if session.force_ai_attack_all else "OFF"
    session.game.log.append(f"[Debug] Force AI to attack with all creatures: {state}.")

@action_handler("debug_clear_summoning_sickness", human_only=DEBUG_ONLY)
def _action_debug_clear_summoning_sickness(session, req, seat_type):
    _, permanent = _debug_target_permanent(session, req)
    if not session.game._is_creature(permanent):
        raise HTTPException(status_code=400, detail="only a creature can have summoning sickness")
    # Drop the marker entirely rather than back-dating it: _advance_summoning_sickness
    # re-stamps a marker that still matches the current turn, so a stale value
    # would come back as sickness on the next opponent's untap step.
    permanent.metadata.pop("summoning_sickness_turn", None)
    session.game.log.append(f"[Debug] {permanent.card.name} loses summoning sickness.")

@action_handler("debug_tap_permanent", "debug_untap_permanent", human_only=DEBUG_ONLY)
def _action_debug_tap_permanent(session, req, seat_type):
    controller_seat, permanent = _debug_target_permanent(session, req)
    make_tapped = req.action == "debug_tap_permanent"
    # Same write path Twiddle uses: a raw state flip that also turns a
    # face-down creature (Illusionary Mask) face up when it becomes tapped.
    # It goes around `become_tapped`, so no "becomes tapped" trigger fires
    # (City of Brass, Psychic Venom, Kudzu). That is deliberate for a debug
    # write — the menu sets up a board rather than playing a turn — and it is
    # the *only* reason those triggers stay quiet here: the engine stopped
    # scoping them to the tap-for-mana path, so any real tap does fire them.
    # `_debug_target_permanent` already resolved the permanent, so hand it over
    # rather than making the helper find it again off a seat and a slot — a
    # second read of one choice is free to disagree with the first.
    session.game._tap_or_untap_target(permanent, make_tapped)
    session.game.log.append(
        f"[Debug] {permanent.card.name} {'tapped' if make_tapped else 'untapped'}."
    )

@action_handler("debug_return_to_hand", "debug_exile_permanent", human_only=DEBUG_ONLY)
def _action_debug_return_to_hand(session, req, seat_type):
    controller_seat, permanent = _debug_target_permanent(session, req)
    zone = "hand" if req.action == "debug_return_to_hand" else "exile"
    name = permanent.card.name
    _debug_move_permanent_off_battlefield(
        session.game, controller_seat, req.target_permanent_index, zone
    )
    session.game.check_state_based_actions()
    moved = "returned to its owner's hand" if zone == "hand" else "exiled"
    session.game.log.append(f"[Debug] {name} {moved}.")

@action_handler("debug_destroy_permanent", human_only=DEBUG_ONLY)
def _action_debug_destroy_permanent(session, req, seat_type):
    controller_seat, permanent = _debug_target_permanent(session, req)
    controller = session.game.players[controller_seat]
    name = permanent.card.name
    # A debug destroy is unconditional — regeneration shields, indestructibility
    # and destruction-replacement shields are all skipped so the tester can
    # always clear the board. It still routes through _permanent_to_graveyard,
    # so dies-triggers and Aura cleanup fire exactly as in a real destruction.
    session.game.remove_from_battlefield(permanent)
    session.game._permanent_to_graveyard(controller, permanent)
    if permanent.card.primary_type == "land":
        session.game._process_land_dies(controller_seat)
    session.game._recompute_continuous_effects()
    session.game.check_state_based_actions()
    session.game.log.append(f"[Debug] {name} destroyed.")


@action_handler("debug_create_copy", human_only=DEBUG_ONLY)
def _action_debug_create_copy(session, req, seat_type):
    controller_seat, permanent = _debug_target_permanent(session, req)
    # A copy in the CR 707 sense, made the one way the engine makes one:
    # ``create_token_copy`` records a layer-1 contribution of the source's
    # *copiable* values, so a Clone-as-Bears copies as Bears and a +1/+1
    # counter or an Aura on the original does not leak into the copy. It enters
    # under the seat that controls the original, because "a copy of this" is a
    # second one of what the board already shows. SBAs run so a copied Aura
    # with nothing to enchant, or a second legend, is handled as the rules say.
    copy = session.game.create_token_copy(controller_seat, permanent)
    session.game.check_state_based_actions()
    session.game.log.append(
        f"[Debug] Created a token copy of {copy.effective_card.name}."
    )


# The object a Debug-Menu control change is recorded under. ``engine/control.py``
# keys layer-2 contributions by source identity, so one shared sentinel means
# sending a permanent back and forth *replaces* the previous debug contribution
# (with a fresh timestamp) rather than piling up a second one — and it is never
# a permanent, so nothing leaving the battlefield can end it.
class _DebugControlSource:
    name = "Debug Menu"


_DEBUG_CONTROL_SOURCE = _DebugControlSource()


@action_handler("debug_send_to_opponent", human_only=DEBUG_ONLY)
def _action_debug_send_to_opponent(session, req, seat_type):
    controller_seat, permanent = _debug_target_permanent(session, req)
    # The first opponent of the seat that *controls* it, not of the seat that
    # clicked: in a two-player game that is the other player whichever side of
    # the board the permanent sits on, so the item is never a no-op.
    opponent_seat = _first_opponent_seat(session.game, controller_seat)
    if opponent_seat is None:
        raise HTTPException(status_code=400, detail="no opposing seat to send it to")
    name = permanent.card.name
    # A control *change* (CR 613 layer 2), not a change of owner: the card still
    # returns to its original owner's hand or graveyard when it leaves, and the
    # same path stamps CR 302.6's summoning sickness for a creature that changes
    # hands. Recorded through ``take_control`` so a hand-built board gets its
    # base controller captured first.
    if not session.game.take_control(permanent, opponent_seat, source=_DEBUG_CONTROL_SOURCE):
        raise HTTPException(status_code=404, detail="permanent not found on that battlefield")
    session.game.log.append(
        f"[Debug] {session.game.players[opponent_seat].name} gains control of {name}."
    )
