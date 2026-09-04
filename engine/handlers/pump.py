from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..pt import add_pt_modifier, set_base_pt
from ._common import (
    apply_temp_pt_boost,
    bound_permanent,
    block_pair_permanents,
    attached_host,
    frozen_that_player_seat,
    permanent_matches_filter,
    resolve_amount,
    resolve_target_permanent,
    resolve_target_permanents,
    resolve_target_slots,
    count_from_payload,
)
from .registry import effect_handler
from ..keywords import grant_keyword, remove_keyword
from ..oracle_types import ATTACHED_PERMANENT_CONTROLLER, COUNTERS_PLACED_THIS_WAY

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
        grant_keyword(target_perm, "trample", duration="end_of_turn")
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
    # "…gets +2/+0 …" with no duration printed (Goblin Ski Patrol) is CR
    # 611.2b's modification that lasts indefinitely — the *persistent* layer-7c
    # channel, the one a +1/+1 counter writes to, rather than a boost some
    # sweep takes back. Named in the payload rather than inferred from its
    # absence: every payload written before this key means end of turn, which
    # is what the default keeps saying.
    if str(instruction.payload.get("duration") or "") == "indefinite":
        add_pt_modifier(source_permanent, power_delta, toughness_delta)
        game.log.append(f"{card.name} gets {power_delta:+}/{toughness_delta:+}")
        return True, "resolved"
    apply_temp_pt_boost(source_permanent, power_delta, toughness_delta)
    game.log.append(
        f"{card.name} gets {power_delta:+}/{toughness_delta:+} until end of turn"
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
    # Function-level, like every other handler that reads a noun phrase: the
    # module graph runs card_loader -> oracle -> subject_filters -> handlers.
    from ..subject_filters import subject_matches

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
        #
        # Through ``subject_matches``, **not** the pure matcher and its two
        # hand-written seat tests. Those covered `controller` and `exclude_self`
        # and nothing else relative, so a *relation* in the phrase was carried
        # by the payload and tested by nobody: "target green creature
        # **blocking this creature**" (Barbed-Back Wurm) would have shrunk any
        # green creature on the table. One reader, with CR 109.5's observer and
        # the ability's own source, is what keeps the list the picker offers
        # and the set this shrinks the same list.
        # "target creature **defending player controls**" (Yare). The seat the
        # trigger's announcement froze if there is one (CR 603.10), and
        # otherwise the live combat's — a spell is resolving inside the combat
        # it names, and outside combat there is no defending player at all
        # (CR 506.2), which makes the phrase match nothing.
        defending = (context.trigger_context or {}).get(
            "trigger_defending_player_index"
        )
        if not isinstance(defending, int):
            defending = game.defending_player_index_now()
        return subject_matches(
            game, perm, filters,
            observer=game.players.index(caster),
            source=context.source_permanent,
            defending=defending,
        )

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(target, caster)
    )
    if target_perm is not None:
        # "…until end of combat" (Glyph of Destruction) is the same boost on a
        # different channel, so it is payload rather than a second kind — the
        # word decides which sweep takes it back. Absent means end of turn,
        # which is what every payload written before the channel table meant.
        until = str(instruction.payload.get("duration") or "end_of_turn")
        apply_temp_pt_boost(target_perm, power_delta, toughness_delta, until=until)
        game.log.append(
            f"{card.name} gives {target_perm.card.name} "
            f"+{power_delta}/+{toughness_delta} until "
            + until.replace("_", " ")
        )
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
    # "…get +1/+1 until end of turn **for each attacking creature other than
    # Márton Stromgald**." The printed P/T sizes one repetition and the count
    # multiplies it — the same `times_x` amount and the same shared evaluator
    # `pump_self` reads, so one printed clause means one number wherever the
    # card prints it. Taken once, here, rather than per creature: CR 611.2c
    # fixes the affected set and the size when the effect begins, and a count
    # re-taken inside the loop would change as the loop's own boosts landed.
    x_count = instruction.payload.get("x_from_count")
    x_value = (
        count_from_payload(game, context, x_count) if x_count is not None else None
    )
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    exclude_colors = set(instruction.payload.get("exclude_colors") or ())
    attacking_only = bool(instruction.payload.get("attacking_only"))
    blocking_only = bool(instruction.payload.get("blocking_only"))
    subtypes = tuple(instruction.payload.get("subtypes") or ())
    exclude_types = tuple(instruction.payload.get("exclude_types") or ())
    with_keywords = tuple(instruction.payload.get("with_keywords") or ())
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
            # "Nonwhite creatures get -1/-1 until end of turn." (Holy Light.)
            # Layer 5 again, in the other direction: a creature *made* white
            # escapes the debuff and a white creature made blue is caught, and
            # a colourless creature is nonwhite because it is in no colour's
            # set (CR 105.2c).
            if exclude_colors and (exclude_colors & set(perm.effective_colors)):
                continue
            # "Other **Orc** creatures" (Orc General). Through ``has_type``, so
            # a creature that *became* an Orc counts and one that stopped being
            # one does not (CR 613 layer 4) — the same reader the type test
            # above it uses, rather than the printed type line.
            if subtypes and not any(perm.has_type(name) for name in subtypes):
                continue
            # "**Nonartifact** creatures get -1/-1 until end of turn." (Stench
            # of Decay.) The same layer-4 reader in the other direction, for
            # the same reason ``exclude_colors`` is: an artifact creature the
            # sweep is not printed to reach must survive it, including one that
            # became an artifact after the spell was cast but before it
            # resolved (CR 611.2c fixes the set at resolution, which is now).
            if exclude_types and any(perm.has_type(name) for name in exclude_types):
                continue
            # "…all attacking creatures **with flanking**" (Telim'Tor). Asked of
            # layer 6 (CR 613.1f) rather than of the printed keyword list, the
            # same reader ``subject_matches`` uses -- so a creature an Aura
            # granted flanking is in the set, which is the whole reason
            # `keywords.LINE_DERIVED_KEYWORDS` puts the word back when it grants
            # the line.
            if with_keywords and not all(
                game._has_keyword(perm, word) for word in with_keywords
            ):
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
    from ..subject_filters import subject_matches

    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    # "**Attacking** creatures gain trample until end of turn" (Stampede). Two
    # payload keys the plain "creatures you control" printing does not carry:
    # the narrowing, and the fact that the sentence named no controller at all.
    # Stampede is castable by the *defending* player, so a grant scoped to the
    # caster's board would reach none of the creatures it names.
    described = instruction.payload.get("filter")
    seats = (
        range(len(game.players))
        if instruction.payload.get("every_seat")
        else (caster_index,)
    )
    # "creatures you control **blocking that creature** gain first strike until
    # end of turn" (Tidal Flats). A relation to the object the loop around this
    # sentence bound rather than a characteristic of the blocker, so it is read
    # off the combat maps here — through the one reader of the relation, and
    # once, before the board walk. CR 611.2c: the set is fixed now, so a
    # creature that starts blocking later is not in it.
    blockers: list | None = None
    if instruction.payload.get("blocking_bound_target"):
        blocked = bound_permanent(game, context)
        blockers = list(game.creatures_blocking(blocked)) if blocked is not None else []
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for seat in seats:
        for perm in game.controlled_by(seat):
            if not every_permanent and not perm.is_creature:
                continue
            if blockers is not None and not any(perm is one for one in blockers):
                continue
            # Through the one reader of what a printed noun phrase means, with the
            # caster as observer (CR 109.5), so "attacking" here and "attacking" on
            # the P/T half of the very same sentence are one question.
            if described and not subject_matches(
                game, perm, described, observer=caster_index,
                source=context.source_permanent,
            ):
                continue
            for keyword in keywords:
                # Through the one seam, so a team grant puts a keyword where its
                # reader looks for the same reasons a single-target grant does.
                _grant_one_keyword(game, perm, keyword, context, lifetime)
            granted += 1
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {granted} {noun} gain {', '.join(keywords)}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("pump_block_pair")
def pump_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**the blocking creature** gets -1/-1 until end of turn." (CR 702.25a's
    definition of flanking, built by ``engine/flanking.py``.)

    The P/T twin of ``grant_keyword_to_block_pair`` below, and it reads the pair
    the same way — through ``block_pair_permanents``, the one function that
    knows the two fire sites bind "that creature" differently. Reaching for the
    stack item's target instead would name the flanker itself on the *blocks*
    half of a block trigger, which is the bug that function exists to stop.

    CR 702.25b's several instances are several abilities, so each resolution
    applies its own -1/-1: the second one shrinks a creature the first has
    already shrunk, which is what makes two instances -2/-2 rather than -1/-1
    computed twice from the printed number.
    """
    power = int(instruction.payload.get("power", 0))
    toughness = int(instruction.payload.get("toughness", 0))
    until = str(instruction.payload.get("duration") or "end_of_turn")
    pumped = 0
    for perm in block_pair_permanents(game, context):
        apply_temp_pt_boost(perm, power, toughness, until=until)
        game.log.append(
            f"{context.card.name} gives {perm.card.name} "
            f"{power:+d}/{toughness:+d} until " + until.replace("_", " ")
        )
        pumped += 1
    if not pumped:
        game.log.append(f"{context.card.name}: no creature in the block pair")
        return True, "no target"
    return True, "resolved"


@effect_handler("grant_keyword_to_block_pair")
def grant_keyword_to_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**that creature** gains first strike until end of turn." (Goblin
    Flotilla.)

    The other half of the block the trigger fired on, resolved by the stable ids
    the fire site recorded (CR 509.3f fixes the set at declaration; an id that
    no longer resolves is a creature that left, and one that returns is a new
    object the sentence never named — CR 400.7).

    ``block_pair_permanents`` is the one reader of that pair, shared with the
    delayed destroy above it, so the two halves of a block are named the same
    way whichever verb the card printed. The grant itself goes through the one
    keyword seam, so it composes with every other layer-6 write by timestamp.
    """
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for perm in block_pair_permanents(game, context):
        for keyword in keywords:
            _grant_one_keyword(game, perm, keyword, context, lifetime)
        granted += 1
    if not granted:
        game.log.append(f"{context.card.name}: no creature in the block pair")
        return True, "no target"
    game.log.append(
        f"{context.card.name}: {granted} creature(s) gain {', '.join(keywords)}"
    )
    return True, "resolved"


@effect_handler("grant_keyword_to_creatures_in_combat_with_source")
def grant_keyword_to_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each creature blocking or blocked by this creature gains first strike
    until end of turn." (Spitting Slug.)

    The set is a combat relation to the ability's own source (CR 509), read
    from the combat maps rather than from any characteristic of the candidates —
    which is why this is not the team grant above: that one walks the caster's
    board, and the creatures blocking this one are the opponent's.

    Locked in at resolution (CR 611.2c), like every other sweep here: a creature
    that joins the block afterwards is not one this effect named.
    """
    keywords = tuple(instruction.payload.get("keywords") or ())
    source = context.source_permanent
    if source is None:
        game.log.append(f"{context.card.name}: no source to read the combat from")
        return True, "resolved"
    lifetime = grant_lifetime(game, instruction, context)
    granted = 0
    for perm in game.creatures_in_combat_with(source):
        for keyword in keywords:
            # Through the one seam, so the keyword lands where its reader looks.
            _grant_one_keyword(game, perm, keyword, context, lifetime)
        granted += 1
    game.log.append(
        f"{context.card.name}: {granted} creature(s) in combat with it gain "
        + ", ".join(keywords)
        + DURATION_WORDS.get(lifetime["duration"], "")
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
        # "Put **X** +0/+1 counters on this creature" (Necropolis): the count
        # may be the where-clause's X, resolved through the same
        # `context.x_value` every other amount reads.
        #
        # …and that X may be *defined* by a count taken at resolution rather
        # than announced with a cast: "put a +1/+1 counter on this creature
        # **for each 1 damage dealt to you this turn**" (Discordant Spirit).
        # The same `x_from_count` channel the pump handlers at the top of this
        # file read, so one printed clause is one number wherever it is spent.
        x_value = context.x_value
        x_count = instruction.payload.get("x_from_count")
        if x_count is not None:
            x_value = count_from_payload(game, context, x_count)
        count = resolve_amount(raw_count, x_value)
    if count <= 0:
        return True, "resolved"
    # Which CR 122.1a pair. Absent on every payload written before Necropolis,
    # and those all mean the one kind this handler used to place - so the
    # default is the whole of the compatibility, and `place_plus1_counters`
    # stays the path for it because that kind is the one with a CR 614 event
    # and a trigger behind it.
    kind = str(instruction.payload.get("counter", "+1/+1"))
    if kind == "+1/+1":
        game.place_plus1_counters(source_permanent, count)
    else:
        game.place_pt_counters(source_permanent, kind, count)
    game.log.append(
        f"{card.name} gets a {kind} counter" if count == 1
        else f"{card.name} gets {count} {kind} counters"
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
    # The host's seat, recorded for the sentences behind this step: "…deals
    # damage … to **its controller**", "…destroy **that creature**" (Consuming
    # Ferocity). The same record ``destroy_attached_permanent`` writes for
    # Orcish Mine, and written *before* anything else for that handler's
    # reason — CR 608.2h's last-known information, so a host that leaves
    # between the two steps still supplies the seat the sentence names.
    seat = game.controller_index_of(attached)
    if seat is not None:
        context.results[ATTACHED_PERMANENT_CONTROLLER] = seat
    kind = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    placed = game.place_pt_counters(attached, kind, count)
    if placed:
        game.log.append(
            f"{context.card.name}: {attached.card.name} gets "
            + (f"a {kind} counter" if placed == 1 else f"{placed} {kind} counters")
        )
    return True, "resolved"


@effect_handler("add_counter_to_bound_permanent")
def add_counter_to_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…at the beginning of each of your draw steps, put a -1/-1 counter on
    **that creature**." (Giant Oyster.)

    The counter's home is the object the *creating* ability bound (CR 603.7c),
    carried by id in the delayed trigger's context — never a pick. Its own kind
    beside ``add_counter_to_target`` for ``destroy_bound_permanent``'s reason:
    routed through the targeted placement, ``engine/targeting.py`` would raise a
    picker for a choice CR 603.3d says was never offered, and the handler would
    then put the counter on whichever permanent the resolution context happened
    to carry.

    Through ``Game.place_pt_counters``, the one placement seam, so the P/T
    channel and the counter record cannot drift and the CR 704.5q annihilation
    sweep has a counter to find.

    A creature already gone takes no counter, which is CR 608.2b doing as much
    as it can rather than a failure — and a repeating ability keeps waiting,
    because whether it is still armed is its duration's question, not this
    one's.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    kind = str(instruction.payload.get("counter", "+1/+1"))
    how_many = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if how_many <= 0:
        return True, "resolved"
    game.place_pt_counters(victim, kind, how_many)
    game.log.append(
        f"{victim.card.name} gets {how_many} {kind} counter(s) "
        f"({context.card.name})"
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
    # Which CR 122.1a counter this is. Absent on every payload written before
    # Lesser Werewolf, and those all mean the one kind this handler used to
    # place — so the default is the whole of the compatibility, and a card
    # printing "-0/-1" is this instruction with a different word in it.
    kind = str(instruction.payload.get("counter", "+1/+1"))
    # "Put **X** +0/+1 counters on target creature." (Living Armor.) How many of
    # that kind, resolved through the same `context.x_value` every other amount
    # reads — absent on every payload written before it, and 1 is what those
    # have always meant.
    how_many = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if how_many <= 0:
        # A where-clause can define an X of zero (a creature with mana value 0),
        # and CR 122.1 places no counters then. Logged as a resolution rather
        # than a miss: the ability did what it said.
        how_many = 0

    # "Return target creature card from your graveyard to the battlefield. Put
    # a +2/+2 counter on **that creature** …" (Soul Exchange.) No target was
    # chosen either: the ability's target is a *card in a graveyard*, and the
    # permanent this names did not exist when it was announced. So the
    # placement reads what the reanimation recorded, by id — the same
    # ``permanents_from`` channel ``grant_target_ability_text`` reads, because
    # the question is the same one.
    #
    # An empty record is a legal outcome (nothing came back), not an error.
    #
    # **The channel carries one id or a list of them, and both reach here.**
    # ``reanimated_permanents`` is a list because "return target creature card"
    # is one step of a sentence that could return several; ``attach_host`` is a
    # bare id, because a choose-one prompt picks exactly one (Thelon's Chant,
    # Tourach's Chant). Every other reader of ``permanents_from``
    # (``destruction``, ``control_changes``) reads the scalar shape only and
    # would raise on the list, so normalising here is the *local* half of a
    # wider question recorded in ROADMAP.md rather than a settled convention.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        placed_on = 0
        recorded = (context.results or {}).get(str(recorded_key))
        if isinstance(recorded, int):
            recorded = (recorded,)
        for permanent_id in recorded or ():
            creature = game.permanent_by_id(permanent_id)
            if creature is None:
                # It left between the two steps of one resolution; a returning
                # permanent is a new object (CR 400.7) and is not this one.
                continue
            game.place_pt_counters(creature, kind, how_many)
            placed_on += 1
            game.log.append(
                f"{creature.card.name} gets {how_many} {kind} counter(s) "
                f"({card.name})"
            )
        if not placed_on:
            game.log.append(f"{card.name}: nothing was left to put a counter on")
        return True, "resolved"

    # "…put a +1/+1 counter on **the first creature**." (Infinite Authority.)
    # No target was ever chosen: the sentence names one half of the pair a block
    # trigger bound, and the ids were frozen when the earlier step of this same
    # effect armed the destruction. Read by id, so a creature that left and came
    # back is a different object (CR 400.7) and gets nothing.
    # "…unless the player puts a -1/-1 counter on a creature they control"
    # (Thelon's Chant, Tourach's Chant.) Nobody targeted anything: the seat the
    # offer was made to picked a creature one step earlier in this same
    # resolution (CR 608.2d), and the pick is in the scratchpad under the key
    # that step always writes. By id, so a creature that left and came back is a
    # different object (CR 400.7) and gets nothing.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        chosen_id = context.results.get(recorded_key)
        creature = (
            game.permanent_by_id(chosen_id) if chosen_id is not None else None
        )
        if creature is None:
            game.log.append(f"{card.name}: no creature was chosen to take a counter")
            return True, "resolved"
        if how_many:
            game.place_pt_counters(creature, kind, how_many)
            game.log.append(
                f"{creature.card.name} gets a {kind} counter ({card.name})"
            )
        return True, "resolved"

    pair_member = instruction.payload.get("pair_member")
    if pair_member:
        bound = (context.trigger_context or {}).get(
            instruction.payload.get("produced_by")
        ) or {}
        creature = game.permanent_by_id(bound.get("own_id"))
        if creature is None:
            game.log.append(f"{card.name}: the creature it names is gone")
            return True, "no target"
        game.place_pt_counters(creature, kind)
        game.log.append(f"{creature.card.name} gets a {kind} counter ({card.name})")
        return True, "resolved"

    if isinstance(targets, dict) and targets.get("kind") == "divided":
        # "Distribute X +1/+1 counters among any number of target creatures."
        # (Spoils of War.) CR 601.2d's counter half: the caster announced how
        # many go where as part of casting, and the shares travel on the same
        # `divided_targets` list a divided damage spell's do — so the division
        # is `engine/divided_damage.py`'s answer here exactly as it is there.
        #
        # A target that has left keeps its share out of the effect (CR 608.2b);
        # nothing redistributes it, which is why the surviving entries are
        # filtered before the division is read rather than after.
        from ..divided_damage import DIVIDED_TARGETS, EVENLY, divide, divided_entry

        announced = list((context.choices or {}).get(DIVIDED_TARGETS) or ())
        if announced:
            # Each entry is turned into a permanent once, through the seam, and
            # carried as the object from there — an index held across the
            # placement loop would address the wrong creature the moment
            # anything left.
            chosen_entries = [
                (entry, creature)
                for entry in announced
                for seat, index, _share in (divided_entry(entry),)
                for creature in (game.permanent_at(seat, index),)
                if creature is not None
            ]
            if not chosen_entries:
                # Every announced target has left. CR 608.2b, and the spell
                # still resolves — `illegal_targets_refusal` declines to answer
                # "every target is illegal" for a divided spell, because a
                # player's face reaches the stack item through the same field a
                # permanent's seat does.
                game.log.append(
                    f"{card.name}: every creature it named has left "
                    f"the battlefield (608.2b)"
                )
                return True, "resolved"
            placements = [
                (creature, share)
                for (_entry, creature), (_seat, _index, share) in zip(
                    chosen_entries,
                    divide(
                        how_many,
                        [entry for entry, _creature in chosen_entries],
                        division=targets.get("division", EVENLY),
                    ),
                )
            ]
        else:
            # **No division was announced at all**, which is not the same
            # question and used to be answered as though it were: the branch
            # logged "no creatures were given counters" and reported itself
            # resolved, so Spoils of War, Contagion and Bounty of the Hunt did
            # nothing whenever the caster reached the engine through its older
            # single-target channel — every AI cast, every scripted duel.
            #
            # The named target takes the whole amount, which CR 601.2d allows
            # (one target, receiving all of it) and which is exactly what the
            # divided *damage* twin's fall-through has always done. Announcing
            # nothing at all is refused one step earlier now, at CR 601.2c, so
            # what reaches here is a caster who named a target the older way.
            #
            # No fallback scan: a named creature that has left takes nothing
            # (CR 608.2b), rather than the counters landing on whichever
            # creature a scan reached first — which for a `+1/+1` distribution
            # could be the opponent's.
            filters = targets.get("filter") or {}
            creature = resolve_target_permanent(
                game, context,
                predicate=lambda perm: (
                    perm.is_creature and permanent_matches_filter(perm, filters)
                ),
                fallback_on_invalid_choice=False,
            )
            if creature is None:
                game.log.append(f"{card.name}: no valid creature target")
                return True, "resolved"
            placements = [(creature, how_many)]
        placed_total = 0
        for creature, share in placements:
            if share <= 0:
                continue
            game.place_pt_counters(creature, kind, share)
            placed_total += share
            # "**For each +1/+1 counter you put on a creature this way,** …"
            # (Bounty of the Hunt.) One entry per *counter*, not per creature:
            # a creature given two is named twice and the sentence behind this
            # runs twice about it. Written here because this is the only step
            # that knows the division — the caster announced it as the spell was
            # cast, and a creature's counters afterwards say nothing about which
            # of them this spell put there.
            context.results.setdefault(COUNTERS_PLACED_THIS_WAY, []).extend(
                [creature] * share
            )
            game.log.append(
                f"{creature.card.name} gets {share} {kind} counter(s) ({card.name})"
            )
        if placed_total == 0:
            game.log.append(f"{card.name}: no creatures were given counters")
        return True, "resolved"

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
            game.place_pt_counters(creature, kind)
            game.log.append(f"{creature.card.name} gets a {kind} counter ({card.name})")
        return True, "resolved"

    filters = instruction.payload.get("targets", {}).get("filter") or {}

    source = context.source_permanent
    in_combat_only = bool(instruction.payload.get("in_combat_with_source"))

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
        # "…blocking or blocked by this creature" (Lesser Werewolf). The
        # relation rides the instruction rather than the filter — no read of the
        # candidate alone can answer it — and is re-checked at resolution as
        # well as at activation, because CR 608.2b asks a target's legality
        # again when the ability resolves.
        if in_combat_only and (
            source is None
            or not any(perm is other for other in game.creatures_in_combat_with(source))
        ):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    target_creature = resolve_target_permanent(
        game, context, predicate=counter_target_legal,
        # "…on target creature **blocking or blocked by this creature**"
        # (Lesser Werewolf). A relation the fallback scan cannot re-derive from
        # the filter, so a chosen creature that has left combat makes the
        # ability do nothing (CR 608.2b) rather than land on a bystander.
        fallback_on_invalid_choice=not in_combat_only,
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    if how_many:
        game.place_pt_counters(target_creature, kind, how_many)
        game.log.append(
            f"{target_creature.card.name} gets a {kind} counter ({card.name})"
            if how_many == 1
            else f"{target_creature.card.name} gets {how_many} {kind} counters "
                 f"({card.name})"
        )
    else:
        game.log.append(f"{card.name}: no counters to place")
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


@effect_handler("add_counter_to_each_matching")
def add_counter_to_each_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a +1/+1 counter on **each creature you control**" (Basri's
    Solidarity); "put a -1/-1 counter on **each creature that player
    controls**" (Misfortune).

    One handler for both, because the effect is one effect and the printed noun
    phrase is the only difference — which is exactly what a filter payload is
    for. It replaced ``add_counter_to_each_you_control``, a kind whose *name*
    was the scope: a second kind beside it would have been one effect with two
    spellings, and the alternative — passing "that player" to something called
    ``…_you_control`` — is a name that lies.

    The board is read here, as the effect resolves (CR 611.2c), through the
    control seam so a borrowed creature counts and a lost one does not.

    "**That player** controls" is not a seat any read of the board can make —
    ``subject_matches`` refuses it outright and says why — so it is stripped
    from the filter and asked as its own question, of the seat the announcement
    froze (CR 700.2e for a mode an opponent chose, CR 603.10 for a trigger).
    An unresolvable seat **ends** the effect rather than dropping the word: a
    dropped scope on a -1/-1 sweep is not a card that does less, it is one that
    shrinks the caster's own board.
    """
    from ..subject_filters import subject_matches

    card = context.card
    caster = context.caster
    kind = instruction.payload.get("counter", "+1/+1")
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    filters = dict(instruction.payload.get("filter") or {})
    scoped_seat: int | None = None
    if filters.get("controller") == "that_player":
        scoped_seat = frozen_that_player_seat(game, context)
        if scoped_seat is None:
            game.log.append(f"{card.name}: no player for 'that player' to name")
            return True, "resolved"
        del filters["controller"]
    observer = game.players.index(caster) if caster in game.players else None
    source = context.source_permanent
    touched: list[Permanent] = []
    for perm in game.all_permanents():
        if scoped_seat is not None and game.controller_index_of(perm) != scoped_seat:
            continue
        if not subject_matches(
            game, perm, filters, observer=observer, source=source
        ):
            continue
        touched.append(perm)
    # Placed after the scan, not during it: `place_pt_counters` runs the CR 614
    # replacements for a +1/+1 counter, and a replacement that moved a creature
    # would renumber a battlefield this loop was still walking.
    for perm in touched:
        game.place_pt_counters(perm, kind, count)
    if touched:
        game.log.append(
            f"{card.name}: {', '.join(p.card.name for p in touched)} "
            f"each got {count} {kind} counter(s)"
        )
    else:
        game.log.append(f"{card.name}: nothing matched, no counters placed")
    return True, "resolved"


def grant_lifetime(game, instruction, context) -> dict:
    """The lifetime this grant printed, as the keyword arguments
    :func:`engine.keywords.grant_keyword` and ``grant_ability_line`` take.

    One reader for every grant handler, because "how long does this last?" is
    one question and a handler that answered it for itself is what let the
    duration collapse in the first place — every one of them passed
    ``until_eot=True`` whatever the card said.

    A seated duration ("until **your** next upkeep") freezes the seat now:
    CR 109.5 makes it the controller of the *ability*, and by the time the
    sweep runs the affected permanent may be controlled by somebody else — or
    be somewhere else entirely.
    """
    from ..keywords import SEATED_GRANT_DURATIONS

    duration = instruction.payload.get("duration")
    lifetime: dict = {"duration": duration}
    if duration in SEATED_GRANT_DURATIONS:
        lifetime["seat"] = game.players.index(context.caster)
    return lifetime


#: How each grant duration reads in the log, so the message says what the card
#: said rather than what the handler used to assume.
DURATION_WORDS = {
    None: "",
    "end_of_turn": " until end of turn",
    "end_of_combat": " until end of combat",
    "your_next_upkeep": " until their next upkeep",
}


@effect_handler("grant_self_flying_until_eot")
def grant_self_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    lifetime = grant_lifetime(game, instruction, context)
    grant_keyword(source_permanent, "flying", **lifetime)
    game.log.append(
        f"{card.name} gains flying" + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_target_flying_until_eot")
def grant_target_flying_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    target_creature = resolve_target_permanent(game, context)
    if target_creature is not None:
        lifetime = grant_lifetime(game, instruction, context)
        grant_keyword(target_creature, "flying", **lifetime)
        game.log.append(
            f"{target_creature.card.name} gains flying"
            + DURATION_WORDS.get(lifetime["duration"], "")
            + f" from {card.name}"
        )
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
    # "…**That creature** gains haste until end of turn." (Shallow Grave,
    # Zirilan of the Claw.) A set an earlier step of this effect recorded,
    # by id — not a target, so there is no picker and no noun phrase to
    # re-check: CR 611.2c fixed the set when the effect began and the record
    # *is* that set. The same `permanents_from` channel
    # `grant_target_ability_text` below reads, because the question is the
    # same one asked of a keyword instead of a quoted line.
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        lifetime = grant_lifetime(game, instruction, context)
        lasting = DURATION_WORDS.get(lifetime["duration"], "")
        granted = 0
        for permanent_id in (context.results or {}).get(str(recorded_key)) or ():
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                # It left between the two steps of one resolution; what comes
                # back is a different object (CR 400.7) and is not this one.
                continue
            for keyword in instruction.payload.get("keywords") or ():
                # **lifetime rather than the two keys by name: a seated
                # duration carries a seat and an unseated one carries none, and
                # naming both would ask for a key that is deliberately absent.
                grant_keyword(permanent, keyword, **lifetime)
            granted += 1
            game.log.append(
                f"{permanent.card.name} gains "
                + ", ".join(instruction.payload.get("keywords") or ())
                + lasting
            )
        if not granted:
            game.log.append(f"{card.name}: nothing was left to grant to")
        game._refresh_dynamic_creatures()
        return True, "resolved"
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

    keywords = tuple(instruction.payload.get("keywords") or ())

    # "**X** target creatures gain islandwalk until end of turn." (Part Water.)
    # The printed count is a *string* until the spell is cast — X is announced,
    # not printed — so it is resolved against the context's X rather than tested
    # with `isinstance(int)`. That test is the exact hole rounds 23 and 27 found
    # in the tap and bounce handlers: it skipped the "x" spelling, fell through
    # to the one-target branch, and affected the first chosen creature while the
    # player watched the rest do nothing.
    lifetime = grant_lifetime(game, instruction, context)
    lasting = DURATION_WORDS.get(lifetime["duration"], "")
    printed_count = (instruction.payload.get("targets") or {}).get("count")
    maximum = (
        resolve_amount(printed_count, context.x_value)
        if printed_count is not None else None
    )
    if isinstance(maximum, int) and maximum > 1:
        chosen = resolve_target_permanents(game, context, predicate=grant_target_legal)
        if not chosen:
            game.log.append(f"{card.name}: no valid creature targets")
            return True, "resolved"
        for permanent in chosen:
            for keyword in keywords:
                _grant_one_keyword(game, permanent, keyword, context, lifetime)
        game.log.append(
            ", ".join(p.card.name for p in chosen)
            + f" gain {' and '.join(keywords)}{lasting} ({card.name})"
        )
        return True, "resolved"

    target_creature = resolve_target_permanent(
        game, context, predicate=grant_target_legal
    )
    if target_creature is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"
    for keyword in keywords:
        _grant_one_keyword(game, target_creature, keyword, context, lifetime)
    game.log.append(
        f"{target_creature.card.name} gains {' and '.join(keywords)}{lasting} ({card.name})"
    )
    return True, "resolved"


@effect_handler("grant_self_ability_text")
def grant_self_ability_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"<This permanent> gains "<ability>"." (CR 113.3.)

    The twin of ``grant_self_keyword_until_eot`` for an ability the layer-6
    word set cannot hold. See ``engine/granted_abilities.py``: the grant is the
    printed line, and the compiler is what turns it back into an ability.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    _grant_ability_texts(game, source_permanent, instruction, context)
    return True, "resolved"


@effect_handler("grant_target_ability_text")
def grant_target_ability_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…that creature gains "<ability>"." (Life Matrix.)

    The printed noun phrase is enforced here as well as at announcement, for
    the reason recorded on ``grant_target_keyword_until_eot`` above: a picker
    and a resolution that disagree are a target the player may announce and the
    effect then declines to affect.

    "Each of **those creatures** gains …" (Dread Wight) is the same grant over
    a set an earlier step of this effect recorded, by id — not a target, so
    there is no picker and no noun phrase to re-check: CR 611.2c fixed the set
    when the effect began and the record *is* that set. A permanent that left
    in between is a new object when it returns (CR 400.7) and simply misses the
    grant; an empty record is a legal outcome rather than an error.
    """
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        granted = 0
        for permanent_id in (context.results or {}).get(str(recorded_key)) or ():
            permanent = game.permanent_by_id(permanent_id)
            if permanent is None:
                continue
            _grant_ability_texts(game, permanent, instruction, context)
            granted += 1
        if not granted:
            game.log.append(f"{context.card.name}: nothing was left to grant to")
        return True, "resolved"
    target_creature = resolve_target_permanent(
        game, context, predicate=_target_grant_predicate(game, instruction, context)
    )
    if target_creature is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    _grant_ability_texts(game, target_creature, instruction, context)
    return True, "resolved"


def _grant_ability_texts(game, permanent, instruction, context) -> None:
    """Record every quoted ability the instruction grants, in printed order.

    Capitalised on the way in because the channel is folded into the
    permanent's *rules text*, which the UI shows — the same reason the
    line-derived keyword grant capitalises. The compiler normalises it again.
    """
    from ..keywords import grant_ability_line, normalized_ability_line

    lifetime = grant_lifetime(game, instruction, context)
    caster_seat = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    texts = tuple(instruction.payload.get("abilities") or ())
    if instruction.payload.get("only_if_absent"):
        # "If it doesn't have "<ability>," it gains that ability." (Musician.)
        # Asked of the permanent's *effective* text, which is where a grant
        # already made and a printed one both read from — a check against the
        # printed card alone would grant Musician's ability a second time on
        # the second activation, and the creature would then owe the upkeep
        # payment twice for one set of counters.
        present = {
            normalized_ability_line(line)
            for line in (permanent.effective_card.oracle_text or "").splitlines()
        }
        texts = tuple(
            text for text in texts if normalized_ability_line(text) not in present
        )
    # **Whose grant this is** (CR 109.5), recorded on every granted line rather
    # than only on the seated durations `grant_lifetime` answers for. A granted
    # ability can name its granter — "Only you may activate this ability"
    # (Martyrdom) — and by the time anyone asks, the spell that said "you" is a
    # card in a graveyard with no controller (CR 108.4) and the creature may be
    # under somebody else's control, which is exactly the case the sentence is
    # printed for. `_check_duration` accepts a seat beside any duration and the
    # sweeps ignore one they did not ask for, so this costs the existing grants
    # a key and nothing else.
    granting = dict(lifetime)
    if caster_seat is not None:
        granting.setdefault("seat", caster_seat)
    for text in texts:
        line = text.strip()
        if not line:
            continue
        grant_ability_line(permanent, line[:1].upper() + line[1:], **granting)
    if texts:
        lasting = DURATION_WORDS.get(lifetime["duration"], "")
        game.log.append(
            f"{permanent.card.name} gains "
            + " and ".join(f'"{text}"' for text in texts)
            + f"{lasting} ({context.card.name})"
        )


def _target_grant_predicate(game, instruction, context):
    """Which permanents a targeted grant may reach, from its printed filter.

    Split out of ``grant_target_keyword_until_eot`` so the quoted-ability grant
    asks the *same* three questions rather than a second spelling of them: the
    printed filter, CR 109.5's source exclusion, and the seat "you control"
    compares against.

    ``subject_types`` is the printed noun of a grant whose target was chosen by
    the clause in front of it ("that **enchantment** gains …", Balduvian
    Shaman). Every other card printing that shape says "creature", which is why
    the type was assumed rather than read — and an assumed creature is a
    silently empty target set for the first card that says anything else.
    """
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    types = tuple(instruction.payload.get("subject_types") or ()) or ("creature",)
    source = context.source_permanent

    def legal(perm) -> bool:
        if not any(perm.has_type(card_type) for card_type in types):
            return False
        if not permanent_matches_filter(perm, filters):
            return False
        if filters.get("exclude_self") and perm is source:
            return False
        if filters.get("controller") == "you" and not game.controls(
            game.players.index(context.caster), perm
        ):
            return False
        return True

    return legal


def _grant_one_keyword(game, permanent, keyword: str, context, lifetime=None) -> None:
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
    from ..keywords import (LINE_DERIVED_KEYWORDS, grant_ability_line,
                            keyword_ability_name)

    # …and layer 6's word-set is not where a *line-derived* ability's reader
    # looks either. CR 702.23a defines "Rampage N" as a triggered ability, so
    # `engine/rampage.py` builds it out of the printed line at compile time —
    # a word in layer 6 would be a grant of nothing. Granting the line is what
    # the permanent now says, and the compiler makes the ability from there.
    # Capitalised because it is folded into the permanent's *printed* rules
    # text, which the UI shows; the compiler lowercases it again.
    # The printed duration, or end of turn for the handlers that have no
    # instruction to read one from (a rider whose whole wording is "until end
    # of turn").
    lifetime = {"duration": "end_of_turn"} if lifetime is None else lifetime
    if keyword_ability_name(keyword) in LINE_DERIVED_KEYWORDS:
        grant_ability_line(permanent, keyword.capitalize(), **lifetime)
        return
    if not keyword.startswith("protection from "):
        grant_keyword(permanent, keyword, **lifetime)
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
        remove_keyword(target, keyword, duration="end_of_turn")
    game.log.append(
        f"{target.card.name} loses {' and '.join(keywords)} until end of turn ({card.name})"
    )
    return True, "resolved"


@effect_handler("remove_team_keyword_until_eot")
def remove_team_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"All creatures lose flying until end of turn." (Whiteout.)

    The mirror of ``grant_team_keyword_until_eot`` and deliberately its shape:
    the affected set locks in at resolution (CR 611.2c), so this walks the board
    now rather than contributing a derived effect, and the same three payload
    keys say how wide it reaches. ``remove_keyword`` writes into layer 6, so a
    creature granted flying *later* in the turn keeps it — the timestamp
    decides, not this handler.
    """
    from ..subject_filters import subject_matches

    caster_index = game.players.index(context.caster)
    keywords = tuple(instruction.payload.get("keywords") or ())
    every_permanent = bool(instruction.payload.get("every_permanent"))
    described = instruction.payload.get("filter")
    seats = (
        range(len(game.players))
        if instruction.payload.get("every_seat")
        else (caster_index,)
    )
    lifetime = grant_lifetime(game, instruction, context)
    stripped = 0
    for seat in seats:
        for perm in game.controlled_by(seat):
            if not every_permanent and not perm.is_creature:
                continue
            if described and not subject_matches(
                game, perm, described, observer=caster_index,
                source=context.source_permanent,
            ):
                continue
            for keyword in keywords:
                remove_keyword(perm, keyword, **lifetime)
            stripped += 1
    game._recompute_continuous_effects()
    noun = "permanent(s)" if every_permanent else "creature(s)"
    game.log.append(
        f"{context.card.name}: {stripped} {noun} lose {', '.join(keywords)}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("remove_self_keyword")
def remove_self_keyword(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature blocks, it loses defender." (Elder Land Wurm.)

    The durationless mirror of ``remove_target_keyword_until_eot``: one layer-6
    removal on the ability's own source, with no expiry stamped on it, so the
    cleanup sweep leaves it alone and the word stays gone. Losing defender
    mid-combat is exactly why the removal has to be a real layer-6 record
    rather than a printed-keyword edit — the creature is already blocking, and
    every later read of "can it attack" asks the layers.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    keywords = tuple(instruction.payload.get("keywords") or ())
    # "…loses flying **until end of turn**" (Leering Gargoyle, Canopy Dragon).
    # Absent means no expiry, which is what every payload written before this
    # key meant and what Elder Land Wurm's defender loss still means.
    duration = instruction.payload.get("duration")
    for keyword in keywords:
        remove_keyword(source_permanent, keyword, duration=duration)
    game._recompute_continuous_effects()
    game.log.append(
        f"{source_permanent.card.name} loses {' and '.join(keywords)}"
        + (" until end of turn" if duration == "end_of_turn" else "")
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
    lifetime = grant_lifetime(game, instruction, context)
    for keyword in keywords:
        _grant_one_keyword(game, source_permanent, keyword, context, lifetime)
    game.log.append(
        f"{card.name} gains {' and '.join(keywords)}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
    return True, "resolved"


@effect_handler("grant_enchanted_keyword_until_eot")
def grant_enchanted_keyword_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**it** gains trample until end of turn", where "it" is the enchanted
    creature (Bestial Fury).

    ``grant_self_keyword_until_eot``'s subject read off the attachment record
    instead of off the ability's own source — the keyword twin of
    ``pump_enchanted_creature``, and one printed sentence produces both.

    The host comes from ``attached_host`` rather than a raw
    ``metadata["attached_to"]`` read, so a resolution that has already removed
    the Aura still knows whose creature it was (CR 603.10) — the same fallback
    Cocoon needs one family over.
    """
    from ._common import attached_host

    card = context.card
    enchanted = attached_host(game, context.source_permanent)
    if enchanted is None:
        return False, "aura not attached to a creature"
    keywords = tuple(instruction.payload.get("keywords") or ())
    lifetime = grant_lifetime(game, instruction, context)
    for keyword in keywords:
        _grant_one_keyword(game, enchanted, keyword, context, lifetime)
    game.log.append(
        f"{card.name}: {enchanted.card.name} gains {' and '.join(keywords)}"
        + DURATION_WORDS.get(lifetime["duration"], "")
    )
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
    # The log names the half the card printed. "…has base **toughness** 1"
    # (Chariot of the Sun) leaves the power standing, which ``set_base_pt``'s
    # None already expresses — reading the pair unconditionally printed a
    # "None/1" nobody could have cast.
    if toughness is None:
        game.log.append(f"{card.name}: {target_perm.card.name} has base power {power} until end of turn")
    elif power is None:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base toughness {toughness} until end of turn"
        )
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
        grant_keyword(target_creature, "flying", duration="end_of_turn")
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
