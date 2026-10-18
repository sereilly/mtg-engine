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
from engine.targeting import cast_helps_the_player_it_names


def _default_target(game, caster_index: int, card_name: str, req) -> int:
    """The seat a cast that named none is aimed at: the caster's own where the
    spell **gives** something to the player it names, the opposing one
    otherwise.

    This was a set of three card names — Ancestral Recall, Healing Salve,
    Stream of Life — which is dispatch on a name in a package the engine's
    name guard does not walk. What the three have in common is in their
    compiled programs ("target player draws", "target player gains life", a
    damage shield), so that is what is asked
    (``targeting.cast_helps_the_player_it_names``), and Inspiration, Stroke of
    Genius and every other printing of those sentences stop defaulting to the
    opponent.

    The card is found where the request says it is being cast from; a card
    this cannot find keeps the opposing default, which is what the engine's
    own ``_spell_default_seat`` answers.
    """
    zone = getattr(req, "from_zone", None) or "hand"
    player = game.players[caster_index]
    pile = getattr(player, zone, None)
    if zone == "library":
        pile = (pile or [])[:1]
    card = next(
        (
            spell for spell in (
                spell_named(held, card_name) for held in (pile or ())
            ) if spell is not None
        ),
        None,
    )
    if card is not None and cast_helps_the_player_it_names(
        card, compile_card_oracle(card),
        mode_index=getattr(req, "mode_index", None),
    ):
        return caster_index
    return game._spell_default_seat(caster_index)

def _mode_target_index(game, mode):
    """The battlefield slot one chosen mode named, preferring its stable id.

    A mode is chosen as the spell is cast and the spell then waits on the stack,
    so the slot it names can renumber underneath it (CR 400.7). The client sends
    the id when it resolved one; an id that no longer names a permanent yields
    None rather than the index beside it, because the index is a *position* and
    the permanent that position now holds is a different object.
    """
    if mode.permanent_id is not None:
        found = game.find_permanent_by_id(mode.permanent_id)
        if found is None:
            # A 404, exactly as the preamble makes for the spell's own target:
            # returning None here would leave the mode with the *index* beside
            # it, which by now addresses whichever permanent slid into the
            # vacated slot. Refusing the whole cast is the honest answer, and
            # it is the one the rest of this protocol already gives.
            raise HTTPException(
                status_code=404,
                detail="that permanent is no longer on the battlefield",
            )
        _seat, permanent = found
        return game.battlefield_index_of(permanent)
    return mode.permanent_index

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
                # The id is resolved to a slot here, at the boundary, exactly as
                # the spell's own target is: a stale id is a refusal further in,
                # never a fall back to whatever now sits at the index.
                "target_permanent_index": _mode_target_index(game, mode),
                "target_stack_index": _engine_stack_index(mode.target_stack_index),
            }
            for mode in req.mode_choices
        ]
    # Fireball-style multi-target spells send a list; it wins over permanent_index.
    # ``target_permanent_index`` is accepted as the same thing: it is what
    # ``target_permanent_id`` normalizes to, and a cast's target has no reason to
    # be spelled differently from every other action's target.
    permanent_target = (
        req.target_permanent_indices
        if req.target_permanent_indices is not None
        else (req.permanent_index if req.permanent_index is not None else req.target_permanent_index)
    )
    target = (
        req.target_seat if req.target_seat is not None
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
                # No **spell** in the pool names a slot in a graveyard — the one
                # ability that does is activated, and its path stamps the pile
                # itself (``_role_announcement_stamps``). Refused loudly rather
                # than translated to a hole in the id list, which the
                # announcement gate would decline as "no valid target" and
                # leave a client author reading the wrong sentence.
                raise HTTPException(
                    status_code=400,
                    detail="a cast cannot name a graveyard slot for a role",
                )
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
        target_permanent_index=permanent_target,
        # The same targets by stable identity. The preamble above resolves these
        # off the wire and deliberately *keeps* them, because a pair of targets
        # may sit on two battlefields and `target_permanent_index` is positional
        # on one `target_seat` — and then this function dropped them, so every
        # cross-board cast over HTTP lost its second slot and resolved as an
        # index on the first slot's board. Rookie Mistake has been half-castable
        # in the browser since round 65 for exactly this reason; the engine and
        # the activation path (below) had it right the whole time.
        target_permanent_ids=req.target_permanent_ids,
        # …or the same announcement one role at a time (see above). Where
        # present it is the announcement, and the engine derives the id list
        # and the seat(s) from it.
        target_role_refs=role_refs,
        x_value=x_value,
        new_color=req.mana_color,
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
        # …and CR 601.2b's optional additional cost, forwarded whole for the
        # reason every cost field here is: dropped, the spell resolves having
        # quietly declined a price the caller announced, and the effect that
        # reads the count back does nothing.
        optional_cost_payments=req.optional_cost_payments,
        # …and CR 601.2b's choice-shaped price, forwarded for the same reason:
        # dropped, the cast silently takes the engine's default and the one
        # choice Caller of the Hunt is about is made by nobody.
        chosen_creature_type=req.chosen_creature_type,
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
