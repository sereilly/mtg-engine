"""Power/toughness **pumps** (CR 613.4c, layer 7c): "+N/+N until end of turn"
on a target, on several, on the source, on an Aura's host, on a block pair, on
the subject an event named, and on every creature a phrase names — and the
pumps that last only while their source stays tapped (Ashnod's Battle Gear).

A modification takes a delta and gives it back when it ends, through
``engine/pt.py``'s one write API; what *sets* a base power and toughness
(CR 613.4b) is ``base_pt.py``'s, and a switch (CR 613.4d) ``pt_switch.py``'s.

Split at the 2,000-line cap's split round, where everything that was not a
pump left for the module the lowering side had already given its subject: a
granted keyword or ability to ``keywords``, its loss to ``keyword_removal``,
counters (CR 122) to ``counters`` and ``counter_removal``, and the two
base-P/T setters to ``base_pt``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..destruction_events import mark_delayed_destruction
from ..models import Permanent
from ..pt import add_pt_modifier
from ..keywords import grant_keyword
from ._amounts import resolve_amount, count_from_payload
from ._common import apply_temp_pt_boost
from ._filters import permanent_matches_filter
from ._targets import (block_pair_permanents, attached_host,
                       defending_player_seat, resolve_target_permanent,
                       resolve_target_permanents, resolve_target_slots)
from .registry import effect_handler

# Re-exported, and not an API: the grants' two shared readers live in
# ``keywords.py``. ``engine/handlers/combat.py`` pulls them from here, from
# inside a function, and another group of the 2,000-line cap's split round is
# cutting that module in parallel — so its import line could not move with this
# split without a merge conflict. The line goes when that importer is repointed;
# the import hygiene guard fails a re-export nobody pulls.
from .keywords import DURATION_WORDS, grant_lifetime

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
        mark_delayed_destruction(game, target_perm, "destroy_if_attacked_eot")
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
    # The **live** attachment record, through the one reader of it: an
    # Equipment that has unattached stays on the battlefield with its last-known
    # host still written on it, and a boost handed to that host is a boost the
    # card no longer grants (CR 611.3b).
    enchanted = attached_host(game, source_permanent, last_known=False)
    if enchanted is None:
        return False, "aura not attached to a creature"
    # "…gets +X/+0 until end of turn, where X is the number of attacking
    # creatures." (Mob Mentality.) X is a count taken at resolution, through
    # the one evaluator every computed amount shares — so the printed clause
    # means the same number here as on the targeted and self pumps beside it.
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
    apply_temp_pt_boost(enchanted, power_delta, toughness_delta)
    game.log.append(
        f"{card.name} grants {enchanted.card.name} "
        f"{power_delta:+}/{toughness_delta:+} until end of turn"
    )
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
    # 611.2a's modification that lasts indefinitely — the *persistent* layer-7c
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
    # "…**it** gets +1/+1 until end of turn for each creature blocking **it**."
    # (Barreling Attack.) One sentence, one pronoun: the creature counted around
    # is the creature being pumped, and neither is the ability's own source —
    # the spell that armed the delayed trigger is a card in a graveyard by now
    # and blocks nothing. So the count is deferred until the target is resolved
    # and measured against *that* permanent, which is the same rewrite
    # `_resolve_per_each_pronoun` makes one package over for the sentence whose
    # subject **is** the source.
    counted_from_target = (
        isinstance(x_count, dict) and x_count.get("relative_to") == "pumped_target"
    )
    if x_count is not None and not counted_from_target:
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
        # "target creature **defending player controls**" (Yare), through the
        # one reader of the phrase (CR 506.2/603.10).
        defending = defending_player_seat(game, context)
        return subject_matches(
            game, perm, filters,
            observer=game.players.index(caster),
            source=context.source_permanent,
            defending=defending,
        )

    # "**Two target creatures** each get +2/+2 until end of turn." (Symbiosis.)
    # The several-target reading of this same instruction, and the same branch
    # `grant_target_keyword_until_eot` takes for "X target creatures gain
    # islandwalk": the printed count is read off the description, resolved
    # against the announced X because a printed "X" is a string until the spell
    # is cast, and every chosen permanent is pumped.
    #
    # Above the single-target read rather than beside it, because that one
    # *falls back to scanning the battlefield* when the chosen target no longer
    # answers — right for one target and wrong for several, which is exactly
    # what `resolve_target_permanents` was written to say. Reached only from a
    # description carrying a count above one, so every one-target payload ever
    # written takes the path below unchanged.
    printed_count = (instruction.payload.get("targets") or {}).get("count")
    maximum = (
        resolve_amount(printed_count, context.x_value)
        if printed_count is not None else None
    )
    if isinstance(maximum, int) and maximum > 1:
        until = str(instruction.payload.get("duration") or "end_of_turn")
        chosen = resolve_target_permanents(game, context, predicate=_eligible)
        if not chosen:
            # Every named target may have become illegal since (CR 608.2b), and
            # an "up to N" may legally have named none.
            game.log.append(f"{card.name}: no valid creature targets")
            return True, "resolved"
        for creature in chosen[:maximum]:
            apply_temp_pt_boost(creature, power_delta, toughness_delta, until=until)
        game.log.append(
            ", ".join(p.card.name for p in chosen[:maximum])
            + f" each get {power_delta:+}/{toughness_delta:+} until "
            + until.replace("_", " ")
            + f" ({card.name})"
        )
        return True, "resolved"

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(target, caster)
    )
    if target_perm is not None:
        if counted_from_target:
            # The deferred count, now that the object both pronouns name is in
            # hand. Re-derived here rather than earlier, so a target that has
            # left (CR 608.2b) never counts at all.
            x_value = count_from_payload(game, context, x_count, source=target_perm)
            power_delta = resolve_amount(
                instruction.payload.get("power", 0), x_value
            )
            toughness_delta = resolve_amount(
                instruction.payload.get("toughness", 0), x_value
            )
            if instruction.payload.get("power_negative"):
                power_delta = -power_delta
            if instruction.payload.get("toughness_negative"):
                toughness_delta = -toughness_delta
        # "…until end of combat" (Glyph of Destruction) is the same boost on a
        # different channel, so it is payload rather than a second kind — the
        # word decides which sweep takes it back. Absent means end of turn,
        # which is what every payload written before the channel table meant.
        until = str(instruction.payload.get("duration") or "end_of_turn")
        apply_temp_pt_boost(target_perm, power_delta, toughness_delta, until=until)
        # Signed by the format, not by a literal "+": a "-X/+X" (Belbe's Armor)
        # or a printed "-2/-0" logged as "+-2" reads as a typo for a boost.
        game.log.append(
            f"{card.name} gives {target_perm.card.name} "
            f"{power_delta:+}/{toughness_delta:+} until "
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


@effect_handler("buff_creatures_global_while_source_tapped")
def buff_creatures_global_while_source_tapped(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Thran Weaponry: "{2}, {T}: All creatures get +2/+2 for as long as this
    artifact remains tapped."

    `pump_target_while_source_tapped`'s global twin, and the same record on the
    same source for the same reason: an effect that ends on a **condition** has
    no moment anyone could hook, so nothing is written onto the creatures and
    nothing schedules a removal. What differs is only the subject — a board scan
    rather than one chosen permanent — so the record carries a `filter` where
    that one carries a `target_id`, and `_refresh_linked_tapped_pumps` reads
    whichever is present.

    The board is **not** frozen here. CR 611.2c fixes the affected set for a
    one-shot pump, but this is CR 611.2b's continuous effect with a duration:
    the set is whatever matches while the condition holds, so a creature that
    arrives after the activation is buffed too and one that leaves stops being.
    That is why the scan lives in the recompute rather than in this handler.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"

    power_delta = resolve_amount(instruction.payload.get("power", 0), context.x_value)
    toughness_delta = resolve_amount(
        instruction.payload.get("toughness", 0), context.x_value
    )
    source_permanent.metadata[PUMP_WHILE_TAPPED_KEY] = {
        "filter": dict(instruction.payload.get("filter") or {}),
        "power": power_delta,
        "toughness": toughness_delta,
    }
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name} gives creatures "
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
    from ..subject_filters import subject_matches

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
    # "All creatures get +X/-X until end of turn." (Flowstone Slide.) With no
    # count to size it, an X is the one the spell *announced* (CR 107.3a) — the
    # same fallback every targeted pump beside this one makes. It read None
    # here, so a variable sweep resolved at 0/0 while reporting supported.
    x_value = (
        count_from_payload(game, context, x_count)
        if x_count is not None else context.x_value
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
    # "Each creature **without flanking blocking this creature** gets -1/-1
    # until end of turn." (Knight of Valor.) A narrowing with no hand-written
    # test of its own below travels as the whole noun-phrase description and is
    # answered by the one matcher — which is also the only thing that can
    # answer these two: "without flanking" is a layer-6 question (CR 613.1f)
    # and "blocking this creature" is a relation to the ability's own source,
    # and neither is readable off the permanent alone.
    #
    # Emitted by the lowering only when there is something to carry, so every
    # card compiled before this key existed takes the same path it always did.
    described = instruction.payload.get("filter")
    # "Choose a creature type. All creatures **of that type** get -1/-1 until
    # end of turn." (Outbreak.) The word the step in front of this one wrote
    # into the scratchpad (CR 608.2d), resolved here the way Extinction's sweep
    # resolves its own — and with that sweep's rule: **no word means no
    # sweep**. A missing record read as "no narrowing" is not a card that does
    # less, it is one that shrinks every creature on the table.
    chosen_subtype = None
    scratch_key = instruction.payload.get("subtype_filter_from")
    if scratch_key is not None:
        chosen_subtype = context.results.get(str(scratch_key))
        if not chosen_subtype:
            game.log.append(f"{card.name}: no creature type was chosen")
            return True, "resolved"
    # "Creatures **target player** controls get +1/+1 until end of turn." (Day.)
    # The seat the announcement chose (CR 601.2c), asked of ``subject_matches``
    # with that seat in hand — the reader the tap, destroy and animation sweeps
    # over the same printed phrase use. With no seat to answer it the word
    # refuses, so the sweep reaches nobody rather than everybody.
    scoped_to = instruction.payload.get("controller")
    targeted_seat = (
        game.players.index(context.target)
        if context.target is not None and context.target in game.players
        else None
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
            if scoped_to is not None and not subject_matches(
                game, perm, {"controller": scoped_to},
                observer=game.players.index(caster),
                targeted_player=targeted_seat,
            ):
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
            # The chosen word, through the same layer-4 reader: a creature
            # made a Zombie this turn is one of "that type".
            if chosen_subtype and not perm.has_type(str(chosen_subtype)):
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
            # Last, because it is the general answer and the keys above are the
            # specific ones: a description that reaches here has already been
            # checked for anything a hand-written test covers, and what is left
            # is exactly what only ``subject_matches`` can read.
            if described is not None and not subject_matches(
                game, perm, described,
                observer=game.players.index(caster),
                source=context.source_permanent,
            ):
                continue
            apply_temp_pt_boost(perm, power_delta, toughness_delta)
    game.log.append(f"{card.name} buffed matching creatures")
    return True, "resolved"


@effect_handler("pump_block_pair")
def pump_block_pair(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**the blocking creature** gets -1/-1 until end of turn." (CR 702.25a's
    definition of flanking, built by ``engine/flanking.py``.)

    The P/T twin of ``keywords.grant_keyword_to_block_pair``, and it reads the pair
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


@effect_handler("pump_event_subject")
def pump_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a Sliver becomes blocked, **that Sliver** gets +1/+1 until end
    of turn for each creature blocking it." (Spined Sliver.)

    ``pump_target_creature_until_eot``'s subject read off the *event* instead of
    off a target, which is the same move ``remove_event_subject_keyword`` one
    screen down makes for a keyword: the trigger chose nothing, so the object is
    the one the fire site froze (CR 603.10) — by id, because by resolution the
    attacker may have been destroyed and a board search would find a look-alike.

    **The count is measured against that same permanent**, which is the whole
    reason this cannot be an existing kind with a flag. One sentence, two
    pronouns, and both name the creature that became blocked; the ability's own
    source is a *different* Sliver whenever the trigger watched somebody else's
    (the condition is "a Sliver", not "this creature"), and counting around the
    source would then have read the wrong creature's blockers. So the frozen
    permanent is handed to ``count_from_payload`` as its source, and
    ``blocking_source`` resolves against it.

    CR 509.3c is the fire site's business, not this handler's: a creature
    becomes blocked **once** however many creatures block it, so this resolves
    once and the number of blockers is the size of the boost rather than the
    number of firings.

    The printed noun phrase is re-checked here rather than trusted from the
    announcement, for the reason every other rebound subject is: the words the
    lowering carried are the words that have to hold when the ability resolves.
    """
    from ..subject_filters import subject_matches

    bound = (context.trigger_context or {}).get("event_subject_permanent_id")
    subject = game.permanent_by_id(bound) if isinstance(bound, int) else None
    if subject is None or not game.is_on_battlefield(subject):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    described = instruction.payload.get("filter")
    if described and not subject_matches(
        game, subject, described,
        observer=game.players.index(context.caster),
        source=context.source_permanent,
    ):
        game.log.append(
            f"{context.card.name}: {subject.card.name} no longer answers the clause"
        )
        return True, "resolved"
    x_value = context.x_value
    x_count = instruction.payload.get("x_from_count")
    if isinstance(x_count, dict):
        x_value = count_from_payload(game, context, x_count, source=subject)
    # The sign is already inside the ``times_x`` amount the lowering built, so
    # the negation flags ``pump_self`` reads are deliberately not consulted —
    # the same double-negation trap Johtull Wurm sprang one package over.
    power_delta = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness_delta = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    until = str(instruction.payload.get("duration") or "end_of_turn")
    apply_temp_pt_boost(subject, power_delta, toughness_delta, until=until)
    game.log.append(
        f"{context.card.name} gives {subject.card.name} "
        f"{power_delta:+d}/{toughness_delta:+d} until " + until.replace("_", " ")
    )
    return True, "resolved"
