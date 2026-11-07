"""Copying a spell on the stack (CR 707.10).

One builder, ``_copy_of_spell``, for every effect that copies a spell — every
decision the original made goes with the copy (CR 707.10: modes, targets, X,
additional and alternative costs) — and the four sentences that call it: "copy
that spell" off a cast trigger (Double Vision, Mirari), "copy target instant or
sorcery spell" (Fork), "copy this spell" (Chain Lightning) and "copy that spell
for each other permanent or player the spell could target" (Radiate). A copy
that may choose new targets is offered them through one offer,
``_offer_copy_new_target`` (``offer_new_targets`` for a single copy), whatever
road made it — a prompt for a seat somebody asks, the measured answer for one
nobody asks.

Split out of ``stack.py`` at the 2,000-line cap's split round. A card put back
onto the stack *as* a copy of the spell it was (Ertai's Meddling) stays with the
exile that froze its announcement, in ``stack.py``; changing the target of a
spell that is not a copy is ``retargeting.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..color_changes import forget_spell_color_change, recolor_spell
from ..game_types import (StackItem, as_target_ids, as_target_slots,
                          single_chosen_id)
from ..resumption import run_resumable
from ._targets import triggering_spell
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("copy_triggering_spell")
def copy_triggering_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Copy that spell. You may choose new targets for the copy."
    (Double Vision.)

    "That spell" is the one the trigger fired on: the object the event
    recorded (``cast_item``) — not the topmost instant or sorcery, which is
    the same object only while nothing has been cast in response, and not the
    card it was cast from, which every other copy of that card on the stack
    shares.

    **A spell that has left the stack is still copied**, as it last existed
    there (CR 608.2h: an effect that needs information from an object no
    longer in the zone it was expected in uses its last known information).
    Both cards printing the sentence are ruled so — Double Vision
    (2020-06-23): "A copy is created even if the spell that caused Double
    Vision's ability to trigger has been countered by the time that ability
    resolves"; Mirari (2004-10-04): "the ability will make a copy of how the
    spell looked right before it was countered". This handler copied nothing
    then, which was the right answer to a different mistake: the lookup it
    replaced went by card, so with the first Bolt of the turn countered in
    response it copied an opponent's Bolt underneath. The frozen object is
    what answers both - it is that spell and no other, on the stack or off.

    A trigger whose event froze no spell copies nothing: there is no "that
    spell" for the words to name.

    **How many is payload** (``for_each``), read by one reader
    (``storm.copies_for_each``). Storm (CR 702.40a) is this sentence with a
    count: "copy it for each other spell that was cast before it this turn. If
    the spell has any targets, you may choose new targets for any of the
    copies." Each copy is its own object with its own offer (2022-12-08 ruling:
    "You can make different choices for each copy"), and a count of none makes
    none. Absent, it is one copy — Double Vision's and Mirari's payload is
    unchanged.
    """
    caster = context.caster
    copied = triggering_spell(game, context)
    if copied is None:
        copied = (context.trigger_context or {}).get("cast_item")
    if copied is None:
        game.log.append(f"{context.card.name}: that spell is no longer on the stack")
        return True, "resolved"
    caster_index = game.players.index(caster)
    copies = 1
    counted = instruction.payload.get("for_each")
    if counted is not None:
        from ..storm import copies_for_each

        owed = copies_for_each(game, counted, copied)
        if owed is None:
            # A count nothing can read is not a number to guess: no copy.
            game.log.append(
                f"{context.card.name}: no record says how many copies to make"
            )
            return True, "resolved"
        copies = owed
        if not copies:
            game.log.append(
                f"{context.card.name}: no spell was cast before it this turn, "
                "so nothing is copied"
            )
            return True, "resolved"
    made: list[StackItem] = []

    def step(position) -> None:
        # The answer to the copy before this one, if it was asked through the
        # prompt that suspends (a card in a graveyard, a spell), exactly once.
        _apply_copy_new_target(game, context, made, caster_index)
        _settle_unasked_copies(game, made, caster_index)
        if position is None:
            return
        copy = _copy_of_spell(copied, caster_index)
        # CR 707.10: a copy has the original's targets (or the ones the
        # copying effect changed them to). It does not choose again — and
        # it is announced once its controller has decided whether to change
        # them (CR 707.10c, ``announce=False``).
        game._stack_push(targets_already_chosen=True, item=copy, announce=False)
        made.append(copy)
        game.log.append(f"{context.card.name} copied {copied.card.name}")
        # "**You may choose new targets for the copy.**" (CR 707.10c.) The
        # sentence is part of this production - the parse requires it - and
        # it was consumed and never offered. Numbered, so a person asked
        # about each of a storm's copies in turn is told which one this is.
        _offer_copy_new_target(
            game, context, copy, caster_index,
            copy_number=position + 1, copy_count=copies,
        )

    # One step per copy and a last one that takes the final answer. The loop
    # is the last thing this handler does (``engine/resumption.py``): a copy
    # whose new target is a card in a graveyard or a spell is asked through
    # ``retarget_choice``, which suspends the resolution until it is answered.
    run_resumable(game, [*range(copies), None], step)
    return True, "resolved"


#: Where a ``retarget_choice`` armed for a copy writes its answer, in the
#: resolution's records, for the next step of the copy loop to read.
_COPY_NEW_TARGET = "_copy_new_target"


def _settle_unasked_copies(game: Game, made: list, seat: int) -> None:
    """Announce every copy in *made* whose offer is settled and that still
    owes its announcements (``StackItem.announcement_owed``): one no prompt
    holds — the ``copy_spell_target`` offer it was armed with has been
    answered, or none was armed. The offer's own answer announces the copy it
    moved; this is the catch for every way an offer ends without one."""
    for copy in made:
        if not copy.announcement_owed:
            continue
        if any(
            choice.data.get("_copy") is copy for choice in game.pending_choices
        ):
            continue
        game.announce_copy_put_onto_stack(copy, chooser=seat)


def _offer_copy_new_target(
    game: Game, context: OracleExecutionContext, copy: StackItem, seat: int,
    *, copy_number: int | None = None, copy_count: int | None = None,
) -> None:
    """Offer *seat* the new target CR 707.10c lets it choose for *copy*.

    **A permanent or a player** goes through the prompt Chain Lightning's copy
    already uses (``copy_spell_target``), answered onto the copy directly — for
    every seat, its default keeping the original's unless the seat is one
    nobody asks and re-aiming it measures better (``ai_prompts.choose_copy_target``).

    **A card in a graveyard or a spell** — Reaping the Graves' "target
    creature card from your graveyard", Hindering Touch's "target spell" —
    goes through CR 115.7's change: ``stack_targets.change_slots`` enumerates
    what the copy could have chosen through the picker's own list, and
    ``retarget_choice`` (Psychic Battle's prompt) offers "keep" beside each.
    Before this a storm copy of Reaping the Graves could only return the card
    its original named, and every copy after the first did nothing. Asked of an
    interactive seat; any other seat's answer is measured, as
    ``copy_spell_target``'s default measures it (``ai_prompts.choose_copy_retarget``:
    each option rehearsed against keeping the original's), and applied here
    at once, since no prompt is armed for it.

    One target only, as ``copy_spell_target`` asks: a copy that chose several
    keeps them all, which is the offer declined rather than a list for the
    wrong slot.

    *copy_number* of *copy_count* is which copy this is, for the prompt's
    words ("copy 2 of 4"); it changes nothing about what is offered.
    """
    if _copy_reaim_is_one_slot(game, copy):
        if not game.arm_copy_spell_target(
            seat, copy, copy_number=copy_number, copy_count=copy_count,
        ):
            # Nothing to change to: the copy keeps the original's targets.
            game.announce_copy_put_onto_stack(copy, chooser=seat)
        return
    from ..stack_targets import (apply_target_change, change_options, change_slots,
                                 target_label)
    from .retargeting import _target_option

    slots = change_slots(game, copy)
    if isinstance(slots, str) or len(slots) != 1:
        game.announce_copy_put_onto_stack(copy, chooser=seat)
        return
    if slots[0].current.kind not in ("graveyard", "stack"):
        game.announce_copy_put_onto_stack(copy, chooser=seat)
        return
    options = change_options(slots, [])
    if not options:
        game.announce_copy_put_onto_stack(copy, chooser=seat)
        return
    if seat not in game.interactive_seats:
        from ..ai_prompts import choose_copy_retarget

        pick = choose_copy_retarget(game, seat, copy, slots, options)
        moved = pick is not None and apply_target_change(game, copy, slots, [pick])
        if moved:
            game.log.append(f"{copy.card.name} (copy) targets {target_label(game, pick)}")
        game.announce_copy_put_onto_stack(copy, chooser=seat, chose=moved)
        return
    name = copy.card.name
    which = (
        f"copy {copy_number} of {copy_count} of {name}"
        if copy_count is not None and copy_number is not None and copy_count > 1
        else f"the copy of {name}"
    )
    game.arm_retarget_choice(
        seat,
        card_name=name,
        prompt=(
            f"Choose a new target for {which} "
            f"(now {target_label(game, slots[0].current)}), or keep it."
        ),
        result_key=_COPY_NEW_TARGET,
        options=[{"kind": "keep", "name": "Keep the original's target"}]
        + [_target_option(game, option) for option in options],
        context=context,
        # Taken by default (a test's drain, an abandoned seat), the offer is
        # declined, as ``copy_spell_target``'s is.
        default_keeps=True,
    )
    context.results[f"{_COPY_NEW_TARGET}_slots"] = slots


def _apply_copy_new_target(
    game: Game, context: OracleExecutionContext, made: list, seat: int,
) -> None:
    """Write the answer :func:`_offer_copy_new_target` asked through
    ``retarget_choice`` onto the copy it was asked about — the last one made —
    once. "Keep", or an answer whose object has gone (CR 115.7a: the target is
    then unchanged), changes nothing."""
    if _COPY_NEW_TARGET not in context.results:
        return
    from ..stack_targets import apply_target_change, target_label

    answer = context.results.pop(_COPY_NEW_TARGET)
    slots = context.results.pop(f"{_COPY_NEW_TARGET}_slots", None)
    if not made:
        return
    copy = made[-1]
    pick = answer.get("_target") if isinstance(answer, dict) else None
    moved = bool(slots) and pick is not None and apply_target_change(
        game, copy, slots, [pick],
    )
    if moved:
        game.log.append(f"{copy.card.name} (copy) targets {target_label(game, pick)}")
    # Announced once, now its controller has answered (CR 707.10c) — kept or
    # moved.
    game.announce_copy_put_onto_stack(copy, chooser=seat, chose=moved)


def _copy_of_spell(copied: StackItem, controller_index: int) -> StackItem:
    """A copy of the spell *copied*, controlled by *controller_index*, with
    every decision made for the original (CR 707.10: "…it copies all
    decisions made when casting it, including modes, targets, the value of X,
    and additional or alternative costs").

    One builder for every effect that copies a spell on the stack. There were
    two, written a set apart, and each had been taught a different half of the
    rule: the trigger's copy (Double Vision, Mirari) carried the graveyard
    card and the several modes of a "choose one or more", and Fork's carried
    neither — so a Forked spell aimed at a card in a graveyard, or one cast
    with two modes, was a copy that had forgotten what it was for.

    **The identity travels with the copy.** An original announced by
    ``permanent_id`` alone, which is how the web layer announces every target,
    has no slot: a copy holding a seat and no object resolved as a spell aimed
    at that player's face, and a copied Lightning Bolt pointed at a creature
    dealt its 3 to the creature's controller.
    """
    copy = StackItem(
        card=copied.card,
        caster_index=controller_index,
        target_player_index=copied.target_player_index,
        target_permanent_index=as_target_slots(copied.target_permanent_index),
        # Its own list: a slot CR 608.2b blanks on one is not blanked on the
        # other.
        target_permanent_id=as_target_ids(copied.target_permanent_id),
        target_graveyard_card=copied.target_graveyard_card,
        x_value=copied.x_value,
        # The copy has the original's choices, so this is one assignment
        # rather than one per choice the original made.
        choices=dict(copied.choices),
        chosen_mode_index=copied.chosen_mode_index,
        chosen_modes=copied.chosen_modes,
        target_stack_item=copied.target_stack_item,
        is_copy=True,
    )
    # …less the one thing in that dict that is not a choice: a colour an effect
    # gave the original (a Lace's record rides ``choices``). CR 707.2 copies
    # the printed values and the decisions, and "other effects … are not
    # copied".
    forget_spell_color_change(copy)
    return copy


def _copy_reaim_is_one_slot(game: Game, copy: StackItem) -> bool:
    """Whether *copy* chose exactly one target ``arm_copy_spell_target`` can
    re-aim: a permanent or a player, on a spell that announced no mode.

    Read off ``stack_targets.chosen_targets``, the one reader of what a stack
    object announced, so "one target" is what the object says rather than a
    count of the channels this handler happens to know.
    """
    from ..stack_targets import chosen_targets

    if copy.chosen_mode_index is not None or copy.chosen_modes:
        return False
    chosen = chosen_targets(game, copy)
    return (
        chosen is not None
        and len(chosen) == 1
        and chosen[0].kind in ("permanent", "player")
    )


@effect_handler("copy_top_stack_spell")
def copy_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Fork: "Copy target instant or sorcery spell... You may choose new targets for
    # the copy." Copy the chosen spell if one was targeted, otherwise the topmost
    # instant or sorcery on the stack (Fork itself has already been popped to
    # resolve). The copy is put onto the stack under Fork's controller so it
    # resolves independently, and gets new targets if the Fork caster chose them.
    caster = context.caster
    card = context.card
    copied = None
    chosen = context.stack_target
    if chosen is not None and chosen in game.stack and chosen.card.primary_type in ("instant", "sorcery"):
        copied = chosen
    if copied is None:
        copied = next(
            (item for item in reversed(game.stack) if item.card.primary_type in ("instant", "sorcery")),
            None,
        )
    if copied is None:
        game.log.append(f"{card.name} resolved with no instant or sorcery spell to copy")
        return True, "resolved"

    caster_index = game.players.index(caster)
    # Every decision made for the original (CR 707.10), through the one
    # builder — this handler had its own, which left the graveyard card and
    # the several modes of a "choose one or more" behind.
    copy = _copy_of_spell(copied, caster_index)
    # "You may choose new targets for the copy." Two ways a caster says so.
    # **On the cast**: a new permanent target named beside the Fork (a
    # creature/permanent index, optionally on a specific player) is where the
    # copy goes, and is the whole of the answer. **Or, having named none, at
    # the prompt below.**
    #
    # Asked of the **id** first: the slot beside it is re-read at resolution
    # relative to the seat the resolution is about
    # (``bare_announcements.resolving_slots``), which for Fork is the forked
    # spell's controller (below) — so a creature named on the other
    # battlefield has no slot there, and read by the slot alone the new target
    # was "not named".
    named_id = single_chosen_id(context.target_permanent_id)
    named_on_the_cast = (
        named_id is not None or context.target_permanent_index is not None
    )
    if named_on_the_cast:
        # **By the id the cast stamped, not by a seat read off the context.**
        # ``context.target`` is no longer the seat the caster named: an
        # instant whose every target is a spell on the stack resolves about
        # that spell's *controller* (``Game.stack_target_seat``, "counter
        # target spell. Its controller loses 3 life"), and Fork's one target
        # is a spell. So the named slot was counted into the forked spell's
        # controller's battlefield — a Fork of one's own Bolt re-aimed at an
        # opponent's creature hit one's own creature in that slot instead,
        # two of the four seatings wrong. The id names the object and its
        # battlefield both (CR 400.7), and travels onto the copy.
        named = game.permanent_by_id(named_id) if named_id is not None else None
        if named is not None:
            copy.target_player_index = game.controller_index_of(named)
            copy.target_permanent_index = as_target_slots(
                game.battlefield_index_of(named)
            )
            copy.target_permanent_id = [named.permanent_id]
        elif named_id is not None:
            # The permanent named on the cast has left: the copy's new target
            # is gone with it, and CR 608.2b removes the copy as it resolves.
            copy.target_permanent_index = None
            copy.target_permanent_id = [named_id]
        else:
            # A caller that announced a slot and stamped no id: the slot is
            # all there is, on the seat the resolution was given.
            copy.target_player_index = (
                game.players.index(context.target)
                if context.target is not None else copied.target_player_index
            )
            copy.target_permanent_index = as_target_slots(
                context.target_permanent_index
            )
            copy.target_permanent_id = None

    game._stack_push(
        # CR 707.10: a copy has the original's targets (or the ones the
        # copying effect changed them to). It does not choose again — and it
        # is announced once its targets are decided (CR 707.10c), below.
        targets_already_chosen=True,
        item=copy,
        announce=False,
    )
    # The copy keeps none of the colour an *effect* gave the original (a
    # Lace's record rides ``choices``, which is copied whole): CR 707.2 copies
    # the printed values and the decisions made in casting, not other effects
    # on the object.
    forget_spell_color_change(game.stack[-1])
    # "…**except that the copy is red.**" (Fork.) CR 707.9b: a characteristic
    # the copy effect sets is the copy's own — the payload's ``recolor``, which
    # the grammar writes only where the card prints the exception
    # (``lowering.stack._lower_copy_target_spell``). Mischievous Quanar prints
    # none, and its copy is the original's colour.
    recolor = instruction.payload.get("recolor")
    if recolor:
        recolor_spell(game.stack[-1], recolor)
    game.log.append(f"{card.name} copied {copied.card.name} (copy put on the stack)")
    if named_on_the_cast:
        # CR 707.10c: "You may choose new targets for the copy" — and this
        # caster did, on the cast: the copy is put onto the stack with them,
        # announced once (the colour above already its own, CR 707.9b).
        # Never asked again: that caster has answered, and a second question
        # would be the same one asked twice.
        game.announce_copy_put_onto_stack(copy, chooser=caster_index, chose=True)
        return True, "resolved"
    # …and a caster who named none **is offered it**, through the one offer
    # every copy road makes (:func:`offer_new_targets`) — the trigger's
    # copies' (Double Vision, storm). The sentence was offered only through
    # the cast's own second step, which a client runs for a permanent picker
    # and cannot run for a player at all; then only to a seat somebody asks,
    # for one permanent-or-player target. So a headless or AI Fork — and
    # Mischievous Quanar's turn-up copy, the same kind — kept the original's
    # target: an opponent's Bolt aimed at the copier's own creature was
    # copied onto that creature (kg4). A seat nobody asks now takes the
    # measured answer (``ai_prompts.choose_copy_target``), and a copy whose
    # one target is a spell or a card in a graveyard (a Forked Counterspell)
    # is offered CR 115.7's change, as a storm copy's is.
    offer_new_targets(game, context, copy, caster_index)
    return True, "resolved"


def offer_new_targets(
    game: Game, context: OracleExecutionContext, copy: StackItem, seat: int,
) -> None:
    """CR 707.10c's "you may choose new targets for the copy", for one copy
    already pushed unannounced (``announce=False``): offered to *seat*
    (:func:`_offer_copy_new_target` — a prompt for a seat somebody asks, the
    measured answer for one nobody asks), the answer written onto the copy,
    and the copy announced once its targets are decided.

    A loop of one offer and the step that takes its answer, because a copy
    whose new target is a card in a graveyard or a spell is asked through
    ``retarget_choice``, which suspends the resolution until it is answered
    (``engine/resumption.py``): **the last thing its caller does**."""
    made = [copy]

    def step(position) -> None:
        if position is None:
            _apply_copy_new_target(game, context, made, seat)
            _settle_unasked_copies(game, made, seat)
            return
        _offer_copy_new_target(game, context, copy, seat)

    run_resumable(game, [0, None], step)


@effect_handler("copy_this_spell")
def copy_this_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…they may copy this spell and may choose a new target for that copy."
    (Chain Lightning.)

    Three things separate this from ``copy_top_stack_spell`` next door, and the
    first is why it cannot reuse it:

    1. **"This spell" is not on the stack.** ``mixins/stack/resolution`` pops a
       stack object *before* executing it, so while Chain Lightning is
       resolving the topmost instant or sorcery up there is somebody else's —
       and a copy-the-top handler would copy that one. The resolving object is
       ``Game.resolving_items``, which is pushed around exactly this window;
       matched by card identity so a nested resolution cannot be mistaken for
       the outer one.
    2. **The copy is not the caster's.** CR 707.10a: the copy is controlled by
       whoever the effect says, and here that is the player who paid — read off
       the payload the sentence's printed subject lowered to, never assumed.
    3. **The re-aiming is that seat's choice**, offered as a pending choice so
       an interactive player answers it and a non-interactive one takes the
       stated default at once (see ``arm_copy_spell_target``).
    """
    who = instruction.payload.get("controller", "you")
    # "you" is the resolving spell's controller (CR 109.5); every other printed
    # subject this sentence can carry names the seat an earlier step recorded,
    # which is what `context.target` holds.
    holder = context.caster if who == "you" else (context.target or context.caster)
    seat = game.players.index(holder)

    # CR 707.10: the copy starts with the original's characteristics and
    # choices. They come from the **resolution context**, not from a stack
    # object, and that is the whole difficulty of "this spell": by the time an
    # instruction of a spell runs, this engine has popped that spell off
    # ``Game.stack``, and by the time an *optional* branch of it runs — the
    # branch a player had to be asked about — the spell may have finished
    # resolving and be in a graveyard. A scan of either place finds the wrong
    # object or none. The context is the one thing that outlives both, and it
    # carries every choice a copy needs.
    #
    # ``resolving_items`` is preferred where it still has the object, because it
    # additionally carries what the context does not (the mode chosen, a spell
    # this one targeted); it is a refinement of the answer, never the answer.
    original = next(
        (
            item
            for item in reversed(getattr(game, "resolving_items", None) or ())
            if item.card is context.card
        ),
        None,
    )
    copy = StackItem(
        card=context.card,
        caster_index=seat,
        target_player_index=(
            original.target_player_index if original is not None
            else game.players.index(context.target) if context.target is not None
            else None
        ),
        target_permanent_index=as_target_slots(
            original.target_permanent_index if original is not None
            else context.target_permanent_index
        ),
        target_permanent_id=as_target_ids(
            original.target_permanent_id if original is not None
            else context.target_permanent_id
        ),
        x_value=original.x_value if original is not None else context.x_value,
        choices=dict(
            original.choices if original is not None else context.choices
        ),
        chosen_mode_index=original.chosen_mode_index if original is not None else None,
        target_stack_item=(
            original.target_stack_item if original is not None
            else context.stack_target
        ),
        is_copy=True,
    )
    # CR 707.2: not what an effect did to the original's colour.
    forget_spell_color_change(copy)
    # Announced once its targets are decided (CR 707.10c), below.
    game._stack_push(item=copy, targets_already_chosen=True, announce=False)
    game.log.append(
        f"{game.players[seat].name} copied {context.card.name} (copy put on the stack)"
    )
    if not instruction.payload.get("may_choose_new_target"):
        game.announce_copy_put_onto_stack(copy, chooser=seat)
        return True, "resolved"
    # The one offer every copy road makes (CR 707.10c).
    offer_new_targets(game, context, copy, seat)
    return True, "resolved"


@effect_handler("copy_spell_for_each_other_target")
def copy_spell_for_each_other_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Copy that spell for each other permanent or player the spell could
    target. Each copy targets a different one of those permanents and
    players." (Radiate.)

    CR 707.10: each copy is built by ``_copy_of_spell`` (every decision the
    original made, controlled by this effect's controller, CR 707.10a) and
    then aimed at one candidate (CR 707.10c), so it "becomes the target" as
    any re-aimed copy does (``announce_targets_chosen``). The candidates are
    the copied card's own picker (``cast_spec_of`` + ``_enumerate_targets``,
    the list ``arm_copy_spell_target`` offers a Fork's controller) asked from
    the copies' controller's seat — the seat whose copy would target them —
    less the one target the spell already has. A permanent is named by its
    id (CR 400.7). The original is untouched and resolves as cast.
    """
    from ..legality import cast_spec_of
    from ..targeting import single_spell_target

    copied = context.stack_target
    card = context.card
    if copied is None or not any(obj is copied for obj in game.stack):
        game.log.append(f"{card.name}: that spell is no longer on the stack")
        return True, "resolved"
    current = single_spell_target(game, copied)
    # "…that targets only a single **permanent or player**": a spell aimed at
    # a spell has a single target too (CR 115.9a), and is not this card's.
    if current is None or current.get("kind") not in ("permanent", "player"):
        game.log.append(
            f"{card.name}: {copied.card.name} does not target only a single "
            "permanent or player"
        )
        return True, "resolved"
    seat = game.players.index(context.caster)
    spec = cast_spec_of(copied.card)
    made = 0
    for candidate in game._enumerate_targets(seat, copied.card, spec, for_cast=True):
        kind = candidate.get("kind")
        if kind == "player":
            if current.get("kind") == "player" and current.get("seat") == candidate.get("seat"):
                continue
            copy = _copy_of_spell(copied, seat)
            copy.target_player_index = candidate.get("seat")
            copy.target_permanent_index = None
            copy.target_permanent_id = None
            label = game.players[candidate["seat"]].name
        elif kind == "permanent":
            perm = game.permanent_at(candidate.get("seat"), candidate.get("index"))
            if perm is None:
                continue
            if current.get("kind") == "permanent" and current.get("permanent_id") == perm.permanent_id:
                continue
            copy = _copy_of_spell(copied, seat)
            copy.target_player_index = game.controller_index_of(perm)
            copy.target_permanent_index = as_target_slots(
                game.battlefield_index_of(perm)
            )
            copy.target_permanent_id = [perm.permanent_id]
            label = perm.card.name
        else:
            continue
        # CR 707.10d: "The copies are put onto the stack with those targets"
        # — the effect names each copy's target, so it is put there with it
        # and announced once: it becomes the target, and is put onto the
        # stack. No player chose it (Psychic Battle's "a player chooses one
        # or more targets" does not hear a target the effect assigned, the
        # reading ``announce_targets_chosen``'s ``at_random`` gives Grip of
        # Chaos's draw). This made two announcements of "becomes the target"
        # per copy — one by the push, one beside the choice.
        game._stack_push(targets_already_chosen=True, item=copy, announce=False)
        game.announce_copy_put_onto_stack(copy, chooser=seat)
        game.log.append(f"{card.name} copied {copied.card.name} targeting {label}")
        made += 1
    if not made:
        game.log.append(f"{card.name}: {copied.card.name} could target nothing else")
    return True, "resolved"
