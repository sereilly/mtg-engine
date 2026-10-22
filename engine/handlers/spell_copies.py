"""Copying a spell on the stack (CR 707.10).

One builder, ``_copy_of_spell``, for every effect that copies a spell — every
decision the original made goes with the copy (CR 707.10: modes, targets, X,
additional and alternative costs) — and the four sentences that call it: "copy
that spell" off a cast trigger (Double Vision, Mirari), "copy target instant or
sorcery spell" (Fork), "copy this spell" (Chain Lightning) and "copy that spell
for each other permanent or player the spell could target" (Radiate). A copy
that may choose new targets is re-aimed through ``arm_copy_spell_target``.

Split out of ``stack.py`` at the 2,000-line cap's split round. A card put back
onto the stack *as* a copy of the spell it was (Ertai's Meddling) stays with the
exile that froze its announcement, in ``stack.py``; changing the target of a
spell that is not a copy is ``retargeting.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..color_changes import forget_spell_color_change, recolor_spell
from ..game_types import StackItem
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
    """
    caster = context.caster
    copied = triggering_spell(game, context)
    if copied is None:
        copied = (context.trigger_context or {}).get("cast_item")
    if copied is None:
        game.log.append(f"{context.card.name}: that spell is no longer on the stack")
        return True, "resolved"
    caster_index = game.players.index(caster)
    copy = _copy_of_spell(copied, caster_index)
    # CR 707.10: a copy has the original's targets (or the ones the copying
    # effect changed them to). It does not choose again.
    game._stack_push(targets_already_chosen=True, item=copy)
    game.log.append(f"{context.card.name} copied {copied.card.name}")
    # "**You may choose new targets for the copy.**" (CR 707.10c.) The
    # sentence is part of this production - the parse requires it - and it was
    # consumed and never offered. Asked through the prompt Chain Lightning's
    # copy already uses, which re-aims **one** permanent-or-player target of
    # a spell with one mode: a copy that chose anything else (several targets,
    # a spell, a card in a graveyard, a mode other than the first) keeps the
    # original's, which is the offer declined rather than a list for the wrong
    # slot. A seat that is not asked keeps the original's too.
    if _copy_reaim_is_one_slot(game, copy):
        game.arm_copy_spell_target(caster_index, copy)
    return True, "resolved"


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
        target_permanent_index=copied.target_permanent_index,
        target_permanent_id=copied.target_permanent_id,
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
    named_id = (
        context.target_permanent_id
        if isinstance(context.target_permanent_id, int) else None
    )
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
            copy.target_permanent_index = game.battlefield_index_of(named)
            copy.target_permanent_id = named.permanent_id
        elif named_id is not None:
            # The permanent named on the cast has left: the copy's new target
            # is gone with it, and CR 608.2b removes the copy as it resolves.
            copy.target_permanent_index = None
            copy.target_permanent_id = named_id
        else:
            # A caller that announced a slot and stamped no id: the slot is
            # all there is, on the seat the resolution was given.
            copy.target_player_index = (
                game.players.index(context.target)
                if context.target is not None else copied.target_player_index
            )
            copy.target_permanent_index = context.target_permanent_index
            copy.target_permanent_id = None

    game._stack_push(
        # CR 707.10: a copy has the original's targets (or the ones the
        # copying effect changed them to). It does not choose again.
        targets_already_chosen=True,
        item=copy,
    )
    # "…**except that the copy is red.**" CR 707.9b: a characteristic the copy
    # effect sets is the copy's own. It was the one rider of Fork's line nothing
    # did — a Forked Ancestral Recall was a blue spell — and the copy also kept
    # whatever colour an *effect* had given the original (a Lace's record rides
    # ``choices``, which is copied whole): CR 707.2 copies the printed values
    # and the decisions made in casting, not other effects on the object.
    forget_spell_color_change(game.stack[-1])
    recolor_spell(game.stack[-1], "R")
    game.log.append(f"{card.name} copied {copied.card.name} (copy put on the stack)")
    if named_on_the_cast:
        # CR 707.10c: "You may choose new targets for the copy" — and this
        # caster did. A copy that kept the original's targets chose nothing,
        # which is why ``_stack_push`` announces no copy on its own.
        #
        # No ``newly_targeted``: this copy was *pushed* with its new target,
        # so ``_stack_push_object`` has already announced it.
        game.announce_targets_chosen(game.stack[-1], chooser=caster_index)
    elif caster_index in game.interactive_seats and _copy_reaim_is_one_slot(
        game, game.stack[-1]
    ):
        # …and a caster who named none **is asked**. The sentence was offered
        # only through the cast's own second step, which a client runs for a
        # permanent picker and cannot run for a player at all — so a Forked
        # Lightning Bolt aimed at a face could not be re-aimed, by any click
        # or any request: no prompt was armed. The prompt the trigger's copy
        # one handler up already uses (and Chain Lightning's), under its
        # condition: one permanent-or-player target, no mode. Its candidates
        # are the copied card's own picker's, the original's target among
        # them — keeping it is the "may" declined.
        #
        # Never beside a target named on the cast: that caster has answered,
        # and a second question would be the same one asked twice. And only
        # of a seat somebody is asking — the prompt's default for any other
        # is "keep the original's", which is what the copy already holds, so
        # an AI's or a headless Fork is left exactly as it was.
        game.arm_copy_spell_target(caster_index, game.stack[-1])
    return True, "resolved"


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
        target_permanent_index=(
            original.target_permanent_index if original is not None
            else context.target_permanent_index
        ),
        target_permanent_id=(
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
    game._stack_push(item=copy, targets_already_chosen=True)
    game.log.append(
        f"{game.players[seat].name} copied {context.card.name} (copy put on the stack)"
    )
    if instruction.payload.get("may_choose_new_target"):
        game.arm_copy_spell_target(seat, copy)
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
    if current is None:
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
            copy.target_permanent_index = game.battlefield_index_of(perm)
            copy.target_permanent_id = perm.permanent_id
            label = perm.card.name
        else:
            continue
        game._stack_push(targets_already_chosen=True, item=copy)
        game.announce_targets_chosen(copy, chooser=seat, newly_targeted=True)
        game.log.append(f"{card.name} copied {copied.card.name} targeting {label}")
        made += 1
    if not made:
        game.log.append(f"{card.name}: {copied.card.name} could target nothing else")
    return True, "resolved"
