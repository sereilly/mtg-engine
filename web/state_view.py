"""The whole-state payload: the one JSON document a client polls.

:func:`_serialize_state` assembles it from every layer below — the serialization
leaves, the pregame / turn-step / combat prompts, the seat and outcome answers —
and does it *per viewer*, because a hand is hidden from everyone but its owner
and a prompt belongs to the seat that owes it. The two playability computations
live here as well: nothing else asks them, and "what can I play right now" is a
question about the view, not about the turn.

**Two functions, and the difference is the point.** :func:`_serialize_state`
reads the game and returns JSON — it does not move a card, lock a division or
settle an ante. :func:`build_state` is what a route calls: it settles what the
game owes (``game_flow.settle_before_observation``) and *then* reads.

They used to be one function, and the one they were was the reading one. Ante
transfer and an AI's Raging River lock ran inside it, so ``GET /state`` moved
cards between players and nothing in the name said so. The settling still has to
happen before a client looks — see that function for why neither is deletable —
but it happens somewhere it can be seen, and the serializer is now a function
you can call to ask what the game looks like without changing the answer.

The session *view* fields (``cleanup_selected_indices``,
``untap_selected_indices``, ``untap_required_lands``) are still normalized in
the serializer, deliberately: they are the viewer's own pending selection, owned
by the ``Session`` rather than the ``Game``, and clamping them to what is
currently legal is part of rendering the prompt rather than a change to the
game. ``_serialize_state`` is a read *of the game*, which is the property that
was missing.
"""

from __future__ import annotations

from engine import Game
from engine.cast_permissions import playable_from_zones
from engine.classifier import classify_card
from engine.models import PlayerState

from .prompts import PromptContext, render_prompts
from .session_store import Session

from .runtime import store
from .seats import _build_rematch_info, _seat_type, _winner
from .serialization import (
    _serialize_card_summary,
    _serialize_player,
    _serialize_stack_item,
)
from .catalog import CATALOG_BY_NAME
from .pregame import _build_pregame_info
from .turn_steps import (
    _build_optional_trigger_info,
    _build_upkeep_mana_prevention_info,
    _build_upkeep_pay_info,
    _cleanup_discard_requirement,
    _clear_cleanup_selection,
    _optional_trigger_pending,
    _untap_land_selection_requirement,
    _upkeep_pay_pending,
)
from .combat_prompts import (
    _build_band_blocker_assignment_info,
    _build_banding_assignment_info,
    _build_camouflage_info,
    _build_multiblock_assignment_info,
    _build_raging_river_info,
)
from .game_flow import settle_before_observation


def _seat_deck_colors(game: Game, seat: int) -> list[str]:
    """Color identity of a seat's deck, derived from its (pre-deal) library —
    works uniformly for random/saved/personal decks and for host/AI/joined-guest
    seats alike, since this is only ever read while the lobby is still open."""
    colors: set[str] = set()
    for card in game.players[seat].library:
        match = CATALOG_BY_NAME.get(card.name.casefold())
        if match:
            colors.update(match["color_identity"])
    return [c for c in ("W", "U", "B", "R", "G") if c in colors]


def _seat_deck_display_name(session: Session, seat: int) -> str:
    if session.mode == "free_for_all":
        name = session.seat_deck_names[seat] if seat < len(session.seat_deck_names) else None
    elif seat == 0:
        name = session.host_deck_name
    else:
        name = session.guest_deck_name
    return name or "Random Deck"


def _can_afford_with_pool(pool: dict, cost: dict, player: PlayerState) -> bool:
    """Check whether `pool` can pay `cost` without mutating either."""
    temp = dict(pool)
    for sym in ("W", "U", "B", "G", "C"):
        if temp.get(sym, 0) < cost.get(sym, 0):
            return False

    available_red = temp.get("R", 0)
    if player.can_spend_white_as_red:
        available_red += temp.get("W", 0)
    if available_red < cost.get("R", 0):
        return False

    temp["W"] -= cost.get("W", 0)
    temp["U"] -= cost.get("U", 0)
    temp["B"] -= cost.get("B", 0)
    temp["G"] -= cost.get("G", 0)
    temp["C"] -= cost.get("C", 0)

    red_to_pay = cost.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] = temp.get("R", 0) - from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not player.can_spend_white_as_red or temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = cost.get("generic", 0)
    if generic > 0:
        available = sum(max(0, temp.get(s, 0)) for s in ("C", "W", "U", "B", "R", "G"))
        if available < generic:
            return False

    return True


def _compute_playable_hand_indices(session: Session, player_index: int) -> list[int]:
    """Return hand indices the player can legally cast right now (considering timing,
    mana already in pool plus potential mana from untapped lands, and restrictions)."""
    game = session.game
    player = game.players[player_index]

    # Bail under blocking UI states where casting is not possible
    if session.pregame_phase is not None:
        return []
    if _cleanup_discard_requirement(session) > 0:
        return []
    if _untap_land_selection_requirement(session) > 0:
        return []
    if _upkeep_pay_pending(session):
        return []
    if _optional_trigger_pending(session):
        return []
    if session.island_sanctuary_pending:
        return []
    if game.pending_search_library is not None:
        return []
    if game.pending_reorder_library is not None:
        return []

    if not game.has_priority(player_index):
        return []

    # Potential mana = current pool + what each untapped land could produce
    potential_pool: dict[str, int] = dict(player.mana_pool)
    for perm in game.controlled_by(player_index):
        if not perm.tapped and perm.card.primary_type == "land":
            for color in perm.effective_produced_mana:
                sym = color.upper()
                potential_pool[sym] = potential_pool.get(sym, 0) + 1

    has_gloom = any(perm.card.name == "Gloom" for perm in game.all_permanents())
    may_play_land = game._may_play_another_land(player_index)
    current_turn = session.current_turn
    is_main_phase = game.current_phase == "main"
    stack_empty = not game.stack

    playable = []
    for i, card in enumerate(player.hand):
        classification = classify_card(card)
        if not classification.supported:
            continue

        # CR 702.8b: flash casts any time an instant could be cast, so both
        # timing gates ask instant-or-flash rather than the type line alone.
        instant_speed = card.primary_type == "instant" or card.has_flash

        # Non-instant-speed spells require it to be your turn
        if player_index != current_turn and not instant_speed:
            continue

        # Sorcery-speed: must be main phase with empty stack on your turn
        # (planeswalkers per CR 306.1).
        if card.primary_type in {"land", "sorcery", "creature", "artifact", "enchantment", "planeswalker"} and not instant_speed:
            if player_index != current_turn or not is_main_phase or not stack_empty:
                continue

        # Card-specific timing restriction
        if "cast this spell only during your declare attackers step" in card.oracle_text.lower():
            if game.current_step != "declare_attackers" or game.active_player_index != player_index:
                continue

        # Blaze of Glory: only during combat before blockers are declared.
        if "cast this spell only during combat before blockers are declared" in card.oracle_text.lower():
            if game.current_phase != "combat" or game.current_step not in (
                "beginning_of_combat",
                "declare_attackers",
            ):
                continue

        # False Orders / similar: only during the declare blockers step.
        if "cast this spell only during the declare blockers step" in card.oracle_text.lower():
            if game.current_phase != "combat" or game.current_step != "declare_blockers":
                continue

        # Target validation (aura enchant targets, removal targets, counter targets, etc.)
        target_ok, _ = game._validate_cast_targets(card, player_index, None)
        if not target_ok:
            continue

        # Land play restriction: CR 305.2's one per turn, plus whatever the
        # allowances on this seat's battlefield add (engine/land_play_allowance.py).
        if card.primary_type == "land" and not may_play_land:
            continue

        # Mana affordability for non-land cards
        if card.primary_type != "land" and game.enforce_mana_costs:
            extra_tax = 3 if (has_gloom and "W" in card.colors) else 0
            # Use x_value=0 so X spells are shown as playable (castable at X=0)
            cost = game._parse_mana_cost(card.mana_cost, x_value=0, extra_generic=extra_tax)
            if not _can_afford_with_pool(potential_pool, cost, player):
                continue

        playable.append(i)

    return playable


def build_state(session: Session, viewer_seat: int | None) -> dict:
    """Settle what the game owes, then read it. What a route calls.

    The order is the contract: an AI's Raging River division and a decided
    game's ante have to be settled *before* the payload is built, or the client
    renders a prompt that is waiting on itself. See
    ``game_flow.settle_before_observation``.
    """
    settle_before_observation(session)
    return _serialize_state(session, viewer_seat)


def _serialize_state(session: Session, viewer_seat: int | None) -> dict:
    """The payload for one viewer. Reads the game; never changes it.

    Callers that are serving a client want :func:`build_state` instead — this
    one deliberately does not settle, so that "what does the game look like"
    can be asked without altering the answer.
    """
    win = _winner(session)

    cleanup_info = None
    cleanup_required = _cleanup_discard_requirement(session)
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and cleanup_required > 0:
        valid_indices = [
            idx
            for idx in sorted(set(session.cleanup_selected_indices))
            if 0 <= idx < len(session.game.players[viewer_seat].hand)
        ]
        session.cleanup_selected_indices = valid_indices
        session.cleanup_required_discards = cleanup_required
        cleanup_info = {
            "required_count": cleanup_required,
            "selected_indices": valid_indices,
            "selected_count": len(valid_indices),
        }
    else:
        _clear_cleanup_selection(session)

    untap_info = None
    untap_required = _untap_land_selection_requirement(session)
    if viewer_seat == session.current_turn and untap_required > 0:
        valid_candidates = [
            idx
            for idx in sorted(set(session.untap_candidate_indices))
            if 0 <= idx < len(session.game.players[viewer_seat].battlefield)
            and session.game.players[viewer_seat].battlefield[idx].card.primary_type in ("land", "creature")
            and session.game.players[viewer_seat].battlefield[idx].tapped
        ]
        session.untap_candidate_indices = valid_candidates

        valid_selected = [idx for idx in sorted(set(session.untap_selected_indices)) if idx in set(valid_candidates)]
        if len(valid_selected) > untap_required:
            valid_selected = valid_selected[:untap_required]
        session.untap_selected_indices = valid_selected
        session.untap_required_lands = untap_required
        # Which permanent types are constrained (Winter Orb → lands, Smoke →
        # creatures) so the prompt can name the right type instead of always
        # saying "lands".
        untap_options = session.game.get_untap_land_selection_options(session.current_turn) or {}
        untap_info = {
            "max_count": untap_required,
            "candidate_indices": valid_candidates,
            "selected_indices": valid_selected,
            "selected_count": len(valid_selected),
            "land_max": untap_options.get("land_max"),
            "creature_max": untap_options.get("creature_max"),
        }

    # Every prompt a seat owes, rendered by web/prompts.py from the one registry
    # in engine/pending_choices.py. This used to be a per-card cascade here: a
    # block of visibility rules and a payload builder for each of eighteen
    # prompts, with nothing checking that a newly armed prompt got one.
    prompt_payloads = render_prompts(
        PromptContext(
            game=session.game,
            viewer_seat=viewer_seat,
            serialize_card=_serialize_card_summary,
            seat_type=lambda seat: _seat_type(session, seat),
        )
    )

    # Time Vault: the begin-of-turn "skip your turn to untap" decision, shown only
    # to the active human player while they decide.
    time_vault_info = None
    if (
        session.time_vault_pending
        and viewer_seat == session.current_turn
        and _seat_type(session, session.current_turn) != "ai"
    ):
        time_vault_info = {"permanents": list(session.time_vault_pending)}

    # Combat legality: which creatures may legally attack (declare-attackers step)
    # and every legal blocker→attacker pairing (declare-blockers step), computed by
    # the engine so the UI offers exactly the assignments the engine would accept.
    combat_state = session.game.get_combat_state()
    game = session.game
    if game.current_turn_phase == "combat" and game.current_step == "declare_attackers":
        combat_state["legal_attacker_indices"] = game.legal_attacker_indices(game.active_player_index)
    else:
        combat_state["legal_attacker_indices"] = []
    # CR 802.4: aggregate legal blocker assignments across every defending
    # player this combat (2+ in FFA), not just a single pre-picked one. Blocker
    # indices are only unambiguous within one defender's battlefield, so tag
    # each pair with which defender it belongs to.
    combat_state["legal_blocker_assignments"] = [
        {**pair, "defending_player_index": defender_index}
        for defender_index in sorted(game.combat_defending_players())
        for pair in game.legal_blocker_assignments(defender_index)
    ]

    return {
        "session_id": session.id,
        "mode": session.mode,
        # CR 407.1: whether this game is played for ante. Drives the ante pile in
        # the board UI and tells a joining player which decks they may bring.
        "playing_for_ante": session.playing_for_ante,
        "status": session.status,
        "current_phase": session.game.current_phase,
        "current_turn_phase": session.game.current_turn_phase,
        "current_step": session.game.current_step,
        "current_turn": session.current_turn,
        "current_turn_is_extra": session.game.current_turn_is_extra,
        "turn_number": session.game.turn,
        "priority_player": session.game.priority_player_index,
        "priority_pass_count": session.game.priority_pass_count,
        "joined_seats": sorted(session.joined_seats),
        "seat_types": session.seat_types,
        "lobby": {
            "game_started": session.game_started,
            "open_seats": store.open_human_seats(session),
            "total_seats": len(session.game.players),
            "joined_count": len(session.joined_seats),
            "seats": [
                {
                    "seat": i,
                    "joined": i in session.joined_seats,
                    "is_ai": session.seat_types.get(i) == "ai",
                    "name": session.game.players[i].name if i in session.joined_seats else None,
                    "deck_name": (
                        _seat_deck_display_name(session, i) if i in session.joined_seats else None
                    ),
                    "colors": (
                        _seat_deck_colors(session.game, i) if i in session.joined_seats else []
                    ),
                }
                for i in range(len(session.game.players))
            ],
        },
        # NOTE (frontend FFA pass): this used to be a hardcoded 2-entry list
        # (session.game.players[0]/[1]), which silently truncated Free-For-All
        # sessions (3-4 players) to 2 players in the serialized state. Generalized
        # to loop over every seat; identical output for the existing 2-player modes.
        "players": [
            _serialize_player(
                session.game.players[i], viewer_seat, i, session.game,
                _compute_playable_hand_indices(session, i) if viewer_seat == i else [],
            )
            for i in range(len(session.game.players))
        ],
        "stack": [_serialize_stack_item(item, session.game) for item in reversed(session.game.stack)],
        "combat": combat_state,
        "log": session.game.log,
        "winner": win,
        "rematch": _build_rematch_info(session, viewer_seat),
        "cleanup_discard": cleanup_info,
        "untap_land_selection": untap_info,
        "optional_untap": (
            {"permanents": list(session.optional_untap_pending)}
            if session.optional_untap_pending and viewer_seat == session.current_turn
            else None
        ),
        "upkeep_pay": _build_upkeep_pay_info(session, viewer_seat),
        "upkeep_mana_prevention": _build_upkeep_mana_prevention_info(session, viewer_seat),
        "optional_trigger": _build_optional_trigger_info(session, viewer_seat),
        "banding_assignment": _build_banding_assignment_info(session, viewer_seat),
        "band_blocker_assignment": _build_band_blocker_assignment_info(session, viewer_seat),
        "multiblock_blocker_assignment": _build_multiblock_assignment_info(session, viewer_seat),
        "raging_river": _build_raging_river_info(session, viewer_seat),
        "camouflage": _build_camouflage_info(session, viewer_seat),
        "island_sanctuary_pending": session.island_sanctuary_pending and viewer_seat == session.current_turn,
        "time_vault": time_vault_info,
        "pregame": _build_pregame_info(session, viewer_seat),
        # CR 601.3 permissions: what the viewer may currently cast or play from
        # their graveyard or exile (engine/cast_permissions.py). Empty for a
        # spectator — a permission belongs to a seat.
        "castable_from_zones": (
            playable_from_zones(session.game, viewer_seat)
            if viewer_seat is not None
            else []
        ),
        **prompt_payloads,
    }
