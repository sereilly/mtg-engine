"""What an announcement that **named no target** is taken to name.

CR 601.2c (and CR 602.2b, which sends an activation through it): "the player
announces their choice of an appropriate object or player for each target the
spell requires." A person at a client is asked — the browser cannot send the
action without an answer, and the wire refuses one that tries
(``legality_abilities.unannounced_activation_target``). A **headless** caller — a test, a
scripted duel, the AI simulator — may leave the target out, and for the life of
this engine that omission was answered at *resolution*, by whichever handler
ran: each one scanned a battlefield with its own predicate and took the first
permanent it met.

A handler's scan is not the picker. It knows what the sentence *names* and
nothing about what may be *targeted* — protection, shroud, "other than this
creature", "with flying", an attacker only — so a bare announcement could act
on a permanent its own picker does not offer (Burning Palm Efreet took flying
from a creature without it; Soul Sculptor, Angelic Shield and Ray of Command
reached a creature with protection or shroud). It was also several scans
rather than one: each sentence of a two-sentence card found its own first
match, so "destroy target creature. Its controller loses 2 life" killed a
creature and charged nobody, and Burning Palm Efreet's damage and its
flying-loss landed on two different creatures. And because the choice was made
by the handler, the stack object carried no target at all: nothing "became the
target", nothing could respond to the choice, and CR 608.2b had nothing to
re-check.

**The omission is answered here instead, once, as the object is announced.**
Every other decision a non-interactive seat owes in this engine is answered by
a registered default (``pending_choices``) rather than by refusing the action;
this is that default for a target. It is the **first entry of the picker's own
list** (``Game._enumerate_targets`` over the slot the announcement owes), read
in *standing order* — so it is by construction a target the gate would have
accepted by name, and it is stamped on the stack object exactly as a named one
is: ``announce_targets_chosen`` fires for it, CR 608.2b re-checks it, and no
handler is left to choose (``handlers/_common.pick_target_permanent`` has no
scan for an announced object).

**Standing order** is the seat an unnamed target has always been looked for
on, first: the seat the caller named beside no object (it is the battlefield
an index would have counted into), else the opposing seat
(``Game._spell_default_seat`` / ``_default_opposing_seat``). Within a seat the
picker's order is kept — a player's face before that player's permanents,
permanents in battlefield order — which is what makes a bare "any target" the
opposing player, as it always was. It is a statement about *where an unnamed
target is looked for*, never about what is good for the announcer: a bare
shield lands on the opposing seat's first creature exactly as a bare Terror
does, and a caller that means its own names it.

What is deliberately **not** defaulted, because each already has a refusal
that is the rule: a printed count of two or more and an announced X
(``legality.exact_target_count`` — naming fewer is an illegal announcement), a
several-role announcement, an Aura's enchant target, and a division
(CR 601.2d).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .legality import (
    activation_target_obligation, cast_target_obligation, exact_target_count,
    targeting_instruction,
)
from .oracle import compile_card_oracle
from .stack_targets import names_a_target
from .target_requirements import narrow_offer
from .targeting import (
    ROLES_TARGET_KIND, activation_target_slot, cast_target_slot,
    graveyard_target_spec, spec_offers_a_player, spec_roles,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game


def standing_order(offered: list[dict], standing_seat: int | None) -> list[dict]:
    """*offered* — a picker's ``valid_targets`` — with *standing_seat*'s
    entries first. A stable sort, so the picker's own order decides within a
    seat and among everything off it (a spell on the stack carries no seat and
    keeps its place: topmost first)."""
    return sorted(offered, key=lambda entry: entry.get("seat") != standing_seat)


def names_an_object(
    target_permanent_index, target_permanent_ids, target_stack_item,
    target_role_refs=None, divided_targets=None,
) -> bool:
    """Whether an announcement's fields name any object at all — the half of
    "did this name a target?" that does not depend on the spec. (A seat alone
    is a target only where the spec offers a player; the two default
    functions below ask, given the seat.)"""
    indices = (
        target_permanent_index
        if isinstance(target_permanent_index, list) else [target_permanent_index]
    )
    return bool(
        any(pid is not None for pid in (target_permanent_ids or ()))
        or any(index is not None for index in indices)
        or target_stack_item is not None
        or target_role_refs
        or divided_targets
    )


def _seat_is_the_target(spec: dict, named_seat) -> bool:
    """Whether a seat sent with no object beside it **is** the announcement's
    target: where the spec offers a player ("any target", "target player").
    Everywhere else it is only the battlefield an index would have counted
    into, and the announcement is still bare."""
    return named_seat is not None and spec_offers_a_player(spec)


def default_activation_target(
    game: "Game", controller_index: int, source_permanent, ability, *,
    named_seat: int | None = None, x_value: int | None = None,
) -> dict | None:
    """The picker entry a **bare activation** of *ability* is taken to name,
    or None when it owes no single target (or none is legal — the gate has
    refused that already).

    The list is the gate's own: the same ``_enumerate_targets`` call
    ``activation_target_refusal`` judges a named target by, over the same
    obligation (``activation_target_obligation``). *named_seat* is a seat the
    caller sent with no object beside it.
    """
    spec = activation_target_obligation(ability, x_value=x_value)
    if spec is None or spec.get("kind") == ROLES_TARGET_KIND:
        # A several-role announcement naming nothing is refused by the gate
        # (every role is announced, CR 601.2c), as the cast side refuses it.
        return None
    if _seat_is_the_target(spec, named_seat):
        return None
    slot = activation_target_slot(ability)
    if slot is not None and exact_target_count(spec, slot[1], x_value) is not None:
        return None
    card = getattr(source_permanent, "effective_card", source_permanent)
    source = source_permanent if hasattr(source_permanent, "permanent_id") else None
    offered = game._enumerate_targets(
        controller_index, card, dict(spec), for_cast=False,
        ability_instruction=targeting_instruction(
            getattr(ability, "instruction", None)
        ),
        source_permanent=source,
        ability_source=source,
    )
    if names_a_target(getattr(ability, "source_line", None)):
        # …out of what the activator may announce **now**: where an
        # opponent's Flagbearer narrows a one-target ability's legal
        # announcement to the Flagbearers it could name
        # (``target_requirements.narrow_offer``), the default is one of them —
        # the list the picker shows, not the list the requirement refuses.
        offered = narrow_offer(
            game, controller_index, {**spec, "valid_targets": offered}
        ).get("valid_targets") or []
    ordered = standing_order(
        offered,
        named_seat if named_seat is not None
        else game._default_opposing_seat(controller_index),
    )
    return ordered[0] if ordered else None


def default_cast_target(
    game: "Game", caster_index: int, card, *,
    named_seat: int | None = None, optional_cost_payments: dict | None = None,
    x_value: int | None = None, mode_index: int | None = None,
) -> "tuple[dict | None, bool]":
    """``(entry, unanswerable)``: the picker entry a **bare cast** of the
    instant or sorcery *card* is taken to name, and whether the cast owes a
    target that **no entry can be** for the X it announced.

    No entry and not unanswerable is "nothing to supply": the spell targets
    nothing, may name nobody, names a seat that is its target, is one of the
    counted shapes another gate refuses, or has an empty picker — whose
    refusal is ``no_legal_cast_target_refusal``'s, asked in its own place in
    the cast. *unanswerable* is the one refusal that gate cannot see: a picker
    with entries, none of which answers the announced X.

    The cast-side twin: ``cast_target_obligation``'s slot, for the mode and
    the kicker the cast announced (CR 601.2b precedes CR 601.2c), over the
    enumeration ``cast_target_refusal`` and ``no_legal_cast_target_refusal``
    read. A permanent spell answers None — an Aura's bare cast is refused
    ("requires a target") and an entry trigger's target is the trigger's.

    **An announced X is part of the question.** "Destroy target artifact with
    mana value X" (Detonate), "…with mana value X or less" (Dominate): the
    picker enumerates before X exists and leaves the bound out, so with an X
    in hand each candidate is put to the gate a named target is put to
    (``_validate_cast_targets``) and the first it accepts is the default. With
    no X announced the target implies it, as it does for a caller who names
    one.
    """
    if card.primary_type not in ("instant", "sorcery"):
        return None, False
    program = compile_card_oracle(card)
    if not program.supported:
        return None, False
    spec = cast_target_obligation(
        card, program, optional_cost_payments=optional_cost_payments,
        x_value=x_value, mode_index=mode_index,
    )
    if spec is None or spec_roles(spec) or _seat_is_the_target(spec, named_seat):
        return None, False
    slot = cast_target_slot(
        card, program, optional_cost_payments=optional_cost_payments,
        mode_index=mode_index,
    )
    if slot is not None and exact_target_count(slot[0], slot[1], x_value) is not None:
        return None, False
    offered = game._enumerate_targets(
        caster_index, card, dict(spec), for_cast=True,
        optional_cost_payments=optional_cost_payments, mode_index=mode_index,
    )
    # …as the cast picker presents it under a Flagbearer's requirement
    # (``CastTargetSpecMixin._under_target_requirements``), for the activation
    # side's reason.
    offered = game._under_target_requirements(
        caster_index, card, {**spec, "valid_targets": offered}, True, mode_index,
    ).get("valid_targets") or []
    standing = named_seat
    if standing is None:
        standing = game._spell_default_seat(caster_index)
        if not 0 <= standing < len(game.players):
            standing = game._default_opposing_seat(caster_index)
    for entry in standing_order(offered, standing):
        if x_value is None or entry.get("kind") not in ("permanent", "stack"):
            return entry, False
        named = announced_fields(game, entry)
        accepted, _reason = game._validate_cast_targets(
            card, caster_index,
            named.get("target_player_index"),
            named.get("target_permanent_index"),
            named.get("target_stack_item"),
            mode_index=mode_index, x_value=x_value,
            target_permanent_ids=named.get("target_permanent_ids"),
            optional_cost_payments=optional_cost_payments,
        )
        if accepted:
            return entry, False
    return None, bool(offered)


def seat_of_unseated_slot(
    game: "Game", announcer_index: int, index, default_seat: int,
) -> int | None:
    """The seat a **battlefield slot named beside no seat** counts into, where
    the default seat has no such slot: the announcer's own battlefield, then
    any other seat's, in seat order. None where the default seat has the slot
    (it is the one meant, and is judged) or no seat does.

    ``activate(…, target_permanent_index=1)`` with no seat is an announcement
    the gates have always read as "that slot, on either battlefield" — the
    opposing one if it has it, else the activator's own (Xenic Poltergeist
    animating its controller's artifact). Nothing said so where the object was
    built: the stack item kept the opposing seat and no id, and the resolution
    found the permanent only because its scan went on to the announcer's side.
    An announced object has no scan, so the announcement is completed here —
    the seat is written beside the slot and the id stamped off it, before any
    cost is paid.
    """
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    seats = range(len(game.players))
    if default_seat in seats and game.permanent_at(
        game.players[default_seat], index
    ) is not None:
        return None
    for seat in [announcer_index] + [
        other for other in seats if other not in (announcer_index, default_seat)
    ]:
        if game.permanent_at(game.players[seat], index) is not None:
            return seat
    return None


def announced_fields(game: "Game", entry: dict) -> dict:
    """*entry* — one picker entry — as the announcement fields that name it:
    ``target_player_index`` / ``target_permanent_index`` /
    ``target_permanent_ids`` / ``target_stack_index`` and
    ``target_stack_item``, only the keys that entry sets. One translation for
    both announcement paths, so a default is written in exactly the vocabulary
    a caller naming the same target would have used.
    """
    kind = entry.get("kind")
    if kind == "player":
        return {"target_player_index": entry["seat"]}
    if kind == "permanent":
        named = game.permanent_at(game.players[entry["seat"]], entry["index"])
        return {
            "target_player_index": entry["seat"],
            "target_permanent_index": entry["index"],
            "target_permanent_ids": (
                [named.permanent_id] if named is not None else None
            ),
        }
    if kind == "graveyard":
        return {
            "target_player_index": entry["seat"],
            "target_permanent_index": entry["index"],
        }
    if kind == "stack":
        # The picker counts the stack top-first; an announcement names a slot
        # bottom-first (``target_stack_index``) and the object itself.
        depth = len(game.stack)
        position = depth - 1 - entry.get("stack_index", -1)
        if 0 <= position < depth:
            return {
                "target_stack_index": position,
                "target_stack_item": game.stack[position],
            }
    return {}


def announced_slots(game: "Game", seat_player, index, ids):
    """The **index** channel of an announced object, read off its **id**
    channel at the moment it resolves: where each announced permanent sits
    *now* on *seat_player*'s battlefield, or None for one that is no longer
    there.

    An announcement records a battlefield target twice — a slot beside a seat
    and the permanent's id (``Game._stamp_stack_targets``) — and the two stop
    agreeing while the object waits on the stack: anything leaving renumbers
    every later slot (CR 400.7 keeps the id). ``handlers/_common``'s resolvers
    prefer the id; a dozen older handlers read the slot alone, so for them

    * a target named **by id and nothing else** — the address this engine asks
      for — was a target nobody named: Swords to Plowshares aimed by id at one
      creature exiled whichever creature its own scan met first, a creature
      with shroud included;
    * a slot recorded at announcement named whatever had slid into it by
      resolution.

    One translation at the seam instead of a fix per handler, and only for an
    announced object (a spell, an activated ability), whose ids are a player's
    choice gated at announcement. A slot whose entry carries **no id** is left
    exactly as it was: that is a card in a graveyard, whose slot counts into a
    different list and has its own stamp (``GraveyardTarget``).
    """
    if seat_player is None:
        return index

    def slot_of(permanent_id):
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None or not game.controls(seat_player, permanent):
            return None
        return game.battlefield_index_of(permanent)

    if isinstance(ids, int) and not isinstance(ids, bool):
        return slot_of(ids)
    if not isinstance(ids, (list, tuple)) or not any(
        isinstance(entry, int) for entry in ids
    ):
        return index
    listed = isinstance(index, (list, tuple))
    indices = list(index) if listed else [index]
    slots = []
    for position, entry in enumerate(ids):
        if isinstance(entry, int):
            slots.append(slot_of(entry))
        else:
            slots.append(indices[position] if position < len(indices) else None)
    if listed or len(slots) > 1:
        return slots
    return slots[0]


def resolving_slots(
    game: "Game", seat_player, index, ids, *, card, mode_index=None, instruction=None,
):
    """:func:`announced_slots` for the object that is resolving — a spell
    (*card*, and the mode it announced) or an activated ability
    (*instruction*) — unless its slot is **a card in a graveyard**. That slot
    counts into a different list, has its own stamp, and the id beside it (an
    activation stamps one off the battlefield slot of the same number) names a
    permanent the object never targeted.
    """
    if graveyard_target_spec(
        card, compile_card_oracle(card), mode_index=mode_index,
        instruction=instruction,
    ) is not None:
        return index
    return announced_slots(game, seat_player, index, ids)

