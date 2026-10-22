"""Changing what a spell or an ability on the stack points at (CR 115.7).

The handler twin of ``engine/grammar/lowering/retargeting.py``: "change the
target of target spell" (Deflection, Reflecting Mirror), the two-step retarget
that first chooses **another** legal target and then moves the spell onto it
(CR 115.7a), and "may change the target or targets" of the object a firing
event was about (Psychic Battle), slot by slot.

Split out of ``stack.py`` at the 2,000-line cap's split round. A copy that may
choose new targets is ``spell_copies.py``'s, re-aimed through
``arm_copy_spell_target``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..divided_damage import DIVIDED_TARGETS, divided_entry, stamped_entry
from ..game_types import StackItem
from ..resumption import run_resumable
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


# ---------------------------------------------------------------------------
# CR 115.7 — changing what a spell on the stack points at
# ---------------------------------------------------------------------------


def _retarget_subject(game: Game, context: OracleExecutionContext, instruction):
    """``(spell, its one current target)`` for a retarget that may still be
    made, or None with the reason logged.

    CR 608.2b asked at the moment the rule asks it. The effect chose its target
    when it was put on the stack, and the whole point of the stack is that time
    passes: the spell can be countered, can resolve, or can have its own target
    changed by something else in between. So every condition the picker checked
    is checked again here, against the object as it stands now.

    The current target comes back beside the spell because both callers need it
    and neither should ask twice: the choosing step excludes it from the
    candidates (CR 115.7a's "**another** legal target") and the changing step
    would otherwise have to re-derive what it is replacing.

    Located by **identity**, never by ``in``: ``StackItem`` compares by value, so
    two copies of one spell aimed at one player are equal and ``in`` would find
    the wrong one — the look-alike bug that ``permanent_id`` solves on the
    battlefield.
    """
    from ..legality import _single_target_is
    from ..targeting import single_spell_target

    card_name = getattr(context.card, "name", "")
    item = context.stack_target
    if item is None or not any(waiting is item for waiting in game.stack):
        game.log.append(
            f"{card_name}: the spell it would retarget is no longer on the stack"
        )
        return None
    chosen = single_spell_target(game, item)
    if chosen is None:
        game.log.append(
            f"{card_name}: {item.card.name} no longer has a single target"
        )
        return None
    required = instruction.payload.get("current_target")
    # None is Deflection: the sentence asks nothing about who the spell points
    # at now. Lowering admits no value but "you" beside it, so a payload
    # carrying another would be a restriction nothing here can test.
    if required is not None and not (
        required == "you"
        and chosen.get("kind") == "player"
        and chosen.get("seat") == game.seat_index(context.caster)
    ):
        game.log.append(
            f"{card_name}: {item.card.name} no longer has a single target that is you"
        )
        return None
    # "…and **that target is a creature**" (Meddle), "…that targets only **a
    # player**" (Rebound). CR 608.2b asked a second time about the *other*
    # object's target, through the reader the picker used — the same
    # arrangement the seat question above has, and the one this restriction did
    # not: it was checked when the ability was activated and never again, so a
    # spell re-aimed at a face in between was still retargeted by a card that
    # only ever named one pointed at a creature.
    wanted_type = instruction.payload.get("current_target_type")
    if wanted_type is not None and not _single_target_is(
        game, chosen, wanted_type, source=context.source_permanent
    ):
        # "…that targets only **this creature**" (Silver Wyvern) is an identity
        # rather than a type, so it is named as one: "no longer a source" is not
        # a sentence, and the seat reading the log is being told which
        # permanent the object stopped pointing at.
        described = (
            context.source_permanent.card.name
            if wanted_type == "source" and context.source_permanent is not None
            else f"a {wanted_type}"
        )
        game.log.append(
            f"{card_name}: {item.card.name}'s target is no longer {described}"
        )
        return None
    return item, chosen


def _same_target(left: dict, right: dict) -> bool:
    """Whether two target descriptors name the same object or face."""
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "player":
        return left.get("seat") == right.get("seat")
    return left.get("permanent_id") == right.get("permanent_id")


def _legal_new_targets(game: Game, item: StackItem, bound) -> list[dict]:
    """The targets *item* could legally have been aimed at instead (CR 115.7a).

    Read through ``_enumerate_targets`` — the one list the picker and the cast
    gate already share — so "another legal target" means for this spell exactly
    what it meant when the spell was cast. Word of Command's "target opponent"
    therefore offers only its own caster's opponents, which is why a spell
    aimed at you by the player it may not aim at themselves simply cannot be
    moved.

    *bound* is the retargeting card's own "The new target must be a …"
    sentence, or None where it prints none. ``"player"`` forces the kind, which
    is both the restriction and an economy: the question is which *faces* are
    legal and a wider spec would walk both battlefields for an answer that card
    never uses. None asks the spell's **own** spec, so Deflection offers exactly
    what that spell could have chosen — a creature for a Lightning Bolt, a face
    for a Mind Twist.

    Each permanent is carried by ``permanent_id``, never by the slot the
    enumeration named it in: a prompt sits between this list and the write, and
    an index is what renumbers underneath one.
    """
    from ..legality import targeting_instruction
    from ..targeting import stack_object_target_spec

    # The object's own spec, which for an **ability** is not the card's. Silver
    # Wyvern re-aims "target spell or ability", and ``derive_cast_spec`` asked of
    # an ability's stack item answers about whatever that *card* does when it is
    # cast — for a creature's activated ability that is a different list or no
    # list at all, so the ability would have been offered the wrong candidates
    # or none. One reader for both kinds, in ``targeting``, so the count asked
    # by ``single_spell_target`` and the candidates offered here cannot disagree.
    spec = stack_object_target_spec(item)
    if spec is None:
        return []
    if bound == "player":
        spec = {**spec, "kind": "player"}
    # "…change that spell's target to **another creature**" (Meddle). The
    # opposite forcing to the one above and for the same reason: the question is
    # which *permanents* are legal, and asking the spell's own spec would offer
    # the faces a Lightning Bolt may also choose. It narrows rather than widens
    # — a spell whose own spec offers no creature offers none here either,
    # because ``_enumerate_targets`` still answers for that card.
    elif bound == "creature":
        spec = {**spec, "kind": "creature"}
    # An ability's own restriction ("target **tapped** creature", "target
    # non-Wall creature") and its source travel with it, for the reason the
    # activation picker passes them: CR 115.7a's replacement must be a target
    # the object *could legally have chosen*, and a narrowing left behind here
    # would offer one it could not. A spell carries neither and passes None,
    # which is exactly what it passed before.
    ability_instruction = (
        targeting_instruction(item.ability_instruction)
        if item.ability_instruction is not None
        else None
    )
    entries = game._enumerate_targets(
        item.caster_index, item.card, spec, for_cast=True,
        ability_instruction=ability_instruction,
        ability_source=item.source_permanent,
        source_permanent=item.source_permanent,
    )
    candidates: list[dict] = []
    for entry in entries:
        if entry.get("kind") == "player":
            seat = entry.get("seat")
            if not isinstance(seat, int) or game.players[seat].lost:
                continue
            candidates.append(
                {"kind": "player", "seat": seat, "name": game.players[seat].name}
            )
            continue
        # A permanent answer is dropped when the card bounds the new target to
        # a **player** — Reflecting Mirror could only ever have offered a face.
        # A creature bound is the other way round: the spec above already
        # narrowed the enumeration to creatures, so what comes back is the list
        # to offer.
        if entry.get("kind") != "permanent" or bound not in (None, "creature"):
            continue
        # The enumeration names a battlefield slot; the seam's bridge turns it
        # into a permanent once, here, and everything downstream carries the id.
        found = game.permanent_at(entry.get("seat"), entry.get("index"))
        permanent_id = None if found is None else game.permanent_id_of(found)
        if permanent_id is None:
            continue
        candidates.append({
            "kind": "permanent",
            "permanent_id": permanent_id,
            "name": entry.get("name", ""),
        })
    return candidates


@effect_handler("choose_new_spell_target")
def choose_new_spell_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Which legal target replaces the one the spell announced (CR 115.7a).

    The first of the retarget's two steps. It is its own step for the reason
    Backdraft's player choice is one (``handlers/player_choices.py``): the
    decision is made *during* this resolution and the step behind it reads the
    answer, so an interactive seat can be asked and the resolution suspended
    until it answers.

    The key is written before anything else, so the step behind this one finds
    ``None`` rather than a key error when there was nobody to choose — "no legal
    new target" is an outcome CR 115.7a names ("the original target is
    unchanged"), not a failure.

    **Another** legal target, which is what the rule says: the target the spell
    already points at is not among the candidates, so a retarget with nowhere
    else to go leaves the spell exactly as it was. A single candidate is taken
    without asking, the shortcut ``choose_player_who_cast`` states — the card
    makes the choice forced, and prompting would ask a question with one answer.
    """
    key = str(instruction.payload["result_key"])
    context.results[key] = None
    card_name = getattr(context.card, "name", "")
    subject = _retarget_subject(game, context, instruction)
    if subject is None:
        return True, "resolved"
    item, current = subject
    candidates = [
        candidate
        for candidate in _legal_new_targets(
            game, item, instruction.payload.get("new_target")
        )
        if not _same_target(candidate, current)
    ]
    if not candidates:
        # Named by the bound the card printed, because that is what the seat is
        # being told: Reflecting Mirror could only ever have offered a player,
        # so "no other legal target" would read as a wider search than it made.
        bounded = "player" if instruction.payload.get("new_target") == "player" else "target"
        game.log.append(
            f"{card_name}: {item.card.name} has no other legal {bounded}"
        )
        return True, "resolved"
    if len(candidates) == 1:
        context.results[key] = candidates[0]
        return True, "resolved"
    game.arm_retarget_choice(
        game.seat_index(context.caster),
        card_name=card_name,
        prompt=f"Choose the new target for {item.card.name}.",
        result_key=key,
        options=candidates,
        context=context,
    )
    return True, "resolved"


@effect_handler("change_target_spell_target")
def change_target_spell_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Change the target of target spell …" (Deflection, Reflecting Mirror —
    CR 115.7a).

    The spell keeps everything else it announced — its controller, its X, its
    modes — and only what it points at moves. That is why this writes the item's
    target fields rather than re-announcing the spell: CR 115.7a changes a
    choice, it does not re-cast anything.

    **All three target fields are written together**, whichever way the new
    target points. A spell re-aimed from a creature onto a face that kept its
    stale ``target_permanent_id`` would be resolved against the creature by
    every handler that prefers the id, and the log would say otherwise.

    ``divided_targets`` is rewritten alongside, because for a spell that
    recorded one it is the list that decides (CR 601.2d's division travels with
    the targets, and CR 115.7f keeps the division itself unchanged — with a
    single target there is only one share to keep). Writing the seat and leaving
    that list behind would log a redirect the damage step then ignored.
    """
    key = str(instruction.payload["result_key"])
    card_name = getattr(context.card, "name", "")
    chosen = context.results.get(key)
    subject = _retarget_subject(game, context, instruction)
    if subject is None:
        return True, "resolved"
    item, _current = subject
    unchanged = f"{card_name}: {item.card.name}'s target is unchanged"
    if not isinstance(chosen, dict):
        game.log.append(unchanged)
        return True, "resolved"
    if chosen.get("kind") == "permanent":
        found = game.find_permanent_by_id(chosen.get("permanent_id"))
        if found is None:
            # It left between the choice and this step. CR 115.7a: a target
            # that can't be changed to another legal target stays as it was.
            game.log.append(unchanged)
            return True, "resolved"
        seat, permanent = found
        item.target_player_index = seat
        item.target_permanent_id = game.permanent_id_of(permanent)
        item.target_permanent_index = game.battlefield_index_of(permanent)
        divided = (item.choices or {}).get(DIVIDED_TARGETS)
        if divided:
            # The list that decides, rewritten here as it is in the player
            # branch below — and for a reason that branch's note already
            # gives: "writing the seat and leaving that list behind would log
            # a redirect the damage step then ignored". It was left behind on
            # this side: a Fireball re-aimed from a face onto a creature logged
            # the new target and dealt its damage to the old one. CR 115.7f
            # keeps the division, so the one share travels with the target.
            share = divided_entry(divided[0])[2] if len(divided) == 1 else None
            item.choices[DIVIDED_TARGETS] = [
                stamped_entry(
                    seat, item.target_permanent_index, share, item.target_permanent_id
                )
            ]
        game.log.append(
            f"{card_name}: {item.card.name} now targets {permanent.card.name}"
        )
        # CR 115.7a: the retargeting effect's controller chose a new target for
        # the object, which is a player choosing a target — and the permanent
        # it now points at has become the target of a spell (CR 603.2).
        game.announce_targets_chosen(
            item, chooser=game.seat_index(context.caster), newly_targeted=True,
        )
        return True, "resolved"
    seat = chosen.get("seat")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(unchanged)
        return True, "resolved"
    item.target_player_index = seat
    item.target_permanent_id = None
    item.target_permanent_index = None
    divided = (item.choices or {}).get(DIVIDED_TARGETS)
    if divided:
        # CR 115.7f keeps the division unchanged, so the one surviving target
        # keeps the share it was announced with. Only when the spell named one
        # target is there a share to carry across; a list this collapses to one
        # face has no single announcement to keep, and an even split of one is
        # the whole amount either way.
        share = divided_entry(divided[0])[2] if len(divided) == 1 else None
        item.choices[DIVIDED_TARGETS] = (
            [(seat, None)] if share is None else [(seat, None, share)]
        )
    game.log.append(
        f"{card_name}: {item.card.name} now targets {game.players[seat].name}"
    )
    game.announce_targets_chosen(
        item, chooser=game.seat_index(context.caster), newly_targeted=True,
    )
    return True, "resolved"


#: Scratchpad key each slot's prompt answers into, in turn. Private to the
#: handler below: it is read by the step behind the prompt and cleared there.
_EVENT_TARGET_PICK = "event_target_change_pick"


def _target_option(game: Game, target) -> dict:
    """One candidate as a ``retarget_choice`` option.

    The public keys are the ones that prompt has always carried (``kind``,
    ``seat`` / ``permanent_id``, ``name``); the descriptor itself rides under a
    private key so the answer is the very object ``change_options`` offered and
    not a second reading of it.
    """
    from ..stack_targets import target_label

    return {
        "kind": target.kind,
        "seat": target.seat,
        "permanent_id": target.permanent_id,
        "name": target_label(game, target),
        "_stack_item": target.stack_item,
        "_stamp": target.stamp,
        "_target": target,
    }


@effect_handler("change_event_object_targets")
def change_event_object_targets(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…may change the target or targets." (Psychic Battle — CR 115.7a.)

    The object is the one **the firing event was about** — the spell or ability
    a player just chose targets for, frozen by identity when the ability
    triggered (CR 603.10). The seat that chooses is payload: this effect's
    controller for the bare sentence, or the seat "the player who reveals the
    card with the greatest mana value" names, through the one reader an offer
    to that seat goes through (``control_flow._offered_seats``) — and where
    that names nobody (a tie, nothing revealed) nothing is changed.

    CR 115.7a, each sentence of it:

    * "each target can be changed only to **another legal target**" — the
      candidates are ``stack_targets.change_slots``', enumerated through the
      list the object's own picker and announcement gate read, minus the
      target the slot already names;
    * "if all the targets aren't changed to other legal targets, **none of them
      are changed**" — every slot is chosen before anything is written, each
      pick is offered only while the slots behind it can still be filled
      (``change_options``), and ``apply_target_change`` writes all of them or
      nothing;
    * CR 115.7e — only the final set is judged, which is why a two-target
      spell may have its targets exchanged.

    One prompt per target, in announcement order, each suspending this
    resolution until it is answered (``run_resumable``). Where the sentence
    says *may*, the first prompt carries "leave the targets as they are" as an
    answer — one decision, not a yes/no in front of a picker. A
    **non-interactive** seat is not asked: ``ai_policy.choose_target_change``
    is its stated policy, read on the spot, and "leave it" is one of its
    answers. On the spot matters: the object is the next thing to resolve, and
    a queued offer drained after the stack empties would be answered too late
    (``lowering/control_flow._offered_target_change``).

    The change is a player choosing targets, so it is announced through the
    one seam — silenced for permanents sharing this one's name when the card
    prints that sentence.
    """
    from ..stack_targets import (
        TARGETS_CHOSEN_ITEM, apply_target_change, change_options, change_slots,
        target_label,
    )

    card_name = getattr(context.card, "name", "")
    item = (context.trigger_context or {}).get(TARGETS_CHOSEN_ITEM)
    if item is None or not any(waiting is item for waiting in game.stack):
        game.log.append(
            f"{card_name}: the spell or ability whose targets were chosen is "
            "no longer on the stack"
        )
        return True, "resolved"
    subject = item.card.name
    unchanged = f"{card_name}: {subject}'s targets remain unchanged"
    # Who chooses first, because it is the half the sentence leads with and
    # the half every player was just shown the evidence for: "the player who
    # reveals the card with the greatest mana value" is decided by the reveal
    # whether or not there turns out to be anything to change.
    who = instruction.payload.get("chooser", "you")
    if who == "you":
        chooser = game.seat_index(context.caster)
    else:
        from .control_flow import _offered_seats

        seats = _offered_seats(game, who, context)
        if not seats:
            game.log.append(unchanged)
            return True, "resolved"
        chooser = seats[0]
    slots = change_slots(game, item)
    if isinstance(slots, str):
        game.log.append(f"{unchanged} ({slots})")
        return True, "resolved"
    if not change_options(slots, []):
        game.log.append(f"{unchanged} (it has no other legal targets)")
        return True, "resolved"
    optional = bool(instruction.payload.get("optional"))
    chooser_name = game.players[chooser].name
    picks: list = []

    def finish() -> None:
        before = ", ".join(target_label(game, slot.current) for slot in slots)
        if len(picks) != len(slots) or not apply_target_change(game, item, slots, picks):
            game.log.append(unchanged)
            return
        after = ", ".join(target_label(game, pick) for pick in picks)
        game.log.append(
            f"{card_name}: {chooser_name} changed {subject}'s "
            f"target{'s' if len(slots) > 1 else ''} from {before} to {after}"
        )
        silently_for = None
        if instruction.payload.get("silent_for_same_name"):
            # "…permanents **named** <this one>": the name this permanent has
            # *now* (CR 707.2 — a copy is named what it copies), and the
            # card's printed name once the permanent is gone.
            source = context.source_permanent
            silently_for = (
                source.effective_card.name if source is not None else card_name
            )
        game.announce_targets_chosen(
            item, chooser=chooser, silently_for=silently_for, newly_targeted=True,
        )

    if chooser not in game.interactive_seats:
        from ..ai_policy import choose_target_change

        chosen = choose_target_change(game, chooser, item, slots) if optional else None
        if chosen is None and not optional:
            # A change the sentence orders: the first complete one, in the
            # order the enumeration lists the candidates.
            chosen = []
            while len(chosen) < len(slots):
                chosen.append(change_options(slots, chosen)[0])
        if chosen is None:
            game.log.append(f"{card_name}: {chooser_name} left {subject}'s targets as they were")
            return True, "resolved"
        picks.extend(chosen)
        finish()
        return True, "resolved"

    state = {"abandoned": False}

    def absorb() -> None:
        # The answer to the slot before this step, exactly once.
        if _EVENT_TARGET_PICK not in context.results:
            return
        answer = context.results.pop(_EVENT_TARGET_PICK)
        if isinstance(answer, dict) and answer.get("_target") is not None:
            picks.append(answer["_target"])
        else:
            # "Leave them as they are", or every candidate left between the
            # question and the answer (``_resolve_retarget_choice``). CR 115.7a
            # either way: nothing is changed.
            state["abandoned"] = True
            state["declined"] = isinstance(answer, dict) and answer.get("kind") == "keep"

    def step(position) -> None:
        absorb()
        if position is None:
            if state.get("declined"):
                game.log.append(
                    f"{card_name}: {chooser_name} left {subject}'s targets as they were"
                )
            elif state["abandoned"]:
                game.log.append(unchanged)
            else:
                finish()
            return
        if state["abandoned"]:
            return
        options = change_options(slots, picks)
        if not options:
            state["abandoned"] = True
            return
        # Declining is offered once, with the first target: after it, the
        # change is under way and CR 115.7a leaves no half of one to keep.
        may_decline = optional and position == 0
        if len(options) == 1 and not may_decline:
            # A choice with one answer is not a question (``choose_new_spell_target``).
            context.results[_EVENT_TARGET_PICK] = _target_option(game, options[0])
            return
        current = target_label(game, slots[position].current)
        game.arm_retarget_choice(
            chooser,
            card_name=card_name,
            prompt=(
                f"Choose the new target for {subject} (now {current})."
                if len(slots) == 1 else
                f"Choose the new target for {subject}: target {position + 1} "
                f"of {len(slots)} (now {current})."
            ),
            result_key=_EVENT_TARGET_PICK,
            options=(
                [{"kind": "keep", "name": "Leave the targets as they are"}]
                if may_decline else []
            ) + [_target_option(game, option) for option in options],
            context=context,
        )

    # One step per slot and a last one that writes. The loop is the last thing
    # this handler does, which is ``engine/resumption.py``'s other half.
    run_resumable(game, [*range(len(slots)), None], step)
    return True, "resolved"
