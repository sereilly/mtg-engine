"""The cast plumbing the normal cast and the debug free-casts share.

``_queue_spell_from_request`` forwards every targeting field on the request in
one place, so the paths can never drift on which parameters they pass (colors
for text-change spells, the chosen stack target, modal modes, X, multi-target
lists, divided damage). The lookup helpers beside it are the request-to-board
resolution the action handlers speak in.
"""

from __future__ import annotations

from fastapi import HTTPException

from engine.models import Permanent, PlayerState


def _default_target(card_name: str, caster_index: int) -> int:
    if card_name in {"Ancestral Recall", "Healing Salve", "Stream of Life"}:
        return caster_index
    return 1 - caster_index

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
    target = req.target_seat if req.target_seat is not None else _default_target(card_name, seat)
    # Cross-seat divided targets (Fireball): (seat, index|None) pairs; an index
    # of None is that player's face.
    # A three-tuple only where a share was announced (CR 601.2d): the two-tuple
    # is what every evenly-divided spell and every non-interactive caller sends,
    # and `engine/divided_damage.divided_entry` reads both.
    divided = (
        [
            (entry.seat, entry.index)
            if entry.amount is None
            else (entry.seat, entry.index, entry.amount)
            for entry in req.divided_targets
        ]
        if req.divided_targets
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
        cost_permanent_ids=req.cost_permanent_ids,
        cost_hand_index=req.cost_hand_index,
        # CR 118.9's announcement, on its own pair of fields for the reason the
        # cost fields above are on theirs: an alternative cost and an additional
        # cost can both apply to one cast (CR 118.9d), so one field could not
        # say which price a click answered.
        alternative_cost=req.alternative_cost,
        alternative_cost_hand_index=req.alternative_cost_hand_index,
        # …and CR 601.2b's optional additional cost, forwarded whole for the
        # reason every cost field here is: dropped, the spell resolves having
        # quietly declined a price the caller announced, and the effect that
        # reads the count back does nothing.
        optional_cost_payments=req.optional_cost_payments,
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
