"""A **bite**: one object deals damage equal to a characteristic it still has.

The handler twin of ``engine/grammar/lowering/_bites.py``, and its line: a bite
reads one object's **power** at resolution (CR 613's computed value, not the
printed one), and that object is the *dealer* — CR 120.7's source of damage is
the object that dealt it, so lifelink, "a source you control" and "damage
dealt by a creature" all answer differently from the generic ``deal_damage``,
whose source is the spell or the ability. Who the dealer is, is the axis the
kinds are named along: the ability's own source (``source_bites_target``), a
permanent an earlier step bound (``bound_bites_source``,
``bound_bites_player``), a chosen target biting another (``target_bites_target``)
or itself (``target_bites_itself``, Repentance), and every creature a phrase
names biting itself (``each_matching_bites_itself``).

A two-way exchange is a fight (CR 701.14), and ``fighting.py``'s.

Split out of ``damage.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from ._common import apply_damage_to_creature
from ._filters import permanent_matches_filter
from ._targets import (recorded_permanent_ids, attached_host,
                       defending_player_seat, resolve_target_permanent)
from .registry import effect_handler


@effect_handler("source_bites_target")
def source_bites_target(game, instruction, context):
    """"It deals damage equal to its power to target creature or planeswalker."
    (Heartfire Immolator.)

    The source paid for this by being **sacrificed**, so by the time it resolves
    it is in a graveyard. Its power is last-known information (CR 608.2), and
    the ``Permanent`` object still carries it: the layer state is recomputed
    without the permanent, but the metadata the bonuses live in belongs to the
    object and nothing off the battlefield touches it. A prowess-pumped
    Immolator therefore deals three, which is the case that makes the
    distinction observable — and its test.
    """
    card = context.card
    source = context.source_permanent
    # ``biter: "attached"`` — the permanent the source is attached to deals the
    # damage (Farrel's Mantle). CR 113.7a leaves the ability the Aura's, so the
    # source is still the Aura and only the dealer moves; read off the source
    # rather than off the target, because an Aura that has fallen off has no
    # creature to bite with and must deal nothing rather than bite with itself.
    if instruction.payload.get("biter") == "attached":
        source = attached_host(game, source)
    elif instruction.payload.get("biter") == "event_subject":
        # ``biter: "event_subject"`` — the object the firing event was about
        # deals the damage (Pandemonium's entering creature). CR 120.7: the
        # damage is the *creature's*, not the enchantment's, so the dealer moves
        # and the ability stays where it is, exactly as it does for an Aura one
        # branch up. Read by the stable id the fire site froze (CR 400.7 — the
        # permanent may have moved since), and a permanent that has left deals
        # nothing rather than the enchantment biting with its own zero power.
        bound = (context.trigger_context or {}).get("event_subject_permanent_id")
        source = game.permanent_by_id(bound) if isinstance(bound, int) else None
    elif instruction.payload.get("biter") == "tapped_this_way":
        # ``biter: "tapped_this_way"`` — "Tap target untapped creature you
        # control. If you do, **it** deals damage …" (Spirit Flare). The
        # creature the step in front of this one tapped, read off the record
        # that step wrote (``tapped_permanents``) by stable id. Exactly one:
        # the pronoun names one object, and a record of none (the tap did not
        # happen, so "if you do" already declined) or of several is no biter.
        tapped = context.results.get("tapped_permanents") or ()
        source = (
            game.permanent_by_id(tapped[0])
            if len(tapped) == 1 and isinstance(tapped[0], int) else None
        )
    if source is None:
        game.log.append(f"{card.name}: nothing to deal the damage")
        return True, "resolved"
    described_targets = instruction.payload.get("targets") or {}
    if described_targets.get("quantifier") == "any_target" and (
        context.target_permanent_index is None
        and context.target_permanent_id is None
    ):
        # CR 115.4's other half: "any target" is a creature, a player or a
        # planeswalker, and the announcement named a **player's face**. The
        # object branch below resolves a permanent and would find none, so the
        # bite would silently deal nothing — the shape this engine calls a
        # runtime decline. Addressed the way ``deal_damage`` addresses the same
        # union: an announced object is an id or an index, and its absence under
        # this quantifier is the face.
        amount = source.effective_power + int(
            instruction.payload.get("power_bonus", 0)
        )
        face = context.target
        context.results["damaged_permanents"] = ()
        game._deal_damage_to_player(
            face, amount, source=source,
            then=lambda dealt: (
                context.results.__setitem__("damage_dealt", dealt),
                dealt and game.log.append(
                    f"{source.card.name} deals {dealt} damage to {face.name}"
                ),
            ),
            asks=True,
        )
        return True, "resolved"
    filters = instruction.payload.get("filter") or {}
    # "…to **another** target creature" (Farrel's Mantle) — re-checked here
    # rather than trusted from the picker, the rule every narrowed handler
    # follows. It is the *biter* that is excluded, which for an Aura is not the
    # ability's source; and the key is only set where the word is printed, so
    # Karplusan Yeti may still aim its own ability at itself.
    excluded = source if instruction.payload.get("exclude_biter") else None
    # "**Any target**" narrows to CR 115.4's union rather than to a printed noun
    # phrase, and it is re-asked here for the reason the filter above is: the
    # announcement chose a legal target and CR 608.2b lets everything change
    # before this runs, so a creature that has since stopped being one is no
    # longer something this damage may be dealt to.
    any_target = described_targets.get("quantifier") == "any_target"
    victim = resolve_target_permanent(
        game, context,
        predicate=lambda perm: (
            perm is not excluded
            and permanent_matches_filter(perm, filters)
            and (
                not any_target
                or perm.is_creature
                or perm.has_type("planeswalker")
            )
        ),
    )
    # What the sentence after this one means by "that creature" (Tracker), by
    # stable id and recorded on **every** path — a producer `_PRODUCES` names
    # that writes only when it hits would leave the next sentence silently
    # acting on nothing. Written before the damage, not after: the damage is
    # resumable (a replacement may ask a question mid-event), and a record
    # stamped after the loop is a record stamped after the resumption returns.
    context.results["damaged_permanents"] = (
        (victim.permanent_id,) if victim is not None else ()
    )
    if victim is None:
        game.log.append(f"{card.name}: no valid target")
        return True, "resolved"
    # "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3's printed
    # constant, added here rather than folded into the power: what the creature
    # *has* is still its power, and a lord counting it must not see the bonus.
    amount = source.effective_power + int(instruction.payload.get("power_bonus", 0))
    apply_damage_to_creature(
        game, victim, amount, source,
        log_message=lambda dealt: (
            f"{source.card.name} deals {dealt} damage to {victim.card.name}"
        ),
        asks=True,
    )
    return True, "resolved"


@effect_handler("bound_bites_source")
def bound_bites_source(game, instruction, context):
    """"That creature deals damage equal to its power to this creature."
    (Tracker's second sentence.)

    The mirror of the bite above with the two ends swapped: the biter is the
    creature the sentence in front of this one chose — read out of the
    resolution scratchpad, never chosen again — and the bitten is the ability's
    own source.

    Not CR 701.14's fight, which this pair looks like. A fight is
    all-or-nothing (701.14b): if either creature has left the battlefield,
    *neither* deals damage. These are two printed sentences, so the first one
    has already happened, and a source that is gone by now simply takes
    nothing.

    The biter's power is read now rather than when the first half resolved,
    which is what the printed order says: a creature that lost the exchange's
    first half is still on the battlefield here (CR 704.3 checks state-based
    actions only when a player would receive priority) and bites back at full
    strength.
    """
    key = instruction.payload.get("permanents_from")
    recorded = recorded_permanent_ids(context, key)
    target = context.source_permanent
    if target is None or not game.is_on_battlefield(target):
        game.log.append(f"{context.card.name}: nothing left to bite back")
        return True, "resolved"
    for permanent_id in recorded:
        biter = game.permanent_by_id(permanent_id)
        if biter is None or not biter.is_creature:
            # It left the battlefield, or stopped being a creature. A dead
            # creature deals no damage (CR 608.2's last-known information is
            # about *reading* it, not about acting from a graveyard).
            continue
        apply_damage_to_creature(
            game, target, biter.effective_power, biter,
            log_message=lambda dealt, biter=biter: (
                f"{biter.card.name} deals {dealt} damage to {target.card.name}"
            ),
            asks=True,
        )
    return True, "resolved"


@effect_handler("bound_bites_player")
def bound_bites_player(game, instruction, context):
    """"Tap target creature that player controls. **That creature deals damage
    equal to its power to the player.**" (Delirium.)

    ``bound_bites_source`` above with the bitten end swapped for a seat: same
    biter, read out of the resolution scratchpad rather than chosen again, and
    the same read of its power at resolution (CR 613's computed value, so a
    pump or an anthem between the tap and this counts).

    Which seat is the biter's **controller**, and that is the sentence's own
    reading rather than a convenience. "The player" points back at the player
    the first sentence named — "target creature **that player** controls" — and
    the object satisfying that phrase is the creature now in hand. Read through
    ``controller_index_of`` so it is layer 2's answer (CR 613), not the
    battlefield list's.

    The damage is dealt **by the creature**, which is the whole reason this is
    an instruction rather than an ``amount_from`` key on ``deal_damage``: a
    lifelinking creature gains its controller life for it (CR 702.15b), and a
    shield answering to "a creature" answers to this.

    A biter that has left the battlefield deals nothing — CR 608.2's
    last-known information is about *reading* a characteristic, not about
    acting from a graveyard — and says so rather than damaging the seat for
    zero.
    """
    key = instruction.payload.get("permanents_from")
    recorded = recorded_permanent_ids(context, key)
    card = context.card
    for permanent_id in recorded:
        biter = game.permanent_by_id(permanent_id)
        if biter is None or not biter.is_creature:
            game.log.append(f"{card.name}: nothing left to deal the damage")
            continue
        seat = game.controller_index_of(biter)
        if seat is None or not 0 <= seat < len(game.players):
            game.log.append(f"{card.name}: no player for the damage to land on")
            continue
        victim = game.players[seat]

        def _report(dealt: int, victim=victim, biter=biter) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(
                    f"{biter.card.name} deals {dealt} damage to {victim.name}"
                )

        game._deal_damage_to_player(
            victim, max(0, biter.effective_power), source=biter,
            then=_report, asks=True,
        )
    return True, "resolved"


@effect_handler("target_bites_itself")
def target_bites_itself(game, instruction, context):
    """"Target creature deals damage to itself equal to its power."
    (Repentance.)

    CR 120.7: the damage is dealt **by the creature**, so the source is the
    permanent itself and not the sorcery — which is what makes a creature with
    protection from its own colour, or one whose damage lifelinks, answer the
    way the card reads. The amount is ``effective_power``, CR 613's computed
    value read at resolution rather than the printed number.

    The printed noun phrase is re-asked here, not only at announcement: a target
    that stopped being a creature between the two is no longer the thing the
    card names (CR 608.2b), which is the same discipline every targeted bite
    above follows.

    A zero-power creature takes nothing, and the handler still reports resolved
    — CR 120.8: damage of 0 is not dealt at all, so nothing is marked and no
    damage trigger fires.
    """
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players
        else None
    )
    biter = resolve_target_permanent(
        game, context,
        predicate=lambda perm: perm.is_creature and subject_matches(
            game, perm, described,
            observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if biter is None:
        game.log.append(f"{context.card.name}: its target is gone (608.2b)")
        return True, "resolved"
    amount = max(0, int(biter.effective_power))
    if amount <= 0:
        game.log.append(
            f"{biter.card.name} has no power to deal damage with"
        )
        return True, "resolved"
    apply_damage_to_creature(
        game, biter, amount, biter,
        log_message=lambda dealt: (
            f"{biter.card.name} deals {dealt} damage to itself"
        ),
        asks=True,
    )
    return True, "resolved"


@effect_handler("each_matching_bites_itself")
def each_matching_bites_itself(game, instruction, context):
    """"Each creature deals damage to itself equal to its power."
    (Wave of Reckoning.)

    :func:`target_bites_itself` over a *described* set instead of a chosen one:
    nothing is targeted and nobody picks, so every permanent the printed noun
    phrase names bites itself (CR 611.2c fixes that set when the effect begins).
    The set resolves through ``subject_matches`` — the one answer for what a
    printed noun phrase means — with the resolving controller as the observer,
    because "you control" is that seat's "you" (CR 109.5).

    CR 120.7: each creature is the **source** of the damage it takes, so the
    dealer is the permanent and never ``context.card``. That is the whole point
    of the kind — routed through the spell, a creature with protection from
    white would shrug off Wave of Reckoning and a lifelinking one would gain its
    controller nothing.

    The amount is ``effective_power``, CR 613's computed value read as the
    damage is dealt rather than a printed number. Reading it inside the loop is
    the same answer as reading it up front: state-based actions do not run until
    the spell finishes resolving (CR 704.3), so nothing here dies or shrinks
    part-way and every creature deals what it had.

    A zero-power creature is not dealt to at all rather than dealt 0 — CR 120.8:
    damage of 0 is not damage, so nothing is marked and no damage trigger fires.
    """
    from ..subject_filters import subject_matches

    described = instruction.payload.get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    targeted = (
        game.players.index(context.target)
        if context.target is not None and context.target in game.players
        else None
    )
    defending = defending_player_seat(game, context)
    struck: list[str] = []
    for perm in list(game.all_permanents()):
        if not subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent, targeted_player=targeted,
            defending=defending,
        ):
            continue
        amount = max(0, int(perm.effective_power))
        if amount <= 0:
            continue
        apply_damage_to_creature(game, perm, amount, perm)
        struck.append(f"{perm.card.name} ({amount})")
    if not struck:
        game.log.append(f"{context.card.name} found nothing to damage")
    else:
        game.log.append(
            f"{context.card.name}: each creature dealt damage to itself — "
            + ", ".join(struck)
        )
    return True, "resolved"


@effect_handler("target_bites_target")
def target_bites_target(game, instruction, context):
    """"Target creature you control deals damage equal to its power to another
    target creature." (Garruk, Savage Herald's -2.) Two chosen targets resolved
    positionally: the biter first, the bitten second. Both are resolved by id
    without an owner constraint - the two must differ (the printed "another").

    **Each slot is tested against its own printed noun phrase**, read out of
    ``targets.filters``, rather than against a "you control" this handler used
    to spell out. That word is Garruk's, not the kind's: "Tap target creature.
    It deals damage equal to its power to another target creature" (Deadshot)
    names anybody's creature as the biter, and a hardcoded seat would have made
    the spell refuse every legal target it has. Through ``subject_matches``,
    the one reader of a printed noun phrase, with the resolving controller as
    CR 109.5's "you" — and re-asked here rather than only at announcement,
    because a target that stopped matching is no longer the thing the card
    names (CR 608.2b)."""
    from ..subject_filters import subject_matches

    ids = context.target_permanent_id
    if not isinstance(ids, list):
        ids = [ids, None]
    resolved = [game.permanent_by_id(pid) if isinstance(pid, int) else None for pid in ids]
    biter = resolved[0] if resolved else None
    bitten = resolved[1] if len(resolved) > 1 else None
    described = instruction.payload.get("targets") or {}
    slot_filters = described.get("filters") or []
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None

    def _slot_matches(perm, index: int) -> bool:
        if index >= len(slot_filters):
            return True
        return subject_matches(
            game, perm, slot_filters[index] or {},
            observer=observer, source=context.source_permanent,
        )

    if biter is None or not biter.is_creature or not _slot_matches(biter, 0):
        game.log.append(f"{context.card.name}: no creature to deal the damage")
        return True, "resolved"
    if (
        bitten is None
        or not bitten.is_creature
        or bitten is biter
        or not _slot_matches(bitten, 1)
    ):
        game.log.append(f"{context.card.name}: no other target creature to damage")
        return True, "resolved"
    amount = biter.effective_power
    apply_damage_to_creature(
        game, bitten, amount, biter,
        log_message=lambda dealt: (
            f"{biter.card.name} deals {dealt} damage to {bitten.card.name}"
        ),
        asks=True,
    )
    return True, "resolved"
