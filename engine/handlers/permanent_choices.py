"""A permanent chosen as an effect resolves, where nothing was targeted.

"Attach target Aura attached to a creature or land to **another permanent of
that type**" (Enchantment Alteration) names two objects and targets one of them.
The second is chosen when the spell resolves, so no target was declared for it
at cast time (CR 601.2c) and no target legality is re-checked for it (CR 608.2b);
the player simply picks, and the rest of the sentence acts on what they picked.

The engine already had one prompt of this shape — Kudzu's reattachment — and it
was Kudzu's all the way down: a ``land_index`` on the wire, a resolver that read
that index off one battlefield, and the card's name in the blocked-action
message. An index is not an identity (CR 400.7), and locating a permanent by
slot is banned outright here, so generalising it meant replacing it rather than
renaming it.

**The general answer is that the chosen permanent is a value.** This module's
one instruction, ``choose_permanent``, arms the prompt and writes the answer's
``permanent_id`` into ``context.results`` under the payload's ``result_key`` —
which is exactly how ``gain_control_until_eot`` already reads a permanent an
earlier step of the same sentence bound (``permanents_from``). Everything after
the choice is ordinary instructions in a ``sequence`` reading that key, so a
card that chooses a permanent and then destroys it needs no new prompt, no new
handler and no new ``Game`` field — only a lowering that names the key.

The prompt is registered ``suspends``: the steps behind it in the same
resolution have not run, and they are the ones that read the answer. A
non-interactive seat takes its default at arm time (``default_at_arm``), so AI
and headless play resolve the whole sentence inline exactly as they did before.

Which permanents may be chosen is :func:`permanent_choice_candidates`, and it is
one rule with three callers — the arming above, the liveness re-check when the
answer arrives, and the web renderer's offered list. A second copy of it is how
a client comes to offer a permanent the engine then refuses, or worse, accepts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle_types import OracleInstruction


def _relative_object(game, payload: dict, context):
    """The permanent the payload's narrowings are stated *relative to*.

    "another permanent of **that** type" is not a phrase about the board — both
    words point back at the object the sentence already named. Only one referent
    is admitted today ("target", the spell's own chosen object), and an
    unrecognised one resolves to nothing rather than to a default: a narrowing
    measured from the wrong object is a wider choice than the card prints.
    """
    if payload.get("relative_to") != "target":
        return None
    target_id = context.target_permanent_id
    if isinstance(target_id, list):
        target_id = target_id[0] if target_id else None
    if not isinstance(target_id, int):
        return None
    return game.permanent_by_id(target_id)


def _has_card_type(permanent, name: str) -> bool:
    # ``is_creature`` rather than the printed line for "creature", exactly as
    # ``permanent_matches_filter`` does, so an animated land counts as one.
    return permanent.is_creature if name == "creature" else permanent.has_type(name)


def shares_a_card_type(first, second) -> bool:
    """Whether two permanents share at least one card type (CR 205.2a).

    The type list is the vocabulary catalog, not a tuple written here: "never
    hardcode a type list" applies to card types as much as to creature types,
    and a permanent simply answers no to the four types no permanent can have.
    """
    from ..grammar.vocabulary import CARD_TYPES

    return any(
        _has_card_type(first, card_type) and _has_card_type(second, card_type)
        for card_type in CARD_TYPES
    )


def permanent_choice_candidates(game, payload: dict, context, among=None) -> list:
    """The permanents a ``choose_permanent`` instruction offers.

    *among* limits the scan to an already-armed list, which is what the liveness
    re-check passes: a permanent that entered after the prompt was armed is not
    an answer, because nothing can enter while a resolution is suspended and a
    board that grew under a queued prompt would mean an answer to a different
    question.

    Every narrowing below is a printed clause carried as payload, never part of
    the instruction kind — so "another permanent of that type" and "a creature
    an opponent controls" are the same instruction with different keys.
    """
    from ..subject_filters import subject_matches

    described = dict(payload.get("filter") or {})
    seat = game.players.index(context.caster)
    source = context.source_permanent
    anchor = _relative_object(game, payload, context)
    host = anchor.metadata.get("attached_to") if anchor is not None else None
    if host is not None and not game.is_on_battlefield(host):
        host = None

    pool = list(among) if among is not None else list(game.all_permanents())
    out = []
    for perm in pool:
        if not game.is_on_battlefield(perm):
            continue
        if anchor is not None and perm is anchor:
            # The Aura being moved is a permanent too, and nothing attaches to
            # itself (CR 303.4a).
            continue
        if not subject_matches(game, perm, described, observer=seat, source=source):
            continue
        if payload.get("exclude_relative_host"):
            # "**another** permanent" — anything but the one it is on now.
            if host is None or perm is host:
                continue
        if payload.get("shares_type_with_relative_host"):
            # "…of **that** type", the type of the permanent the anchor is
            # attached to. With nothing attached there is no such type, so the
            # phrase names nothing rather than everything.
            if host is None or not shares_a_card_type(perm, host):
                continue
        if payload.get("legal_host_for_relative"):
            # CR 303.4j, asked before the move so an illegal pick is never
            # offered — the same predicate the attach itself re-asks.
            from ..auras import aura_attach_refusal

            if anchor is None or aura_attach_refusal(game, anchor, perm) is not None:
                continue
        out.append(perm)
    return out


def _chooser_seat(game, payload: dict, context) -> int | None:
    """Whose choice this is (CR 601.2c does not make it always the controller's).

    "…of **an opponent's** choice" (Nova Pentacle) hands the pick to the other
    seat, and that is payload rather than a second instruction kind: the prompt,
    the candidate rule and the recorded answer are identical either way, and
    only the seat asked differs. A card printing "target opponent chooses" needs
    no code here.

    None when the named chooser does not exist — a lone survivor has no opponent
    — which the caller reports as a choice nobody could make rather than
    defaulting to the controller, who is exactly the seat the card said must not
    choose.
    """
    caster_seat = game.players.index(context.caster)
    if payload.get("chooser") != "opponent":
        return caster_seat
    return next(
        (
            index
            for index, player in enumerate(game.players)
            if index != caster_seat and not player.lost
        ),
        None,
    )


@effect_handler("choose_permanent")
def choose_permanent(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Ask this effect's controller for one permanent and record which.

    The key is written before anything else, so a later step of the sentence
    reading it finds ``None`` rather than a key error when there was nothing to
    choose — "no legal choice" is an outcome, not a failure.
    """
    payload = instruction.payload
    result_key = payload["result_key"]
    context.results[result_key] = None
    seat = _chooser_seat(game, payload, context)
    if seat is None:
        game.log.append(
            f"{getattr(context.card, 'name', '')}: there is nobody to make the choice"
        )
        return True, "resolved"
    candidates = permanent_choice_candidates(game, payload, context)
    card_name = getattr(context.card, "name", "")
    if not candidates:
        game.log.append(f"{card_name}: there is no permanent it could choose")
        return True, "resolved"
    game.arm_permanent_choice(
        seat,
        card_name=card_name,
        prompt=payload.get("prompt") or "Choose a permanent.",
        result_key=result_key,
        payload=payload,
        context=context,
        candidates=candidates,
    )
    return True, "resolved"
