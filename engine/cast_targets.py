"""What a cast announces, read off the program the announcement describes.

A spell chooses its targets once, as it is cast (CR 601.2c), and what it may
choose depends on what the rest of the announcement said: the mode it chose
(CR 700.2a, :func:`announced_mode_instructions`), the kicker costs it paid
(CR 702.33g: a kicked-only part's targets are chosen only if the spell was
kicked, :func:`_as_kicked`), and the zone it is cast from (a cost naming a
zone is a price for casting from that zone, :func:`_cast_cost_picker`).
:func:`_cast_target_spec` is the target half — an Aura's enchant line, a
copy-as-it-enters choice, an instant's or sorcery's own steps, or a
permanent's entry trigger, whose target this engine names as the permanent is
cast (:func:`cast_announced_entry_trigger`, CR 603.3d).

``targeting.derive_cast_spec`` puts the cost half and the target half
together and stays the entry point. Split out of ``engine/targeting.py`` at
the 2,000-line cap; ``engine.targeting`` still exports the names its callers
pull.
"""

from __future__ import annotations

from .cast_costs import costs_charged_from, kicker_costs, kickers_paid
from .enter_effects import copy_on_enter_type
from .enchant_targets import (_ENCHANT_GRAVEYARD_LINE, card_enchant_subject,
                              enchant_subject_spec)
from .target_roles import payload_own_role
from .cost_pickers import _cost_picker_spec
from .instruction_targets import (_WRAPPER_STEP_KEYS, _first_described_slot,
                                  _from_instructions)


def _cast_cost_picker(
    card, from_zone: str, *, announced: dict | None = None
) -> dict | None:
    """The picker a printed additional cost needs when *card* is cast from
    *from_zone*, or None when the costs charged there choose nothing.

    **Zone-scoped, exactly as the payment is.** ``queue_from_hand`` gathers the
    costs it will charge with the same test, because a cost naming a zone is a
    price for casting from *that* zone: Demonic Embrace pays 3 life and a card
    from the graveyard and nothing at all from the hand, so a picker that read
    the card alone asked a hand cast to name a discard it would never be
    charged for — and then, being a cost picker, took the place of the Aura's
    enchant target and made the card uncastable from either zone.
    """
    for cost in costs_charged_from(card, from_zone):
        cost_spec = _cost_picker_spec(cost, announced=announced)
        if cost_spec is not None:
            # The zone the cast leaves, carried so the enumerator can tell a
            # hand cast from a graveyard one: CR 601.2a withholds the spell
            # itself from a discard cost only when the hand is where it came
            # from, and a second copy of Demonic Embrace in hand really can pay
            # for the one in the graveyard. Emitted only for a cast from
            # somewhere else, so every spec written before a zone-scoped cost
            # existed is unchanged and "hand" stays the reader's default.
            if from_zone != "hand":
                return {**cost_spec, "cast_zone": from_zone}
            return cost_spec
    return None


def _kickers_announced(card, optional_cost_payments) -> "tuple[str, ...] | None":
    """Which of *card*'s kicker costs an announcement takes, by key -- or None
    when there is no announcement to read or *card* prints no kicker.

    The one place the picker turns CR 601.2b's answer so far
    (*optional_cost_payments*, the map the offer prompt re-asks the spec with)
    into CR 702.33's: through ``cast_costs.kickers_paid``, the reader the
    resolution itself asks, over a record shaped like the one the cast will
    write. So "kicked", and "kicked with **which** cost" (CR 702.33b: a
    Battlemage prints two), mean to the picker exactly what they will mean to
    the spell.

    None is "the caller is asking about the card, not about a cast" and reads
    every arm; an empty tuple is a cast that declined every kicker.
    """
    if optional_cost_payments is None:
        return None
    if not kicker_costs(card.oracle_text or ""):
        return None
    return kickers_paid(card, {"additional_costs_paid": optional_cost_payments})


def _kicker_gate_holds(gate: dict, paid) -> bool:
    """Whether a ``was_kicked`` condition will hold for a cast that paid the
    kicker costs *paid*.

    The picker's reading of ``handlers/_record_conditions``' evaluator, one branch
    each: the unqualified question is "any of them" (CR 702.33d), and one
    carrying ``kicker`` -- "kicked with its {1}{G} kicker", CR 702.33f -- is
    about that one cost.
    """
    wanted = gate.get("kicker")
    answer = bool(paid) if wanted is None else str(wanted) in tuple(paid)
    return answer != bool(gate.get("negated"))


def _as_kicked(instructions, paid) -> tuple:
    """*instructions* as a cast that paid the kicker costs *paid* (a tuple of
    keys; empty for an unkicked cast) will run them.

    CR 702.33g: "If part of a spell's ability has its effect only if that spell
    was kicked, and that part of the ability includes any targets, the spell's
    controller chooses those targets only if that spell was kicked." So the
    picker must read the program the *announcement* describes, not the card:
    Probe's "target player discards two cards" names nobody on an unkicked
    cast, and an Emissary's "destroy target land" is a trigger that will not
    trigger (CR 603.4).

    Two gates, both the grammar's own: an ``if_then`` whose condition is
    ``was_kicked`` collapses to the arm that will run (which is also what makes
    a "... instead" pair name one target rather than two), and an instruction
    carrying it as an ``intervening_if`` stays only when the gate will hold.
    Everything else is walked through the wrappers ``_WRAPPER_STEP_KEYS``
    already names, so a gate inside a ``sequence`` is found where it is.

    *paid* is which costs, not whether: a card may print two kickers
    (CR 702.33b) and gate one trigger on each ("if it was kicked with its
    {1}{G} kicker", CR 702.33f), so a Battlemage kicked only with its second
    cost names the second trigger's target and not the first's. Each gate is
    asked through :func:`_kicker_gate_holds`.

    **A third gate, for the announcement the arms share.** "Prevent all combat
    damage target creature would deal this turn. If this spell was kicked,
    prevent all combat damage **another** target creature would deal this
    turn." (Falling Timber.) The printed "another" makes the two targets one
    ordered *roles* announcement, and the lowering stamps that whole list onto
    every step that spends a slot of it -- so the step **outside** the kicked
    arm still described two targets after the arm was taken away, and an
    unkicked Falling Timber was refused "requires 2 targets" while one named
    with two was accepted. :func:`_without_unspent_roles` drops a role no
    surviving step spends, which is the rule read off the program rather than
    off the card.
    """
    viewed = _kicked_arms(instructions, paid)
    dropped = _spent_roles(instructions, set()) - _spent_roles(viewed, set())
    if not dropped:
        return viewed
    return _without_unspent_roles(viewed, dropped)


#: Where a wrapper keeps the steps under it, for the roles walk two functions
#: down. ``lowering/_roles._ANNOUNCEMENT_BRANCH_KEYS``' list, spelled again here
#: because this module is imported by that one: every key a stamped roles
#: description can sit under, which is wider than ``_WRAPPER_STEP_KEYS`` by the
#: toll's ``otherwise`` (Withdraw).
_ROLE_BRANCH_KEYS = ("steps", "then", "else", "action", "otherwise")


def _spent_roles(instructions, found: set) -> set:
    """Every role name a step under *instructions* acts on (its ``targets``
    description's own ``role`` key), gathered into *found*."""
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        role = payload_own_role(payload)
        if role is not None:
            found.add(role)
        for key in _ROLE_BRANCH_KEYS:
            nested = payload.get(key)
            if isinstance(nested, (list, tuple)):
                _spent_roles(nested, found)
    return found


def _without_unspent_roles(instructions, dropped: set) -> tuple:
    """*instructions* with the roles named in *dropped* taken out of every
    shared roles description (CR 702.33g).

    A description left with **one** role is put back to the ordinary one-target
    shape it was stamped from -- ``roles_spec`` refuses a one-role list, on the
    ground that the two shapes must not both be able to mean the same spell --
    and one left with several keeps the rest in order.

    **Only a trailing role is dropped.** The chosen targets travel as one
    positional list in role order (:func:`role_slot`), and the resolution reads
    the card's own program, not this view: taking a role out of the *front*
    would move every later slot down one in the announcement and leave the
    handler reading the old position. No card prints its kicked-only target
    first; a description that did is left whole, which asks for a target the
    card would not rather than resolving one step onto another's object.
    """
    rewritten: list = []
    for instruction in instructions:
        payload = getattr(instruction, "payload", None) or {}
        updated = None
        described = payload.get("targets")
        if payload_own_role(payload) is not None:
            roles = [entry for entry in described.get("roles") or ()]
            kept = [
                entry for entry in roles
                if not (isinstance(entry, dict) and entry.get("role") in dropped)
            ]
            if len(kept) < len(roles) and roles[:len(kept)] == kept:
                if len(kept) == 1:
                    plain = {
                        key: value for key, value in described.items()
                        if key not in ("roles", "role")
                    }
                    plain["kind"] = kept[0].get("kind", "object")
                else:
                    plain = {**described, "roles": kept}
                updated = {**payload, "targets": plain}
        for key in _ROLE_BRANCH_KEYS:
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            inner = _without_unspent_roles(tuple(nested), dropped)
            if inner != tuple(nested):
                updated = {**(updated or payload), key: inner}
        rewritten.append(
            instruction if updated is None
            else type(instruction)(instruction.kind, instruction.value, updated)
        )
    return tuple(rewritten)


def _kicked_arms(instructions, paid) -> tuple:
    """The arm-and-gate half of :func:`_as_kicked`: every ``was_kicked``
    ``if_then`` collapsed to the arm that will run for a cast that paid the
    kicker costs *paid*, every instruction gated on it kept or dropped --
    each asked through :func:`_kicker_gate_holds` -- recursing through the
    wrappers."""
    kept: list = []
    for instruction in instructions:
        payload = instruction.payload or {}
        gate = payload.get("intervening_if")
        if isinstance(gate, dict) and gate.get("kind") == "was_kicked":
            if not _kicker_gate_holds(gate, paid):
                continue
        condition = payload.get("condition")
        if (
            instruction.kind == "if_then"
            and isinstance(condition, dict)
            and condition.get("kind") == "was_kicked"
        ):
            arm = "then" if _kicker_gate_holds(condition, paid) else "else"
            kept.extend(_kicked_arms(tuple(payload.get(arm) or ()), paid))
            continue
        rewritten = None
        for key in _WRAPPER_STEP_KEYS.get(instruction.kind, ()):
            steps = tuple(payload.get(key) or ())
            if not steps:
                continue
            viewed = _kicked_arms(steps, paid)
            if viewed != steps:
                rewritten = {**(rewritten or payload), key: viewed}
        if rewritten is not None:
            instruction = type(instruction)(
                instruction.kind, instruction.value, rewritten
            )
        kept.append(instruction)
    return tuple(kept)


def announced_mode_instructions(program, mode_index: "int | None") -> tuple:
    """The instructions a cast naming *mode_index* will run: the chosen mode's
    own for a modal spell (CR 700.2a), *program*'s otherwise.

    **The one answer to "which steps is this announcement about?"** for a
    "Choose one —" spell, and it is the resolution's answer read early:
    ``Game._select_executable_instruction`` runs
    ``program.modes[mode_index].instruction`` when the caster named a real mode
    and falls back to ``program.instructions`` — which for a modal card *is*
    mode 0's instruction — when it named none (a headless caller; an AI seat
    names its mode since ``ai_policy.CastAction.mode_index``). So a
    spec, an obligation or a legality question derived through this function
    is about the very steps that will resolve, whichever mode was named.

    It was three readers. The cast gates declined modal spells outright ("the
    derived spec is mode 0's"), ``web/serialization`` kept a per-kind table of
    its own whose fall-through answered "player", and the per-kind arms in
    ``_validate_cast_targets`` were the only thing that read the chosen mode —
    for the eleven kinds they name, and by index alone. Planeshift's Charms sat
    between all three: Rith's Charm was accepted at a *basic* land, Crosis's
    Charm at a black creature, and the browser offered a player for "deals 1
    damage to target creature".
    """
    modes = tuple(getattr(program, "modes", ()) or ())
    if (
        isinstance(mode_index, int)
        and not isinstance(mode_index, bool)
        and 0 <= mode_index < len(modes)
        and modes[mode_index].instruction is not None
    ):
        return (modes[mode_index].instruction,)
    return tuple(program.instructions)


def _cast_target_spec(
    card, program, *, kickers: "tuple[str, ...] | None" = None,
    mode_index: "int | None" = None,
) -> dict | None:
    """What *card* announces as a **target** when it is cast (CR 601.2c), or
    None when it targets nothing. The cost half of the announcement is
    :func:`_cast_cost_picker`; :func:`derive_cast_spec` is the two together.

    *mode_index* is CR 601.2b's other answer, for a "Choose one —" spell: the
    chosen mode's steps are the spell (:func:`announced_mode_instructions`), so
    its target is that mode's and no other's. None reads mode 0, which is what
    a cast naming no mode resolves as.

    *kickers* is CR 702.33g's answer when the caller has one
    (:func:`_kickers_announced`): a tuple of the kicker costs the cast paid --
    empty for one that declined -- reads the program through
    :func:`_as_kicked`, and None -- a caller asking about the card rather than
    about an announcement -- reads every arm, which is what this did before the
    pool printed a kicker."""
    def viewed(instructions):
        if kickers is None:
            return instructions
        return _as_kicked(tuple(instructions), kickers)

    graveyard_aura = _ENCHANT_GRAVEYARD_LINE.search(program.normalized_text or "")
    if graveyard_aura is not None:
        # Animate Dead. `_apply_aura_effect` reads the chosen index out of
        # whichever graveyard the caster pointed at, so unlike the spell-side
        # `reanimate_creature` this one is not scoped to their own.
        return {"kind": "graveyard_creature"}

    enchant = card_enchant_subject(card.oracle_text)
    if enchant is not None:
        return enchant_subject_spec(enchant)

    copied = copy_on_enter_type(program.normalized_text or "")
    if copied is not None:
        # Clone / Copy Artifact / Vesuvan Doppelganger. `optional` is what tells
        # the UI to offer the choice only when there is something to copy, and
        # to let the permanent enter as itself otherwise (CR 707.9a).
        return {"kind": copied, "optional": True}

    # Only a spell picks a target as it is cast. A permanent's instructions
    # include those of its *abilities*, which choose their own targets on
    # activation — reading a filter off those would make the UI demand a target
    # for casting Royal Assassin because its tap ability destroys a tapped
    # creature. 27 cards in the pool derive a target they do not have if this
    # gate is removed, so it is measured rather than assumed.
    type_line = card.type_line.lower()
    if "instant" in type_line or "sorcery" in type_line:
        return _from_instructions(
            viewed(announced_mode_instructions(program, mode_index))
        )

    # A permanent's enters-the-battlefield trigger is the one exception: this
    # engine picks its target as the permanent is cast (Oubliette), where
    # CR 603.3d would choose it when the trigger goes on the stack. That is a
    # standing approximation, not a targeting question — but while it holds, the
    # prompt has to be raised at cast time or the trigger has no target at all.
    #
    # The **first** one that describes a target, and only that one: a cast
    # carries one set of target fields, so a second entry trigger with a target
    # of its own (a Battlemage kicked with both costs) is announced by nobody
    # here and chooses on the stack -- see
    # ``triggered_abilities._apply_self_enters_battlefield_triggers``, which spends the
    # announcement on exactly the trigger this reads.
    return _from_instructions(viewed(_entry_trigger_instructions(program)))


def _entry_trigger_instructions(program) -> list:
    """Every supported "when this enters" trigger's instruction, in printed
    order -- the list a permanent spell's cast-time picker is derived from."""
    return [
        ability.instruction
        for ability in program.triggered_abilities
        if ability.supported
        and ability.instruction is not None
        and ability.condition.kind == "enters_battlefield"
    ]


def cast_announced_entry_trigger(
    card, program, *, optional_cost_payments: dict | None = None
) -> "tuple[object, object] | None":
    """``(ability, instruction)`` for the entry trigger whose target a cast of
    *card* names, or None when its cast names no trigger's target.

    :func:`_cast_target_spec`'s last branch, made askable from the other side.
    That branch answers *what kind* of thing the cast picks; the list of what
    may be picked has to be the trigger's own (CR 603.3d — the cast is naming
    in advance what the trigger chooses as it is put on the stack), and the
    enumerator can only build that list from the trigger: its instruction
    carries the printed narrowing, and it is an **ability**, which is what
    protection, hexproof and shroud are asked about.

    The trigger is the first that describes a choice, under the kicker the
    cast announced (CR 702.33g) — the same walk, one trigger at a time, so the
    ability comes back beside the instruction as that announcement will run
    it. None for an Aura (its cast names what it enchants, CR 115.1b), for a
    copy-as-it-enters permanent (its cast names what it copies) and for an
    instant or sorcery.
    """
    type_line = card.type_line.lower()
    if "instant" in type_line or "sorcery" in type_line:
        return None
    text = program.normalized_text or ""
    if (
        _ENCHANT_GRAVEYARD_LINE.search(text) is not None
        or card_enchant_subject(card.oracle_text) is not None
        or copy_on_enter_type(text) is not None
    ):
        return None
    kickers = _kickers_announced(card, optional_cost_payments)
    for ability in program.triggered_abilities:
        if not (
            ability.supported
            and ability.instruction is not None
            and ability.condition.kind == "enters_battlefield"
        ):
            continue
        instructions = (ability.instruction,)
        if kickers is not None:
            instructions = _as_kicked(instructions, kickers)
        slot = _first_described_slot(instructions)
        if slot is not None and slot[0].get("kind") != "none":
            return ability, instructions[0]
    return None


def entry_trigger_instructions(
    card, program, *, optional_cost_payments: dict | None = None
) -> tuple:
    """The entry-trigger instructions a cast of *card* announced with
    *optional_cost_payments* will fire, in printed order.

    :func:`_cast_target_spec`'s own list, made askable: the picker reads the
    first of these that describes a target, and a caller deciding whether an
    optional cost is worth paying (``ai_policy``) needs the whole list -- which
    triggers a kicker **buys** is the difference between this for the
    announcement and this for ``{}``.

    Read through :func:`_as_kicked` when the caller gives an announcement and
    the card prints a kicker (CR 702.33g), so a Battlemage's "if it was kicked
    with its {2}{R} kicker" trigger is in the list only for a cast that paid
    {2}{R}. With none given, every trigger the card prints.
    """
    instructions = tuple(_entry_trigger_instructions(program))
    kickers = _kickers_announced(card, optional_cost_payments)
    if kickers is None:
        return instructions
    return _as_kicked(instructions, kickers)
