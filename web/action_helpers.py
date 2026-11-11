"""The cast plumbing the normal cast and the debug free-casts share.

``_queue_spell_from_request`` forwards every targeting field on the request in
one place, so the paths can never drift on which parameters they pass (colors
for text-change spells, the chosen stack target, modal modes, X, multi-target
lists, divided damage). The lookup helpers beside it are the request-to-board
resolution the action handlers speak in.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.faces import spell_named
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.ai_target_sides import cast_helps_the_player_it_names
from engine.target_keywords import (BATTLEFIELD, ability_target_zone,
                                    cast_target_zone, slot_keywords)
from engine.targeting import derive_activation_spec

_GONE = "that permanent is no longer on the battlefield"


def wire_target_keywords(
    game, zone: str, announcer: int, seat, *, ids=None, slot=None,
    graveyard_indices=None,
) -> dict:
    """A request's target as the engine's zone keywords
    (``engine/target_keywords``): ``target_graveyard_indices`` as the client
    sent it, the permanent ids as they came (the preamble has 404'd a stale
    one), and otherwise **the old slot fields** — ``target_permanent_index``,
    ``target_permanent_indices``, a cast's ``permanent_index`` — accepted for
    one more round and read in the zone the card names its target in
    (*zone*): a graveyard card by its place, a permanent by the id of what
    stands in that slot now. A battlefield slot that holds nothing is the 404
    a stale id is, never an announcement of nothing.

    The one place the wire's target reaches the engine: no slot is handed on.
    """
    if graveyard_indices is not None:
        return {"target_graveyard_indices": list(graveyard_indices)}
    if ids is not None:
        return {"target_permanent_ids": list(ids)}
    if slot is None:
        return {}
    keywords = slot_keywords(game, zone, announcer, seat, slot)
    if any(pid is None for pid in keywords.get("target_permanent_ids") or ()):
        raise HTTPException(status_code=404, detail=_GONE)
    return keywords


def request_target_ids(req) -> "list[int] | None":
    """The permanents a request names as its targets by id: the list, or
    the one, or None."""
    if req.target_permanent_ids is not None:
        return list(req.target_permanent_ids)
    if req.target_permanent_id is not None:
        return [req.target_permanent_id]
    return None


def activation_zone(game, permanent, ability_index) -> str:
    """The zone the activation of *permanent*'s ability names its target
    in — the ability ``ability_index`` names among its usable ones, or (none
    named) the first that chooses anything: the ability whose spec the
    client's picker read (``Game.activation_target_spec``)."""
    usable = game.usable_abilities_of(permanent, card=permanent.effective_card)
    if ability_index is not None:
        chosen = usable[ability_index] if 0 <= ability_index < len(usable) else None
    else:
        chosen = next((a for a in usable if derive_activation_spec(a) is not None), None)
    return BATTLEFIELD if chosen is None else ability_target_zone(chosen)


def _default_target(game, caster_index: int, card_name: str, req) -> int:
    """The seat a cast that named none is aimed at: the caster's own where the
    spell **gives** something to the player it names, the opposing one
    otherwise.

    This was a set of three card names — Ancestral Recall, Healing Salve,
    Stream of Life — which is dispatch on a name in a package the engine's
    name guard does not walk. What the three have in common is in their
    compiled programs ("target player draws", "target player gains life", a
    damage shield), so that is what is asked
    (``ai_target_sides.cast_helps_the_player_it_names``, the derivation the AI's
    own tie-break between two seats reads), and Inspiration, Stroke of
    Genius and every other printing of those sentences stop defaulting to the
    opponent.

    The card is found where the request says it is being cast from; a card
    this cannot find keeps the opposing default, which is what the engine's
    own ``_spell_default_seat`` answers.
    """
    card = _spell_requested(game, caster_index, card_name, req)
    if card is not None and cast_helps_the_player_it_names(
        card, compile_card_oracle(card),
        mode_index=getattr(req, "mode_index", None),
    ):
        return caster_index
    return game._spell_default_seat(caster_index)

def _spell_requested(game, caster_index: int, card_name: str, req):
    """The spell the request casts, found where it says it is cast from
    (the named half of a split card), or None."""
    zone = getattr(req, "from_zone", None) or "hand"
    player = game.players[caster_index]
    pile = getattr(player, zone, None)
    if zone == "library":
        pile = (pile or [])[:1]
    return next(
        (
            spell for spell in (
                spell_named(held, card_name) for held in (pile or ())
            ) if spell is not None
        ),
        None,
    )


def _mode_target_keywords(game, card, caster_index: int, mode) -> dict:
    """One chosen mode's targets as the engine's zone keywords: its ids (each
    checked, a stale one the 404 the cast's own is), or its slot in the zone
    that mode names its target in (:func:`wire_target_keywords`)."""
    several = getattr(mode, "permanent_ids", None)
    if several and (mode.permanent_id is not None or mode.permanent_index is not None):
        raise HTTPException(
            status_code=422,
            detail="a mode names its permanents once: permanent_ids alone",
        )
    ids = list(several) if several else (
        [mode.permanent_id] if mode.permanent_id is not None else None
    )
    for permanent_id in ids or ():
        if game.find_permanent_by_id(permanent_id) is None:
            raise HTTPException(status_code=404, detail=_GONE)
    zone = (
        cast_target_zone(card, mode_index=mode.index) if card is not None else BATTLEFIELD
    )
    return wire_target_keywords(
        game, zone, caster_index, mode.target_seat, ids=ids, slot=mode.permanent_index,
    )


def _queue_spell_from_request(game, seat: int, card_name: str, req, *, x_value):
    """Queue a spell from ``seat``'s hand using every targeting field on the
    request, so the normal ``cast`` action and the debug free-cast paths share
    one code path and can never drift on which parameters they forward (colors
    for text-change spells, the chosen stack target, modal mode, X, multi-target
    lists). Callers prepare ``x_value`` and, for the free casts, inject the card
    into hand and toggle ``enforce_mana_costs`` around this call."""
    def _engine_stack_index(top_first):
        # The client sends a top-first stack index; the engine stack is
        # bottom-first. One converter, because a multi-mode spell may name a
        # stack object per mode and a second spelling of this arithmetic is a
        # second chance to get the direction wrong.
        if top_first is None:
            return None
        return len(game.stack) - 1 - top_first

    engine_stack_index = _engine_stack_index(req.target_stack_index)
    cast_card = _spell_requested(game, seat, card_name, req)
    # "Choose one or more —": each mode's own targets (CR 601.2c), forwarded as
    # the plain dicts the engine's ``_resolve_chosen_modes`` reads. The seat and
    # index keep the engine's names here rather than the wire's, so the
    # translation happens once, at the boundary.
    mode_choices = None
    if getattr(req, "mode_choices", None):
        mode_choices = [
            {
                "index": mode.index,
                "target_player_index": mode.target_seat,
                # Each mode's targets in the engine's zone keywords, checked
                # here at the boundary as the spell's own are: a stale id is a
                # 404, never a fall back to whatever now sits at an index.
                **_mode_target_keywords(game, cast_card, seat, mode),
                "target_stack_index": _engine_stack_index(mode.target_stack_index),
            }
            for mode in req.mode_choices
        ]
    # The cast's target in the engine's zone keywords (`wire_target_keywords`):
    # its ids — the list, the one, or a cast's ``permanent_id`` (which names
    # its target) — else the old slot fields, read in the zone the spell names
    # its target in. A several-target list wins over the one slot.
    target_ids = request_target_ids(req)
    if target_ids is None and req.permanent_id is not None:
        target_ids = [req.permanent_id]
    target_fields = wire_target_keywords(
        game,
        cast_target_zone(cast_card, mode_index=req.mode_index)
        if cast_card is not None else BATTLEFIELD,
        seat,
        req.target_seat,
        ids=target_ids,
        slot=(
            req.target_permanent_indices
            if req.target_permanent_indices is not None
            else (req.permanent_index if req.permanent_index is not None else req.target_permanent_index)
        ),
        graveyard_indices=req.target_graveyard_indices,
    )
    # **An empty roles announcement is "no target", not a bare cast.** "Any
    # number of target opponents" (Wheel and Deal) and "any number of target
    # players or planeswalkers" (Kaboom!) may name none (CR 601.2c), and
    # ``target_role_refs: []`` is how a client says so — the walk ended before
    # its first optional role. Without this the default seat below rode the
    # cast as its first target: a Kaboom! cast naming nobody went on the stack
    # aimed at the opponent. A walk whose first role is owed is still refused
    # by the engine's own gate ("requires N targets").
    names_no_role = req.target_role_refs is not None and len(req.target_role_refs) == 0
    target = (
        req.target_seat if req.target_seat is not None
        else None if names_no_role
        else _default_target(game, seat, card_name, req)
    )
    # A roles announcement whose slots are not all permanents (Donate's "target
    # player gains control of target permanent you control"). One entry per
    # role, in role order, **forwarded** as the plain dicts the engine's own
    # channel takes — the shape the activate branch in ``actions.py`` has
    # always forwarded, so a cast and an activation say "this slot is a
    # player" in the same words.
    #
    # This used to translate the refs here, onto the two channels a cast had:
    # the id list and **one** seat ("a third parameter on ``queue_from_hand``
    # would be a second spelling of an announcement it already takes"). One
    # seat is what could not say "target player … **another** target player"
    # (Cultural Exchange) — the second ref overwrote the first — so the
    # translation is the engine's now (``_role_announcement_stamps``, the one
    # an activation goes through), and what stays at the boundary is the part
    # that is about the wire: which end of the stack an index counts from.
    role_refs = None
    if req.target_role_refs:
        role_refs = []
        for ref in req.target_role_refs:
            if ref.seat is not None:
                role_refs.append({"seat": ref.seat})
                continue
            if ref.stack_index is not None:
                # A role whose object is a **spell on the stack** ("Counter
                # target spell and … deals 3 damage to target creature",
                # Suffocating Blast). The stack channel a cast already has:
                # the index, converted here like the request's own, and a
                # marker saying which slot it fills.
                engine_stack_index = _engine_stack_index(ref.stack_index)
                role_refs.append({"stack": True})
                continue
            if ref.graveyard_seat is not None:
                # A role whose object is a **card in a graveyard** ("Destroy
                # target non-Zombie creature. … Return up to one target Zombie
                # card from your graveyard to your hand.", Cruel Revival — the
                # first spell to print one). Forwarded as the address an
                # activation's role sends, and stamped by the same translation
                # (``_role_announcement_stamps``); the cast gate judges it
                # through the roles walk (``_named_role_targets``). It was
                # refused here while no spell printed the shape, rather than
                # turned into a hole in the id list.
                role_refs.append({
                    "graveyard_seat": ref.graveyard_seat,
                    "graveyard_index": ref.graveyard_index,
                })
                continue
            role_refs.append({"permanent_id": ref.permanent_id})
    # Cross-seat divided targets (Fireball): (seat, index|None) pairs; an index
    # of None is that player's face.
    # A three-tuple only where a share was announced (CR 601.2d): the two-tuple
    # is what every evenly-divided spell and every non-interactive caller sends,
    # and `engine/divided_damage.divided_entry` reads both.
    #
    # **An empty list is forwarded as one**, not as an absent field: "each of
    # up to three targets" (Shower of Coals) may be cast naming nobody
    # (CR 115.6), and `[]` is how a client says so — the default seat below
    # rides every cast, so without the list the engine reads a face. For every
    # other spell an empty list and an absent one are the same announcement.
    divided = (
        [
            (entry.seat, entry.index)
            if entry.amount is None
            else (entry.seat, entry.index, entry.amount)
            for entry in req.divided_targets
        ]
        if req.divided_targets is not None
        else None
    )
    return game.queue_from_hand(
        seat,
        card_name,
        target_player_index=target,
        # The targets by stable identity (or a graveyard card by its place):
        # a pair of targets may sit on two battlefields, which no slot on one
        # `target_seat` can say — Rookie Mistake was half-castable in the
        # browser while this forwarded a slot beside its ids.
        **target_fields,
        # …or the same announcement one role at a time (see above). Where
        # present it is the announcement, and the engine derives the id list
        # and the seat(s) from it.
        target_role_refs=role_refs,
        x_value=x_value,
        new_color=req.mana_color,
        mana_combination=req.mana_combination,
        target_stack_index=engine_stack_index,
        mode_index=req.mode_index,
        mode_choices=mode_choices,
        old_color=req.old_color,
        divided_targets=divided,
        from_zone=req.from_zone or "hand",
        use_free_permission=req.use_free_permission,
        # A printed additional cost's payment (CR 601.2b). Its own field, not
        # the target one, for the reason `cost_permanent_id`'s comment in
        # schemas.py gives about activation: a spell can have both a target and
        # a cost, and overloading one field would make the cost eat the
        # creature the spell was aimed at.
        cost_permanent_index=req.cost_permanent_index,
        # And the same choice for a cost that eats more than one permanent
        # (Phyrexian Tribute): one index cannot name two victims, so the id list
        # the activation path has always forwarded is forwarded here too.
        #
        # **A single ``cost_permanent_id`` travels as an id as well.** The
        # request resolver turns it into a bare slot and writes no seat beside
        # it, and the engine counts a cost slot into the *caster's*
        # battlefield — so an id naming somebody else's creature arrived as
        # whatever the caster held in that slot. The engine refuses a named
        # payment that cannot pay (``_named_cast_cost_refusal``, CR 601.2h),
        # and it can only refuse what it is told was named; the activation
        # branch of ``web/actions.py`` forwards its cost id for this reason.
        cost_permanent_ids=(
            req.cost_permanent_ids
            if req.cost_permanent_ids is not None
            or getattr(req, "cost_permanent_id", None) is None
            else [req.cost_permanent_id]
        ),
        cost_hand_index=req.cost_hand_index,
        # …and which cards in the caster's graveyard pay "exile X cards from
        # your graveyard" (Skeletal Scrying, Haunting Misery), by slot, on the
        # field the activation branch already forwards for Psychatog. The
        # engine holds a named set to the count (CR 601.2h) and takes the top
        # of the pile for a cast that names none, so an absent field is every
        # cast a client that does not know the field makes today.
        cost_graveyard_indices=req.cost_graveyard_indices,
        # …and the further cards of a "discard two cards" cost (Forbid's
        # buyback), on the activation path's field.
        cost_other_hand_indices=req.cost_other_hand_indices,
        # CR 118.9's announcement, on its own pair of fields for the reason the
        # cost fields above are on theirs: an alternative cost and an additional
        # cost can both apply to one cast (CR 118.9d), so one field could not
        # say which price a click answered.
        alternative_cost=req.alternative_cost,
        alternative_cost_hand_index=req.alternative_cost_hand_index,
        alternative_cost_permanent_ids=req.alternative_cost_permanent_ids,
        alternative_cost_other_hand_indices=req.alternative_cost_other_hand_indices,
        alternative_cost_index=req.alternative_cost_index,
        # …and CR 601.2b's optional additional cost, forwarded whole for the
        # reason every cost field here is: dropped, the spell resolves having
        # quietly declined a price the caller announced, and the effect that
        # reads the count back does nothing.
        optional_cost_payments=req.optional_cost_payments,
        # …and CR 601.2b's choice-shaped price, forwarded for the same reason:
        # dropped, the cast silently takes the engine's default and the one
        # choice Caller of the Hunt is about is made by nobody.
        chosen_creature_type=req.chosen_creature_type,
        # …and the copy-as-it-enters "may" declined (Clone, Sculpting Steel),
        # forwarded for the same reason: dropped, a cast naming no copy target
        # copies the first permanent of the type, which is the answer the
        # player just refused.
        decline_copy=getattr(req, "decline_copy", None),
        # CR 609.7a's "a source of your choice", on its own trio of fields for
        # the reason the cost fields above are on theirs: a spell may name a
        # source *and* its own targets (Kor Chant names two), so one field could
        # not say which answer a click was. The wire's names keep the engine's
        # `chosen_` prefix here — `source_seat` is already a local inside
        # `_cast_onto_stack`, meaning the zone the spell is leaving.
        #
        # The stack index goes through `_engine_stack_index` with the target's,
        # and for the same reason it exists: the client counts the stack
        # top-first and the engine bottom-first, and a second spelling of the
        # arithmetic is a second chance to get the direction wrong. The activate
        # branch in `actions.py` writes its own copy of it, which is the
        # duplication this one avoids.
        chosen_source_seat=req.source_seat,
        chosen_source_permanent_index=req.source_permanent_index,
        chosen_source_stack_index=_engine_stack_index(req.source_stack_index),
    )

def _find_card_in_hand(player: PlayerState, card_name: str):
    """The spell *card_name* names out of *player*'s hand, or None.

    ``spell_named`` rather than a name comparison: a split card is cast by the
    name of one of its halves (CR 709.3, CR 709.4a), and what comes back is
    that half — the card the timing gates below the caller must judge
    (CR 709.3a), not the two-spell card it is printed on.
    """
    return next(
        (
            spell for spell in (spell_named(card, card_name) for card in player.hand)
            if spell is not None
        ),
        None,
    )

def _answers_to_name(permanent: Permanent, name: str) -> bool:
    """Whether *name* is one a request may name *permanent* by: the name it has
    (CR 707.2 — a copy's is the copied object's, which is what the wire sends
    as ``name``) or the card it is printed on (the wire's ``printed_name``,
    which a client written before the copy's name moved still sends)."""
    return name in (permanent.effective_card.name, permanent.card.name)


def _find_controlled_permanent(
    player: PlayerState,
    permanent_name: str | None,
    permanent_index: int | None,
) -> tuple[int, Permanent] | None:
    if permanent_index is not None:
        if permanent_index < 0 or permanent_index >= len(player.battlefield):
            return None
        permanent = player.battlefield[permanent_index]
        if permanent_name and not _answers_to_name(permanent, permanent_name):
            return None
        return permanent_index, permanent

    if permanent_name is None:
        return None

    for idx, permanent in enumerate(player.battlefield):
        if _answers_to_name(permanent, permanent_name):
            return idx, permanent
    return None


# ---------------------------------------------------------------------------
# A prompt's answer names permanents by id (CR 400.7)
# ---------------------------------------------------------------------------


def answered_permanent_id(game, req, *, id_field: str, slot_field: str, seat: int) -> int | None:
    """The permanent a prompt's answer names, by ``permanent_id``.

    *id_field* where the request carries it — the address every offered entry
    gives, already resolved by ``web.actions._resolve_permanent_ids`` (which
    404s a stale one). Else the slot in *slot_field* on *seat*'s battlefield,
    turned into the id of what is in that slot **now**: the alternative a
    client written against slots still sends, read once, on arrival, and
    never stored or handed on. None where the request names neither; a slot
    that names nothing is a 404, as a stale id is.
    """
    permanent_id = getattr(req, id_field)
    if permanent_id is not None:
        return permanent_id
    slot = getattr(req, slot_field)
    if slot is None:
        return None
    named = game.permanent_at(seat, slot)
    if named is None:
        raise HTTPException(status_code=404, detail="that permanent is no longer on the battlefield")
    return named.permanent_id


def own_slots_of(game, seat: int, permanent_ids) -> list[int]:
    """*permanent_ids* (deduplicated, in order) as slots on *seat*'s own
    battlefield, for an engine entry point that still counts by slot — read
    on arrival, against the board that entry point is about to read. An id
    naming a permanent the seat does not control is refused (400); a stale
    one never gets here (the dispatch preamble's 404)."""
    slots = []
    for permanent_id in dict.fromkeys(permanent_ids):
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None or not game.controls(seat, permanent):
            raise HTTPException(status_code=400, detail="that permanent is not one you were offered")
        slots.append(game.battlefield_index_of(permanent))
    return slots


def balance_round_slots(game, req) -> tuple[list[int], list[int]]:
    """``(land slots, creature slots)`` of a ``balance_confirm`` answer.

    By id (``target_permanent_ids``, each offered entry's ``id``): the lands in
    Balance's lands round, the creatures in its creatures round — one round is
    answered at a time — turned into the seat's slots on arrival, the board
    the engine's check reads (``own_slots_of``). Absent, the slot fields a
    client written against slots still sends."""
    lands = list(req.land_indices or [])
    creatures = list(req.creature_indices or [])
    if req.target_permanent_ids is None:
        return lands, creatures
    choice = game.pending_choice_of("balance", req.seat)
    stage = choice.data.get("stage") if choice is not None else None
    if stage not in ("lands", "creatures"):
        raise HTTPException(status_code=400, detail="this Balance round chooses no permanents")
    slots = own_slots_of(game, req.seat, req.target_permanent_ids)
    return (slots, creatures) if stage == "lands" else (lands, slots)
