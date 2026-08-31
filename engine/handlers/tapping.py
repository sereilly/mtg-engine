from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import X_FROM_COUNT
from ._common import (
    frozen_that_player_seat,
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
    """"Untap this creature." — and, where the sentence continues, the object
    the clause behind it names.

    The record is written **before** the tapped check and whether or not the
    permanent was tapped, which is `untap_target_permanent`'s rule beside it and
    for its reason: CR 611.2c fixes the set when the effect begins, so "untap it
    **and remove it from combat**" (Melee's delayed ability) is about the
    creature the sentence chose, not about whether the untap had anything to do.
    A vigilance attacker was never tapped and is still "it".
    """
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    context.results.setdefault("untapped_permanents", []).append(
        source_permanent.permanent_id
    )
    if not source_permanent.tapped:
        return False, f"{card.name} is already untapped"
    game.become_untapped(source_permanent)
    # The permanent, not the card: a delayed ability created by a spell
    # (Melee's "untap it") carries the *spell* as its card and the creature it
    # is about as its source, and "Melee untapped itself" names the wrong
    # object in the one place a player reads what happened.
    game.log.append(f"{source_permanent.card.name} untapped")
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
        # Through `subject_matches` rather than the pure matcher, with the
        # resolving seat as the observer, for the reason the filtered tap beside
        # it does: "**you control**" (Ebony Horse) is a seat comparison
        # (CR 109.5), not something readable off the permanent. The lowering
        # admits exactly what this answers, so the list the picker offers and
        # the list this accepts are one list.
        from ..subject_filters import subject_matches

        described = {
            key: value for key, value in instruction.payload.items()
            if key != "targets"
        }
        observer = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        perm = resolve_target_permanent(
            game, context,
            predicate=lambda p: subject_matches(
                game, p, described, observer=observer,
                source=context.source_permanent,
            ),
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
    # "Untap target permanent", unnarrowed — through the same id-aware resolver
    # every branch above uses. It used to hand the seat and the slot to
    # `_tap_or_untap_target`, which followed the index alone: a target that left
    # while the ability waited renumbered the slot under it (CR 400.7) and the
    # untap landed on whichever permanent slid in. Hematite Talisman and its
    # four siblings fire this off a *trigger*, which CR 608.2b's gate does not
    # cover, so nothing above caught it. `predicate` stays "any permanent" —
    # the printed noun is "permanent", not "creature".
    untapped = game._tap_or_untap_target(
        resolve_target_permanent(
            game, context, player=target, predicate=lambda p: True,
        ),
        make_tapped=False,
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
        # What this step affected, under the key every other tap writes —
        # "tap the creature, **remove it from combat**" (Imprison) reads it
        # back, and by id because a removal in between renumbers every later
        # slot (CR 400.7). Recorded whether or not it was already tapped:
        # CR 611.2c fixes the set when the effect begins, and the sentence
        # after it is about that creature either way.
        context.results["tapped_permanents"] = (attached_to.permanent_id,)
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
    described = dict(instruction.payload)
    # This kind's payload *is* its filter, with no wrapper key — so a
    # dispatch-level key stamped onto it has to be lifted off before it is read
    # as one. "…**where X is** the number of Islands tapped this way" (Monsoon)
    # stamps its definition on every instruction of the sentence, this sweep
    # included, and the matcher would then be handed a key no filter has.
    described.pop(X_FROM_COUNT, None)
    # "…all untapped Islands **that player** controls" (Monsoon). The seat is
    # the one the firing event froze (CR 603.10), not the source's controller —
    # which is the wrong seat on every end step but their own.
    # ``subject_matches`` refuses ``that_player`` outright and says why: the
    # seat is known only to the resolution holding the trigger's context, which
    # is here. Rewritten into the relative key the matcher does answer, against
    # that seat, exactly as ``untap_up_to_matching`` rewrites Mudslide's "they
    # control".
    if described.get("controller") == "that_player":
        frozen = frozen_that_player_seat(game, context)
        if frozen is None:
            return False, "no seat was frozen for 'that player'"
        observer = frozen
        described["controller"] = "you"
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, described,
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
    # "…where X is the number of Islands **tapped this way**" (Monsoon). How
    # many the sweep actually turned, which is the only place the sentence after
    # it can read the number from: by then the board says how many are tapped,
    # not how many this effect tapped, and CR 611.2c fixed the set when the
    # effect began. The victims themselves are deliberately *not* recorded —
    # unlike a destruction sweep's, they are still on the battlefield, so a card
    # asking about them would have somewhere to look; none does, and a record
    # nothing reads is a claim nothing checks.
    #
    # The tap direction only, for that same reason: no card counts what an
    # untap sweep untapped, and ``_PRODUCES`` declares what this records.
    if make_tapped:
        context.results["tapped_this_way"] = len(changed)
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
    printed_count = targets_desc.get("count") if isinstance(targets_desc, dict) else None
    # "**X** target creatures" (Winter Blast) — the count is the announced X,
    # which is a string on the payload because it is not a number until the
    # spell is cast. An `isinstance(int)` test skipped that spelling entirely
    # and fell through to the one-target branch below, tapping the first slot
    # and dropping the rest; the untap beside this one reads the same key with
    # `not in (None, 1)` and never had the hole.
    maximum = (
        resolve_amount(printed_count, context.x_value)
        if printed_count is not None else None
    )
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
    # The unnarrowed "tap target permanent" (Twiddle's first mode), resolved by
    # id like the narrowed branch above it — see the untap twin for why the
    # index alone was wrong.
    tapped = game._tap_or_untap_target(
        resolve_target_permanent(
            game, context, player=target, predicate=lambda p: True,
        ),
        make_tapped=True,
    )
    game.log.append(
        "Tapped target permanent" if tapped is not None else "No valid permanent to tap"
    )
    _record_tapped(context, [tapped])
    return True, "resolved"


@effect_handler("tap_creatures_blocking_target")
def tap_creatures_blocking_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Tap all creatures blocking target attacking creature." (Feint.)

    The set is named by a *relation*, not by a characteristic: the spell chooses
    one attacking creature and every creature blocking it is affected. So the
    target is resolved first and ``creatures_blocking`` — the one reader of that
    combat relation, band-propagated blocks included (CR 702.22h) — supplies the
    set, rather than any scan of the battlefield.

    Which attacker was chosen is re-checked here as well as at cast time: CR
    608.2b asks a target's legality again on resolution, and a creature removed
    from combat in response makes this do nothing rather than tap the blockers
    of whichever attacker a fallback scan reached first.

    The printed noun phrase of the *blockers* still rides as the filter, because
    a card printing "tap all Walls blocking …" is this instruction with a
    different payload. The chosen attacker's id is recorded so a later sentence
    can say "that creature" — Feint's own second sentence does.
    """
    targets = instruction.payload.get("targets") or {}
    blocked_filter = targets.get("filter") or {}

    def _eligible(perm) -> bool:
        return perm.is_creature and permanent_matches_filter(perm, blocked_filter)

    attacker = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_on_invalid_choice=False
    )
    if attacker is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    blocker_filter = {
        key: value for key, value in instruction.payload.items() if key != "targets"
    }
    chosen = [
        blocker
        for blocker in game.creatures_blocking(attacker)
        if permanent_matches_filter(blocker, blocker_filter)
    ]
    for blocker in chosen:
        if not blocker.tapped:
            game.become_tapped(blocker)
            game._turn_face_up(blocker)
        game.log.append(
            f"{context.card.name} tapped {blocker.card.name} "
            f"(blocking {attacker.card.name})"
        )
    if not chosen:
        game.log.append(
            f"{context.card.name}: nothing is blocking {attacker.card.name}"
        )
    _record_tapped(context, chosen)
    # The chosen attacker, for the sentence that says "that creature". By id
    # rather than by object or slot (CR 400.7).
    context.results["blocked_target"] = attacker.permanent_id
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


@effect_handler("tap_recorded_permanents")
def tap_recorded_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…put a paralyzation counter on each creature blocking or blocked by
    this creature and tap **those creatures**." (Dread Wight.)

    Neither a sweep nor a choice: the set is whatever an earlier step of this
    same effect recorded (CR 611.2c fixed it when the effect began), and the
    record is the only place it can be read from — the sentence in front of
    this one named its creatures by a combat relation, and this trigger
    resolves in the step where CR 511.2 takes every creature out of combat.

    By id, because a permanent may have left in between: a returning one is a
    new object (CR 400.7) and this effect never named it, so it is simply not
    tapped. An empty record is a legal outcome, not an error.
    """
    recorded = (context.results or {}).get(
        str(instruction.payload.get("permanents_from", ""))
    ) or ()
    tapped = []
    for permanent_id in recorded:
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None or permanent.tapped:
            continue
        # Through ``become_tapped``, so everything that must happen when a
        # permanent becomes tapped happens — the same reason ``tap_self`` does.
        game.become_tapped(permanent)
        tapped.append(permanent.card.name)
    game.log.append(
        f"{context.card.name} tapped {', '.join(tapped)}"
        if tapped else f"{context.card.name}: nothing was left to tap"
    )
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
    if key is None:
        # "**Target creature** doesn't untap during its controller's next untap
        # step." (Barl's Cage.) The sentence chooses for itself instead of
        # restating an earlier step's pick, so the permanent comes from the
        # ability's own target — and an explicitly chosen non-matching one
        # fizzles rather than sliding onto whatever else is legal (CR 608.2b).
        from ..subject_filters import subject_matches

        described = {
            key_: value for key_, value in instruction.payload.items()
            if key_ not in ("targets", "untap_steps")
        }
        observer = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        chosen = resolve_target_permanent(
            game, context,
            predicate=lambda p: subject_matches(
                game, p, described, observer=observer,
                source=context.source_permanent,
            ),
            fallback_on_invalid_choice=False,
        )
        recorded = (chosen.permanent_id,) if chosen is not None else ()
    else:
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
    # Through `subject_matches` rather than the pure matcher, with the resolving
    # seat as the observer: "an opponent controls" (Hyperion Blacksmith) is a
    # seat comparison (CR 109.5), not something readable off the permanent. The
    # lowering admits exactly what this answers, and the picker carries the same
    # narrowing, so the list offered and the list accepted are one list.
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items() if key != "targets"
    }
    observer = game.players.index(context.caster) if context.caster in game.players else None
    perm = resolve_target_permanent(
        game, context,
        predicate=(
            (lambda p: subject_matches(
                game, p, described,
                observer=observer, source=context.source_permanent,
            ))
            if described else (lambda p: True)
        ),
        fallback_on_invalid_choice=not described,
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
    seat = game.players.index(context.caster)
    # "…**that player** may choose any number of tapped creatures … they
    # control" (Mudslide). The chooser is the seat the firing event froze
    # (CR 603.10), not the source's controller — which is the wrong seat on
    # every upkeep but their own. The lowering only emits the key under an
    # event that stamps it, so an absent one is a bug rather than a card.
    if instruction.payload.get("who") == "event_subject_player":
        frozen = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(frozen, int) or not (0 <= frozen < len(game.players)):
            return False, "no seat was frozen for 'that player'"
        seat = frozen
    # Imported here rather than at module scope: `engine/subject_filters.py`
    # imports this package's `_common`, so a top-level import would close the
    # cycle at load time.
    from ..subject_filters import subject_matches

    filt = dict(instruction.payload.get("filter") or {})
    # "…**they** control", where "they" is the chooser. `subject_matches`
    # refuses `that_player` outright and says why: the seat is known only to
    # the resolution holding the trigger's context, which is here. Rewritten
    # into the relative key the matcher does answer, against this seat.
    if filt.get("controller") == "that_player":
        filt["controller"] = "you"
    printed = instruction.payload.get("amount", 0)
    if printed == "any":
        # "**Any number**" — the cap is however many the board holds for that
        # seat right now (CR 608.2 counts at resolution).
        amount = sum(
            1 for perm in game.all_permanents()
            if subject_matches(game, perm, filt, observer=seat)
        )
    else:
        amount = resolve_amount(printed, context.x_value)
    game.arm_pending_choice(
        "untap_up_to", seat,
        amount=amount,
        filter=filt,
        # "…and **pay {2} for each creature chosen this way**" (Mudslide). The
        # price of one pick; the prompt multiplies it by how many were made.
        # Absent for Rewind, whose untap is free.
        cost_each=dict(instruction.payload.get("cost_each") or {}),
        # The seat "you control" is relative to, so the picker asks the same
        # question the lowering's gate admitted.
        observer=seat,
        card_name=context.card.name,
    )
    game.log.append(
        f"{game.players[seat].name} may untap up to "
        f"{amount} matching permanents"
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


#: The counters whose presence keeps a permanent from untapping, recorded on the
#: **restricted** permanent rather than on the source — the condition is a fact
#: about it ("for as long as **it** has a paralyzation counter on it", Dread
#: Wight), so the record has to travel with it and the source may be long gone.
#:
#: A tuple of counter names, not one, because two effects may hold the same
#: permanent under two different counters and the restriction ends only when
#: *neither* is on it any more. Written here and read by
#: ``engine/phases/untap_step.py``; one name for the same reason
#: :data:`UNTAP_LOCK_WHILE_TAPPED_KEY` has one.
UNTAP_BLOCKED_WHILE_COUNTERS_KEY = "untap_blocked_while_counters"


@effect_handler("restrict_untap_while_counter")
def restrict_untap_while_counter(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each of those creatures doesn't untap during its controller's untap
    step **for as long as it has a paralyzation counter on it**." (Dread
    Wight.)

    A continuous effect with no end date (CR 611.2b), so nothing clears it: the
    untap step re-asks the condition every turn and the restriction lapses of
    itself when the last counter comes off — which is what the ability the same
    card grants is for. That is why the counter's *name* is recorded rather
    than a flag: a flag would freeze the creature for the rest of the game,
    which is the exact trap ``self_untap_counter_condition`` was written to
    avoid one file over.

    The set is whatever an earlier step of this effect recorded, by id — a
    permanent that left is a new object when it returns (CR 400.7) and carries
    neither the counter nor the restriction.
    """
    counter = str(instruction.payload.get("counter", ""))
    recorded = (context.results or {}).get(
        str(instruction.payload.get("permanents_from", ""))
    ) or ()
    marked = []
    for permanent_id in recorded:
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None:
            continue
        held = tuple(permanent.metadata.get(UNTAP_BLOCKED_WHILE_COUNTERS_KEY) or ())
        if counter not in held:
            permanent.metadata[UNTAP_BLOCKED_WHILE_COUNTERS_KEY] = held + (counter,)
        marked.append(permanent.card.name)
    game.log.append(
        f"{', '.join(marked)} won't untap while holding a {counter} counter"
        if marked else f"{context.card.name}: nothing was held down"
    )
    return True, "resolved"
