"""Control-changing effect handlers — CR 613 layer 2 as one-shot effects.

The steal family: a control change is a *contribution* recorded through
``engine/control.py`` (``take_control`` / ``change_control``), never a move,
and each handler here differs only in what ends it — cleanup for the
until-end-of-turn form, the ON_LEAVE hook for Aladdin's, the monitored
``LINKED_CONTROL_CONDITIONS`` sweep (CR 611.2b, ``mixins/game_ending.py``)
for the linked Legends steals. Split out of ``board_misc.py`` when this
family pushed it past the 1,000-line signal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import permanent_matches_filter, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


@effect_handler("gain_control_until_eot")
def gain_control_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Gain control of target creature until end of turn." (Traitorous Greed.)

    A CR 613 layer-2 *contribution* with a lifetime rather than a move, so
    nothing has to be put back: cleanup drops the contribution and whatever
    remains decides. ``base_controller_index`` is untouched, which is what makes
    the reversion correct and CR 108.3 ownership still read off the original
    seat.

    The contribution belongs to the **spell**, not to a permanent — there is no
    permanent to belong to — so the card is its source. Two copies in one turn
    collapse to one contribution, which is the right answer: both end at the same
    cleanup.
    """
    from ..control import change_control

    # "Gain control of **that creature** until end of turn." (Disharmony.)
    # The object was bound by an earlier step of this same resolution and
    # recorded by id; nothing is chosen here (CR 611.2c fixed the set when
    # the effect began). An empty record is a legal outcome — the earlier
    # step may have found nothing — and is not an error.
    bound_key = instruction.payload.get("permanents_from")
    if bound_key:
        seat = game.players.index(context.caster)
        for permanent_id in context.results.get(bound_key) or ():
            bound = game.permanent_by_id(permanent_id)
            if bound is None:
                continue
            change_control(bound, seat, source=context.card, until_eot=True)
            game.log.append(
                f"{context.caster.name} gains control of {bound.card.name} "
                "until end of turn"
            )
        game._sync_control()
        return True, "resolved"

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: permanent_matches_filter(perm, filters),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent to gain control of")
        return True, "resolved"
    seat = game.players.index(context.caster)
    change_control(target, seat, source=context.card, until_eot=True)
    game._sync_control()
    context.results["controlled_permanent"] = target.permanent_id
    # The sentences after this one are *about the same creature* ("Untap that
    # creature. It gains haste…"), and it is now on a different battlefield.
    # `context.target` is the seat the remaining steps resolve their target id
    # against — deliberately scoped, so a stale id cannot resolve to a permanent
    # that changed hands between the choice and the resolution. This effect is
    # what changed those hands, one step ago, so the scope is updated rather than
    # widened: the id still has to name a permanent that seat controls.
    context.target = context.caster
    game.log.append(
        f"{context.caster.name} gains control of {target.card.name} until end of turn"
    )
    return True, "resolved"


@effect_handler("steal_target_permanent_linked_to_self")
def steal_target_permanent_linked_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Aladdin: "Gain control of target artifact for as long as you control
    this creature." The control change is a CR 613 layer-2 contribution keyed
    on Aladdin itself (not on an Aura), so ON_LEAVE_BATTLEFIELD["Aladdin"] ends
    it with end_control_changes_from when Aladdin leaves the battlefield."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # Guardian Beast: "other players can't gain control of" the artifacts it
    # protects.
    target_perm = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.has_type("artifact") and not game._untapped_artifact_protector_active(p),
    )
    if target_perm is None:
        game.log.append(f"{card.name}: no valid artifact target")
        return True, "resolved"
    from ..control import LINKED_CONTROL_CONDITIONS

    # "…for as long as **you control** this creature" is a condition, not just
    # a leave-the-battlefield event: Control Magic on Aladdin ends the steal
    # with Aladdin still on the battlefield (CR 611.2b). The state-based sweep
    # reads this record; the ON_LEAVE hook still ends the change at the moment
    # of leaving, and the sweep finds nothing left to do.
    if not game.take_control(
        target_perm, caster, source=source_permanent,
        extra_meta={LINKED_CONTROL_CONDITIONS: ("you_control_source",)},
    ):
        return True, "resolved"
    game.log.append(f"{card.name} gains control of {target_perm.card.name}")
    return True, "resolved"


@effect_handler("steal_creature_while_tapped_and_weaker")
def steal_creature_while_tapped_and_weaker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Old Man of the Sea: "Gain control of target creature with power less
    than or equal to this creature's power for as long as this creature
    remains tapped and that creature's power remains less than or equal to
    this creature's power." Both revert conditions are re-checked
    continuously by the game_ending.py SBA-style check (stolen_while_tapped_
    and_weaker marks this as that specific steal, distinct from Aladdin's
    single-condition linked duration)."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _eligible(perm: Permanent) -> bool:
        return perm.is_creature and perm.effective_power <= source_permanent.effective_power

    target_perm = resolve_target_permanent(game, context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    if not game.take_control(
        target_perm,
        caster,
        source=source_permanent,
        extra_meta={"stolen_while_tapped_and_weaker": True},
    ):
        return True, "resolved"
    game.log.append(f"{card.name} gains control of {target_perm.card.name}")
    return True, "resolved"


@effect_handler("steal_target_linked_to_source")
def steal_target_linked_to_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Willow Satyr / Rubinia Soulsinger: "Gain control of target [legendary]
    creature for as long as you control this creature and this creature
    remains tapped."

    The contribution is Aladdin's (CR 613 layer 2, keyed on the source
    permanent); what is new is the **monitored** duration: the payload's
    ``link_conditions`` are stamped onto the source
    (``engine/control.LINKED_CONTROL_CONDITIONS``) and the state-based sweep
    in ``mixins/game_ending.py`` re-checks them, so the change ends the moment
    the source untaps, changes controller or leaves (CR 611.2b).

    CR 611.2b's other half is checked here first: a duration already over when
    the effect would first apply means the effect never starts — the rule's
    own example (Master Thief) is this ability's sentence. So untapping the
    source in response leaves the target where it is, rather than stealing it
    for the moment before the sweep would revert it.
    """
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    seat = game.players.index(caster)
    conditions = tuple(instruction.payload.get("link_conditions") or ())
    if (
        "you_control_source" in conditions
        and game.controller_index_of(source_permanent) != seat
    ):
        game.log.append(
            f"{context.card.name}: no longer under its activator's control, "
            "so the control change never starts"
        )
        return True, "resolved"
    if "source_remains_tapped" in conditions and not source_permanent.tapped:
        game.log.append(
            f"{context.card.name} is untapped, so the control change never starts"
        )
        return True, "resolved"
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    target_perm = resolve_target_permanent(
        game, context,
        predicate=lambda p: permanent_matches_filter(p, filters),
        fallback_on_invalid_choice=False,
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target to gain control of")
        return True, "resolved"
    from ..control import LINKED_CONTROL_CONDITIONS

    if not game.take_control(
        target_perm, caster, source=source_permanent,
        extra_meta={LINKED_CONTROL_CONDITIONS: conditions},
    ):
        return True, "resolved"
    game.log.append(f"{context.card.name} gains control of {target_perm.card.name}")
    return True, "resolved"


@effect_handler("steal_blockers_of_source")
def steal_blockers_of_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The Wretched: "At end of combat, gain control of all creatures blocking
    this creature for as long as you control this creature."

    The set was fixed when the trigger fired (CR 611.2c): the end-of-combat
    dispatcher captured the blockers by id into the trigger context, because
    by the time this resolves the combat record has been cleared. Each steal
    is the same monitored contribution the targeted form records, with the
    single "you control this creature" condition — the sweep ends every one
    of them together when The Wretched changes controller or leaves.
    """
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None or caster is None:
        return True, "resolved"
    seat = game.players.index(caster)
    if game.controller_index_of(source_permanent) != seat:
        # CR 611.2b: the duration was over before the effect first applied.
        game.log.append(
            f"{context.card.name}: no longer under its controller's control, "
            "so the control change never starts"
        )
        return True, "resolved"
    from ..control import LINKED_CONTROL_CONDITIONS

    conditions = tuple(instruction.payload.get("link_conditions") or ())
    stolen = 0
    for permanent_id in (context.trigger_context or {}).get("blocker_ids") or ():
        blocker = game.permanent_by_id(permanent_id)
        if blocker is None:
            continue
        if game.take_control(
            blocker, caster, source=source_permanent,
            extra_meta={LINKED_CONTROL_CONDITIONS: conditions},
        ):
            game.log.append(
                f"{context.card.name} gains control of {blocker.card.name}"
            )
            stolen += 1
    if not stolen:
        game.log.append(f"{context.card.name}: nothing was blocking it")
    return True, "resolved"
