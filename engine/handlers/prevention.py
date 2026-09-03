from __future__ import annotations

from typing import TYPE_CHECKING

from ..shields import (
    make_source_type_shield,
    make_targeting_source_shield,
    add_shield,
    make_capped_charge,
    make_capped_source,
    make_color_shield,
    make_half_charge,
    make_half_source,
    make_life_gain_charge,
    make_life_gain_source,
    make_numeric_pool,
    make_subject_shield,
    make_whole_charge,
    make_whole_source,
)
from ._common import (attached_host, bound_permanent, resolve_amount,
                      resolve_target_permanent)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import PlayerState
    from ..oracle import OracleInstruction


def _grant_pool(recipient, amount: int, source_name: str | None):
    """Arm one CR 615.7 numeric shield on *recipient* and return it.

    A shield rather than an addition to a running total: several "prevent the
    next N damage" effects on one recipient are several effects, each with its
    own granting card for the badge. What they hold together is still the one
    number ``damage_prevention_pool`` reports.

    Returned so the resolution that armed it can record it — Sacred Boon's
    second sentence reads back what *this* shield prevented, and only the object
    survives from here to the end step.
    """
    if amount <= 0:
        return None
    return add_shield(recipient, make_numeric_pool(amount, source_name))


def apply_prevention_shield(
    game: Game,
    target: PlayerState,
    target_permanent_index: object,
    amount: int,
    source_name: str | None = None,
    context: OracleExecutionContext | None = None,
) -> str:
    """Grant `amount` prevention shields to a chosen creature, or otherwise to the
    target player. Records `source_name` (the granting card) so the UI can show
    its art on the shield badge. Returns the name of the beneficiary."""
    if (
        isinstance(target_permanent_index, int)
        and 0 <= target_permanent_index < len(target.battlefield)
        and target.battlefield[target_permanent_index].is_creature
    ):
        permanent = target.battlefield[target_permanent_index]
        _record_shield(context, _grant_pool(permanent, amount, source_name), permanent)
        game.log.append(f"{permanent.card.name} gains prevention shield for {amount} damage")
        return permanent.card.name
    _record_shield(context, _grant_pool(target, amount, source_name), None)
    game.log.append(f"{target.name} gains prevention shield for {amount} damage")
    return target.name


#: The resolution-scratchpad key a granted shield is recorded under, and the id
#: of the permanent it protects. Named once because the step that writes them
#: and the delayed ability that reads them are a whole turn apart — see
#: ``lowering/_records._PRODUCES``.
PREVENTION_SHIELD_RESULT = "prevention_shield"
PREVENTION_SHIELD_TARGET_RESULT = "prevention_shield_target"


def _record_shield(context, shield, permanent) -> None:
    """Record the shield this step armed, for a later sentence of the same
    effect to read back (CR 615.5's "prevented this way").

    The shield **object**, not a number: what it prevents is not known yet, and
    by the time the reader runs the shield may have been spent and dropped from
    its recipient. Nothing serialises a resolution's scratchpad or a delayed
    ability's captured values, so the reference is the record.
    """
    if shield is None or context is None:
        return
    context.results[PREVENTION_SHIELD_RESULT] = shield
    if permanent is not None:
        context.results[PREVENTION_SHIELD_TARGET_RESULT] = permanent.permanent_id


def _sized_for_recipient(
    game: Game,
    context: OracleExecutionContext,
    instruction: OracleInstruction,
    target: PlayerState,
    amount: int,
) -> int:
    """*amount*, or the second size the card prints for a matching recipient.

    "Prevent the next 1 damage that would be dealt to any target this turn. **If
    it's a green creature, prevent the next 2 damage instead.**" (Elvish
    Healer.) One shield of one size, chosen here because here is the first place
    the target is known — the size cannot be decided when the line compiles, and
    two shields would prevent three.

    Asked through ``subject_matches``, the one reader of a printed noun phrase,
    with the ability's controller as the observer (CR 109.5) — so "green" is
    layer 5's answer and a creature recoloured since the ability was activated
    is sized by what it is now.
    """
    alternate = instruction.payload.get("amount_if")
    if not alternate:
        return amount
    # The same choice ``apply_prevention_shield`` is about to make — a creature
    # the ability named, or nothing and therefore the player — resolved through
    # the id seam rather than by indexing the battlefield, so the two cannot
    # disagree about which permanent is being shielded.
    chosen = resolve_target_permanent(
        game, context,
        player=target,
        predicate=lambda perm: perm.is_creature,
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if chosen is None:
        return amount
    from ..subject_filters import subject_matches

    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    if subject_matches(
        game, chosen, dict(alternate.get("filter") or {}),
        observer=observer, source=context.source_permanent,
    ):
        return int(alternate.get("amount", amount))
    return amount


@effect_handler("grant_prevention_shield")
def grant_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    source_name = context.card.name if context.card else None
    # CoP-style abilities say "prevent damage to you" — protection_kind="color"
    # means the caster/controller is always the beneficiary. Conservator-style
    # abilities ("...dealt to you this turn") set to_self=True for the same reason.
    prevention_color = instruction.payload.get("prevention_color")
    # "a black **or red** source of your choice" (Greater Realm of
    # Preservation): one shield answering to either colour, never one shield
    # per colour — two would let a black source and a red source each be
    # prevented off a single activation.
    prevention_colors = tuple(
        instruction.payload.get("prevention_colors") or ()
    ) or ((prevention_color,) if prevention_color else ())
    if instruction.payload.get("prevention_color_chosen"):
        # "…a source of your choice **of the chosen color**" (Prismatic
        # Circle). The colour is not in the sentence: it is what this permanent
        # recorded as it entered (CR 614.1c), read here rather than at damage
        # time because CR 615.9 rechecks the *source* against a property the
        # shield already holds — and the property was fixed when this ability
        # resolved.
        #
        # Nothing recorded arms nothing, the reading
        # ``prevention._resolved_chosen_color`` takes of the same phrase on the
        # static side: a shield naming no colour would answer to every source,
        # which is the widest possible reading of a sentence that names one.
        recorded = (
            getattr(context.source_permanent, "metadata", {}) or {}
        ).get("chosen_color")
        prevention_colors = (str(recorded),) if recorded else ()
    # Circle of Protection: Artifacts — the same Circle keyed on a card type.
    # Its own branch rather than a widened colour one: `make_color_shield` sets
    # the colour field, and a shield holding a card type in it would be
    # compared against `source_colors` and never match.
    source_type = instruction.payload.get("prevention_source_type")
    if instruction.payload.get("protection_kind") == "source_type" and source_type:
        add_shield(caster, make_source_type_shield(str(source_type), source_name))
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            f"an {source_type} source"
        )
        return True, "resolved"
    if instruction.payload.get("protection_kind") == "color":
        # Circle of Protection: "The next time a <color> source of your choice
        # would deal damage to you this turn, prevent that damage." Each activation
        # arms one color-scoped shield that prevents the entire next damage event
        # from a source of that color (CR 615) — distinct from the generic numeric
        # prevention pool so it only stops matching-colored damage.
        #
        # Only when a colour was actually recorded: CR 615.9 rechecks the
        # source's properties against the shield's, so a shield naming no colour
        # can never match anything. The legacy parse rule can still produce one
        # from a card whose text has no colour word, and arming nothing is what
        # the old list-of-None amounted to.
        for _ in range(max(1, amount) if prevention_colors else 0):
            add_shield(caster, make_color_shield(prevention_colors, source_name))
        # The chosen source (if the controller picked a specific permanent) is
        # recorded only for the log; matching is by color.
        chosen_perm = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
        chosen = chosen_perm.card.name if chosen_perm is not None else None
        game.log.append(
            f"{caster.name} sets a Circle of Protection shield against "
            + (
                f"{chosen} (a {'/'.join(prevention_colors)} source)"
                if chosen
                else f"a {'/'.join(prevention_colors)} source"
            )
        )
        return True, "resolved"

    if instruction.payload.get("to_self"):
        _record_shield(context, _grant_pool(caster, amount, source_name), None)
        game.log.append(f"{caster.name} gains prevention shield for {amount} damage")
        return True, "resolved"

    # Fylgja: "Remove a healing counter from this Aura: Prevent the next 1
    # damage that would be dealt to enchanted creature this turn." The shield
    # protects the permanent the ability's source is attached to — read through
    # `attached_host`, the one accessor for that relation, so an Aura that has
    # come unattached shields nothing rather than shielding itself.
    if instruction.payload.get("to_attached"):
        host = attached_host(game, context.source_permanent)
        if host is not None:
            _record_shield(context, _grant_pool(host, amount, source_name), host)
            game.log.append(
                f"{host.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # Rock Hydra: "{R}: Prevent the next 1 damage that would be dealt to this
    # creature this turn." The shield protects the ability's own source
    # permanent, never the (defaulted) target.
    if instruction.payload.get("to_source"):
        source_perm = context.source_permanent
        if source_perm is not None:
            _record_shield(
                context, _grant_pool(source_perm, amount, source_name), source_perm
            )
            game.log.append(
                f"{source_perm.card.name} gains prevention shield for {amount} damage"
            )
        return True, "resolved"

    # "Prevent the next N damage that would be dealt to any target" (Healing
    # Salve's prevention mode, Samite Healer, …): the target may be a creature,
    # in which case the shield protects that creature rather than its controller.
    amount = _sized_for_recipient(game, context, instruction, target, amount)
    apply_prevention_shield(
        game, target, context.target_permanent_index, amount, source_name,
        context=context,
    )
    return True, "resolved"


@effect_handler("add_pt_counters_per_damage_prevented")
def add_pt_counters_per_damage_prevented(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sacred Boon: "…At the beginning of the next end step, put a +0/+1 counter
    on that creature for each 1 damage prevented this way."

    A delayed triggered ability (CR 603.7) firing a whole turn after the spell
    resolved, so both of the things it names come from what that resolution
    recorded: the shield it armed and the creature it armed it on. The shield is
    the object rather than a number because the number did not exist yet — the
    total goes on accumulating for the rest of the turn, which is the whole
    reason the counters are placed at the end step and not at once.

    Nothing is placed when the shield absorbed nothing: "for each 1 damage
    prevented" over zero points is zero counters, which is the card and not a
    failure. Nor when the creature has left — CR 603.7c's object is addressed by
    the id that survives it, and a permanent that came back is a different one
    (CR 400.7).
    """
    recorded = context.trigger_context or {}
    shield = recorded.get(PREVENTION_SHIELD_RESULT)
    prevented = int(getattr(shield, "prevented", 0) or 0)
    permanent_id = recorded.get(PREVENTION_SHIELD_TARGET_RESULT)
    card_name = getattr(context.card, "name", "an effect")
    if prevented <= 0 or not isinstance(permanent_id, int):
        game.log.append(f"{card_name}: no damage was prevented this way")
        return True, "resolved"
    permanent = game.permanent_by_id(permanent_id)
    if permanent is None:
        game.log.append(f"{card_name}: the creature it shielded is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+0/+1"))
    placed = game.place_pt_counters(permanent, counter, prevented)
    if placed:
        game.log.append(
            f"{card_name}: {permanent.card.name} gets {placed} {counter} "
            f"counter{'s' if placed != 1 else ''}"
        )
    return True, "resolved"


@effect_handler("grant_reverse_damage_shield")
def grant_reverse_damage_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Reverse Damage: arm a one-shot shield against "a source of your choice".

    The caster picks the source — a permanent on any battlefield (chosen via
    target_permanent_index) or a spell on the stack (the threatening burn spell,
    chosen via stack_target). Only damage from that source is prevented and gained
    as life. With no chosen source (AI / headless casts), fall back to a generic
    charge that shields the entire next damage event from any source.
    """
    caster = context.caster
    chosen = None
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
    granted_by = context.card.name if context.card else None
    if chosen is not None:
        add_shield(caster, make_life_gain_source(chosen, granted_by))
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name} armed a Reverse Damage shield against {getattr(source_card, 'name', 'a source')}"
        )
    else:
        add_shield(caster, make_life_gain_charge(granted_by))
        game.log.append(f"{caster.name} armed a Reverse Damage shield")
    return True, "resolved"


@effect_handler("grant_whole_prevention_shield")
def grant_whole_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pentagram of the Ages: "The next time a source of your choice would deal
    damage to you this turn, prevent that damage."

    The same choice the two shields below and above it make — a permanent on any
    battlefield, or a spell on the stack matched by the ``CardDefinition`` it
    will deal its damage with — because it is the same printed phrase (CR
    615.8). What differs is only what happens after the prevention, which here
    is nothing: Reverse Damage's sentence continues and this one stops.

    ``from_source`` is the third way the sentence names its source: not chosen
    at all, but printed — "The next time **this creature** would deal damage to
    you this turn" (Mercenaries). One payload key rather than a kind of its own,
    because the shield it arms is the same whole-instance shield; only where the
    source comes from differs.

    The shield goes on ``caster`` either way, and on this card that is not the
    permanent's controller: Mercenaries prints "Any player may activate this
    ability", so the seat that paid is the seat protected (CR 109.5).
    """
    caster = context.caster
    granted_by = context.card.name if context.card else None
    if instruction.payload.get("from_source"):
        source_perm = context.source_permanent
        if source_perm is None:
            game.log.append(f"{granted_by}: its own source is gone")
            return True, "resolved"
        add_shield(caster, make_whole_source(source_perm, granted_by))
        game.log.append(
            f"{caster.name} will prevent the next damage {source_perm.card.name} "
            "would deal them"
        )
        return True, "resolved"
    if context.stack_target is not None:
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(
            game, context, predicate=lambda p: True, fallback_players=()
        )
    if chosen is not None:
        add_shield(caster, make_whole_source(chosen, granted_by))
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name} will prevent the next damage from "
            f"{getattr(source_card, 'name', 'a source')}"
        )
    else:
        add_shield(caster, make_whole_charge(granted_by))
        game.log.append(f"{caster.name} will prevent the next damage dealt to them")
    return True, "resolved"


@effect_handler("grant_half_prevention_shield")
def grant_half_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Dark Sphere: "The next time a source of your choice would deal damage to
    you this turn, prevent half that damage, rounded down."

    The same choice Reverse Damage's shield makes — a permanent on any
    battlefield, or a spell on the stack matched by the CardDefinition it will
    deal its damage with — because it is the same printed phrase (CR 615.8).
    What differs is only what the shield absorbs, and that is the shield's own
    arithmetic rather than anything decided here: half of an event nobody can
    size yet.
    """
    caster = context.caster
    rounding = str(instruction.payload.get("half", "down"))
    granted_by = context.card.name if context.card else None
    if context.stack_target is not None:
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(
            game, context, predicate=lambda p: True, fallback_players=()
        )
    if chosen is not None:
        add_shield(caster, make_half_source(chosen, rounding, granted_by))
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name} will prevent half the next damage from "
            f"{getattr(source_card, 'name', 'a source')}"
        )
    else:
        add_shield(caster, make_half_charge(rounding, granted_by))
        game.log.append(f"{caster.name} will prevent half the next damage dealt to them")
    return True, "resolved"


@effect_handler("grant_forcefield_shield")
def grant_forcefield_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Honor the chosen unblocked attacker so only that creature's combat damage is
    # capped to 1. Fall back to a generic "next combat damage" cap for AI/headless
    # activations that supply no target.
    chosen = resolve_target_permanent(game, context, fallback_players=())
    if chosen is not None:
        add_shield(caster, make_capped_source(chosen))
        game.log.append(f"Forcefield will prevent all but 1 combat damage from {chosen.card.name}")
    else:
        add_shield(caster, make_capped_charge())
        game.log.append("Forcefield shield granted")
    return True, "resolved"


@effect_handler("redirect_one_damage_to_owner")
def redirect_one_damage_to_owner(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
        source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
    ) + 1
    game.log.append(f"{card.name} will redirect next 1 damage to its owner")
    return True, "resolved"


@effect_handler("jade_monolith_redirect")
def jade_monolith_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Jade Monolith: "The next time a source of your choice would deal damage to
    target creature this turn, that source deals that damage to you instead."

    The controller chooses the target creature (target_permanent_index on the
    target player's battlefield) AND the damage source (choices["chosen_source"]: a
    battlefield permanent or a stack spell's card). The next damage that source
    would deal to the creature is redirected to the controller; with no recorded
    source choice (AI/legacy activations) any source's damage is redirected.
    """
    caster = context.caster
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        caster_idx = game.players.index(caster)
        target_creature.metadata["redirect_damage_to_player"] = caster_idx
        chosen_source = context.choices.get("chosen_source")
        if chosen_source is not None:
            target_creature.metadata["redirect_damage_source"] = chosen_source
            source_name = getattr(getattr(chosen_source, "card", chosen_source), "name", "source")
            game.log.append(
                f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}"
                f" (source: {source_name})"
            )
        else:
            target_creature.metadata.pop("redirect_damage_source", None)
            game.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
    return True, "resolved"


@effect_handler("shield_target_land_from_destruction")
def shield_target_land_from_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pyramids mode 2: "The next time target land would be destroyed this
    turn, remove all damage marked on it instead." Arms a one-shot shield the
    destroy paths consume via _consume_land_destruction_shield."""
    card = context.card
    target_land = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.card.primary_type == "land",
        fallback_players=(context.caster, context.target),
    )
    if target_land is None:
        game.log.append(f"{card.name}: no valid land target")
        return True, "resolved"
    target_land.metadata["land_destruction_shield_this_turn"] = True
    game.log.append(
        f"{card.name}: the next time {target_land.card.name} would be destroyed this turn, "
        "all damage marked on it is removed instead"
    )
    return True, "resolved"


@effect_handler("arm_mirror_damage")
def arm_mirror_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Eye for an Eye: the next damage dealt to you this turn by "a source of
    your choice" also hits that source's controller for the same amount.

    Mirrors Reverse Damage's shape: the caster picks the source — a permanent on
    any battlefield (target_permanent_index) or a spell on the stack
    (stack_target) — and only damage from that source is mirrored, matched by
    identity in _deal_damage_to_player. With no chosen source (AI / headless
    casts) fall back to a generic charge that mirrors the next damage event from
    any source."""
    caster = context.caster
    if context.stack_target is not None:
        # A spell on the stack: match later by its card identity (the same
        # CardDefinition the spell deals damage with when it resolves).
        chosen = context.stack_target.card
    else:
        chosen = resolve_target_permanent(game, context, predicate=lambda p: True, fallback_players=())
    if chosen is not None:
        caster.mirror_damage_sources.append(chosen)
        source_card = getattr(chosen, "card", chosen)
        game.log.append(
            f"{caster.name}: the next damage {getattr(source_card, 'name', 'a source')} "
            f"deals to them this turn is mirrored to its controller ({context.card.name})"
        )
    else:
        caster.mirror_damage_charges += 1
        game.log.append(
            f"{caster.name}: the next damage dealt to them this turn is mirrored "
            f"to its source's controller ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("grant_source_class_prevention_shield")
def grant_source_class_prevention_shield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Al-abara's Carpet: "Prevent all damage that would be dealt to you this
    turn by attacking creatures without flying."

    One :class:`~engine.shields.Shield` on the ability's controller carrying the
    printed noun phrase, so this needs no field on ``PlayerState`` and no
    clearing line in a turn step — the sweep reads its ``lifetime``.

    The *set* of sources is deliberately not captured: the phrase is re-matched
    when damage would be dealt (CR 615.9), so a creature that attacks after this
    resolves is covered and one that gains flying in the meantime is not.
    """
    caster = context.caster
    described = dict(instruction.payload.get("filter") or {})
    seat = game.players.index(caster)
    source_name = context.card.name if context.card else None
    add_shield(caster, make_subject_shield(described, seat, source_name))
    game.log.append(
        f"{caster.name} is shielded this turn from damage dealt by matching "
        f"sources ({source_name})"
    )
    return True, "resolved"


@effect_handler("prevent_damage_to_target_until_eot")
def prevent_damage_to_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all damage that would be dealt to it this turn." (Glyph of
    Destruction.)

    The recipient half of ``prevent_damage_by_target_until_eot``, and a separate
    instruction for the reason that one's docstring gives in the other
    direction: a creature that cannot be hurt and a creature that cannot hurt
    anything are different cards, and one flag covering both would make either
    card's creature untouchable in combat.

    "It" is whatever the sentence in front of this one named — the chosen target
    if the spell chose one, and otherwise the ability's own source. The printed
    pronoun cannot say which, so the referent is resolved here where both are
    known rather than guessed at compile time.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention import (
        COMBAT_SHIELD_BOTH, COMBAT_SHIELD_TO, add_directional_shield,
    )

    combat_only = bool(instruction.payload.get("combat_only"))
    # "…dealt **to and dealt by** that creature this turn" (Ebony Horse, Maze
    # of Ith). The printed sentence puts one object on both ends of the event,
    # which is a *direction* the shield reader already answers for — so it is
    # this instruction with one payload key rather than a second kind. The word
    # is what separates Maze of Ith from Awe Strike: one creature is harmless
    # as well as unhurt, the other only unhurt.
    both_ends = bool(instruction.payload.get("to_and_by"))
    direction = COMBAT_SHIELD_BOTH if both_ends else COMBAT_SHIELD_TO
    # "…this turn" (Maze of Ith) or "…**this combat**" (Winter's Chill). The
    # window is payload, so the shield ends where the card says rather than
    # where the only sweep that existed happened to run.
    from ..shields import END_OF_COMBAT, END_OF_TURN

    lifetime = (
        END_OF_COMBAT
        if instruction.payload.get("duration") == "end_of_combat"
        else END_OF_TURN
    )

    def arm(permanent) -> None:
        add_directional_shield(
            permanent, direction, combat_only=combat_only, lifetime=lifetime,
        )
        game.log.append(
            f"all {'combat ' if combat_only else ''}damage that would be dealt "
            "to " + ("and dealt by " if both_ends else "")
            + f"{permanent.card.name} "
            + ("this combat" if lifetime == END_OF_COMBAT else "this turn")
            + f" is prevented ({context.card.name})"
        )

    # "Untap any number of target creatures. Prevent all combat damage that
    # would be dealt to and dealt by **those creatures** this turn." (Energy
    # Arc.) A *set* rather than one recipient, and the set is whatever an
    # earlier step of this same effect recorded — CR 611.2c fixed it when the
    # effect began, and the record is the only place it can be read from now.
    # The shield is the same shield armed several times, which is what makes
    # this a payload key rather than a second kind.
    #
    # By id, because a permanent may have left in between: a returning one is a
    # new object (CR 400.7) that this effect never named, so it is simply not
    # shielded. An empty record is a legal outcome — the spell may name no
    # targets at all — not an error.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        recorded = (context.results or {}).get(str(recorded_key)) or ()
        if isinstance(recorded, int):
            recorded = (recorded,)
        shielded = 0
        for permanent_id in recorded:
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                continue
            arm(permanent)
            shielded += 1
        if not shielded:
            game.log.append(f"{context.card.name}: nothing was left to shield")
        return True, "resolved"
    # Through the innermost binding, so a shield printed inside a loop is armed
    # on the creature the iteration is on rather than on the first of the
    # resolution's targets (Winter's Chill). Outside a loop `bound_permanent`
    # *is* the target resolution this line has always done.
    perm = bound_permanent(game, context, predicate=lambda p: p.is_creature)
    if perm is None:
        perm = context.source_permanent
    if perm is None:
        game.log.append(f"{context.card.name}: no permanent to shield")
        return True, "resolved"
    arm(perm)
    return True, "resolved"


@effect_handler("lock_damage_to_target")
def lock_damage_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Damage that would be dealt to that creature this turn can't be prevented
    or dealt instead to another permanent or player." (Whippoorwill.)

    The inverse of every other handler in this file: it arms nothing, it takes
    the machinery *away*. `damage_events.damage_candidates` is the one place a
    damage event's contention set is assembled, and it drops the contenders
    that prevent or move the damage when the recipient carries this marker — so
    a shield added later is covered without knowing the clause exists.

    "That creature" is the object the sentence in front of it targeted, so no
    target is chosen again and nothing is described for the picker.
    """
    from ..damage_events import DAMAGE_LOCK

    perm = resolve_target_permanent(
        game, context,
        predicate=lambda p: p.is_creature,
        fallback_on_invalid_choice=False,
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no creature to lock")
        return True, "resolved"
    perm.metadata[DAMAGE_LOCK] = True
    game.log.append(
        f"damage dealt to {perm.card.name} this turn can't be prevented or "
        f"redirected ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("prevent_damage_by_target_until_eot")
def prevent_damage_by_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Prevent all [combat] damage that would be dealt by target creature this
    turn." (Horn of Deafening, Lady Evangela, Kry Shield.)

    The printed word "combat" is payload, not a second kind: with it the shield
    sees combat damage alone, without it (Kry Shield) it sees the creature's
    ping abilities too. Dropping it would make Horn of Deafening the wider card
    it is not.

    A shield on the damage's **source**, not on a recipient: the creature is
    still perfectly able to be dealt combat damage and to die to it. That
    direction is what the marker carries, and it is why this is not Ebony
    Horse's two-way flag with a different name — folding them together would
    make every creature either card touches unkillable in combat.

    Cleared by the cleanup step through ``_EOT_METADATA_KEYS``, which is what
    "this turn" means here.
    """
    from ..prevention import COMBAT_SHIELD_BY, add_directional_shield

    combat_only = bool(instruction.payload.get("combat_only"))
    # Through the innermost binding, exactly as the recipient half above does
    # and for its reason: "**For each attacking red creature,** prevent all
    # combat damage that would be dealt by **that creature** this turn"
    # (Heroism) names a different creature each time round, and the sentence
    # chooses no target at all — so a read of the resolution's targets would
    # shield whichever creature a fallback happened to find.
    perm = bound_permanent(
        game, context,
        predicate=lambda p: p.is_creature,
        fallback_players=tuple(game.players),
    )
    if perm is None:
        game.log.append(f"{context.card.name}: no creature to silence")
        return True, "resolved"
    shielded = [perm]
    # "…by that creature **and each creature blocking it**." (Feint.) The second
    # printed source is a set named by a combat relation to the first, so it is
    # read from the combat maps at resolution rather than from any description:
    # a creature that started blocking after the spell was cast is one of them
    # (CR 611.2c fixes the set when the effect begins, which is now), and a
    # blocker of a *different* attacker is not.
    if instruction.payload.get("also_blocking_target"):
        for blocker in game.creatures_blocking(perm):
            if not any(blocker is already for already in shielded):
                shielded.append(blocker)
    for creature in shielded:
        add_directional_shield(creature, COMBAT_SHIELD_BY, combat_only=combat_only)
        game.log.append(
            f"all {'combat ' if combat_only else ''}damage {creature.card.name} "
            f"would deal this turn is prevented ({context.card.name})"
        )
    return True, "resolved"


@effect_handler("prevent_damage_from_targeting_sources_until_eot")
def prevent_damage_from_targeting_sources_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Silhouette: "Choose target creature. If a spell or ability that targets
    that creature would cause a source to deal damage to that creature this
    turn, prevent that damage."

    The spell's own chosen creature (CR 601.2c — the first sentence is the
    choosing) carries the shield, so nothing here re-reads the text or picks a
    creature of its own. With the target gone the spell simply does nothing,
    which is CR 608.2b rather than a failure.
    """
    target = resolve_target_permanent(game, context, fallback_players=())
    if target is None:
        game.log.append(f"{context.card.name}: its target is gone")
        return True, "resolved"
    add_shield(
        target,
        make_targeting_source_shield(context.card.name if context.card else None),
    )
    game.log.append(
        f"{target.card.name} is shielded from spells and abilities that target it"
    )
    return True, "resolved"
