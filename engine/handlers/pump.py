from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..pt import set_base_pt
from ._common import (
    apply_temp_pt_boost,
    attached_host,
    permanent_matches_filter,
    resolve_amount,
    resolve_target_permanent,
    resolve_target_permanents,
    resolve_target_slots,
    count_from_payload,
)
from .registry import effect_handler
from ..keywords import grant_keyword, remove_keyword

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("berserk_pump")
def berserk_pump(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_perm = resolve_target_permanent(game, context)
    if target_perm is not None:
        boost = target_perm.effective_power
        # "+X/+0 until end of turn" — apply now and track it so cleanup removes it
        # if the creature survives (Berserk only destroys it if it attacked).
        apply_temp_pt_boost(target_perm, boost)
        grant_keyword(target_perm, "trample", until_eot=True)
        # "At the beginning of the next end step, destroy that creature if it
        # attacked this turn." Mark it; the end step checks attacked_this_turn.
        target_perm.metadata["destroy_if_attacked_eot"] = True
        game.log.append(f"{card.name} pumped {target_perm.card.name} by +{boost}/+0 and granted trample")
    else:
        game.log.append(f"{card.name}: no valid creature target")
    return True, "resolved"


@effect_handler("pump_enchanted_creature")
def pump_enchanted_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    enchanted = source_permanent.metadata.get("attached_to")
    if enchanted is None:
        return False, "aura not attached to a creature"
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    apply_temp_pt_boost(enchanted, power_delta, toughness_delta)
    game.log.append(f"{card.name} grants {enchanted.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


@effect_handler("pump_self")
def pump_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # "…gets +X/+0 until end of turn, where X is the number of other attacking
    # creatures." (Alpine Houndmaster.) X is defined by a count taken at
    # resolution, through the one evaluator every computed amount shares — so
    # the same printed clause means the same number here as on a targeted pump.
    x_value = context.x_value
    x_count = instruction.payload.get("x_from_count")
    if x_count is not None:
        x_value = count_from_payload(game, context, x_count)
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    if instruction.payload.get("power_negative"):
        power_delta = -power_delta
    if instruction.payload.get("toughness_negative"):
        toughness_delta = -toughness_delta
    apply_temp_pt_boost(source_permanent, power_delta, toughness_delta)
    game.log.append(
        f"{card.name} gets {power_delta:+}/{toughness_delta:+} until end of turn"
    )
    return True, "resolved"


@effect_handler("pump_self_with_sacrifice_condition")
def pump_self_with_sacrifice_condition(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    apply_temp_pt_boost(source_permanent, 1)
    activation_count = int(source_permanent.metadata.get("pump_activation_count", 0)) + 1
    source_permanent.metadata["pump_activation_count"] = activation_count
    if activation_count >= 4:
        source_permanent.metadata["sacrifice_at_next_end_step"] = True
    game.log.append(
        f"{card.name} gets +1/+0 until end of turn (activation {activation_count})"
    )
    return True, "resolved"


@effect_handler("pump_target_creature_until_eot")
def pump_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    x_value = context.x_value
    # "…where X is the number of cards in your graveyard" (Liliana, Waker of
    # the Dead): X is defined by a zone count at resolution, not announced.
    # The sign travels separately because the payload's "x" cannot be negated.
    x_count = instruction.payload.get("x_from_count")
    if x_count is not None:
        # Through the one evaluator. This used to be a second counter with a
        # second spelling of the spec — hardcoded to the graveyard, reading
        # `card_types` where every other reader says `filter` — so the same
        # printed clause meant two things depending on the sentence around it.
        x_value = count_from_payload(game, context, x_count)
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    if instruction.payload.get("power_negative"):
        power_delta = -power_delta
    if instruction.payload.get("toughness_negative"):
        toughness_delta = -toughness_delta
    blocking_only = bool(instruction.payload.get("blocking_only"))

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        # Righteousness: the target must be a creature that is currently blocking.
        if blocking_only and not game._is_blocking_creature(perm):
            return False
        # The rest of the printed noun phrase. This asked only "is it a
        # creature?", so Ranger's Guile's "target creature **you control**"
        # pumped an opponent's creature — the pump half of the same card whose
        # keyword half had the identical hole.
        if not permanent_matches_filter(perm, filters):
            return False
        if filters.get("exclude_self") and perm is context.source_permanent:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(caster), perm
        ):
            return False
        return True

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(target, caster)
    )
    if target_perm is not None:
        apply_temp_pt_boost(target_perm, power_delta, toughness_delta)
        game.log.append(f"{card.name} gives {target_perm.card.name} +{power_delta}/+{toughness_delta} until end of turn")
    return True, "resolved"


#: What a "for as long as this permanent remains tapped" pump records on its
#: **source**: the pumped permanent's id and the boost. Read by
#: ``mixins/permanent_state._refresh_linked_tapped_pumps`` on every recompute.
#: One name, because the handler that writes it and the refresh that reads it
#: are in different files and a second spelling is how they come apart.
PUMP_WHILE_TAPPED_KEY = "pump_while_tapped"


@effect_handler("pump_target_while_source_tapped")
def pump_target_while_source_tapped(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ashnod's Battle Gear: "{2}, {T}: Target creature you control gets +2/-2
    for as long as this artifact remains tapped." Tawnos's Weaponry is the same
    card with a different boost.

    **Nothing is written onto the pumped creature.** The boost is recorded on
    the *source* and contributed by the derived-buff recompute while the source
    is tapped, so it ends the instant the source untaps — or leaves, or is
    untapped by something else mid-turn — and no cleanup step has to remember
    to subtract it. A delta on the target would be the Aspect of Wolf bug with
    a different trigger for the mismatch (`_add_static_pt`'s docstring).

    The record is keyed by ``permanent_id``, not by holding the Permanent:
    CR 400.7 makes a returning permanent a new object, and an id that no longer
    resolves simply contributes nothing.
    """
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    power_delta = resolve_amount(instruction.payload.get("power", 0), context.x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), context.x_value)
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        if not permanent_matches_filter(perm, filters):
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(caster), perm
        ):
            return False
        return True

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(context.target, caster)
    )
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"

    source_permanent.metadata[PUMP_WHILE_TAPPED_KEY] = {
        "target_id": target_perm.permanent_id,
        "power": power_delta,
        "toughness": toughness_delta,
    }
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{card.name} gives {target_perm.card.name} "
        f"{power_delta:+d}/{toughness_delta:+d} while it remains tapped"
    )
    return True, "resolved"


@effect_handler("pump_targets_until_eot")
def pump_targets_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, target creature gets +0/+2 and **another** target
    creature gets -2/-0." (Rookie Mistake.)

    One instruction rather than two pumps in a `sequence`, for the reason
    `_fused_prepare_then_interact` gives: the two clauses name *different* chosen
    objects, and every single-target handler in the engine resolves through
    `_one_choice`, which reads the first entry of the target list. Lowered as a
    sequence the card would compile cleanly and pump one creature twice.

    How many slots there are, and how big each boost is, is payload — the effect
    is one pump per slot and only the numbers differ.

    The slots are resolved **positionally** and each is checked against its own
    filter, because "target creature" and "another target creature" may
    legitimately sit on two battlefields. A slot that no longer answers is
    dropped and the rest of the effect still happens (CR 608.2b); a slot naming a
    permanent an earlier slot already took is dropped too, which is the
    resolution-time half of the printed "another" (the picker enforces the
    announcement half, CR 601.2c).
    """
    card = context.card
    slots = tuple(instruction.payload.get("slots") or ())
    targets = instruction.payload.get("targets") or {}
    slot_filters = targets.get("filters") or [targets.get("filter") or {}] * len(slots)
    distinct = bool(targets.get("distinct"))
    caster_index = game.players.index(context.caster)
    chosen = resolve_target_slots(game, context, len(slots))

    taken: list[Permanent] = []
    for index, permanent in enumerate(chosen):
        wanted = slot_filters[index] if index < len(slot_filters) else {}
        if permanent is None or not game.is_on_battlefield(permanent):
            game.log.append(f"{card.name}: nothing legal in slot {index + 1}")
            continue
        if not permanent.is_creature or not permanent_matches_filter(permanent, wanted):
            game.log.append(f"{card.name}: slot {index + 1} is no longer a legal target")
            continue
        # "you control" / "you don't control" are seat tests, which
        # permanent_matches_filter deliberately does not answer — the same split
        # prepare_then_interact makes.
        controller = wanted.get("controller")
        if controller == "you" and not game.controls(caster_index, permanent):
            continue
        if controller == "not_you" and game.controls(caster_index, permanent):
            continue
        if distinct and any(permanent is seen for seen in taken):
            game.log.append(
                f"{card.name}: slot {index + 1} named a creature an earlier slot already took"
            )
            continue
        taken.append(permanent)
        spec = slots[index]
        power = resolve_amount(spec.get("power", 0), context.x_value)
        toughness = resolve_amount(spec.get("toughness", 0), context.x_value)
        apply_temp_pt_boost(permanent, power, toughness)
        game.log.append(
            f"{card.name} gives {permanent.card.name} {power:+}/{toughness:+} until end of turn"
        )
    return True, "resolved"


# buff_creatures_global from a SPELL (sorcery/instant): locks in the set of
# affected creatures at resolution (611.2c). Uses power_bonus so it is NOT
# recalculated dynamically (unlike static abilities which use static_buff_*).
@effect_handler("buff_creatures_global")
def buff_creatures_global(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    card = context.card
    color_sym = instruction.payload.get("color")
    power_delta = int(instruction.payload.get("power", 0))
    toughness_delta = int(instruction.payload.get("toughness", 0))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    blocking_only = bool(instruction.payload.get("blocking_only"))
    # "**Other** creatures you control" (Bolt Hound) — CR 109.5's exclusion of
    # the ability's own source, which no per-permanent filter can test.
    exclude_self = (
        context.source_permanent
        if instruction.payload.get("exclude_self") else None
    )
    if instruction.payload.get("opponents_only"):
        # "Creatures your opponents control get -2/-2 until end of turn"
        # (Massacre Wurm): every opponent's board and none of the caster's.
        target_players = [
            game.players[i] for i in game.opponents_of(game.players.index(caster))
        ]
    else:
        target_players = game.players if instruction.payload.get("all") else [caster]
    for player in target_players:
        for perm in list(player.battlefield):
            if not perm.is_creature:
                continue
            if exclude_self is not None and perm is exclude_self:
                continue
            # Army of Allah: only creatures attacking at resolution are buffed.
            if attacking_only and not perm.attacking:
                continue
            # Piety: only creatures blocking at resolution are buffed.
            if blocking_only and not game._is_blocking_creature(perm):
                continue
            # `effective_colors` is layer 5 — which already reads the
            # override this used to patch on by hand, so the two-line
            # reimplementation below it was a second copy of one rule.
            if color_sym and color_sym not in perm.effective_colors:
                continue
            apply_temp_pt_boost(perm, power_delta, toughness_delta)
    game.log.append(f"{card.name} buffed matching creatures")
    return True, "resolved"


@effect_handler("grant_team_keyword_until_eot")
def grant_team_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Creatures you control gain flying until end of turn." (Basri, Devoted
    Paladin's −6.) The affected set locks in at resolution (CR 611.2c), which
    is why this walks the board now instead of contributing a derived buff.

    ``every_permanent`` widens the same grant to the whole board (Heroic
    Intervention's "Permanents you control gain hexproof and indestructible"):
    both keywords are asked of the permanent, not of the creature — hexproof is
    read by ``_can_be_targeted`` and indestructible by ``_is_indestructible``,
    neither of which cares what type it is — so the only thing that changes is
    who is in the loop."""
    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    granted = 0
    for perm in game.controlled_by(caster_index):
        if not every_permanent and not perm.is_creature:
            continue
        for keyword in keywords:
            grant_keyword(perm, keyword, until_eot=True)
        granted += 1
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {granted} {noun} gain {', '.join(keywords)} until end of turn"
    )
    return True, "resolved"


@effect_handler("grant_team_assign_unblocked_until_eot")
def grant_team_assign_unblocked_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Garruk, Savage Herald's −7: creatures you control gain "You may have
    this creature assign its combat damage as though it weren't blocked" until
    end of turn. The combat damage step reads the flag; cleanup clears it (the
    key is in _EOT_METADATA_KEYS)."""
    caster_index = game.players.index(context.caster)
    granted = 0
    for perm in game.controlled_by(caster_index):
        if perm.is_creature:
            perm.metadata["assign_combat_damage_as_unblocked_until_eot"] = True
            granted += 1
    game.log.append(
        f"{context.card.name}: {granted} creature(s) may assign combat damage as though unblocked"
    )
    return True, "resolved"


def place_loyalty_counters(permanent, count: int) -> int:
    """Put *count* loyalty counters on *permanent*; return the new total.

    CR 306.5c: a planeswalker's loyalty **is** its loyalty counters, so this is
    the one key damage marks against and a loyalty cost pays from. One function
    because there is now more than one way a counter arrives — the ability's own
    source, and a permanent its controller chose.
    """
    loyalty = int(permanent.metadata.get("loyalty_counters", 0)) + count
    permanent.metadata["loyalty_counters"] = loyalty
    return loyalty


@effect_handler("add_loyalty_counters")
def add_loyalty_counters(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a loyalty counter on Garruk." (Garruk, Unleashed's −2.) Loyalty on
    the battlefield IS its loyalty counters (CR 306.5c), the same key damage
    and loyalty costs adjust. The source may already have left — a walker that
    paid itself to 0 dies before its ability resolves — in which case the
    counter lands on nothing (CR 608.2b handles the analogous target)."""
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: its source has left, no loyalty added")
        return True, "resolved"
    count = int(instruction.payload.get("count", 1))
    total = place_loyalty_counters(source, count)
    game.log.append(
        f"{context.card.name}: {count} loyalty counter(s) added (now {total})"
    )
    return True, "resolved"


@effect_handler("add_loyalty_counters_to_chosen")
def add_loyalty_counters_to_chosen(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a loyalty counter on a Liliana planeswalker you control."
    (Liliana's Scrounger.)

    No "target" is printed, so nothing was chosen when the ability went on the
    stack (CR 115.1b): the controller picks now, out of what the noun phrase
    names *now* — the ``untap_up_to`` shape, not the targeted one. Reading it as
    a target would move the choice to announcement and let the ability be
    countered on resolution (CR 608.2b) when the walker it named has left, where
    the printed card would simply pick another.

    One candidate is not a choice and is applied at once; several arm the
    prompt; none does nothing, because "a Liliana planeswalker you control" can
    name an empty set and the ability still resolves.
    """
    # Imported here rather than at module scope: engine/subject_filters.py
    # imports handlers._common, so a module-level import would close the cycle
    # through engine/handlers/__init__.py. Same reason engine/oracle.py imports
    # it inside _resolve_subject_groups.
    from ..subject_filters import subject_matches

    seat = game.players.index(context.caster)
    described = dict(instruction.payload.get("filter") or {})
    count = int(instruction.payload.get("count", 1))
    source = context.source_permanent
    candidates = [
        perm
        for perm in game.all_permanents()
        if subject_matches(game, perm, described, observer=seat, source=source)
    ]
    if not candidates:
        game.log.append(
            f"{context.card.name}: nothing it controls can receive a loyalty counter"
        )
        return True, "resolved"
    if len(candidates) == 1:
        total = place_loyalty_counters(candidates[0], count)
        game.log.append(
            f"{context.card.name}: {count} loyalty counter(s) on "
            f"{candidates[0].card.name} (now {total})"
        )
        return True, "resolved"
    game.arm_pending_choice(
        "loyalty_recipient", seat,
        card_name=context.card.name,
        count=count,
        filter=described,
        _candidates=candidates,
        _source=source,
    )
    return True, "resolved"


@effect_handler("add_power_counters_to_self")
def add_power_counters_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{X}, {T}: Put up to X +1/+0 counters on this creature. This ability
    can't cause the total number of +1/+0 counters on this creature to be
    greater than N." — Clockwork Beast (seven) and Clockwork Avian (four).

    The cap is on the payload. It used to be the constant 7 in this function
    and the word "seven" inside a card-name-keyed hook's dictionary key, which
    is two copies of one number and the reason the Avian needed a second entry
    to say four.
    """
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    amount = instruction.payload.get("amount", 0)
    requested = context.x_value or 0 if amount == "x" else int(amount)
    cap = int(instruction.payload.get("cap", 0))
    current = int(source_permanent.metadata.get("plus_1_0_counters", 0))
    added = min(max(0, requested), max(0, cap - current))
    if added:
        # Through the counter seam rather than the two channels by hand: the
        # cap above reads the record, so a placement that wrote only
        # `power_bonus` would let the ability run past its own limit, and a
        # direct `power_bonus` poke is the P/T write `engine/pt.py` exists to
        # keep in one place.
        game.place_pt_counters(source_permanent, "+1/+0", added)
    game.log.append(f"{card.name} gets {added} +1/+0 counter(s)")
    return True, "resolved"


@effect_handler("add_plus1_counters_for_each_creature_died")
def add_plus1_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Khabál Ghoul: "At the beginning of each end step, put a +1/+1 counter on
    this creature for each creature that died this turn." Resolves off the stack;
    the death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    game.place_plus1_counters(source, count)
    game.log.append(f"{source.card.name} gets {count} +1/+1 counter(s)")
    return True, "resolved"


@effect_handler("add_counter_to_self")
def add_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # "…put **that many** +1/+1 counters on this creature." (Tetravus.) The
    # count is a back-reference to what the step before it recorded; absent, the
    # payload means one, which is what every earlier caller emitted.
    raw_count = instruction.payload.get("count", 1)
    if raw_count == "trigger_count":
        count = int(context.results.get("trigger_count", 0))
    else:
        count = int(raw_count)
    if count <= 0:
        return True, "resolved"
    game.place_plus1_counters(source_permanent, count)
    game.log.append(
        f"{card.name} gets a +1/+1 counter" if count == 1
        else f"{card.name} gets {count} +1/+1 counters"
    )
    return True, "resolved"


@effect_handler("grant_keyword_to_attached")
def grant_keyword_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…and that creature gains flying." (Cocoon's hatch, bound to the
    enchanted creature.)

    A one-shot grant with no printed duration: CR 611.2c makes it last as long
    as the creature, so it is recorded on the *creature* through the layer-6
    write API — never derived from the Aura, which this same resolution has
    just sacrificed. ``attached_host`` supplies the last-known host for
    exactly that reason (CR 603.10).
    """
    host = attached_host(game, context.source_permanent)
    if host is None:
        game.log.append(f"{context.card.name}: nothing is enchanted to grant to")
        return True, "resolved"
    keyword = str(instruction.payload.get("keyword", ""))
    grant_keyword(host, keyword)
    game._refresh_dynamic_creatures()
    game.log.append(f"{context.card.name}: {host.card.name} gains {keyword}")
    return True, "resolved"


@effect_handler("add_pt_counters_to_attached")
def add_pt_counters_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever enchanted creature becomes tapped, put a -0/-2 counter on it."
    (Spirit Shackle.)

    The recipient is the permanent this Aura is attached to — no target was
    chosen, because an Aura's effect on its own host never offers one — and the
    counter's kind is payload, so any CR 122.1a pair the grammar reads lands
    here without a second handler.

    Through ``place_pt_counters``: a counter placed by poking the P/T channels
    is a counter no sweep can find, which is what Unstable Mutation's upkeep
    pass did under a comment promising that 704.5q applied to it.
    """
    attached = attached_host(game, context.source_permanent)
    if attached is None:
        return True, "resolved"
    kind = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    placed = game.place_pt_counters(attached, kind, count)
    if placed:
        game.log.append(
            f"{context.card.name}: {attached.card.name} gets "
            + (f"a {kind} counter" if placed == 1 else f"{placed} {kind} counters")
        )
    return True, "resolved"


@effect_handler("add_counter_to_target")
def add_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on target creature", and on *each of up to N* target
    creatures.

    The kind Dwarven Weaponsmith's hook has always emitted (it resolved to
    nothing before this handler existed) and the grammar now lowers to as well.
    How many targets it takes is payload rather than a second instruction kind,
    because the effect is identical and only the count differs — the same reason
    a combat restriction carries its land type as data.

    The two counts take different resolvers on purpose. One target falls back to
    scanning when the chosen one is gone, which is the behaviour every
    single-target handler in the engine has; several are resolved strictly, so a
    dead target is dropped (CR 608.2b) rather than replaced by whichever creature
    the scan reached first — twice, if two slots decayed.
    """
    card = context.card
    targets = instruction.payload.get("targets") or {}
    maximum = targets.get("count") if isinstance(targets, dict) else None

    if isinstance(maximum, int) and maximum > 1:
        filters = targets.get("filter") or {}
        # The filter decides which permanents qualify, including "you control" —
        # asking it rather than assuming the caster's side is what keeps
        # "up to two target creatures" (Basri's Aegis, either side) and "up to
        # two other target creatures you control" (Basri's Acolyte) one handler.
        source = context.source_permanent

        def eligible(perm) -> bool:
            if not permanent_matches_filter(perm, filters):
                return False
            # "other" (CR 109.5's exclusion of the source) and "you control" are
            # both outside permanent_matches_filter's vocabulary — it answers
            # about a permanent alone, and these two need the source and the
            # board — so they are asked here rather than widened into it.
            if filters.get("exclude_self") and perm is source:
                return False
            if filters.get("controller") == "you" and not game.controls(context.caster, perm):
                return False
            return True

        chosen = resolve_target_permanents(game, context, predicate=eligible)
        if not chosen:
            # "Up to two" may legally name none, and every named target may have
            # become illegal since (CR 608.2b) — both resolve to nothing here.
            game.log.append(f"{card.name}: no creatures were given counters")
            return True, "resolved"
        for creature in chosen[:maximum]:
            game.place_plus1_counters(creature)
            game.log.append(f"{creature.card.name} gets a +1/+1 counter ({card.name})")
        return True, "resolved"

    filters = instruction.payload.get("targets", {}).get("filter") or {}

    source = context.source_permanent

    def counter_target_legal(perm) -> bool:
        # "target creature with a +1/+1 counter on it" (Tempered Veteran): the
        # counter restriction is enforced at resolution too, so the fallback
        # scan can never land on a counterless creature.
        #
        # The seat and identity questions are asked here too, which they were
        # not — the several-target branch fifty lines above asks all three, and
        # the two branches of one handler disagreeing is how Pridemalkin,
        # Invigorating Surge and Basri's Lieutenant all put their "+1/+1 counter
        # on target creature **you control**" onto an opponent's creature.
        if not perm.is_creature or not permanent_matches_filter(perm, filters):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    target_creature = resolve_target_permanent(game, context, predicate=counter_target_legal)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    game.place_plus1_counters(target_creature)
    game.log.append(f"{target_creature.card.name} gets a +1/+1 counter ({card.name})")
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) Read *after* the placement, so the one just put down
    # is doubled too — and placed through the same seam, so a Conclave Mentor
    # raises the doubling exactly as it raised the first counter (CR 614).
    if instruction.payload.get("then_double"):
        existing = int(target_creature.metadata.get("plus_counters", 0))
        if existing:
            game.place_plus1_counters(target_creature, existing)
            game.log.append(
                f"{target_creature.card.name}'s +1/+1 counters doubled to "
                f"{target_creature.metadata.get('plus_counters', 0)} ({card.name})"
            )
    return True, "resolved"


@effect_handler("double_target_power_until_eot")
def double_target_power_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Double the power of target creature until end of turn." (Unleash Fury.)

    The power is read at resolution and added as an until-end-of-turn boost, so
    doubling a 3/3 that a Giant Growth already pumped doubles the *six*, not the
    printed three — which is what "double" means and what an amount fixed when
    the spell was cast could not express.
    """
    card = context.card
    target_creature = resolve_target_permanent(
        game, context, predicate=lambda perm: perm.is_creature
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    power = target_creature.effective_power
    if power <= 0:
        # Doubling nothing (or a negative power) adds nothing: CR 107.1b has no
        # negative power on the battlefield, and +0/+0 is not worth logging as
        # an effect that happened.
        game.log.append(f"{card.name}: {target_creature.card.name} has no power to double")
        return True, "resolved"
    apply_temp_pt_boost(target_creature, power, 0)
    game.log.append(
        f"{card.name} doubled {target_creature.card.name}'s power to "
        f"{target_creature.effective_power}"
    )
    return True, "resolved"


@effect_handler("add_counter_to_each_you_control")
def add_counter_to_each_you_control(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on each creature you control." (Basri's
    Solidarity.) Read through the control seam, so a borrowed creature counts
    and a lost one does not."""
    card = context.card
    caster = context.caster
    for perm in game.controlled_by(caster):
        if not perm.is_creature:
            continue
        game.place_plus1_counters(perm)
    game.log.append(f"{card.name}: each creature {caster.name} controls gets a +1/+1 counter")
    return True, "resolved"


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    grant_keyword(source_permanent, "flying", until_eot=True)
    game.log.append(f"{card.name} gains flying until end of turn")
    return True, "resolved"


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        game.log.append(f"{target_creature.card.name} gains flying until end of turn from {card.name}")
    return True, "resolved"


@effect_handler("grant_target_keyword_until_eot")
def grant_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target creature gains <keyword(s)> until end of turn." The payload
    carries the words; the lowering admits only implemented keywords, so a
    grant here always grants behaviour that exists.

    The printed noun phrase is enforced here as well as at announcement. It was
    not: this handler resolved with the default "is it a creature?" predicate and
    read no filter at all, so Ranger's Guile's "target creature **you control**"
    handed +1/+1 and hexproof to an opponent's creature, and Selfless Savior's
    "**another**" excluded nothing. The same three questions
    ``add_counter_to_target``'s several-target branch already asks, for the same
    reason — a picker and a resolution that disagree are a target the player may
    announce and the effect then declines to affect.
    """
    card = context.card
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    source = context.source_permanent

    def grant_target_legal(perm) -> bool:
        if not perm.is_creature or not permanent_matches_filter(perm, filters):
            return False
        # "another" (CR 109.5's source exclusion) and "you control" are identity
        # and seat questions, which permanent_matches_filter deliberately does
        # not answer — it is about one permanent alone.
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    target_creature = resolve_target_permanent(
        game, context, predicate=grant_target_legal
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        _grant_one_keyword(game, target_creature, keyword, context)
    game.log.append(
        f"{target_creature.card.name} gains {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


def _grant_one_keyword(game, permanent, keyword: str, context) -> None:
    """Put one granted keyword where its reader will find it.

    Layer 6 holds a *word*, and "protection from black" is not one — it is the
    keyword `protection` carrying a quality, which `_protection_qualities` reads
    from its own channel. That channel has existed since protection was written,
    with a comment saying no card in the pool used it yet; Feat of Resistance is
    that card.

    "The color of your choice" is resolved here because CR 609.3 makes the
    choice part of the *resolution*. An unanswered choice grants nothing rather
    than defaulting to a colour: a protection the player did not pick is a
    protection from the wrong things, and doing nothing is the honest failure.
    """
    from ..grammar.phrases import PROTECTION_FROM_CHOSEN_COLOR

    if not keyword.startswith("protection from "):
        grant_keyword(permanent, keyword, until_eot=True)
        return
    if keyword == PROTECTION_FROM_CHOSEN_COLOR:
        symbol = game._normalize_mana_color((context.choices or {}).get("new_color"))
        if symbol is None:
            game.log.append(
                f"{context.card.name}: no colour was chosen, so nothing is protected from"
            )
            return
        word = _COLOR_SYMBOL_TO_WORD.get(symbol)
    else:
        word = keyword[len("protection from "):].strip()
    if word:
        permanent.metadata[f"protection_from_{word}"] = True


_COLOR_SYMBOL_TO_WORD = {
    "W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
}


@effect_handler("remove_target_keyword_until_eot")
def remove_target_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"It loses indestructible until end of turn." (Soul Sear — the pronoun
    binds the damage sentence's target.) `remove_keyword` puts the removal
    into layer 6, so it beats an older grant by timestamp and expires at
    cleanup with everything else until-end-of-turn."""
    card = context.card
    # The damage target may be a planeswalker, so no creature predicate: the
    # removal reaches whatever permanent the spell chose.
    target = resolve_target_permanent(game, context, predicate=lambda p: True)
    if target is None:
        game.log.append(f"{card.name}: no valid target to strip")
        return True, "resolved"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        remove_keyword(target, keyword, until_eot=True)
    game.log.append(
        f"{target.card.name} loses {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


@effect_handler("grant_self_keyword_until_eot")
def grant_self_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"This creature gains <keyword(s)> until end of turn." (Fetid Imp.)"""
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    keywords = tuple(instruction.payload.get("keywords") or ())
    for keyword in keywords:
        _grant_one_keyword(game, source_permanent, keyword, context)
    game.log.append(
        f"{card.name} gains {' and '.join(keywords)} until end of turn"
    )
    return True, "resolved"


@effect_handler("grant_islandwalk_and_linked_destroy")
def grant_islandwalk_and_linked_destroy(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sandals of Abdallah: "Target creature gains islandwalk until end of
    turn. When that creature dies this turn, destroy this artifact." The grant
    is an until-end-of-turn layer-6 grant; the death link is recorded on the
    creature and drained by _permanent_to_graveyard + the state-based sweep."""
    card = context.card
    source_permanent = context.source_permanent
    target_creature = resolve_target_permanent(game, context)
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    grant_keyword(target_creature, "islandwalk", until_eot=True)
    if source_permanent is not None:
        links = target_creature.metadata.setdefault("on_death_destroy_permanents", [])
        if source_permanent not in links:
            links.append(source_permanent)
    game.log.append(f"{target_creature.card.name} gains islandwalk until end of turn ({card.name})")
    return True, "resolved"


@effect_handler("set_base_pt_target_until_eot")
def set_base_pt_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sorceress Queen ("has base power and toughness 0/2") / Singing Tree
    ("has base power 0", toughness untouched). ``payload["toughness"]`` is
    None when the ability only sets power."""
    card = context.card
    source_permanent = context.source_permanent
    exclude_self = bool(instruction.payload.get("exclude_self"))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    flying_only = bool(instruction.payload.get("flying_only"))

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        if exclude_self and source_permanent is not None and perm is source_permanent:
            return False
        if attacking_only and not perm.attacking:
            return False
        if flying_only and not game._has_keyword(perm, "flying"):
            return False
        return True

    target_perm = resolve_target_permanent(game, context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"

    power = instruction.payload.get("power")
    toughness = instruction.payload.get("toughness")
    set_base_pt(target_perm, power, toughness, until_eot=True)
    if toughness is None:
        game.log.append(f"{card.name}: {target_perm.card.name} has base power {power} until end of turn")
    else:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base power and toughness {power}/{toughness} until end of turn"
        )
    return True, "resolved"


@effect_handler("grant_flying_and_delayed_destruction")
def grant_flying_and_delayed_destruction(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    def _is_legal(perm) -> bool:
        return (
            perm.is_creature
            and perm.effective_toughness < source_permanent.effective_power
        )

    # Honor the player-chosen creature (Stone Giant targets "target creature you
    # control with toughness less than this creature's power"). Fall back to the
    # first legal creature only for AI/untargeted activations — an explicitly
    # chosen illegal target fizzles.
    target_creature = resolve_target_permanent(
        game, context, player=caster, predicate=_is_legal, fallback_on_invalid_choice=False
    )
    if target_creature is not None:
        grant_keyword(target_creature, "flying", until_eot=True)
        target_creature.metadata["destroy_at_next_end_step"] = True
        game.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
    else:
        game.log.append("No valid target for Stone Giant effect")
    return True, "resolved"


@effect_handler("set_team_base_pt_until_eot")
def set_team_base_pt_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, creatures you control have base power and toughness
    X/X, where X is the number of cards in your hand." (Jolrael, Mwonvuli
    Recluse.)

    CR 613 layer 7b applied to a *set* rather than to a chosen permanent, which
    is why it is its own kind: the targeted handler beside it asks a picker which
    permanent, and this one asks the board which permanents.

    **X is fixed once, as the ability resolves.** CR 608.2's value is calculated
    on resolution and does not track the hand afterwards — drawing a card later
    in the turn does not grow the team, and a continuous recompute would say it
    does. That is the whole reason the amount is resolved here and stamped,
    rather than carried as a spec for the layer refresh to re-evaluate.

    The set is snapshotted for the same reason: a creature entering after this
    resolves was never affected (CR 611.2c).
    """
    x_value = context.x_value
    x_count = instruction.payload.get("x_from_count")
    if x_count is not None:
        x_value = count_from_payload(game, context, x_count)
    power = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    seat = game.players.index(context.caster)
    affected = [perm for perm in game.controlled_by(seat) if perm.is_creature]
    for perm in affected:
        set_base_pt(perm, power, toughness, until_eot=True)
    game.log.append(
        f"{context.card.name}: {len(affected)} creature(s) have base power and "
        f"toughness {power}/{toughness} until end of turn"
    )
    return True, "resolved"
