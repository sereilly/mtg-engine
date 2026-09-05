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

from ._common import count_from_payload
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

    recorded = payload.get("among_record")
    if among is None and recorded is not None:
        # "…sacrifices one of **those creatures**" (Retribution). The offer is
        # the set an earlier step of this same resolution chose, not the board:
        # scanning the board would let the player give up any creature they
        # control, which is a strictly better card than the one printed. An
        # unwritten record offers nothing, which is the honest outcome — the
        # sentence names a set nobody made.
        among = tuple(context.results.get(str(recorded)) or ())
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
        if payload.get("controlled_by"):
            # "the <type> **you each** control" (Juxtapose): whose battlefield
            # this side of the choice is drawn from. A seat question, which
            # `subject_matches` deliberately does not answer for a named
            # *other* player — "you" it can, the spell's chosen player it
            # cannot, and both sides of one exchange need the same rule.
            wanted = _controlled_by_seat(
                game, payload["controlled_by"], context, payload
            )
            if wanted is None or not game.controls(wanted, perm):
                continue
        if payload.get("legal_host_for_relative"):
            # CR 303.4j, asked before the move so an illegal pick is never
            # offered — the same predicate the attach itself re-asks.
            from ..auras import aura_attach_refusal

            if anchor is None or aura_attach_refusal(game, anchor, perm) is not None:
                continue
        if payload.get("legal_host_for_source"):
            # "…a creature **this card** could enchant" (Takklemaggot): the
            # same rule measured against the ability's own source, which by the
            # time this resolves is a card in a graveyard rather than a
            # permanent. Asked of the card-shaped half of the one predicate,
            # never of a second copy of the enchant clause.
            from ..auras import enchant_card_refusal

            if enchant_card_refusal(
                game, context.card, seat, perm
            ) is not None:
                continue
        out.append(perm)
    if payload.get("greatest_mana_value") and out:
        # "…with the **greatest** mana value" (CR 202.3, read off the printed
        # cost like every other mana-value question in the engine). A
        # superlative over the narrowed set rather than a filter key, because
        # it is a fact about the *set*: no permanent can answer it alone, which
        # is exactly why the card then has to say who breaks a tie.
        best = max(int(getattr(perm.card, "cmc", 0) or 0) for perm in out)
        out = [
            perm for perm in out
            if int(getattr(perm.card, "cmc", 0) or 0) == best
        ]
    return out


def _controlled_by_seat(game, word: str, context, payload: dict | None = None) -> int | None:
    """The seat a ``controlled_by`` word names.

    "you" is the effect's controller, "target" is the player the spell chose
    (CR 115.10b), and "chooser" is whoever is being asked — Preacher's "they",
    a pronoun naming the player the phrase already named. Anything else names
    nobody rather than defaulting: a side of an exchange drawn from the wrong
    battlefield is a different card.
    """
    if word == "you":
        return game.players.index(context.caster)
    if word == "target":
        return (
            game.players.index(context.target)
            if context.target in game.players
            else None
        )
    if word == "chooser":
        # "…of an opponent's choice **they** control" (Preacher): the seat being
        # asked. A pronoun naming the player the phrase already named, so the
        # picked-from battlefield and the picking seat are one answer rather
        # than two that can disagree once there are three players.
        return _chooser_seat(game, payload or {}, context)
    return None


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
    chooser = payload.get("chooser")
    if chooser == "event_subject_player":
        # "At the beginning of each player's upkeep, destroy target nonartifact
        # creature **that player** controls **of their choice**." (The Abyss.)
        # The seat the firing event *is about*, frozen by the fire site
        # (CR 603.10) — one step over from the branch below, which names the
        # controller of an object the event was about. A trigger that fires
        # once per player has a different seat every firing, and by resolution
        # the only one still readable off the board is the source's controller,
        # which is the wrong one on every upkeep but their own. None when no
        # event named one, which the caller reports as a choice nobody could
        # make rather than handing the pick to the ability's controller — the
        # seat the card has just said must not choose.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if isinstance(seat, int) and 0 <= seat < len(game.players):
            return seat
        return None
    if chooser == "event_subject_controller":
        # "**That creature's** controller chooses …" (Takklemaggot): the seat
        # the firing event froze, which is the one place it can be read — the
        # creature is in a graveyard by the time this resolves and a graveyard
        # card has no controller (CR 108.4a). None when no event named one,
        # which the caller reports as a choice nobody could make.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if isinstance(seat, int) and 0 <= seat < len(game.players):
            return seat
        return None
    if chooser == "chosen_player":
        # "Choose two target creatures controlled by the same opponent.
        # **That player** chooses and sacrifices one of those creatures."
        # (Retribution.) The seat an earlier step of this same resolution
        # recorded — the one the printed relation named — read back through the
        # key every "the player this effect chose" is written under. None when
        # nothing recorded one, which the caller reports as a choice nobody
        # could make rather than handing the pick to the ability's controller,
        # the seat the card has just said must not choose.
        seat = (context.results or {}).get("chosen_player")
        if isinstance(seat, int) and 0 <= seat < len(game.players):
            return seat
        return None
    if chooser == "target":
        # "**their** controller chooses one of them" (Juxtapose): the seat the
        # candidates were drawn from, which for this side is the spell's chosen
        # player. Payload, like every other chooser, so the picking seat and
        # the picked-from seat stay one decision.
        return _controlled_by_seat(game, "target", context, payload)
    if chooser != "opponent":
        return caster_seat
    return next(
        (
            index
            for index, player in enumerate(game.players)
            if index != caster_seat and not player.lost
        ),
        None,
    )


@effect_handler("choose_permanents")
def choose_permanents(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"that player **chooses up to two Plains**" (Raiding Party.)

    :func:`choose_permanent`'s plural, and a second instruction rather than a
    count on the first: the answer is a *set*, so the prompt collects a list,
    the resolver validates the whole list before recording any of it, and the
    default has a ceiling to respect. One id and a list of ids are two shapes on
    the wire and two shapes in ``results``, and a kind that meant either would
    leave every reader asking which.

    **The record accumulates.** The sentence this is a step of runs once per
    creature tapped this way, by several seats, and the sentence behind *it*
    asks about "all Plains that weren't chosen this way **by any player**" —
    one question about every answer. So the picks are appended to the key rather
    than assigned to it, and the key is written empty first so a loop that ran
    zero times still leaves a set to subtract.

    Who chooses is payload, exactly as it is for the singular: ``chooser`` names
    a seat the sentence names outright, and ``chooser_seat_record`` names a seat
    an *earlier step of this same resolution* wrote down about the object the
    loop is currently on (``PER_OBJECT_SEAT_RECORDS``). With no entry there is
    nobody to ask, which is the honest outcome rather than handing the pick to
    the ability's controller.
    """
    payload = instruction.payload
    result_key = payload["result_key"]
    context.results.setdefault(result_key, [])
    record = payload.get("chooser_seat_record")
    if record is not None:
        found = context.iteration_seats.get(str(record))
        seat = found if isinstance(found, int) and 0 <= found < len(game.players) else None
    else:
        seat = _chooser_seat(game, payload, context)
    card_name = getattr(context.card, "name", "")
    if seat is None:
        game.log.append(f"{card_name}: there is nobody to make the choice")
        return True, "resolved"
    candidates = permanent_choice_candidates(game, payload, context)
    # "**For each land target player controls in excess of the number you
    # control**, choose a land that player controls." (Equipoise.) How many is
    # a quantity the resolution computes, through the one evaluator every other
    # computed count in this engine goes through — so "the number of lands you
    # control" means here what it means in a pump or a where-clause, and the
    # difference is clamped at zero by the same arithmetic (CR 107.1b).
    #
    # ``exact_count`` is the printed sentence, not a convenience: "for each X,
    # choose a Y" says how many *are* chosen, so the number is a floor as well
    # as a ceiling. A ceiling alone would let a seat answer none and the card
    # would do nothing.
    up_to = int(payload.get("up_to", 1))
    at_least = int(payload.get("at_least", 0) or 0)
    counted = payload.get("count_from")
    if counted is not None:
        up_to = count_from_payload(
            game, context, dict(counted), instruction,
            source=context.source_permanent,
        )
        if payload.get("exact_count"):
            at_least = up_to
        if up_to <= 0:
            # CR 608.2's "as much as possible": a count of nothing is not a
            # prompt with no answer, it is a step that asked for nothing.
            game.log.append(f"{card_name}: nothing to choose")
            return True, "resolved"
    if len(candidates) < max(at_least, 1):
        game.log.append(f"{card_name}: there is no permanent it could choose")
        return True, "resolved"
    game.arm_permanent_set_choice(
        seat,
        card_name=card_name,
        prompt=payload.get("prompt") or "Choose permanents.",
        result_key=result_key,
        payload=payload,
        context=context,
        candidates=candidates,
        up_to=up_to,
        at_least=at_least,
    )
    return True, "resolved"


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
    # "Put a -1/-1 counter on **the other**." (Retribution.) The member of the
    # offered set the pick did *not* take. Written here for ``result_key``'s
    # reason — a later step reading it finds None rather than a key error when
    # there was nothing to choose — and filled in beside the answer below,
    # which is the one moment both halves are in hand.
    remainder_key = payload.get("remainder_key")
    if remainder_key is not None:
        context.results[str(remainder_key)] = None
    seat = _chooser_seat(game, payload, context)
    if seat is not None:
        # Who was asked, for a later sentence that speaks about them rather than
        # about what they picked — "…deals 1 damage to **that player**"
        # (Takklemaggot's granted trigger). Recorded whether or not they
        # actually choose anything, because the question was still put to them.
        context.results["chosen_player"] = seat
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
    if payload.get("only_on_tie") and len(candidates) == 1:
        # "**If two or more** permanents a player controls are tied for
        # greatest, their controller chooses one of them." (Juxtapose.) With
        # one candidate the card names it outright, so recording it is the
        # whole of the step — prompting anyway would ask a player a question
        # with one answer, four times per cast.
        context.results[result_key] = candidates[0].permanent_id
        return True, "resolved"
    game.arm_permanent_choice(
        seat,
        card_name=card_name,
        prompt=payload.get("prompt") or "Choose a permanent.",
        result_key=result_key,
        payload=payload,
        context=context,
        candidates=candidates,
        optional=bool(payload.get("optional")),
        remainder_key=(None if remainder_key is None else str(remainder_key)),
    )
    return True, "resolved"
