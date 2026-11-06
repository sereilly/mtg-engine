"""Handlers that answer the prompts answered with permanents, players, spells
or abilities.

One handler per kind of prompt, split as the renderers are (its renderer is in
``web/prompt_board.py``): a trigger's target and order (CR 603.3b–d), a
reflexive trigger's target, a copied or retargeted spell's new targets, a
modal spell's modes and their targets, permanents to tap, untap, sacrifice or
keep (Balance's lists among them), a permanent, several or a player chosen as
an effect resolves (the planeswalker a loyalty counter lands on among them),
damage aimed at any target by an opponent's choice, a spell named out of the
turn's casts, and a spell cast by a prompt rather than from a hand (face down,
by madness, the card Word of Command makes its target play).

Each one validates the client's answer against the prompt the engine armed
(never against the live board - CR 611.2c/603.12 fixed those sets when the
effect began) and hands it to the engine's confirm entry point.
"""

from __future__ import annotations

from fastapi import HTTPException
from engine.faces import choose_a_face_refusal, spell_named
from .action_registry import action_handler
from .action_helpers import _queue_spell_from_request, answered_permanent_id, balance_round_slots


@action_handler("trigger_target_confirm")
def _action_trigger_target_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("trigger_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no trigger target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # A permanent by its stable id, a player by their seat — the two shapes the
    # prompt offers, and exactly one of them per answer. An id wins where both
    # arrive, because an answer carrying one is about a permanent whatever seat
    # it happens to sit on.
    # ...or several permanents at once, for an ability that prints several
    # targets ("up to two target creatures"): CR 601.2c makes them one
    # announcement, so they arrive as one list. The engine re-checks every id
    # against the list it offered and the count against the printed one, so a
    # client cannot widen the announcement by sending more.
    #
    # An **empty** list is the answer "nobody", which "up to one target …"
    # allows (CR 601.2c). It has to be sent — absent is a malformed answer, as
    # it always was — and the engine takes it only from a prompt it armed as
    # an "up to", so an ability that owes its target cannot be skipped by
    # sending one.
    #
    # A **division** ("distribute three -1/-1 counters among one, two, or
    # three target creatures", Shambling Swarm — the prompt carries
    # ``division_total``) arrives the way a divided *spell's* announcement
    # does: ``divided_targets``, one entry per creature with its ``amount``
    # (CR 601.2d). ``target_permanent_ids`` is still accepted for a division
    # nobody had to choose (one target, or one counter apiece); the engine
    # refuses it where the split is the announcer's to make.
    if pending.data.get("division_total") is not None and req.divided_targets:
        ids = []
        for entry in req.divided_targets:
            permanent_id = entry.id
            if permanent_id is None and entry.index is not None:
                permanent = session.game.permanent_at(entry.seat, entry.index)
                permanent_id = None if permanent is None else permanent.permanent_id
            if permanent_id is None:
                raise HTTPException(
                    status_code=400, detail="a division names creatures, not players",
                )
            ids.append(permanent_id)
        amounts = [entry.amount for entry in req.divided_targets]
        if not session.game.confirm_trigger_target(
            req.seat, permanent_ids=ids,
            amounts=None if all(amount is None for amount in amounts) else amounts,
        ):
            raise HTTPException(status_code=400, detail="invalid division")
        return
    if req.target_permanent_ids is not None and (
        req.target_permanent_ids or pending.data.get("up_to")
    ):
        if not session.game.confirm_trigger_target(
            req.seat, permanent_ids=list(req.target_permanent_ids)
        ):
            raise HTTPException(status_code=400, detail="invalid target selection")
        return
    # ...or a **spell** ("counter target spell", Mystic Snake), named the way a
    # cast names one: `target_stack_index`, top-first into the stack the client
    # was shown. Resolved against the prompt's own candidates — a position the
    # picker did not offer names nothing — and read ahead of the two fields
    # below, because an answer carrying it is about the stack whatever else it
    # happens to carry.
    if req.target_stack_index is not None:
        named = session.game.trigger_target_stack_item(
            req.seat, req.target_stack_index
        )
        if named is None or not session.game.confirm_trigger_target(
            req.seat, stack_item=named
        ):
            raise HTTPException(status_code=400, detail="invalid target")
        return
    # **Several cards in one graveyard** ("exile up to two target cards from a
    # single graveyard", Gravegouger): the pile and every slot, as one
    # announcement — the prompt carries ``max_targets`` and
    # ``single_graveyard``. The engine holds each slot to the list it offered
    # in that pile and the count to the printed one.
    if req.graveyard_indices is not None and pending.data.get("max_targets"):
        if req.target_seat is None:
            raise HTTPException(
                status_code=400, detail="target_seat names whose graveyard",
            )
        if not session.game.confirm_trigger_target(
            req.seat, seat=req.target_seat,
            graveyard_indices=list(req.graveyard_indices),
        ):
            raise HTTPException(status_code=400, detail="invalid graveyard targets")
        return
    # A **card in a graveyard** (Gravedigger): the pile and the slot, the two
    # things the prompt listed it by. Ahead of the seat-alone branch below,
    # which would otherwise read the pile's seat as a targeted player.
    if req.graveyard_index is not None:
        if req.target_seat is None:
            raise HTTPException(
                status_code=400, detail="target_seat names whose graveyard",
            )
        if not session.game.confirm_trigger_target(
            req.seat, seat=req.target_seat, graveyard_index=req.graveyard_index,
        ):
            raise HTTPException(status_code=400, detail="invalid graveyard target")
        return
    if req.target_permanent_id is None and req.target_seat is None:
        raise HTTPException(
            status_code=400,
            detail="target_permanent_id, target_seat or target_stack_index is required",
        )
    # Checked against the list the prompt offered, not against the board:
    # CR 603.3d chose the targets as the ability went on the stack.
    ok = session.game.confirm_trigger_target(
        req.seat,
        permanent_id=req.target_permanent_id,
        seat=req.target_seat if req.target_permanent_id is None else None,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")

@action_handler("reflexive_target_confirm")
def _action_reflexive_target_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("reflexive_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no reflexive target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None:
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    # Checked against the list the prompt offered, not against the board:
    # CR 603.12's ability chose its targets when it was created.
    ok = session.game.confirm_reflexive_target(req.seat, req.target_permanent_id)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")

@action_handler("copy_spell_target_confirm")
def _action_copy_spell_target_confirm(session, req, seat_type):
    """CR 707.10: the copy's controller re-aiming it, by stable id or by seat.

    "Any target" is a player *or* a permanent (CR 115.4), so this answer carries
    either — and both are checked back against the list the prompt offered, so a
    client that invents a candidate is refused rather than obeyed.

    ``accept: false`` declines the offer (CR 707.10c's "may"): the copy keeps
    the original's target, whatever it is — the one answer a click on a
    candidate cannot give when that target is no longer legal.
    """
    pending = next(
        (c for c in session.game.pending_choices_of("copy_spell_target")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no copy target pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.accept is False:
        if not session.game.confirm_copy_spell_target(req.seat, keep=True):
            raise HTTPException(status_code=400, detail="invalid target")
        return
    if req.target_permanent_id is None and req.target_seat is None:
        raise HTTPException(
            status_code=400, detail="target_permanent_id or target_seat is required"
        )
    ok = session.game.confirm_copy_spell_target(
        req.seat,
        permanent_id=req.target_permanent_id,
        target_seat=req.target_seat,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid target")


@action_handler("permanent_choice_confirm")
def _action_permanent_choice_confirm(session, req, seat_type):
    # The general "a permanent chosen as the spell resolves" prompt. Answered by
    # stable id and re-checked by the engine against the live candidate rule, so
    # a client that offers a whole battlefield cannot widen the choice.
    pending = next(
        (c for c in session.game.pending_choices_of("permanent_choice")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no permanent choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if req.target_permanent_id is None and not pending.data.get("optional"):
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    # A missing id is a *decline*, and only where the card printed one
    # (Takklemaggot's "If they don't"). The engine re-checks the same flag, so a
    # client that omits the id on a mandatory choice is refused there too.
    if not session.game.confirm_permanent_choice(req.seat, req.target_permanent_id):
        raise HTTPException(status_code=400, detail="invalid permanent choice")

@action_handler("permanent_set_choice_confirm")
def _action_permanent_set_choice_confirm(session, req, seat_type):
    # The plural of the prompt above: several permanents chosen as the effect
    # resolves, by stable id, re-checked by the engine against the same live
    # candidate rule and against the printed ceiling.
    pending = next(
        (c for c in session.game.pending_choices_of("permanent_set_choice")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no permanent choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal — "up to two" includes none. The engine refuses a
    # list that is too long or names something it did not offer, so a client
    # cannot widen the choice by sending more.
    if not session.game.confirm_permanent_set_choice(
        req.seat, req.target_permanent_ids or []
    ):
        raise HTTPException(status_code=400, detail="invalid permanent selection")

@action_handler("keep_permanents_confirm")
def _action_keep_permanents_confirm(session, req, seat_type):
    # Cataclysm / Limited Resources: the permanents this seat *keeps*, by stable
    # id. The engine re-checks them against the same pool rule the prompt was
    # rendered from: each answers a slot of its own, and no printed slot the
    # seat can answer is left out — so a client cannot keep more than the card
    # offers, or skip a choice it makes the seat take. Fewer is legal where one
    # permanent answers several slots (the cards' rulings), and only there.
    pending = next(
        (c for c in session.game.pending_choices_of("keep_permanents")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no keep choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_keep_permanents(
        req.seat, req.target_permanent_ids or []
    ):
        raise HTTPException(status_code=400, detail="invalid keep selection")

@action_handler("tap_any_number_confirm")
def _action_tap_any_number_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("tap_any_number")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no tap choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal: "any number" includes none, and the card says
    # "you **may**". The engine re-checks every id against the same list the
    # prompt offered, so a stale pick is refused rather than silently
    # dropped.
    ok = session.game.confirm_tap_any_number(req.seat, req.target_permanent_ids or [])
    if not ok:
        raise HTTPException(status_code=400, detail="invalid tap selection")

@action_handler("untap_up_to_confirm")
def _action_untap_up_to_confirm(session, req, seat_type):
    pending = next(
        (c for c in session.game.pending_choices_of("untap_up_to")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no untap choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # An empty list is legal — "up to" includes zero (CR 601.2c's cousin
    # on resolution); the ids ride the same field every other action uses.
    ok = session.game.confirm_untap_up_to(req.seat, req.target_permanent_ids or [])
    if not ok:
        raise HTTPException(status_code=400, detail="invalid untap selection")

@action_handler("aggregate_sacrifice_confirm")
def _action_aggregate_sacrifice_confirm(session, req, seat_type):
    # Phyrexian Dreadnought: the whole set at once, addressed by stable id. The
    # engine re-checks it against the same candidate rule the prompt was drawn
    # from *and* against the printed floor -- an answer under the floor is not a
    # cheaper payment, it is no payment, so it is refused rather than applied.
    pending = next(
        (c for c in session.game.pending_choices_of("aggregate_sacrifice")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no sacrifice choice pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    # `target_permanent_ids` is the field the set picker beside this one
    # already carries for the same shape of answer -- a second field meaning
    # "the permanents this answer names" is a second answer to it.
    if req.target_permanent_ids is None:
        raise HTTPException(
            status_code=400, detail="target_permanent_ids is required"
        )
    if not session.game.confirm_aggregate_sacrifice(
        req.seat, req.target_permanent_ids
    ):
        raise HTTPException(status_code=400, detail="that set does not pay the cost")


@action_handler("face_down_cast_confirm")
def _action_face_down_cast_confirm(session, req, seat_type):
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

@action_handler("opponent_damage_choose")
def _action_opponent_damage_choose(session, req, seat_type):
    # Cuombajj Witches: the opposing chooser picks any target for the second
    # damage packet — a player face (``target_seat`` alone) or a creature by
    # its ``valid_targets`` entry's ``id`` (``answered_permanent_id``).
    pending = session.game.pending_opponent_damage
    if pending is None or pending.get("chooser_index") != req.seat:
        raise HTTPException(status_code=400, detail="no opponent damage choice is pending for you")
    if req.target_seat is None or not (0 <= req.target_seat < len(session.game.players)):
        raise HTTPException(status_code=400, detail="target_seat is required")
    permanent_id = answered_permanent_id(session.game, req, id_field="target_permanent_id",
                                         slot_field="target_permanent_index", seat=req.target_seat)
    if not session.game.confirm_opponent_damage_choice(req.seat, req.target_seat, permanent_id=permanent_id):
        raise HTTPException(status_code=400, detail="failed to resolve the damage choice")

@action_handler("mode_choice_confirm")
def _action_mode_choice_confirm(session, req, seat_type):
    # A modal ability (Relic Bind, Trufflesnout, Elder Gargaroth): the
    # controller picks a mode (hand_index = position in the offered list) and,
    # for a mode that targets, that mode's target in the same answer - CR
    # 700.2b and CR 601.2c make them one announcement, so sending them apart
    # would leave the ability on the stack half-announced.
    #
    # The target is named by stable id for an object and by seat for a player,
    # and the engine matches it against the very list this prompt offered.
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (mode index) is required")
    target = None
    if req.target_permanent_id is not None or req.target_seat is not None:
        target = {"permanent_id": req.target_permanent_id, "seat": req.target_seat}
    if not session.game.resolve_pending_choice(
        "mode_choice", req.seat, mode_index=req.hand_index, target=target
    ):
        raise HTTPException(
            status_code=400,
            detail="no mode choice is pending for you, or that mode and target are not offered",
        )

@action_handler("opponent_mode_choice_confirm")
def _action_opponent_mode_choice_confirm(session, req, seat_type):
    # "An opponent chooses one -" (Fatal Lore, Library of Lat-Nam, Misfortune):
    # CR 700.2e hands the mode to a player who is not the caster, and CR 601.2b
    # puts the choice inside the announcement - so this arrives while the spell
    # is already on the stack and nobody has had priority.
    #
    # A mode index and nothing else — unlike `mode_choice_confirm` above, which
    # carries the mode's target because there the same seat picks both. Here
    # they are two players, so the caster's targets arrive afterwards through
    # `modal_mode_targets_confirm` below (CR 601.2c after CR 601.2b).
    if req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index (mode index) is required")
    if not session.game.resolve_pending_choice(
        "opponent_mode_choice", req.seat, mode_index=req.hand_index
    ):
        raise HTTPException(
            status_code=400,
            detail="no opponent mode choice is pending for you, or that mode is not offered",
        )

@action_handler("modal_mode_targets_confirm")
def _action_modal_mode_targets_confirm(session, req, seat_type):
    # The other half of the prompt above (Fatal Lore). CR 601.2c names the
    # targets *after* CR 601.2b picks the mode, and on this card those two steps
    # belong to different players — so the caster answers here, once the
    # opponent's mode is known, still inside the announcement nobody has had
    # priority in.
    #
    # By stable id and as a list: "up to two" is a ceiling, and an empty list is
    # a legal answer. The engine re-checks every id against the list it offered,
    # so a client cannot widen the announcement by sending more.
    pending = next(
        (c for c in session.game.pending_choices_of("modal_mode_targets")),
        None,
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no modal targets pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    if not session.game.confirm_modal_mode_targets(
        req.seat, req.target_permanent_ids or []
    ):
        raise HTTPException(status_code=400, detail="invalid target selection")

@action_handler("loyalty_recipient_confirm")
def _action_loyalty_recipient_confirm(session, req, seat_type):
    # Liliana's Scrounger: which planeswalker the loyalty counter lands on.
    # Answered by stable id — the engine re-checks it against the live
    # candidate set — never by battlefield slot.
    if req.target_permanent_id is None:
        raise HTTPException(status_code=400, detail="target_permanent_id is required")
    if not session.game.confirm_loyalty_recipient(req.seat, req.target_permanent_id):
        raise HTTPException(status_code=400, detail="invalid loyalty-counter recipient")

@action_handler("counter_distribution_confirm")
def _action_counter_distribution_confirm(session, req, seat_type):
    # Forgotten Ancient: how many counters onto which creatures, as one answer
    # — the shape a divided announcement already arrives in
    # (``divided_targets``: a creature by ``id`` and its ``amount``). An
    # absent or empty list moves none, which "any number" allows. The engine
    # holds every id to the live candidates and the total to what the source
    # still has, so a client cannot move more than is there.
    pending = next(
        (c for c in session.game.pending_choices_of("counter_distribution")), None
    )
    if pending is None:
        raise HTTPException(status_code=400, detail="no counter distribution pending")
    if req.seat != pending.player_index:
        raise HTTPException(status_code=400, detail="not your choice")
    ids, amounts = [], []
    for entry in req.divided_targets or []:
        if entry.id is None or entry.amount is None:
            raise HTTPException(
                status_code=400,
                detail="each entry names a creature by id and how many counters",
            )
        ids.append(entry.id)
        amounts.append(entry.amount)
    if not session.game.confirm_counter_distribution(req.seat, ids, amounts):
        raise HTTPException(status_code=400, detail="invalid counter distribution")

@action_handler("player_choice_confirm")
def _action_player_choice_confirm(session, req, seat_type):
    # Backdraft: "Choose a player who cast one or more sorcery spells this
    # turn." The engine re-checks the seat against the offered list, so a stale
    # answer is refused rather than applied to whoever now sits there.
    if req.chosen_seat is None:
        raise HTTPException(status_code=400, detail="chosen_seat is required")
    if not session.game.confirm_player_choice(req.seat, req.chosen_seat):
        raise HTTPException(status_code=400, detail="invalid player choice")

@action_handler("cast_choice_confirm")
def _action_cast_choice_confirm(session, req, seat_type):
    # Backdraft: which of the offered spells "one of those" names, by its
    # position in the turn's cast ledger.
    if req.cast_index is None:
        raise HTTPException(status_code=400, detail="cast_index is required")
    if not session.game.confirm_cast_choice(req.seat, req.cast_index):
        raise HTTPException(status_code=400, detail="invalid spell choice")

@action_handler("madness_cast_confirm")
def _action_madness_cast_confirm(session, req, seat_type):
    """Madness (CR 702.35a): "its owner may cast it by paying [cost] rather
    than paying its mana cost. If that player doesn't, they put this card into
    their graveyard."

    ``accept`` false declines. True casts the exiled card, announced on the
    same fields an ordinary ``cast`` carries (targets, X, mode, division) and
    forwarded through the same plumbing (``_queue_spell_from_request``), out of
    exile and for the madness cost — so the client's cast dialog is the one it
    already has. The cast is made **during the trigger's resolution**
    (CR 608.2g): there is no priority to hold and no timing to check, which is
    why this is not the ``cast`` route and asks neither. A cast the engine
    refuses (unpaid mana, a missing target) is a 400 with the engine's own
    reason, and the offer stays open.
    """
    if req.accept is None:
        raise HTTPException(status_code=400, detail="accept is required")
    game = session.game
    if not req.accept:
        if not game.confirm_madness_cast(req.seat, False):
            raise HTTPException(status_code=400, detail="no madness cast is offered to you")
        return
    choice = game.pending_choice_of("madness_cast", req.seat)
    if choice is None:
        raise HTTPException(status_code=400, detail="no madness cast is offered to you")
    card_name = req.card_name or choice.data.get("card_name") or ""
    announced = req.model_copy(update={"from_zone": "exile", "alternative_cost": True})

    def perform(table):
        return _queue_spell_from_request(
            table, req.seat, card_name, announced, x_value=req.x_value,
        )

    outcome: list = []
    if not game.confirm_madness_cast(req.seat, True, perform=perform, outcome=outcome):
        detail = (
            outcome[-1].details if outcome and getattr(outcome[-1], "details", None)
            else "the madness cast was refused"
        )
        raise HTTPException(status_code=400, detail=detail)


@action_handler("retarget_choice_confirm")
def _action_retarget_choice_confirm(session, req, seat_type):
    # Deflection: which legal target replaces the one the spell announced, by
    # its position in the offered list. The engine re-checks that position
    # against the candidates that are *still* legal (CR 115.7a), so an answer
    # naming a creature that has since died is refused rather than applied to
    # whatever slid into its place.
    if req.target_index is None:
        raise HTTPException(status_code=400, detail="target_index is required")
    if not session.game.confirm_retarget_choice(req.seat, req.target_index):
        raise HTTPException(status_code=400, detail="invalid target choice")

@action_handler("word_of_command_confirm")
def _action_word_of_command_confirm(session, req, seat_type):
    # Word of Command: the caster records the card the target must play
    # (accept=False / no hand_index declines). The spell stays on the stack
    # and finishes resolving when priority is next released.
    if req.accept is False:
        hand_index = -1
    elif req.hand_index is None:
        raise HTTPException(status_code=400, detail="hand_index is required")
    else:
        hand_index = req.hand_index
    # `card_name` is the spell the chosen card is to be cast as — which half,
    # for a split card (CR 709.3; the caster chooses, CR 723.5). The prompt
    # lists each half under the card's `faces`.
    pending = session.game.pending_word_of_command
    if pending is not None and pending.get("caster_index") == req.seat and hand_index >= 0:
        hand = session.game.players[pending["target_index"]].hand
        if hand_index < len(hand):
            refusal = choose_a_face_refusal(hand[hand_index])
            if refusal is not None and spell_named(hand[hand_index], req.card_name or "") is None:
                raise HTTPException(status_code=400, detail=refusal)
    ok = session.game.confirm_word_of_command(
        req.seat, hand_index, defer_resolution=True, spell_name=req.card_name,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="no Word of Command pending for you")

@action_handler("balance_confirm")
def _action_balance_confirm(session, req, seat_type):
    pending = session.game.pending_balance
    if pending is None or req.seat not in pending["plans"]:
        raise HTTPException(status_code=400, detail="no balance choice pending for you")
    # The round's permanents by id, each offered entry's (or by slot).
    land_indices, creature_indices = balance_round_slots(session.game, req)
    ok = session.game.confirm_balance(
        req.seat,
        land_indices=land_indices,
        creature_indices=creature_indices,
        hand_indices=req.discard_indices or [],
    )
    if not ok:
        raise HTTPException(status_code=400, detail="invalid balance selection (wrong number of cards)")

@action_handler("sacrifice_confirm")
def _action_sacrifice_confirm(session, req, seat_type):
    # The seat's own prompt, not the first one queued: a prompt owed by
    # another seat is not a reason to refuse this one.
    if session.game.pending_choice_of("sacrifice", req.seat) is None:
        raise HTTPException(status_code=400, detail="no sacrifice pending for you")
    # A beginning phase this sacrifice paused resumes from the action tail in
    # web/actions.py, along with every other prompt's — the resume used to live
    # here, which is why a phase paused on any other decision stayed paused.
    if req.sacrifice_permanent_ids is not None:
        ok = session.game.confirm_sacrifice(
            req.seat, permanent_ids=list(req.sacrifice_permanent_ids),
        )
    else:
        ok = session.game.confirm_sacrifice(req.seat, list(req.sacrifice_indices or []))
    if not ok:
        raise HTTPException(status_code=400, detail="invalid sacrifice selection")

@action_handler("order_triggers_confirm")
def _action_order_triggers_confirm(session, req, seat_type):
    # CR 603.3b: the seat orders the triggered abilities it put on the stack
    # together. A list that is not a permutation of the offered ones is
    # refused and the prompt stays owed.
    if session.game.pending_choice_of("order_triggers", req.seat) is None:
        raise HTTPException(status_code=400, detail="no trigger order pending for you")
    if req.trigger_order is None:
        raise HTTPException(status_code=400, detail="trigger_order is required")
    if not session.game.confirm_order_triggers(req.seat, req.trigger_order):
        raise HTTPException(status_code=400, detail="invalid trigger order")

@action_handler("target_group_order_confirm")
def _action_target_group_order_confirm(session, req, seat_type):
    # Kaboom!'s ruling: the order within each player's group of targets. An
    # order that is not every target once, groups in turn order, is refused
    # and the prompt stays owed.
    if req.target_order is None:
        raise HTTPException(status_code=400, detail="target_order is required")
    if not session.game.confirm_target_group_order(req.seat, req.target_order):
        raise HTTPException(status_code=400, detail="no such target order pending for you")
