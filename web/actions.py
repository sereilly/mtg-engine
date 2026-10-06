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
from engine.cast_timing import casts_at_instant_speed
from engine.faces import choose_a_face_refusal, holds_spell_named, spell_named
from engine.mana_payment import taps_for_payment
from engine.mixins.turn_management import is_tap_alone_mana_ability
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
        # Not for ``activate``, whose handler makes the same fill itself: there
        # ``target_seat`` also says whether the client *announced* a seat
        # (CR 601.2c), and a value written here would make every activation
        # sent by id look as though it had.
        if req.target_seat is None and req.action != "activate":
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
                spell_named(entry, req.card_name) for entry in caster.command_zone
                if spell_named(entry, req.card_name) is not None
                and session.game.may_cast_from_command_zone(req.seat, entry)
            ),
            None,
        )
        if card is None:
            raise HTTPException(
                status_code=400,
                detail="that card is not your commander in the command zone (CR 903.8)",
            )
    elif req.from_zone == "library":
        # A library is a hidden zone (CR 400.2), so this is not the loop below
        # with a third zone in it: only the caster's own top card can be
        # covered, and looking any further would be searching a deck for a
        # named card. ``permission_for`` is still the gate — the engine
        # re-checks it, and this turns "no" into a 400 with the reason.
        own = session.game.players[req.seat].library
        top = own[0] if own else None
        card = (
            spell_named(top, req.card_name)
            if top is not None
            and spell_named(top, req.card_name) is not None
            and permission_for(
                session.game, req.seat, top, "library",
                as_land=top.primary_type == "land",
                spell=spell_named(top, req.card_name),
            ) is not None
            else None
        )
        if card is None:
            raise HTTPException(
                status_code=400,
                detail="no effect allows playing that card from the top of your library",
            )
    elif req.from_zone in ("graveyard", "exile"):
        # Casting from outside the hand needs a permission grant
        # (engine/cast_permissions.py); the engine re-checks, this just
        # turns "no" into a 400 with the reason instead of a queue refusal.
        # Every seat's copy of the zone, not only the caster's: a grant names
        # whose pile it opens (engine/cast_permissions.py's `zone_seat`), and
        # Grinning Totem's exiled card sits in the *searched* player's exile
        # while the permission belongs to the searcher. The caster's own pile
        # is looked at first, so nothing that resolved here before moves.
        seats = [req.seat] + [
            seat for seat in range(len(session.game.players)) if seat != req.seat
        ]
        # ``spell_named`` at each of the four lookups in this handler: a split
        # card is cast by the name of one of its halves (CR 709.3), the
        # permission is asked of the card as the zone holds it *and* of the
        # half it is being cast as (`permission_for`'s `spell`), and what the
        # timing gates below judge is the half (CR 709.3a).
        card = next(
            (
                spell_named(entry, req.card_name)
                for seat in seats
                for entry in getattr(session.game.players[seat], req.from_zone)
                if spell_named(entry, req.card_name) is not None
                and (
                    grant := permission_for(
                        session.game, req.seat, entry, req.from_zone,
                        as_land=entry.primary_type == "land",
                        spell=spell_named(entry, req.card_name),
                    )
                ) is not None
                and grant.zone_seat == seat
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
            # CR 709.3: a split card named whole names no half. Said in the
            # rule's words rather than as "card not in hand", which is false —
            # the card is right there, and a client author reading that would
            # go looking for a hand-sync bug.
            refusal = next(
                (
                    choose_a_face_refusal(entry) for entry in caster.hand
                    if entry.name == req.card_name
                    and choose_a_face_refusal(entry) is not None
                ),
                None,
            )
            raise HTTPException(status_code=400, detail=refusal or "card not in hand")

    # CR 702.8b: a card with flash casts any time an instant could be cast, so
    # the two sorcery-speed gates below ask instant-or-flash, not the type line
    # alone. A land is never cast and keeps sorcery timing. Asked of
    # `engine/cast_timing.py` rather than spelled here, because there are three
    # sources of the answer now — the type, the printed keyword and a card that
    # grants itself flash (Mirage's five Auras) — and this question is asked in
    # two places: a card castable in the picker and refused by the action is the
    # shape a second copy produces.
    instant_speed = casts_at_instant_speed(card, session.game, req.seat)
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

    # ``has_type`` (CR 613 layer 4), not the printed line: which tap this is
    # depends on what the permanent is now.
    if permanent.has_type("land"):
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
    # ability whose whole cost is {T} (CR 106.12's "tap for mana"). Non-mana
    # land abilities (Island of Wak-Wak's power-set, Library of Alexandria's
    # draw) and priced mana abilities (Gemstone Mine, the depletion lands) go
    # through the normal ability path, which pays what they cost.
    #
    # **And the chosen ability travels with the tap.** This used to test a
    # three-kind set — a third copy of CR 605.1a — because the seam took no
    # ability index and ran the land's *first* tap-alone mana ability, so
    # routing a second one there would have produced the first one's mana.
    # The consequence was measured: 26 lands whose tap-alone mana ability
    # lowers to a ``sequence`` or an ``if_then`` (the ten painlands, the Urza
    # tri-lands, Ancient Tomb, Rainbow Vale, the Ice Age depletion lands …)
    # never reached the seam — no Desolation record, no Deep Water / Infernal
    # Darkness / Contamination swap, no Mana Flare — and a land's *granted*
    # mana ability (Overlaid Terrain on a Karplusan Forest) could not be
    # reached at all, because the seam always ran the land's own. The seam
    # takes the index now (``tap_land_for_mana(ability_index=…)``), and
    # ``is_tap_alone_mana_ability`` is the one predicate the seam and this
    # route ask.
    #
    # Still open, and the note's remaining half: a *priced* mana ability (the
    # six above) is paid by the activation path, which announces no
    # tap-for-mana event. The seam refuses those by design (CR 602.2b); closing
    # it means moving the announcement into the mana ability's resolution.
    land_as_mana_tap = permanent.has_type("land")
    seam_ability_index = None
    if land_as_mana_tap:
        # A named ability of a land that has none left (CR 305.7 — its type
        # was set) is refused with the engine's own reason. The list below is
        # empty for such a land, and an index into an empty list used to fall
        # through to "no ability named": the request asked for the Factory's
        # animation and got a mana tap.
        if req.ability_index is not None:
            lost = session.game.lost_abilities_refusal(permanent)
            if lost is not None:
                raise HTTPException(status_code=400, detail=lost)
        usable = session.game.usable_abilities_of(
            permanent, card=permanent.effective_card
        )
        chosen_ability = None
        if req.ability_index is not None and 0 <= req.ability_index < len(usable):
            chosen_ability = usable[req.ability_index]
            seam_ability_index = req.ability_index
        elif usable and (
            not permanent.effective_produced_mana
            # …or on a land the tap seam refuses (``taps_for_payment``): its
            # mana ability costs more than {T} (a depletion land's counter), or
            # needs priority and asks the table (Rhystic Cave). The seam has
            # nothing to run for either, so a click sent to it failed with
            # "failed to tap land for mana" however the client asked; the
            # activation path pays the cost, gates the timing and offers the
            # toll.
            or not taps_for_payment(permanent)
        ):
            # No explicit choice on a land that makes no mana: its only
            # meaningful activation is its first ability.
            chosen_ability = usable[0]
            seam_ability_index = 0
        if chosen_ability is not None and not is_tap_alone_mana_ability(chosen_ability):
            land_as_mana_tap = False

    if land_as_mana_tap:
        tapped = session.game.tap_land_for_mana(
            req.seat,
            permanent.card.name,
            chosen_color=req.mana_color or "G",
            permanent_index=permanent_index,
            ability_index=seam_ability_index,
        )
        if not tapped:
            raise HTTPException(status_code=400, detail="failed to tap land for mana")
    else:
        if not session.game.has_priority(req.seat):
            raise HTTPException(status_code=400, detail="you do not currently have priority")
        if req.target_seat is not None:
            target = req.target_seat
        elif req.permanent_id is not None:
            # The fill ``_resolve_permanent_ids`` makes for every other action
            # sent by id — the seat the named permanent is on — made here so
            # that ``req.target_seat`` still says what the client sent.
            target = (
                source_controller_seat
                if source_controller_seat is not None else req.seat
            )
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
        # **The permanent a cost was announced with, by identity.** The request
        # resolver above turns ``cost_permanent_id`` into a bare slot and writes
        # no seat beside it, and the engine counts a cost slot into the
        # *payer's* battlefield — so an id naming somebody else's permanent
        # arrived as whatever the payer happened to hold in that slot. The
        # engine refuses a named payment that cannot pay
        # (``_named_cost_refusal``, CR 601.2h), and it can only refuse what it
        # is told was named: the id travels, and the slot only where it means
        # what the engine will read it as.
        cost_permanent_ids = req.cost_permanent_ids
        cost_permanent_index = req.cost_permanent_index
        if req.cost_permanent_id is not None:
            if cost_permanent_ids is None:
                cost_permanent_ids = [req.cost_permanent_id]
            named_cost = session.game.permanent_by_id(req.cost_permanent_id)
            if named_cost is None or not session.game.controls(req.seat, named_cost):
                cost_permanent_index = None
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
            # …and the same announcement where its slots are not all
            # permanents (Goblin Welder's artifact plus a card in a graveyard).
            # Forwarded as plain dicts, which is the shape the engine's own
            # channel takes: the engine has no business importing a request
            # model, and the two names are the same words.
            target_role_refs=(
                [ref.model_dump() for ref in req.target_role_refs]
                if req.target_role_refs
                else None
            ),
            # CR 601.2d's announced division, forwarded exactly as the cast
            # path's helper forwards it and in the same shape: a two-tuple
            # where no share was announced (which is what an evenly-divided
            # ability and every non-interactive caller send) and a three-tuple
            # where one was. Serra's Hymn is the pool's first ability to print
            # a division, so this field reached the engine on the cast side
            # alone until now.
            divided_targets=(
                [
                    (entry.seat, entry.index)
                    if entry.amount is None
                    else (entry.seat, entry.index, entry.amount)
                    for entry in req.divided_targets
                ]
                if req.divided_targets
                else None
            ),
            target_stack_index=engine_stack_index,
            ability_index=req.ability_index,
            x_value=req.x_value,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_index=req.cost_hand_index,
            cost_other_hand_indices=req.cost_other_hand_indices,
            # Phyrexian Splicer: the ability the activation chose (CR 601.2b),
            # forwarded like every other announcement-time choice above.
            chosen_keyword=req.chosen_keyword,
            source_seat=req.source_seat,
            source_permanent_index=req.source_permanent_index,
            source_stack_index=engine_source_stack_index,
            source_controller_index=source_controller_seat,
            # CR 601.2c through CR 602.2b: a client announces every target an
            # ability owes — the browser runs a picker for each and cannot send
            # the activation without an answer — so the engine is told this
            # caller is one, and whether the seat above was sent or is this
            # route's default. A bare ``activate`` for "Prevent the next X
            # damage that would be dealt to target creature" (Samite Pilgrim)
            # returned 200 and shielded the opponent.
            seat_announced=req.target_seat is not None,
        )
        if not result.supported:
            raise HTTPException(status_code=400, detail=result.details)
        session.game.note_priority_action_taken(req.seat)


@action_handler("activate_hand", human_only=HUMAN_ONLY)
def _action_activate_hand(session, req, seat_type):
    """CR 113.6j — activate an ability of a card in the seat's own **hand**.

    Cycling (CR 702.29a) is what makes this a route rather than a curiosity: 34
    of Urza's Saga's cards compile to "[Cost], Discard this card: Draw a card.",
    and until this existed the browser had no gesture that could reach any of
    them. ``Game.activate_from_hand`` has been in the engine since M21's Waker
    of Waves, unreachable from the app for the whole time.

    ``ability_index`` indexes the hand-activatable abilities — the same list
    ``state.hand_abilities`` is built from, so the index the client sends back
    names the ability the button was labelled with. ``hand_index`` says *which
    copy*, because two copies of a card in a hand are the same immutable
    ``CardDefinition`` and a name alone would activate whichever came first.
    """
    if req.card_name is None and req.hand_index is None:
        raise HTTPException(
            status_code=400, detail="card_name or hand_index is required"
        )
    hand = session.game.players[req.seat].hand
    hand_index = req.hand_index
    if hand_index is not None and not 0 <= hand_index < len(hand):
        raise HTTPException(status_code=400, detail="card not in hand")
    card_name = req.card_name
    if card_name is None:
        card_name = hand[hand_index].name
    if not session.game.has_priority(req.seat):
        raise HTTPException(status_code=400, detail="you do not currently have priority")
    result = session.game.activate_from_hand(
        req.seat,
        card_name,
        ability_index=req.ability_index if req.ability_index is not None else 0,
        hand_index=hand_index,
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


@action_handler("special_action", human_only=HUMAN_ONLY)
def _action_special_action(session, req, seat_type):
    """CR 116 — an action taken with priority that does not use the stack.

    One branch for every kind the table grants, because what varies between
    them is the card and the kind, not the plumbing: the seat, the address and
    the refusal are the same three questions each time. The refusal comes from
    ``engine/special_actions``' own gates, the same ones the state payload asks
    before offering the action — an action the client offers and the engine
    refuses is a button that does nothing.

    Two seams, and the *address* is what tells them apart: 116.2e's offer is
    made by a card in a hand and 116.2c/116.2d's by a permanent on the
    battlefield.

    CR 116.3 gives the player priority again afterwards, so this deliberately
    does **not** pass or advance; ``note_priority_action_taken`` is the same
    "you did something in this window" note every other action makes.
    """
    from engine.special_actions import (take_permanent_special_action,
                                        take_special_action)

    kind = req.special_action_kind or ""
    # CR 116.2c/116.2d's offers are made by a permanent, not by a card in hand,
    # so the request names one — by `permanent_id`, which the preamble at the
    # top of this module has already resolved (a stale id is a 404 there, never
    # a fall back to a slot). Which of the two seams answers is decided by which
    # address the request carries, not by the kind: a kind list here would be a
    # second copy of the two registries.
    if req.permanent_id is not None or req.permanent_index is not None:
        permanent = (
            session.game.permanent_by_id(req.permanent_id)
            if req.permanent_id is not None
            else session.game.permanent_at(
                session.game.players[req.seat], req.permanent_index
            )
        )
        if permanent is None:
            raise HTTPException(status_code=404, detail="permanent not found")
        # "…may **sacrifice a permanent of their choice**" (CR 116.2d): the
        # taker names the price on the same channel a CR 601.2b additional cost
        # already travels on, resolved to a permanent by the preamble above.
        # None leaves the deterministic pick, which is what a non-interactive
        # seat gets everywhere else in this engine.
        sacrificed = (
            session.game.permanent_by_id(req.cost_permanent_id)
            if req.cost_permanent_id is not None
            else None
        )
        refusal = take_permanent_special_action(
            session.game, req.seat, permanent, kind, sacrificed=sacrificed
        )
        if refusal is not None:
            raise HTTPException(status_code=400, detail=refusal)
        session.game.note_priority_action_taken(req.seat)
        return

    player = session.game.players[req.seat]
    index = req.hand_index
    if index is None or not (0 <= index < len(player.hand)):
        raise HTTPException(status_code=400, detail="card not in hand")
    card = player.hand[index]
    refusal = take_special_action(session.game, req.seat, card, kind)
    if refusal is not None:
        raise HTTPException(status_code=400, detail=refusal)
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
        matching_indices = [
            idx for idx, card in enumerate(active_hand)
            # Either spelling of a split card: this is a discard being named,
            # not a half being cast (CR 709.2 — it is one card).
            if holds_spell_named(card, req.card_name)
        ]
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
