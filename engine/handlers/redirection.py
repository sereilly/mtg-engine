"""CR 614.9's damage redirections, and the other replacements a resolving
effect arms on a damage event.

The handler twin of ``engine/grammar/lowering/redirection.py``, and wider than
its name for that module's reason: it is CR 614 on a damage event. A
**redirection** changes who the damage is dealt *to* — the damage is still
dealt, in full, by the same source, so lifelink, the damage triggers and the
dealt-damage records all still apply, which is why a redirect read as a shield
would lose all three. Each handler arms a ``DamageRedirect``
(``engine/damage_redirects.py``) with its source, its recipient and its
lifetime: from a target, off a target, between two targets, the next N damage
only (Daughter of Autumn), a chosen source's damage, a class of sources'.
Beside them are the two replacements that change the *event* rather than its
recipient: damage that becomes counter removal (Soul Echo) and a turn-long
change to how much is dealt (Equal Treatment, Blind Fury,
``engine/turn_replacements.py``).

Split out of ``damage.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage_redirects import DamageRedirect, add_redirect
from ..divided_damage import DIVIDED_TARGETS, divided_entry
from ._amounts import resolve_amount
from ._filters import permanent_matches_filter
from ._targets import (divided_target_permanent, resolve_target_permanent,
                       resolve_target_slots)
from .prevention import chosen_shield_source
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("arm_damage_to_counter_removal")
def arm_damage_to_counter_removal(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Soul Echo: "…target opponent may choose that for each 1 damage that
    would be dealt to you until your next upkeep, you remove an echo counter
    from this enchantment instead."

    Arms the CR 614 replacement `engine/replacements.py` applies. The record
    goes on the **permanent**, not on the seat it covers: the counters it
    spends live there, CR 122.2 takes them with the permanent when it leaves,
    and a record on the player would outlive the store and replace damage with
    nothing.

    The seat is the ability's *controller* (CR 109.5) even though the offer was
    made to an opponent — "you" in the sentence behind "may choose that" is
    still the ability's own controller, and the lowering refuses any other
    reading rather than letting the wrong life total be covered.

    The duration needs no field: the sweep at the top of the upkeep step drops
    every record naming the seat whose upkeep it is, which is exactly "until
    your next upkeep".
    """
    from ..replacements import DAMAGE_TO_COUNTER_REMOVAL_RECORD

    source = context.source_permanent
    if source is None:
        game.log.append(f"{context.card.name}: no permanent to spend counters from")
        return True, "resolved"
    seat = game.players.index(context.caster)
    source.metadata[DAMAGE_TO_COUNTER_REMOVAL_RECORD] = {
        "counter": str(instruction.payload.get("counter", "")),
        "seat": seat,
    }
    game.log.append(
        f"Damage to {game.players[seat].name} will remove "
        f"{instruction.payload.get('counter')} counters from {source.card.name} "
        "until their next upkeep"
    )
    return True, "resolved"


@effect_handler(
    "redirect_damage_from_target_until_eot",
    "redirect_damage_from_chosen_source_until_eot",
)
def redirect_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Arm a CR 614.9 redirection on this ability's controller.

    Shimian Night Stalker: "All damage that would be dealt to you this turn by
    target attacking creature is dealt to this creature instead."
    Nova Pentacle: "The next time a source of your choice would deal damage to
    you this turn, that damage is dealt to target creature of an opponent's
    choice instead."

    One handler for both kinds, because what differs is only how the moved
    damage's source was named — a target the picker ran over, or the chosen
    source recorded at activation. The record itself
    (``engine/damage_redirects.py``) says nothing about which card armed it.

    **Nothing is armed unless every piece of the sentence resolved.** A record
    with no source watches *every* source and a record with no new recipient
    watches for nothing; both are strictly wider or strictly emptier than the
    card, and either one would report a card working while it does something
    else. The one deliberate exception is a chosen source that was never
    recorded — AI and headless activations pick no source at all — where the
    record falls back to the next damage from any source, exactly as Reverse
    Damage's and Jade Monolith's fallbacks do, because the effect is spent on
    one instance either way.
    """
    payload = instruction.payload
    caster = context.caster
    card_name = getattr(context.card, "name", "")
    targets_source = instruction.kind == "redirect_damage_from_target_until_eot"

    if payload.get("any_recipient"):
        # "The next time a source of your choice would deal damage this turn,
        # that damage is dealt to **that source's controller** instead."
        # (Reflect Damage.) Neither end of the event is named by the sentence:
        # the record watches whatever the chosen source damages, and who takes
        # it is derived from the source when the damage would be dealt
        # (CR 109.5's controller is a live question). So there is no recipient
        # to resolve here and no new recipient to check for liveness — the
        # record carries the derivation instead, and `live_recipient` performs
        # it.
        #
        # The record hangs off the caster because it has nothing else to hang
        # off, exactly as a class-scoped one does, and
        # `damage_redirects.source_keyed_redirects` is what finds it again.
        moved_source = chosen_shield_source(game, context)
        add_redirect(
            caster,
            DamageRedirect(
                new_recipient=None,
                source=moved_source,
                uses=payload.get("uses"),
                any_recipient=True,
                to_source_controller=True,
                source_name=card_name or None,
            ),
        )
        named = getattr(getattr(moved_source, "card", moved_source), "name", None)
        game.log.append(
            f"{card_name}: the next damage {named or 'any source'} would deal "
            "this turn is dealt to its controller instead"
        )
        return True, "resolved"
    if targets_source and payload.get("new_recipient") == "damage_source":
        # "The next time target attacking creature would deal combat damage to
        # this creature this turn, that creature deals that damage to itself
        # instead." (Shield Dancer.) The record hangs off what it protects —
        # the ability's own permanent, or its controller — answers to the
        # announced source by identity, and names that same source as the
        # taker. CR 614.9's liveness rule still holds: if the attacker has left
        # by then, ``live_recipient`` answers None and the damage lands where
        # it was going.
        protected = (
            context.source_permanent if payload.get("protects") == "source"
            else caster
        )
        if protected is None or (
            protected is not caster and not game.is_on_battlefield(protected)
        ):
            game.log.append(f"{card_name}: nothing is there to protect")
            return True, "resolved"
        described = (payload.get("targets") or {}).get("filter") or {}
        moved_source = resolve_target_permanent(
            game,
            context,
            predicate=lambda perm: permanent_matches_filter(perm, described),
            fallback_players=(),
        )
        if moved_source is None:
            game.log.append(f"{card_name}: its target is gone, nothing is redirected")
            return True, "resolved"
        add_redirect(
            protected,
            DamageRedirect(
                new_recipient=moved_source,
                source=moved_source,
                uses=payload.get("uses"),
                combat_only=bool(payload.get("combat_only")),
                source_name=card_name or None,
            ),
        )
        protected_name = getattr(getattr(protected, "card", None), "name", None)
        game.log.append(
            f"{card_name}: the next "
            + ("combat damage " if payload.get("combat_only") else "damage ")
            + f"{moved_source.card.name} would deal to "
            f"{protected_name or protected.name} this turn is dealt to "
            f"{moved_source.card.name} instead"
        )
        return True, "resolved"
    if targets_source and payload.get("new_recipient") == "source_controller":
        # "All combat damage that would be dealt to you this turn by target
        # unblocked creature is dealt to **its controller** instead." (Mirror
        # Strike.) The record watches the caster and the announced source, and
        # its taker is the source's controller derived when the damage would be
        # dealt — Reflect Damage's ``to_source_controller``, on a record that
        # *does* name the recipient it protects. The source is re-checked
        # against the printed phrase (CR 608.2b) and never guessed.
        described = (payload.get("targets") or {}).get("filter") or {}
        moved_source = resolve_target_permanent(
            game,
            context,
            predicate=lambda perm: permanent_matches_filter(perm, described),
            fallback_players=(),
        )
        if moved_source is None:
            game.log.append(f"{card_name}: its target is gone, nothing is redirected")
            return True, "resolved"
        add_redirect(
            caster,
            DamageRedirect(
                new_recipient=None,
                source=moved_source,
                uses=payload.get("uses"),
                to_source_controller=True,
                combat_only=bool(payload.get("combat_only")),
                source_name=card_name or None,
            ),
        )
        game.log.append(
            f"{card_name}: "
            + ("combat damage " if payload.get("combat_only") else "damage ")
            + f"{moved_source.card.name} would deal to {caster.name} this turn "
            "is dealt to its controller instead"
        )
        return True, "resolved"
    if payload.get("new_recipient") == "source":
        new_recipient = context.source_permanent
    elif payload.get("new_recipient") == "target":
        # "…that damage is dealt to **target creature you control** instead."
        # (General's Regalia.) The taker is a target the *activating* player
        # announced (CR 601.2c), re-checked here against the printed noun phrase
        # (CR 608.2b) through `subject_matches` rather than the pure matcher:
        # "you control" is a seat, which only the game can answer.
        #
        # No scan-the-board fallback, for the reason the source arm below gives
        # in the other direction: a redirect onto a creature nobody named moves
        # damage onto a permanent the player never chose.
        from ..subject_filters import subject_matches

        described = (payload.get("targets") or {}).get("filter") or {}
        observer = game.players.index(caster) if caster in game.players else None
        new_recipient = resolve_target_permanent(
            game,
            context,
            predicate=lambda perm: subject_matches(
                game, perm, described, observer=observer,
                source=context.source_permanent,
            ),
            fallback_players=(),
        )
    else:
        chosen_id = context.results.get(payload.get("result_key"))
        new_recipient = (
            game.permanent_by_id(chosen_id) if isinstance(chosen_id, int) else None
        )
    if new_recipient is None or not game.is_on_battlefield(new_recipient):
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"

    if targets_source:
        described = (payload.get("targets") or {}).get("filter") or {}
        moved_source = resolve_target_permanent(
            game,
            context,
            predicate=lambda perm: permanent_matches_filter(perm, described),
            # No scan-the-board fallback: a redirect armed on a creature nobody
            # named moves damage the player never chose to move.
            fallback_players=(),
        )
        if moved_source is None:
            game.log.append(f"{card_name}: its target is gone, nothing is redirected")
            return True, "resolved"
    else:
        # "A source of your choice", through the one reader every card that
        # prints the phrase uses — which knows the choice can arrive on either
        # of two channels. This read ``choices["chosen_source"]`` alone, the
        # channel a card uses when its *target* is something else (General's
        # Regalia: the creature that takes the damage is the target, so the
        # source rides beside it). Nova Pentacle's taker is an opponent's
        # choice, not a target, so its picker **is** the source picker and its
        # answer arrives as the ability's named permanent or spell: unread
        # here, the record was armed against no source at all and moved the
        # next damage from anything.
        #
        # The target channel is not the source's where the target is the
        # taker, which is what ``from_target_channel`` is for.
        moved_source = chosen_shield_source(
            game, context,
            from_target_channel=payload.get("new_recipient") != "target",
        )

    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=new_recipient,
            source=moved_source,
            uses=payload.get("uses"),
            # "All **combat** damage … by target attacking creature …": the
            # lowering carries the word only on the targeted-source arm.
            combat_only=bool(payload.get("combat_only")),
            source_name=card_name or None,
        ),
    )
    source_name = getattr(
        getattr(moved_source, "card", moved_source), "name", "any source"
    )
    game.log.append(
        f"{card_name}: damage {source_name} would deal to {caster.name} this turn "
        f"is dealt to {new_recipient.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_chosen_source_damage_off_target_until_eot")
def redirect_chosen_source_damage_off_target_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Shaman en-Kor: "{1}{W}: The next time a source of your choice would deal
    damage to target creature this turn, that damage is dealt to this creature
    instead."

    Two announcements, on two channels. The **protected creature** is a target
    (CR 601.2c), so it arrives through the ability's ordinary target resolution
    and is re-checked against the printed noun phrase here (CR 608.2b). The
    **source** is CR 615.8's "a source of your choice", which is not a target at
    all and rides ``choices["chosen_source"]`` — read straight off that channel
    rather than through ``chosen_shield_source``, whose fallback reads the
    ability's *target* as the source and would arm the record against the very
    creature it is guarding.

    A whole instance rather than a point pool: "the next **time**" is one damage
    event however large, which is ``uses=1`` with no ``amount``. The damage is
    still dealt in full by the same source and only its recipient changes, so
    lifelink and every "whenever ~ deals damage" see all of it — the reason this
    is a redirect record and not a shield.

    With no source recorded — an AI or headless activation picks none — the
    record answers to any source, which is the fallback every card printing the
    phrase already takes (Reverse Damage, Jade Monolith): the effect is spent on
    one instance either way.

    **Oracle's Attendants prints the blanket**: "{T}: All damage that would be
    dealt to target creature this turn by a source of your choice is dealt to
    this creature instead." No ``uses`` in the payload, so the record moves
    every instance the chosen source deals the creature all turn — and for that
    one the fallback above is refused, exactly as Kor Chant's handler below
    refuses it: a blanket answering to any source would move every point dealt
    to the creature all turn. CR 609.7a requires the source be chosen, and an
    announcement that named none has not made the choice.
    """
    from ..subject_filters import subject_matches

    card_name = getattr(context.card, "name", "")
    taker = context.source_permanent
    if taker is None or not game.is_on_battlefield(taker):
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    protected = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=taker
        ),
        # No scan-the-board fallback: a redirect armed on a creature nobody
        # named moves damage the player never chose to move.
        fallback_players=(),
    )
    if protected is None:
        game.log.append(f"{card_name}: its target is gone, nothing is redirected")
        return True, "resolved"
    moved_source = context.choices.get("chosen_source")
    uses = instruction.payload.get("uses")
    if uses is None and moved_source is None:
        game.log.append(
            f"{card_name}: no damage source was chosen, so no damage is moved"
        )
        return True, "resolved"
    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            source=moved_source,
            uses=None if uses is None else int(uses),
            source_name=card_name or None,
        ),
    )
    source_name = getattr(
        getattr(moved_source, "card", moved_source), "name", "any source"
    )
    game.log.append(
        f"{card_name}: "
        + ("the next damage " if uses is not None else "all damage ")
        + f"{source_name} would deal to "
        f"{protected.card.name} this turn is dealt to {taker.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_damage_off_target_until_eot")
def redirect_damage_off_target_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sivvi's Valor: "All damage that would be dealt to target creature this
    turn is dealt to you instead."

    The handler above with nothing chosen but the creature: the record hangs
    off the announced target (CR 601.2c, re-checked here against the printed
    phrase per CR 608.2b) and answers to **every** source, which is what "all
    damage" with no "by …" means — so there is no ``chosen_source`` to read and
    no fallback to guard against.

    The taker is the payload's ``new_recipient``: "you" is the controller of
    this spell or ability (CR 109.5), "source" the permanent whose ability it
    is. Neither is frozen past what CR 614.9 already says about it —
    ``damage_redirects.live_recipient`` asks, when the damage would be dealt,
    whether the player is still in the game or the permanent still a creature
    on the battlefield, and the redirect does nothing if not. And the damage is
    still **dealt by the original source** to whoever takes it, so lifelink,
    protection and "a source you control" all read the source that dealt it.

    The record lives on the creature, so the creature leaving takes it along:
    a permanent that returns is a new object (CR 400.7) with no record on it,
    and the cleanup sweep clears it with the turn.
    """
    from ..subject_filters import subject_matches

    card_name = getattr(context.card, "name", "")
    payload = instruction.payload
    caster = context.caster
    if payload.get("new_recipient") == "source":
        taker = context.source_permanent
        if taker is None or not game.is_on_battlefield(taker):
            game.log.append(f"{card_name}: nothing is there to take the damage")
            return True, "resolved"
        taker_name = taker.card.name
    else:
        taker = caster
        taker_name = caster.name
    described = (payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(caster) if caster in game.players else None
    protected = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer,
            source=context.source_permanent,
        ),
        # No scan-the-board fallback: a redirect armed on a creature nobody
        # named moves damage the player never chose to move.
        fallback_players=(),
    )
    if protected is None:
        game.log.append(f"{card_name}: its target is gone, nothing is redirected")
        return True, "resolved"
    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            uses=payload.get("uses"),
            combat_only=bool(payload.get("combat_only")),
            source_name=card_name or None,
        ),
    )
    game.log.append(
        f"{card_name}: "
        + ("the next " if payload.get("uses") else "all ")
        + ("combat " if payload.get("combat_only") else "")
        + f"damage that would be dealt to {protected.card.name} this turn is "
        f"dealt to {taker_name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_chosen_source_damage_between_targets_until_eot")
def redirect_chosen_source_damage_between_targets_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Kor Chant: "All damage that would be dealt this turn to target creature
    you control by a source of your choice is dealt to another target creature
    instead."

    The handler above with the *taker* announced as well, so three answers
    arrive on two channels: both creatures are targets (CR 601.2c) and come in
    role order through ``resolve_target_slots`` — positionally, never compacted,
    because slot 1 sliding into slot 0 would hand the redirect's damage to the
    creature it was meant to protect — while the **source** is CR 609.7a's
    choice, which is not a target and rides ``choices["chosen_source"]``.

    Read off that channel alone (``from_target_channel=False``): the fallback
    inside :func:`chosen_shield_source` reads the spell's *target* as the
    source, and here that target is the creature being guarded, so the record
    would answer only to damage that creature itself dealt.

    Both noun phrases are re-checked here (CR 608.2b) rather than trusted from
    the announcement — "you control" in particular, which the picker enforces at
    cast and which a control change between announcement and resolution can
    undo.

    **With no source announced, nothing is armed.** Every other card printing
    the phrase carries ``uses=1`` and may safely fall back to a record answering
    to any source — spent on one instance either way — but this one is blanket
    for the turn, so the same fallback would move every point of damage dealt
    all turn onto the second creature. CR 609.7a requires a source to be chosen;
    an announcement that named none has not made the choice, and the narrow
    reading is the only one that cannot be wrong in the player's favour.
    """
    from ..subject_filters import subject_matches

    card_name = getattr(context.card, "name", "")
    payload = instruction.payload
    targets = payload.get("targets") or {}
    slot_filters = list(
        targets.get("filters") or [targets.get("filter") or {}] * 2
    )
    protected, taker = resolve_target_slots(game, context, 2)
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    for slot, permanent in enumerate((protected, taker)):
        described = slot_filters[slot] if slot < len(slot_filters) else {}
        if (
            permanent is None
            or not game.is_on_battlefield(permanent)
            or not subject_matches(game, permanent, described, observer=observer)
        ):
            game.log.append(
                f"{card_name}: one of its targets is gone, nothing is redirected"
            )
            return True, "resolved"
    if protected is taker:
        # "**another** target creature" — CR 601.2c's distinctness, which the
        # roles walk gives the picker for free and which is asserted again here
        # for the caller that names its targets directly.
        game.log.append(
            f"{card_name}: its two targets must be different creatures"
        )
        return True, "resolved"

    moved_source = chosen_shield_source(game, context, from_target_channel=False)
    if moved_source is None:
        game.log.append(
            f"{card_name}: no damage source was chosen, so no damage is moved"
        )
        return True, "resolved"

    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            source=moved_source,
            uses=payload.get("uses"),
            source_name=card_name or None,
        ),
    )
    source_name = getattr(
        getattr(moved_source, "card", moved_source), "name", "the chosen source"
    )
    game.log.append(
        f"{card_name}: damage {source_name} would deal to "
        f"{protected.card.name} this turn is dealt to {taker.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_next_damage_to_source_until_eot")
def redirect_next_damage_to_source_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Daughter of Autumn: "{W}: The next 1 damage that would be dealt to target
    white creature this turn is dealt to this creature instead." Hazduhr the
    Abbot prints the same sentence with ``X`` for the number.

    A **point pool** rather than a whole-event record (CR 615.7 read with
    CR 614.9's verb): the record carries how many points it can still move, and
    what a larger event leaves over is dealt to the creature normally. Which is
    why the amount is resolved here and not at the arming's parse — Hazduhr's is
    the X his controller announced, and an X of 0 arms nothing rather than
    arming a record that can move nothing and would sit on the creature until
    the cleanup step.

    The record hangs off the **protected creature**, which is the ordinary home
    for one (``engine/damage_redirects.py``: a record lives on the recipient it
    watches), and points at the permanent whose ability this is. If that
    permanent has left by the time the damage would be dealt, CR 614.9 makes the
    redirect do nothing — ``live_recipient`` answers that, so nothing here has
    to hold the Abbot on the battlefield.

    The target is re-checked against the printed noun phrase at resolution
    (CR 608.2b) rather than trusted from the activation, and through
    ``subject_matches`` with the ability's controller as the observer, because
    "white creature **you control**" is that seat's "you" (CR 109.5). No
    scan-the-board fallback: a redirect armed on a creature nobody named moves
    damage the player never chose to move.
    """
    from ..subject_filters import subject_matches

    payload = instruction.payload
    card_name = getattr(context.card, "name", "")
    taker = context.source_permanent
    if taker is None or not game.is_on_battlefield(taker):
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"
    described = (payload.get("targets") or {}).get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    protected = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=taker
        ),
        fallback_players=(),
    )
    # "…dealt to **target creature, planeswalker, or player**" (Martyrdom's
    # granted ability). CR 115.4's union, and the one recipient this handler had
    # no branch for: the record hangs off *whatever* the damage would be dealt
    # to, and ``engine/damage_redirects`` has carried a player there since it
    # was written (CR 615.1's wording puts a player and a permanent on the same
    # footing). Which of the two was chosen is read the way every other
    # any-target effect reads it — a permanent when one was named, and the
    # resolution's player otherwise — rather than by a second convention.
    if protected is None and (
        (payload.get("targets") or {}).get("quantifier") == "any_target"
    ):
        player = context.target
        if player is None or getattr(player, "lost", False):
            game.log.append(f"{card_name}: its target is gone, nothing is redirected")
            return True, "resolved"
        amount = resolve_amount(payload.get("amount", 0), context.x_value)
        if amount <= 0:
            game.log.append(f"{card_name}: no damage to move")
            return True, "resolved"
        add_redirect(
            player,
            DamageRedirect(
                new_recipient=taker,
                amount=amount,
                uses=None,
                source_name=card_name or None,
            ),
        )
        game.log.append(
            f"{card_name}: the next {amount} damage that would be dealt to "
            f"{player.name} this turn is dealt to {taker.card.name} instead"
        )
        return True, "resolved"
    if protected is None:
        game.log.append(f"{card_name}: its target is gone, nothing is redirected")
        return True, "resolved"
    amount = resolve_amount(payload.get("amount", 0), context.x_value)
    if amount <= 0:
        game.log.append(f"{card_name}: no damage to move")
        return True, "resolved"
    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            amount=amount,
            uses=None,
            source_name=card_name or None,
        ),
    )
    game.log.append(
        f"{card_name}: the next {amount} damage that would be dealt to "
        f"{protected.card.name} this turn is dealt to {taker.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_next_damage_from_source_until_eot")
def redirect_next_damage_from_source_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Zhalfirin Crusader: "{1}{W}: The next 1 damage that would be dealt to
    this creature this turn is dealt to any target instead."

    ``redirect_next_damage_to_source_until_eot`` with the two ends of the event
    exchanged. The record still hangs off the **protected** recipient, which is
    where one always hangs (``engine/damage_redirects.py``) — here that is the
    permanent whose ability this is, and the *taker* is what the activation
    chose.

    A **point pool** rather than a whole-event record, read with CR 614.9's
    verb: each point moves one point and a larger event leaves the rest marked
    on the Crusader as normal. The damage is still dealt in full by the same
    source, so lifelink and "whenever ~ deals damage" see all of it — which is
    why this is a redirect record and not a shield.

    CR 614.9 is a liveness rule, and it is `applicable_redirect` that enforces
    it: a taker that has left the battlefield or stopped being a creature makes
    the effect do nothing, and the damage lands on the Crusader as though the
    ability had never been activated. Nothing here has to hold the taker in
    play.

    The five en-Kor creatures print the same sentence with the taker **narrowed**
    — "…is dealt to target creature you control instead" — so the printed noun
    phrase is re-checked here at resolution (CR 608.2b) rather than trusted from
    the activation, through ``subject_matches`` with the ability's controller as
    the observer, because "creature **you control**" is that seat's "you"
    (CR 109.5). That check is the whole difference between the two spellings:
    with an empty description it admits everything, which is what "any target"
    means.
    """
    from ..subject_filters import subject_matches

    card_name = getattr(context.card, "name", "")
    protected = context.source_permanent
    if protected is None or not game.is_on_battlefield(protected):
        game.log.append(f"{card_name}: its own source is gone")
        return True, "resolved"
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    # "…is dealt to **any target** instead" — CR 115.4's union, read the way
    # every other any-target effect reads it: a permanent when one was named,
    # and the resolution's player otherwise. The permanent is asked first
    # because naming one also fills the player slot with whoever controls it.
    taker = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described, observer=observer, source=protected
        ),
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if taker is None and not described:
        # Only the union spelling has a player to fall back to. A narrowed
        # object phrase names a permanent and nothing else, so reading the
        # resolution's player here would move the damage onto a seat the card
        # never offered.
        taker = context.target
    if taker is None or getattr(taker, "lost", False):
        game.log.append(f"{card_name}: its target is gone, nothing is redirected")
        return True, "resolved"
    taker_name = getattr(taker, "name", None) or taker.card.name
    uses = instruction.payload.get("uses")
    if uses is not None:
        # "**The next time** damage would be dealt to this creature this turn,
        # that damage is dealt to any target instead." (Mirrorwood Treefolk.)
        # CR 615.8's one instance in place of the point pool: the whole of the
        # next event moves however large it is, and then the record is spent.
        # No ``amount`` at all, which is what "the whole event" means on a
        # ``DamageRedirect`` — and no source, so combat damage, a burn spell
        # and the controller's own sources are all the next time.
        add_redirect(
            protected,
            DamageRedirect(
                new_recipient=taker,
                uses=int(uses),
                source_name=card_name or None,
            ),
        )
        game.log.append(
            f"{card_name}: the next time damage would be dealt to "
            f"{protected.card.name} this turn, it is dealt to {taker_name} "
            "instead"
        )
        return True, "resolved"
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    if amount <= 0:
        game.log.append(f"{card_name}: no damage to move")
        return True, "resolved"
    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            amount=amount,
            uses=None,
            source_name=card_name or None,
        ),
    )
    game.log.append(
        f"{card_name}: the next {amount} damage that would be dealt to "
        f"{protected.card.name} this turn is dealt to {taker_name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_next_damage_between_targets_until_eot")
def redirect_next_damage_between_targets_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Captain's Maneuver: "The next X damage that would be dealt to target
    creature, planeswalker, or player this turn is dealt to another target
    creature, planeswalker, or player instead."

    The point pool of the two handlers above with **both** ends announced. The
    record hangs off the first target, where one always hangs
    (``engine/damage_redirects.py``), and points at the second; the spell is
    neither end, and has left the stack long before any damage is dealt.

    The two targets arrive on ``divided_targets`` — the one channel that
    carries a list of targets spanning both battlefields and the players' faces
    — in the order the sentence names them, each resolved by the id the cast
    path stamped (``divided_target_permanent``), never by slot. Read
    **positionally and never compacted**: entry 1 sliding into entry 0's place
    would arm the redirect on the creature that was meant to take the damage.

    CR 608.2b at resolution, one end at a time. With the protected end gone
    there is nothing to watch, and with the taker gone there is nowhere to send
    it — CR 614.9's "the effect does nothing" arrived early, which the card's
    own rulings state for both ends. A taker that leaves *after* this resolves
    is CR 614.9 proper, and ``applicable_redirect`` answers it when the damage
    would be dealt.

    X is the number announced as the spell was cast (CR 601.2b); an X of 0
    arms nothing rather than a record that can move nothing and would sit on
    its recipient until the cleanup step.
    """
    card_name = getattr(context.card, "name", "")
    entries = list((context.choices or {}).get(DIVIDED_TARGETS) or ())
    if len(entries) == 1:
        # CR 608.2b: an end that became illegal while the spell waited is
        # blanked out of the announcement before this runs
        # (``legality.blank_illegal_resolution_targets`` drops a divided
        # entry), so one entry here is two that were announced and one that
        # is gone - the case the check below was written for, said the way it
        # says it.
        game.log.append(f"{card_name}: one of its targets is gone, nothing is redirected")
        return True, "resolved"
    if len(entries) != 2:
        game.log.append(f"{card_name}: its two targets were not announced")
        return True, "resolved"
    ends: list = []
    for entry in entries:
        seat, index, _share = divided_entry(entry)
        if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
            ends.append(None)
        elif index is None:
            player = game.players[seat]
            ends.append(None if getattr(player, "lost", False) else player)
        else:
            permanent = divided_target_permanent(game, entry)
            ends.append(
                permanent
                if permanent is not None and game.is_on_battlefield(permanent)
                # CR 115.4: "any target" is a creature, a planeswalker or a
                # battle. One that stopped being any of them while the spell
                # waited is an illegal target (CR 608.2b).
                and (
                    permanent.is_creature
                    or permanent.has_type("planeswalker")
                    or permanent.has_type("battle")
                )
                else None
            )
    protected, taker = ends
    if protected is None or taker is None or protected is taker:
        game.log.append(f"{card_name}: one of its targets is gone, nothing is redirected")
        return True, "resolved"
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    if amount <= 0:
        game.log.append(f"{card_name}: no damage to move")
        return True, "resolved"
    add_redirect(
        protected,
        DamageRedirect(
            new_recipient=taker,
            amount=amount,
            uses=None,
            source_name=card_name or None,
        ),
    )
    protected_name = getattr(protected, "name", None) or protected.card.name
    taker_name = getattr(taker, "name", None) or taker.card.name
    game.log.append(
        f"{card_name}: the next {amount} damage that would be dealt to "
        f"{protected_name} this turn is dealt to {taker_name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_matching_damage_to_you_until_eot")
def redirect_matching_damage_to_you_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Blood of the Martyr: "Until end of turn, if damage would be dealt to any
    creature, you may have that damage dealt to you instead."

    The record hangs off the **caster**, and it is the one record in the family
    that does not live on the recipient it watches. The recipients are a printed
    noun phrase — every creature, including the ones that enter after this
    resolves — so there is no object to hang it on and nothing to update when
    one arrives. Hanging it on the taker instead means the cleanup sweep that
    already clears a player's redirects clears this one too, with no new
    lifetime and no new field
    (see ``engine/damage_redirects.class_redirects``).
    """
    caster = context.caster
    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=caster,
            recipients=dict(instruction.payload.get("recipients") or {}),
            optional=bool(instruction.payload.get("optional")),
            source_name=getattr(context.card, "name", None),
        ),
    )
    game.log.append(
        f"{getattr(context.card, 'name', 'an effect')}: {caster.name} may take "
        "damage dealt to any creature this turn"
    )
    return True, "resolved"


@effect_handler("redirect_source_class_damage_until_eot")
def redirect_source_class_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Kjeldoran Royal Guard: "{T}: All combat damage that would be dealt to you
    by unblocked creatures this turn is dealt to this creature instead."

    The record hangs off the **caster**, which is the recipient it protects, so
    the cleanup sweep that already clears a player's redirects ends it — no new
    lifetime and no new field. What it answers to is the printed noun phrase
    rather than one chosen object: ``sources`` is re-asked of each damage source
    when the damage would be dealt (CR 614.9 fixes nothing when the ability
    resolves), so a creature that is still unblocked in the combat damage step
    is covered and one that got blocked is not.

    The Guard itself is the new recipient, read off ``source_permanent`` rather
    than described — and if it has left the battlefield by the time the damage
    would be dealt, ``live_recipient`` makes the redirect do nothing, which is
    CR 614.9 rather than a failure here.
    """
    caster = context.caster
    guard = context.source_permanent
    card_name = getattr(context.card, "name", None)
    spell_types = tuple(instruction.payload.get("spell_types") or ())
    if spell_types:
        # "The next time an **instant or sorcery spell** would deal damage to
        # you this turn, that spell deals that damage to its controller
        # instead." (Aegis of Honor.) The same record with the class named as
        # a kind of spell: ``spell_sources`` is what Harsh Judgment's static
        # derives, with no colour here, and the taker is read off the spell
        # when the damage would be dealt (``to_source_controller``) — which is
        # why this arm needs no permanent to take anything, and why an Aegis
        # that has left the battlefield by then changes nothing (CR 113.7a:
        # once activated, the ability exists independently of its source).
        add_redirect(
            caster,
            DamageRedirect(
                new_recipient=None,
                spell_sources=(spell_types, None),
                to_source_controller=True,
                uses=instruction.payload.get("uses"),
                source_name=card_name,
            ),
        )
        game.log.append(
            f"{card_name}: the next time an "
            + " or ".join(spell_types)
            + f" spell would deal damage to {caster.name} this turn, it deals "
            "that damage to its controller instead"
        )
        return True, "resolved"
    if guard is None:
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"
    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=guard,
            sources=dict(instruction.payload.get("sources") or {}),
            combat_only=bool(instruction.payload.get("combat_only")),
            uses=None,
            source_name=card_name,
        ),
    )
    game.log.append(
        f"{card_name}: {'combat ' if instruction.payload.get('combat_only') else ''}"
        f"damage matching sources would deal to {caster.name} this turn is dealt "
        f"to {guard.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_source_damage_to_target_until_eot")
def redirect_source_damage_to_target_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Soltari Guerrillas: "{0}: The next time this creature would deal combat
    damage to an opponent this turn, it deals that damage to target creature
    instead."

    The redirect whose source is the ability's **own** permanent and whose
    protected recipient is somebody else's seat. Both halves are what make it a
    kind of its own:

    * the source needs no picker and no record — it is ``source_permanent``, and
      ``source_matches`` compares it by identity, so a second Guerrillas does
      not answer for this one.
    * the record is armed on the **opponents**, because that is what the
      sentence describes. Every other recorded redirect goes on its controller.

    **One record, shared between those seats.** CR 615.8's "the next *time*" is
    one instance of one replacement effect, so a per-seat copy would fire once
    per opponent in a multiplayer game — the list is the index, and appending the
    same object to several of them is what makes the single ``uses`` counter the
    one they all spend. It is also why the seats are enumerated here and not
    frozen at lowering: a player who has left is nobody's opponent (CR 800.4a).

    Nothing is armed unless the target resolved. A record with no new recipient
    watches for nothing, and `live_recipient` would make it do nothing anyway —
    but a card that reported "armed" and moved no damage is exactly the silence
    this repo's Rock Hydra test exists to catch, so the log says which happened.
    """
    payload = instruction.payload
    caster = context.caster
    card_name = getattr(context.card, "name", "")
    source = context.source_permanent
    if source is None:
        # A named-source record with no source watches *every* source, which is
        # strictly wider than the card. Refusing to arm is the narrow direction.
        game.log.append(f"{card_name}: its source has left, nothing is redirected")
        return True, "resolved"
    described = (payload.get("targets") or {}).get("filter") or {}
    new_recipient = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: permanent_matches_filter(perm, described),
        # No scan-the-board fallback, for `redirect_damage_until_eot`'s reason:
        # damage moved onto a creature nobody named is damage the player never
        # chose to move.
        fallback_players=(),
    )
    if new_recipient is None or not game.is_on_battlefield(new_recipient):
        game.log.append(f"{card_name}: its target is gone, nothing is redirected")
        return True, "resolved"
    record = DamageRedirect(
        new_recipient=new_recipient,
        source=source,
        uses=payload.get("uses"),
        combat_only=bool(payload.get("combat_only")),
        source_name=card_name or None,
    )
    if payload.get("protects") == "opponents":
        watched = [
            game.players[seat]
            for seat in game.opponents_of(game.players.index(caster))
        ]
    else:
        watched = [caster]
    for player in watched:
        add_redirect(player, record)
    game.log.append(
        f"{card_name}: the next {'combat ' if record.combat_only else ''}damage "
        f"{source.card.name} would deal to "
        + (", ".join(p.name for p in watched) or "nobody")
        + f" this turn is dealt to {new_recipient.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_damage_from_target_spell_until_eot")
def redirect_damage_from_target_spell_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Reverberation: "All damage that would be dealt this turn by target
    sorcery spell is dealt to that spell's controller instead."

    The record hangs off the **stack item**, not off a recipient and not off the
    card, and that is the whole of what makes this card possible. A spell's
    damage source is its printed ``CardDefinition`` (CR 109.5) — one object per
    card, handed out once per copy by the deck builder — so a record matching on
    the source would move a *second* copy's damage too. A ``StackItem`` is one
    object per cast, and ``Game.resolving_items`` is where the damage paths can
    reach it (see ``engine/damage_redirects.resolving_object_redirects``).

    The chosen spell's type is re-checked here rather than trusted from the
    cast: CR 608.2b asks whether the target is still legal when the spell
    resolves, and a spell that has changed type in between is one this card no
    longer names.
    """
    item = context.stack_target
    card_name = getattr(context.card, "name", "")
    if item is None or not any(entry is item for entry in game.stack):
        game.log.append(f"{card_name}: the spell it named is no longer on the stack")
        return True, "resolved"
    wanted = instruction.payload.get("card_types") or ()
    if wanted and getattr(item.card, "primary_type", None) not in wanted:
        game.log.append(
            f"{card_name}: {item.card.name} is no longer "
            f"{'/'.join(str(t) for t in wanted)} spell it named"
        )
        return True, "resolved"
    controller = game.players[item.caster_index]
    add_redirect(
        item,
        DamageRedirect(
            new_recipient=controller,
            # The spell's own card, so that damage *another* source deals while
            # this one resolves — a sorcery that has a creature deal it — stays
            # where it was dealt. The cast is what the record is found by; the
            # card is what it answers to.
            source=item.card,
            source_name=card_name or None,
        ),
    )
    game.log.append(
        f"{card_name}: damage {item.card.name} would deal is dealt to "
        f"{controller.name} instead"
    )
    return True, "resolved"


@effect_handler("arm_turn_damage_replacement")
def arm_turn_damage_replacement(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If any source would deal 1 or more damage to a permanent or player this
    turn, it deals 2 damage to that permanent or player instead." (Equal
    Treatment.) "If a creature would deal combat damage to a creature this
    turn, it deals double that damage to that creature instead." (Blind Fury.)

    A CR 614 replacement armed by a *resolving spell*, so there is no permanent
    for an interceptor to read and the effect is recorded on its controller's
    seat (``engine/turn_replacements.py``) with the turn as its lifetime; the
    interceptors in ``engine/replacements.py`` read the record and the cleanup
    step's one sweep ends it. Every printed narrowing rides the record, so the
    interceptor tests what the card said rather than what one card says.

    Two resolutions arm two records — two effects (CR 614.5) — which is what
    makes two Blind Furies quadruple the damage.
    """
    from ..turn_replacements import DAMAGE, TurnReplacement, arm_turn_replacement

    payload = instruction.payload
    record = arm_turn_replacement(game, TurnReplacement(
        seat=game.players.index(context.caster),
        event=DAMAGE,
        source_name=getattr(context.card, "name", None),
        combat_only=bool(payload.get("combat_only")),
        source_creature=bool(payload.get("source_creature")),
        recipient_creature=bool(payload.get("recipient_creature")),
        at_least=int(payload.get("at_least", 1) or 1),
        multiplier=int(payload.get("multiplier", 1) or 1),
        becomes=(
            int(payload["becomes"]) if payload.get("becomes") is not None else None
        ),
    ))
    what = (
        f"becomes {record.becomes}" if record.becomes is not None
        else f"is multiplied by {record.multiplier}"
    )
    game.log.append(
        f"{context.card.name}: this turn, "
        + ("combat " if record.combat_only else "")
        + "damage "
        + ("dealt by a creature " if record.source_creature else "")
        + ("to a creature " if record.recipient_creature else "")
        + what
    )
    return True, "resolved"
