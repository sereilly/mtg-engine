from __future__ import annotations

from typing import TYPE_CHECKING

from ._common import (
    permanent_matches_filter,
    resolve_amount,
    resolve_target_permanent,
    resolve_target_permanents,
)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("untap_self")
def untap_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    if not source_permanent.tapped:
        return False, f"{card.name} is already untapped"
    game.become_untapped(source_permanent)
    game.log.append(f"{card.name} untapped itself")
    return True, "resolved"


@effect_handler("tap_self")
def tap_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Tap this creature." — the tap twin of ``untap_self``.

    Goes through ``become_tapped`` rather than setting the flag: everything
    that must happen when a permanent becomes tapped hangs off that one call,
    which is why the engine has it at all.
    """
    permanent = context.source_permanent
    if permanent is None:
        return False, "ability not implemented"
    if permanent.tapped:
        return True, "already tapped"
    game.become_tapped(permanent)
    return True, "resolved"


@effect_handler("untap_target_land")
def untap_target_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Honor an explicitly chosen land (Ley Druid: "{T}: Untap target land" — the
    # player picks which land). Fall back to the first land the target controls
    # only when no explicit choice was made.
    perm = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.card.primary_type == "land",
        fallback_on_invalid_choice=False,
    )
    if perm is not None:
        game.become_untapped(perm)
    game.log.append("Untapped target land" if perm is not None else "No land to untap")
    return True, "resolved"


@effect_handler("untap_target_permanent")
def untap_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Untap target permanent", and the narrowed forms.

    The narrowing is applied here rather than refused at lowering (which is what
    sent "untap target **land**" to a handler of its own). An explicitly chosen
    non-matching permanent fizzles instead of sliding onto an arbitrary legal
    one — the same rule the filtered tap beside it follows.
    """
    # "Untap X target lands." (Candelabra of Tawnos.) The several-targets
    # description says a list was collected; each slot resolves strictly, so a
    # target that has left is dropped rather than slid onto another (CR 608.2b).
    targets_desc = instruction.payload.get("targets") or {}
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        # The printed noun phrase, enforced here as well as at announcement.
        # `resolve_target_permanents` defaults to "is it a creature?", which
        # would have matched none of Candelabra's lands — and, on a card that
        # did name creatures, would have skipped the rest of the phrase.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda p: permanent_matches_filter(p, instruction.payload),
        )
        for perm in chosen:
            game.become_untapped(perm)
        game.log.append(
            f"Untapped {len(chosen)} permanent(s)" if chosen
            else "No valid permanents to untap"
        )
        # What it records is what a later sentence means by "it"/"that
        # creature" — every permanent this instruction affected, already
        # untapped or not (CR 611.2c fixes the set when the effect begins).
        # By id, never by object or slot (idiom #11, CR 400.7).
        context.results["untapped_permanents"] = tuple(
            perm.permanent_id for perm in chosen
        )
        return True, "resolved"

    narrowed = any(
        key in instruction.payload
        for key in ("type_filter", "subtype_filter", "color_filter")
    )
    if narrowed:
        perm = resolve_target_permanent(
            game, context,
            predicate=lambda p: permanent_matches_filter(p, instruction.payload),
            fallback_on_invalid_choice=False,
        )
        if perm is not None:
            game.become_untapped(perm)
        game.log.append(
            f"Untapped {perm.card.name}" if perm is not None
            else "No valid permanent to untap"
        )
        # The record Disharmony's later sentences read ("remove it from
        # combat", "gain control of that creature"): the permanent this
        # instruction resolved, whether or not it was tapped — a vigilance
        # attacker is still "it" (CR 611.2c fixes the set when the effect
        # begins). By id, never by object or slot (idiom #11, CR 400.7).
        context.results["untapped_permanents"] = (
            (perm.permanent_id,) if perm is not None else ()
        )
        return True, "resolved"
    target = context.target
    untapped = game._tap_or_untap_target(
        target, make_tapped=False, target_permanent_index=context.target_permanent_index
    )
    game.log.append(
        "Untapped target permanent" if untapped is not None else "No valid permanent to untap"
    )
    # The same record the filtered branch above keeps, for the same reason: a
    # producer `_PRODUCES` names has to write on every path it takes, or the
    # sentence after it silently acts on nothing.
    context.results["untapped_permanents"] = (
        (untapped.permanent_id,) if untapped is not None else ()
    )
    return True, "resolved"


@effect_handler("untap_attacker_and_prevent_combat_damage")
def untap_attacker_and_prevent_combat_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Ebony Horse: untap the chosen attacking creature you control and shield
    # it — all combat damage that would be dealt to or by it this turn is
    # prevented (the flag is honored in combat_damage_step and cleared in
    # cleanup via _EOT_METADATA_KEYS).
    caster = context.caster
    perm = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.is_creature and p.attacking and game.controls(caster, p),
        fallback_players=(caster,),
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no attacking creature you control to untap")
        return True, "resolved"
    game.become_untapped(perm)
    perm.metadata["prevent_combat_damage_to_and_by_until_eot"] = True
    game.log.append(
        f"{context.card.name} untapped {perm.card.name}; all combat damage to and by it is prevented this turn"
    )
    return True, "resolved"


@effect_handler("untap_enchanted_creature")
def untap_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    attached_to = source_permanent.metadata.get("attached_to")
    if attached_to is not None:
        game.become_untapped(attached_to)
        game.log.append(f"Untapped {attached_to.card.name} via {card.name}")
    return True, "resolved"


@effect_handler("tap_enchanted_creature")
def tap_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this Aura enters, tap enchanted creature." (Paralyze, Venarian
    Gold, Cocoon.) The tap twin of ``untap_enchanted_creature``, and a handler
    of its own for the same reason: the subject is known from the source's own
    attachment, so no target is chosen and the targeted tap would ask for one.

    ``_turn_face_up`` for the reason ``tap_target_permanent`` calls it: a
    face-down creature (Illusionary Mask) turns face up when it becomes
    tapped, and this is a way it becomes tapped.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    attached_to = source_permanent.metadata.get("attached_to")
    if attached_to is not None and game.is_on_battlefield(attached_to):
        game.become_tapped(attached_to)
        game._turn_face_up(attached_to)
        game.log.append(f"{context.card.name} tapped {attached_to.card.name}")
    return True, "resolved"


def _tap_or_untap_all_matching(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    *, make_tapped: bool,
) -> tuple[bool, str]:
    """"Untap all lands you control." (Reset.) "Tap all legendary creatures."
    (Arena of the Ancients.)

    A sweep over a described set, not a choice: nothing is targeted and nobody
    picks, so every permanent the phrase names is affected (CR 611.2c fixes
    the set when the effect begins). The set resolves through
    ``subject_matches`` — one answer for what a printed noun phrase means —
    with the resolving controller as the observer, because "you control" is
    that seat's "you" (CR 109.5). The lowering admits only payloads that
    matcher tests in full, so nothing here can quietly reach a wider set than
    the card prints.
    """
    from ..subject_filters import subject_matches

    observer = game.players.index(context.caster) if context.caster in game.players else None
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, instruction.payload,
            observer=observer, source=context.source_permanent,
        )
    ]
    changed = []
    for perm in matched:
        if make_tapped:
            if game.become_tapped(perm):
                game._turn_face_up(perm)
                changed.append(perm)
        elif game.become_untapped(perm):
            changed.append(perm)
    verb = "tapped" if make_tapped else "untapped"
    if changed:
        game.log.append(
            f"{context.card.name} {verb} " + ", ".join(p.card.name for p in changed)
        )
    else:
        game.log.append(f"{context.card.name}: nothing to tap or untap")
    return True, "resolved"


@effect_handler("tap_all_matching")
def tap_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    return _tap_or_untap_all_matching(game, instruction, context, make_tapped=True)


@effect_handler("untap_all_matching")
def untap_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    return _tap_or_untap_all_matching(game, instruction, context, make_tapped=False)


@effect_handler("tap_target_permanent")
def tap_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    targets_desc = instruction.payload.get("targets") or {}
    maximum = targets_desc.get("count") if isinstance(targets_desc, dict) else None
    if isinstance(maximum, int) and maximum > 1:
        return _tap_several_targets(game, instruction, context, targets_desc, maximum)
    target = context.target
    # Ali Baba: "Tap target Wall." — the parsed noun-phrase filter restricts
    # what the ability may tap; an explicitly chosen non-matching permanent
    # fizzles rather than falling back to an arbitrary one.
    #
    # Every filter key, not the three type-ish ones a hand-written probe used to
    # name: "Tap target **untapped creature you control**" (Energy Tap) carries
    # a seat, and a seat this branch never looked at is a restriction dropped —
    # the spell tapping an opponent's creature and making its mana. So the test
    # is `subject_matches`, the one answer for what a printed noun phrase means,
    # with the resolving controller as "you" (CR 109.5); the lowering admits
    # only payloads it can test in full.
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items() if key != "targets"
    }
    if described:
        caster = context.caster
        observer = game.players.index(caster) if caster in game.players else None
        perm = resolve_target_permanent(
            game,
            context,
            predicate=lambda p: subject_matches(
                game, p, described, observer=observer,
                source=context.source_permanent,
            ),
            fallback_players=(target, caster),
            fallback_on_invalid_choice=False,
        )
        if perm is not None:
            game.become_tapped(perm)
            game._turn_face_up(perm)
            game.log.append(f"Tapped {perm.card.name}")
        else:
            game.log.append("No valid permanent to tap")
        _record_tapped(context, [perm] if perm is not None else [])
        return True, "resolved"
    tapped = game._tap_or_untap_target(
        target, make_tapped=True, target_permanent_index=context.target_permanent_index
    )
    game.log.append(
        "Tapped target permanent" if tapped is not None else "No valid permanent to tap"
    )
    _record_tapped(context, [tapped])
    return True, "resolved"


def _record_tapped(context: OracleExecutionContext, chosen) -> None:
    """Record what this instruction tapped, for the sentence after it.

    ``_PRODUCES`` names ``tap_target_permanent`` as the producer of
    ``tapped_permanents``, but only the several-target branch ever wrote it —
    so "Tap target creature. **It** doesn't untap …" (Telekinesis) had a
    producer the table promised and the scratchpad did not hold, and the second
    sentence marked nothing while the card compiled clean. By id, never by
    object or slot: the next instruction runs after this one, and a permanent
    may have left in between (CR 400.7).
    """
    context.results["tapped_permanents"] = tuple(
        perm.permanent_id for perm in chosen if perm is not None
    )


def _tap_several_targets(
    game: Game,
    instruction: OracleInstruction,
    context: OracleExecutionContext,
    targets_desc: dict,
    maximum: int,
) -> tuple[bool, str]:
    """"Tap up to two target creatures." (Frost Breath.)

    The same effect per permanent as the one-target tap, so it is the same
    instruction kind with a several-targets description rather than a second kind
    — the identical argument ``bounce_target_creature`` and
    ``add_counter_to_target`` make.

    Each slot resolves strictly: a target that has left or stopped matching is
    dropped and the rest still happens (CR 608.2b). No fallback scan, because a
    fallback per slot would tap whichever permanent the scan reached first, twice
    over, for a choice the player made once.

    What it records is what the *next* sentence means. "Those creatures" names
    every creature this instruction affected, which is not the same as every
    creature it changed: one that was already tapped is still one of those
    creatures (CR 611.2c fixes the set when the effect begins), so it is recorded
    whether or not ``become_tapped`` had anything to do.
    """
    card = context.card
    filters = targets_desc.get("filter") or {}
    source = context.source_permanent
    caster_index = game.players.index(context.caster)

    def eligible(perm) -> bool:
        if not permanent_matches_filter(perm, filters):
            return False
        # "other" and "you control" are outside permanent_matches_filter's
        # vocabulary — it answers about a permanent alone and these two need the
        # source and the board — so they are asked here, the same split
        # add_counter_to_target makes.
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(caster_index, perm):
            return False
        if filters.get("controller") == "not_you" and game.controls(caster_index, perm):
            return False
        return True

    chosen = resolve_target_permanents(game, context, predicate=eligible)[:maximum]
    for perm in chosen:
        if not perm.tapped:
            game.become_tapped(perm)
            game._turn_face_up(perm)
        game.log.append(f"{card.name} tapped {perm.card.name}")
    if not chosen:
        game.log.append(f"{card.name}: nothing was tapped")
    # By id, never by object or slot: the next instruction runs after this one,
    # and a permanent may have left in between (idiom #11, CR 400.7).
    context.results["tapped_permanents"] = tuple(perm.permanent_id for perm in chosen)
    return True, "resolved"


@effect_handler("skip_next_untap")
def skip_next_untap(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Those creatures don't untap during their controller's next untap step."
    (Frost Breath.)

    A continuous effect with a stated duration (CR 611.2a) whose only observable
    moment is one turn-based action (CR 502.3, "effects can keep one or more of a
    player's permanents from untapping"). So it is a marker on each affected
    permanent rather than a registered continuous effect: nothing between now and
    that untap step can read it, and the untap step both honours it and ends it —
    the same shape ``phased_out`` uses for the other thing CR 502 does per
    controller.

    **Per creature, not per caster.** The marker carries no seat. The untap step
    runs for the active player and looks only at permanents that player controls,
    so two creatures under two controllers each wait for their own controller's
    step with nothing recording whose step it is.

    Which permanents "those creatures" names comes from the scratchpad, keyed by
    the producing instruction's recorded result (``engine/grammar/lower.py``'s
    ``_PRODUCES``). An empty record is a legal outcome — "up to two" may name
    none — and is not an error.
    """
    key = instruction.payload.get("permanents_from")
    recorded = context.results.get(key) or ()
    # "…next **two** untap steps" (Telekinesis). The marker is a count of steps
    # rather than a flag, because how many of the same turn-based action the
    # restriction survives is the only thing that differs between the two
    # printings — and a flag would let the creature untap a turn early.
    steps = max(1, int(instruction.payload.get("untap_steps") or 1))
    marked = 0
    for permanent_id in recorded:
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None:
            # It left the battlefield between the two steps. A new object comes
            # back (CR 400.7), and this effect never applied to it.
            continue
        # The larger of the two, never the sum: two effects each holding a
        # permanent down for one step both expire during the same untap step
        # (CR 701.43b, said of exert — the keyworded form of this effect).
        held = int(permanent.metadata.get("skip_next_untap") or 0)
        permanent.metadata["skip_next_untap"] = max(held, steps)
        plural = "" if steps == 1 else f" {steps}"
        game.log.append(
            f"{permanent.card.name} won't untap during its controller's next"
            f"{plural} untap step" + ("" if steps == 1 else "s")
        )
        marked += 1
    if not marked:
        game.log.append(f"{context.card.name}: nothing was held down")
    return True, "resolved"


@effect_handler("tap_or_untap_target")
def tap_or_untap_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Twiddle: toggle the chosen permanent's tapped state (tap an untapped one,
    # untap a tapped one). Honor the explicitly chosen permanent on either
    # battlefield; fall back to the first permanent for AI/headless play.
    #
    # "Tap or untap target **creature**" (Tolarian Kraken) narrows what may be
    # chosen, so the printed noun phrase is applied here rather than refused at
    # lowering. An explicitly chosen non-matching permanent fizzles instead of
    # sliding onto an arbitrary legal one — the same rule the filtered tap above
    # follows, and for the same reason.
    narrowed = any(
        key in instruction.payload
        for key in ("type_filter", "subtype_filter", "color_filter")
    )
    perm = resolve_target_permanent(
        game, context,
        predicate=(
            (lambda p: permanent_matches_filter(p, instruction.payload))
            if narrowed else (lambda p: True)
        ),
        fallback_on_invalid_choice=not narrowed,
    )
    if perm is None:
        game.log.append("No valid permanent to tap or untap")
        return True, "resolved"
    perm.tapped = not perm.tapped
    if perm.tapped:
        game._turn_face_up(perm)
    game.log.append(f"{'Tapped' if perm.tapped else 'Untapped'} {perm.card.name}")
    return True, "resolved"


@effect_handler("tap_target_player_lands_and_drain_mana")
def tap_target_player_lands_and_drain_mana(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    for perm in game.controlled_by(target):
        if perm.card.primary_type == "land":
            game.become_tapped(perm)
    for sym in ("W", "U", "B", "R", "G", "C"):
        target.mana_pool[sym] = 0
    for bucket in target.restricted_mana.values():
        bucket.clear()
    game.log.append(f"{card.name} tapped all lands and drained mana from {target.name}")
    return True, "resolved"


@effect_handler("tap_any_number_then_pump_self")
def tap_any_number_then_pump_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may tap any number of untapped creatures you control. This creature
    gets +1/+1 until end of turn for each creature tapped this way." (Siege
    Striker.)

    Arms the pick and stops. The boost is applied by the choice's *resolver*,
    because the number is what the seat answers — fusing the two sentences into
    one instruction is what lets the count stay inside a single decision instead
    of having to survive a suspended resolution.

    The source rides as an id, not an object: the seat may answer after other
    things have resolved, and CR 400.7 makes a permanent that left and came back
    a new object, so the pump must find the creature that armed this or none.
    """
    caster_index = game.players.index(context.caster)
    source = context.source_permanent
    game.arm_pending_choice(
        "tap_any_number", caster_index,
        filter=dict(instruction.payload.get("filter") or {}),
        untapped_only=bool(instruction.payload.get("untapped_only")),
        power=int(instruction.payload.get("power", 0)),
        toughness=int(instruction.payload.get("toughness", 0)),
        source_id=game.permanent_id_of(source) if source is not None else None,
        card_name=context.card.name,
    )
    return True, "resolved"


@effect_handler("untap_up_to_matching")
def untap_up_to_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Untap up to four lands." (Rewind.) No "target" is printed, so nothing
    was chosen at cast: the controller picks the permanents now, on
    resolution, through the pending-choice queue — the shape round 15's census
    said this clause needed, as distinct from the targeted "up to N" family."""
    caster_index = game.players.index(context.caster)
    game.arm_pending_choice(
        "untap_up_to", caster_index,
        amount=resolve_amount(instruction.payload.get("amount", 0), context.x_value),
        filter=dict(instruction.payload.get("filter") or {}),
        card_name=context.card.name,
    )
    game.log.append(
        f"{context.caster.name} may untap up to "
        f"{instruction.payload.get('amount', 0)} matching permanents"
    )
    return True, "pending_untap_up_to"


#: What a "doesn't untap … for as long as this permanent remains tapped"
#: records on its **source**: the restricted permanent's id. Read by the untap
#: step, which skips the permanent while the source is still tapped.
#:
#: One name, because the handler that writes it and the step that reads it are
#: in different files and a second spelling is how they come apart.
UNTAP_LOCK_WHILE_TAPPED_KEY = "untap_lock_while_tapped"


@effect_handler("restrict_untap_while_source_tapped")
def restrict_untap_while_source_tapped(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Phyrexian Gremlins: "{T}: Tap target artifact. It doesn't untap during
    its controller's untap step **for as long as this creature remains
    tapped**."

    Nothing is written onto the restricted permanent. The record lives on the
    source and the untap step reads it back while the source is tapped, so the
    restriction ends the instant the Gremlins untaps — or leaves, taking its
    record with it — and no step has to remember to clear a flag. The same
    shape round 5's linked pump uses, and for the same reason: a duration that
    ends on a *condition* has no moment anyone could hook.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    target = game.permanent_by_id(context.target_permanent_id) if context.target_permanent_id else None
    if target is None and isinstance(context.target_permanent_index, int):
        target = game.chosen_permanent(
            context.target, context.target_permanent_index, context.target_permanent_id
        )
    if target is None:
        game.log.append(f"{context.card.name}: nothing to hold tapped")
        return True, "resolved"
    source.metadata[UNTAP_LOCK_WHILE_TAPPED_KEY] = target.permanent_id
    game.log.append(
        f"{target.card.name} won't untap while {context.card.name} remains tapped"
    )
    return True, "resolved"
