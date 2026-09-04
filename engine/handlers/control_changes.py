"""Control-changing effect handlers — CR 613 layer 2 as one-shot effects.

The steal family: a control change is a *contribution* recorded through
``engine/control.py`` (``take_control`` / ``change_control``), never a move,
and each handler here differs only in what ends it — cleanup for the
until-end-of-turn form, the ON_LEAVE hook for Aladdin's, the monitored
``LINKED_CONTROL_CONDITIONS`` sweep (CR 611.2b, ``mixins/game_ending.py``)
for every "for as long as …" steal. Split out of ``board_misc.py`` when this
family pushed it past the 1,000-line signal.

Aladdin used to have a handler of its own, ``steal_target_permanent_linked_to_self``,
which looked for an *artifact* in its own code — so the identical printed
sentence about a land (Orcish Squatters) or a creature (Merieke Ri Berit) had
nowhere to go. The type is payload now and Aladdin resolves through
``steal_target_linked_to_source`` like every other one; the ON_LEAVE hook stays,
because the sweep and the hook end the same contribution and ending it twice is
a no-op.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import (attached_host, permanent_matches_filter,
                      resolve_target_permanent,
                      resolve_target_slots)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


#: "When you lose control of the creature, tap it." (Ray of Command, Magus of
#: the Unseen.) CR 603.7's delayed trigger, stamped on the permanent the control
#: change took and read where that change ends — the cleanup step, which is the
#: one place an until-end-of-turn control contribution is dropped. State at one
#: fire site rather than an object on the stack, the arrangement
#: `destroy_at_end_of_combat` already uses for a delayed action with one place
#: to happen. **Consumed** where it is read rather than swept: the trigger fires
#: once, for the change that armed it, and a permanent that left the battlefield
#: before then took the marker with it (CR 400.7).
TAP_WHEN_CONTROL_LOST = "tap_when_control_lost"


@effect_handler("gain_control_until_eot", "gain_control_of_target")
def gain_control_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Gain control of target creature until end of turn." (Traitorous Greed),
    and the untimed "Gain control of target nonartifact, nonblack creature."
    (Ritual of the Machine.)

    A CR 613 layer-2 *contribution* with a lifetime rather than a move, so
    nothing has to be put back: cleanup drops the contribution and whatever
    remains decides. ``base_controller_index`` is untouched, which is what makes
    the reversion correct and CR 108.3 ownership still read off the original
    seat.

    The contribution belongs to the **spell**, not to a permanent — there is no
    permanent to belong to — so the card is its source. Two copies in one turn
    collapse to one contribution, which is the right answer: both end at the same
    cleanup.

    **Two kinds, one handler, and the lifetime read off the kind.** CR 611.2a
    gives an effect with no stated duration no end at all, so the untimed steal
    is this same contribution with ``until_eot`` false — everything else about
    it (the CR 608.2b re-check, Guardian Beast's prohibition, the rescope of
    ``context.target`` for the sentences behind it) is identical, and a second
    handler would be a second place to fix each. The lifetime is the *kind*
    rather than a payload key because it is the whole difference between the
    two sentences: a lowering that forgot a flag would record an indefinite
    steal that quietly ends at cleanup, where a lowering that names the wrong
    kind reaches a table that does not have it.
    """
    from ..control import change_control

    until_eot = instruction.kind.endswith("_until_eot")
    ends = "until end of turn" if until_eot else "for as long as the game lasts"

    # "Gain control of **that creature** until end of turn." (Disharmony.)
    # The object was bound by an earlier step of this same resolution and
    # recorded by id; nothing is chosen here (CR 611.2c fixed the set when
    # the effect began). An empty record is a legal outcome — the earlier
    # step may have found nothing — and is not an error.
    # "When this Aura enters, gain control of **enchanted land** until end of
    # turn." (Wellspring.) The Aura's own host: nothing is chosen, so there
    # is no target to resolve and no noun phrase to re-check — an Aura's
    # effect on what it enchants names exactly one permanent.
    #
    # ``attached_host`` is the same reader every other attached effect uses,
    # and an Aura attached to nothing takes nothing: CR 704.5m has already
    # put such an Aura in a graveyard, so this is the resolution finding the
    # world moved rather than a failure.
    if instruction.payload.get("attached"):
        host = attached_host(game, context.source_permanent)
        if host is None or not game.is_on_battlefield(host):
            game.log.append(f"{context.card.name}: nothing is enchanted")
            return True, "resolved"
        if game.cant_gain_control(host, context.caster):
            game.log.append(
                f"{context.card.name}: {host.card.name} can't change controllers"
            )
            return True, "resolved"
        change_control(
            host, game.players.index(context.caster),
            source=context.source_permanent, until_eot=until_eot,
        )
        game._sync_control()
        game.log.append(
            f"{context.caster.name} gains control of {host.card.name} {ends}"
        )
        return True, "resolved"

    bound_key = instruction.payload.get("permanents_from")
    if bound_key:
        seat = game.players.index(context.caster)
        took = False
        for permanent_id in context.results.get(bound_key) or ():
            bound = game.permanent_by_id(permanent_id)
            if bound is None:
                continue
            # Guardian Beast at the seam's own question: Magus of the Unseen
            # untaps and borrows an *artifact*, which is exactly what the Beast
            # protects. `change_control` is reached directly here (there is no
            # source permanent to key the contribution on), so the prohibition
            # is asked rather than inherited from `take_control`.
            if game.cant_gain_control(bound, context.caster):
                game.log.append(
                    f"{context.card.name}: {bound.card.name} can't change controllers"
                )
                continue
            change_control(bound, seat, source=context.card, until_eot=until_eot)
            if instruction.payload.get("tap_when_lost"):
                bound.metadata[TAP_WHEN_CONTROL_LOST] = True
            took = True
            game.log.append(
                f"{context.caster.name} gains control of {bound.card.name} "
                f"{ends}"
            )
        game._sync_control()
        if took:
            # **The same rescope the targeted branch below makes, and for the
            # same reason.** The sentences after this one are about the creature
            # this one just moved — "That creature gains haste until end of
            # turn" (Ray of Command), "It gains haste" (Magus of the Unseen) —
            # and they resolve the announced id against `context.target`'s
            # board. Only the branch below did it, so under the bound spelling
            # the id was still scoped to the seat the creature had *left*: it
            # resolved to nothing, and the grant that followed logged "no valid
            # creature target" while the card compiled clean.
            #
            # Two branches of one handler that leave different things behind for
            # the next step is the shape this is: what differs between them is
            # how the object was named, which is nothing the sentences after
            # them can see.
            context.target = context.caster
        return True, "resolved"

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    # Through ``subject_matches`` — the one reader of what a printed noun
    # phrase means — with the seat and the source this resolution holds, so the
    # set the picker offered and the set this accepts are decided by the same
    # function. The pure matcher answers about a permanent alone and **refuses**
    # every seat-relative key outright, so "target … creature **that attacked
    # you this turn**" (Jabari's Influence) resolved to nothing after a picker
    # that had offered exactly one legal creature. That is Reality Ripple's
    # defect one file over, and the same fix.
    from ..subject_filters import subject_matches

    observer = game.players.index(context.caster)
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, filters, observer=observer,
            source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent to gain control of")
        return True, "resolved"
    if game.cant_gain_control(target, context.caster):
        game.log.append(
            f"{context.card.name}: {target.card.name} can't change controllers"
        )
        return True, "resolved"
    seat = game.players.index(context.caster)
    change_control(target, seat, source=context.card, until_eot=until_eot)
    game._sync_control()
    # The sentences after this one are *about the same creature* ("Untap that
    # creature. It gains haste…"), and it is now on a different battlefield.
    # `context.target` is the seat the remaining steps resolve their target id
    # against — deliberately scoped, so a stale id cannot resolve to a permanent
    # that changed hands between the choice and the resolution. This effect is
    # what changed those hands, one step ago, so the scope is updated rather than
    # widened: the id still has to name a permanent that seat controls.
    context.target = context.caster
    game.log.append(
        f"{context.caster.name} gains control of {target.card.name} {ends}"
    )
    return True, "resolved"


@effect_handler("give_control_of_source_to_player")
def give_control_of_source_to_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target opponent gains control of this creature." (Chaos Lord.)

    The mirror of every steal in this file: the source hands *itself* over
    rather than taking something. Same mechanism — one CR 613 layer-2
    contribution through ``take_control``, with the permanent as its own source
    — and no lifetime at all (CR 611.2b), so nothing sweeps it back. Chaos Lord
    fires this every upkeep, and re-recording replaces the previous
    contribution and takes a fresh timestamp, which is what lets the creature
    keep moving between seats turn after turn.

    A source that has left takes nobody with it, and a seat the spell never
    chose is a resolution with nothing to name: both log and stop rather than
    guessing a player, for the reason the sacrifice payer above fails on an
    unrecognized ``who`` — handing a creature to the wrong seat is the same
    wrong direction as sacrificing the wrong player's.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: it is no longer on the battlefield")
        return True, "resolved"
    who = str(instruction.payload.get("who") or "")
    if who == "you":
        recipient = context.caster
    elif who in ("target_opponent", "target_player"):
        recipient = context.target
    elif who == "chosen":
        # "**An opponent** gains control of this land …" (Rainbow Vale.) The
        # seat the ``choose_opponent`` step in front of this one announced
        # (CR 608.2d), read out of the scratchpad under the one key a chosen
        # player is ever written to. Nobody chosen means nobody gains control —
        # falling back to the caster would hand the permanent to the seat the
        # sentence has just said it is *not*.
        seat = context.results.get("chosen_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{context.card.name}: no opponent was chosen")
            return True, "resolved"
        recipient = game.players[seat]
    elif who == "event_subject_player":
        # "At the beginning of **each player's** upkeep, that player may pay
        # … **they** gain control of this creature." (Emberwilde Djinn.)
        # Nobody chose and nobody targeted: the seat is whose upkeep the
        # firing was, frozen into the trigger's context by the upkeep step
        # (CR 603.10) — the same key the offer in front of this instruction
        # armed its prompt on, so the player who paid and the player who
        # gains control are one seat by construction.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            # No frozen seat means the trigger did not record one. Falling
            # back to the caster would hand the creature to the player the
            # sentence has just named as somebody else.
            game.log.append(f"{context.card.name}: no seat was recorded")
            return True, "resolved"
        recipient = game.players[seat]
    else:
        return False, f"unsupported control recipient {who!r}"
    if recipient is None or recipient not in game.players:
        game.log.append(f"{context.card.name}: no player to hand it to")
        return True, "resolved"
    seat = game.players.index(recipient)
    if seat == game.controller_index_of(source):
        # Already theirs — the same seat was chosen twice, or an earlier
        # contribution has already moved it. Recording again would be a no-op
        # with a fresh timestamp; saying so is more useful than doing it.
        game.log.append(
            f"{context.card.name} is already controlled by {recipient.name}"
        )
        return True, "resolved"
    if not game.take_control(source, seat, source=source):
        # `take_control` refuses CR 614.17's prohibition (Guardian Beast) and a
        # permanent on no battlefield. Both are "the control change does not
        # happen", which is a legal outcome and not a failure of the ability.
        game.log.append(f"{context.card.name}: control can't change")
        return True, "resolved"
    game.log.append(f"{recipient.name} gains control of {context.card.name}")
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
    if "source_on_battlefield" in conditions and not game.is_on_battlefield(
        source_permanent
    ):
        # CR 611.2b's other half again: a duration already over when the effect
        # would first apply means the effect never starts. The Bandits can be
        # killed in response to their own ability.
        game.log.append(
            f"{context.card.name} has left the battlefield, so the control "
            "change never starts"
        )
        return True, "resolved"
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        # "…gain control of target creature **of an opponent's choice** they
        # control" (Preacher). The creature was picked by another seat as this
        # resolution ran, so it comes out of the scratchpad rather than off the
        # ability's own target — the same `permanents_from` reading every other
        # step that acts on an earlier one's pick uses.
        permanent_id = context.results.get(recorded_key)
        target_perm = (
            game.permanent_by_id(permanent_id) if permanent_id is not None else None
        )
    else:
        filters = (instruction.payload.get("targets") or {}).get("filter") or {}
        # Through ``subject_matches`` rather than the pure matcher, because one
        # narrowing a steal may print is not about the object at all: "target
        # creature **whose controller controls an Island**" (Seasinger) asks
        # what the candidate's controller has elsewhere, which needs the game.
        # ``controller`` is lifted off first — it is enforced by the picker at
        # activation (``_PICKER_ENFORCED_CONTROLLERS``), and asking it again
        # here against a seat this call does not name would refuse every
        # candidate rather than narrow the set.
        # Imported here rather than at module scope: ``subject_filters`` reads
        # this package's ``_common``, so a module-level import closes the cycle
        # through ``engine/handlers/__init__.py`` — the same reason
        # ``handlers/stack.py`` imports ``control_flow`` inside its function.
        from ..subject_filters import subject_matches

        observed = {k: v for k, v in filters.items() if k != "controller"}
        target_perm = resolve_target_permanent(
            game, context,
            predicate=lambda p: (
                subject_matches(game, p, observed, observer=seat,
                                source=source_permanent)
                # Guardian Beast, asked here as well as at the seam
                # (`Game.cant_gain_control`, which `take_control` also asks):
                # the two answer different moments. This one keeps the
                # resolution from choosing a permanent it would then decline;
                # the seam is the backstop for every other way control moves.
                and not game.cant_gain_control(p, caster)
            ),
            fallback_on_invalid_choice=False,
        )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target to gain control of")
        return True, "resolved"
    # "**An opponent may** gain control of a creature you control of their
    # choice…" (Infernal Denizen.) Who *keeps* the permanent is not always the
    # resolving object's controller (CR 109.5's default): here it is the seat
    # that made the pick, recorded by the `choose_permanent` in front of this
    # step under the one key that step always writes. An unrecognized word names
    # nobody rather than falling back to the caster — the caster is the seat
    # this sentence has said it is *not*, and handing them the creature would
    # turn a drawback into a second copy of the {T} ability.
    gains_to = instruction.payload.get("new_controller")
    if gains_to is not None:
        if gains_to != "chooser":
            return False, f"unsupported new controller {gains_to!r}"
        chooser_seat = context.results.get("chosen_player")
        if not isinstance(chooser_seat, int) or not (
            0 <= chooser_seat < len(game.players)
        ):
            game.log.append(
                f"{context.card.name}: nobody was asked, so nobody gains control"
            )
            return True, "resolved"
        caster = game.players[chooser_seat]
    from ..control import LINKED_CONTROL_CONDITIONS

    if not game.take_control(
        target_perm, caster, source=source_permanent,
        extra_meta={LINKED_CONTROL_CONDITIONS: conditions},
    ):
        return True, "resolved"
    # **The rescope ``gain_control_until_eot`` makes, and for its reason.** The
    # sentence after this one is about the creature this one just moved — "When
    # Merieke Ri Berit leaves the battlefield or becomes untapped, destroy
    # **that creature**" — and it resolves the announced id against
    # `context.target`'s board. Left pointing at the seat the creature has now
    # *left*, the delayed ability found nothing to bind and armed nothing at
    # all, logging "had no creature to watch" while the card compiled clean.
    context.target = caster
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


@effect_handler("exchange_control_of_targets")
def exchange_control_of_targets(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exchange control of target artifact, creature, or land you control and
    target permanent an opponent controls that shares one of those types with
    it." (Gauntlets of Chaos, CR 701.12b.)

    Two layer-2 *contributions*, one per permanent, recorded through
    ``engine/control.py`` — never a move. Each permanent keeps its own
    ``base_controller_index``, so an effect that later ends one half reverts
    that permanent to the seat it entered under rather than to whichever seat
    the swap left holding it, and destroying one half leaves the other exactly
    where the exchange put it.

    CR 701.12a is the reason every check happens before either contribution is
    recorded: an exchange is atomic, so a slot that is gone, that no longer
    matches its printed noun phrase, or that fails the cross-slot type test
    means **no part** of the exchange occurs. Half an exchange is a gift.

    CR 701.12b is the other early exit: two permanents one player already
    controls exchange to nothing, and recording two contributions for it would
    stamp a layer-2 effect that says what was already true — visible the moment
    something else ends one of them.
    """
    from ..auras import auras_attached_to
    from ..control import change_control

    card = context.card
    payload = instruction.payload
    targets = payload.get("targets") or {}
    slot_filters = list(targets.get("filters") or [targets.get("filter") or {}] * 2)
    chosen = resolve_target_slots(game, context, 2)
    caster_index = game.players.index(context.caster)

    legal: list[Permanent] = []
    for index, permanent in enumerate(chosen):
        wanted = slot_filters[index] if index < len(slot_filters) else {}
        if permanent is None or not game.is_on_battlefield(permanent):
            break
        if not permanent_matches_filter(permanent, wanted):
            break
        # "you control" / "an opponent controls" are seat questions, which
        # `permanent_matches_filter` deliberately does not answer.
        controller = wanted.get("controller")
        controlled_by_caster = game.controls(caster_index, permanent)
        if controller == "you" and not controlled_by_caster:
            break
        if controller in ("opponent", "not_you") and controlled_by_caster:
            break
        # Guardian Beast: an exchange hands each permanent to the *other* seat,
        # so a protected artifact on either side means no part of the exchange
        # happens (CR 701.12a's atomicity, CR 614.17's prohibition).
        other = chosen[1 - index] if index < 2 else None
        other_seat = (
            game.controller_index_of(other) if other is not None else None
        )
        if other_seat is not None and game.cant_gain_control(permanent, other_seat):
            break
        legal.append(permanent)

    if len(legal) != 2 or legal[0] is legal[1]:
        game.log.append(f"{card.name}: the exchange could not be completed, so nothing happens")
        return True, "resolved"
    first, second = legal

    if payload.get("shares_a_type"):
        # "…that shares one of **those** types with it" — those types being the
        # first slot's printed list. Read off that filter rather than named
        # here, so a card exchanging two permanents from a different list gets
        # the test for free.
        printed = slot_filters[0].get("type_filter") or ()
        if isinstance(printed, str):
            printed = [printed]
        if not any(
            first.has_type(card_type) and second.has_type(card_type)
            for card_type in printed
        ):
            game.log.append(
                f"{card.name}: {second.card.name} shares none of "
                f"{first.card.name}'s printed types, so nothing happens"
            )
            return True, "resolved"

    seat_of_first = game.controller_index_of(first)
    seat_of_second = game.controller_index_of(second)
    if seat_of_first is None or seat_of_second is None or seat_of_first == seat_of_second:
        game.log.append(f"{card.name}: both permanents have one controller, so nothing happens")
        return True, "resolved"

    change_control(first, seat_of_second, source=card)
    change_control(second, seat_of_first, source=card)
    game._sync_control()
    context.results["exchanged_permanents"] = [first.permanent_id, second.permanent_id]
    game.log.append(
        f"{card.name}: {game.players[seat_of_first].name} and "
        f"{game.players[seat_of_second].name} exchanged control of "
        f"{first.card.name} and {second.card.name}"
    )

    if payload.get("destroy_attached_auras"):
        # "If those permanents are exchanged this way, destroy all Auras
        # attached to them." Reached only from below the exchange, which is the
        # printed condition: nothing was exchanged on any path that returned
        # above. The Auras are grouped by *their* controller, which need not be
        # either of the two seats above — the sweep destroys a permanent on the
        # battlefield it is actually on.
        doomed = [aura for host in (first, second) for aura in auras_attached_to(host)]
        for seat, player in enumerate(game.players):
            on_this_board = {
                aura.permanent_id
                for aura in doomed
                if game.controller_index_of(aura) == seat
            }
            if not on_this_board:
                continue
            for destroyed in game._destroy_swept_permanents(
                player, lambda perm: perm.permanent_id in on_this_board
            ):
                game.log.append(f"{card.name} destroyed {destroyed.card.name}")
    return True, "resolved"


@effect_handler("exchange_control_of_bound")
def exchange_control_of_bound(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Exchange control of two permanents *earlier steps of this resolution
    chose* (Juxtapose, CR 701.12b).

    The difference from ``exchange_control_of_targets`` beside it is only where
    the two permanents come from: nothing was targeted here, so each side was
    recorded by a ``choose_permanent`` step and is read back by its stable id
    (CR 400.7 — an index would name whichever permanent slid into the slot).
    Everything else is that handler's rules and for its reasons: CR 701.12a
    makes the exchange atomic, so a side that has left the battlefield or that
    both seats turn out to share means **no part** of it happens.

    The layer-2 contribution is keyed on the *instruction*, not on the card.
    One cast of Juxtapose makes two exchanges, and a permanent can be in both
    (an artifact creature) — keyed on the card, recording the second would drop
    the first, because ``change_control`` keeps one contribution per source.
    Two exchanges are two instruction objects, so they are two sources.
    """
    from ..control import change_control

    card = context.card
    first = game.permanent_by_id(context.results.get(instruction.payload["first_from"]))
    second = game.permanent_by_id(context.results.get(instruction.payload["second_from"]))
    if first is None or second is None or first is second:
        game.log.append(
            f"{card.name}: nothing to exchange on one side, so nothing happens"
        )
        return True, "resolved"
    if not game.is_on_battlefield(first) or not game.is_on_battlefield(second):
        game.log.append(
            f"{card.name}: a chosen permanent has left, so the exchange does not happen"
        )
        return True, "resolved"
    seat_of_first = game.controller_index_of(first)
    seat_of_second = game.controller_index_of(second)
    if seat_of_first is None or seat_of_second is None or seat_of_first == seat_of_second:
        game.log.append(
            f"{card.name}: both permanents have one controller, so nothing happens"
        )
        return True, "resolved"
    # Guardian Beast on the bound spelling too: Juxtapose's second exchange is
    # over *artifacts*, which is precisely what the Beast protects.
    if game.cant_gain_control(first, seat_of_second) or game.cant_gain_control(
        second, seat_of_first
    ):
        game.log.append(
            f"{card.name}: a permanent can't change controllers, so nothing happens"
        )
        return True, "resolved"
    change_control(first, seat_of_second, source=instruction)
    change_control(second, seat_of_first, source=instruction)
    game._sync_control()
    game.log.append(
        f"{card.name}: {game.players[seat_of_first].name} and "
        f"{game.players[seat_of_second].name} exchanged control of "
        f"{first.card.name} and {second.card.name}"
    )
    return True, "resolved"
