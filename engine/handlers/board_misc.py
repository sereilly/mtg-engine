from __future__ import annotations

from typing import TYPE_CHECKING

from ..land_types import MIRE_COUNTER, change_land_type
from ..layer_bridge import GAINED_TYPES
from ..models import CardDefinition, Permanent
from ..oracle_types import OracleInstruction
from ..pt import set_base_pt
from ..text_changes import LAND_TYPE_WORDS, change_color_word, change_land_word
from ..tokens import make_token_card
from ._common import permanent_matches_filter, resolve_amount, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


@effect_handler("create_emblem")
def create_emblem(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You get an emblem with "<ability>"." (CR 114.2.) The emblem lives on
    its owner's ``emblems`` list — the engine's command zone — as a dict plus a
    detached Permanent whose card carries the text, which is what lets the
    trigger machinery fire it like any permanent's ability (CR 114.4)."""
    caster = context.caster
    text = str(instruction.payload.get("text", ""))
    name = f"{context.card.name} Emblem"
    emblem_card = CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Emblem",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )
    caster.emblems.append({
        "name": name,
        "oracle_text": text,
        "source_name": context.card.name,
        "_permanent": Permanent(card=emblem_card),
    })
    game.log.append(f'{caster.name} gets an emblem: "{text}"')
    return True, "resolved"


@effect_handler("create_delayed_trigger")
def create_delayed_trigger(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A resolving ability creating a delayed triggered ability (CR 603.7):
    "Whenever one or more nontoken creatures attack this turn, …" (Basri Ket's
    −2). The entry waits on ``game.delayed_triggers``; the declare-attackers
    step fires it, and cleanup clears "this turn" entries."""
    payload = instruction.payload
    game.delayed_triggers.append({
        "controller_index": game.players.index(context.caster),
        "event": payload.get("event", "creatures_attack"),
        "batch": bool(payload.get("batch")),
        "nontoken": bool(payload.get("nontoken")),
        # "…whenever **a creature you control with power 2 or less** deals
        # combat damage to a player" (Subira). The narrowing travels as the same
        # filter payload every other one does; both fire sites ask
        # `subject_matches`, which has the seat "you control" needs. Empty means
        # no narrowing, which is what Basri Ket's entries carry.
        "attacker_filter": dict(payload.get("attacker_filter") or {}),
        "instruction": payload.get("instruction"),
        "source_name": context.card.name,
        "card": context.card,
        "duration": payload.get("duration", "end_of_turn"),
    })
    game.log.append(f"{context.card.name} set up a delayed trigger for this turn")
    return True, "resolved"


@effect_handler("gain_control_until_eot")
def gain_control_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Gain control of target creature until end of turn." (Traitorous Greed.)

    A CR 613 layer-2 *contribution* with a lifetime rather than a move, so
    nothing has to be put back: cleanup drops the contribution and whatever
    remains decides. ``base_controller_index`` is untouched, which is what makes
    the reversion correct and CR 108.3 ownership still read off the original
    seat.

    The contribution belongs to the **spell**, not to a permanent — there is no
    permanent to belong to — so the card is its source. Two copies in one turn
    collapse to one contribution, which is the right answer: both end at the same
    cleanup.
    """
    from ..control import change_control

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: permanent_matches_filter(perm, filters),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent to gain control of")
        return True, "resolved"
    seat = game.players.index(context.caster)
    change_control(target, seat, source=context.card, until_eot=True)
    game._sync_control()
    context.results["controlled_permanent"] = target.permanent_id
    # The sentences after this one are *about the same creature* ("Untap that
    # creature. It gains haste…"), and it is now on a different battlefield.
    # `context.target` is the seat the remaining steps resolve their target id
    # against — deliberately scoped, so a stale id cannot resolve to a permanent
    # that changed hands between the choice and the resolution. This effect is
    # what changed those hands, one step ago, so the scope is updated rather than
    # widened: the id still has to name a permanent that seat controls.
    context.target = context.caster
    game.log.append(
        f"{context.caster.name} gains control of {target.card.name} until end of turn"
    )
    return True, "resolved"


@effect_handler("steal_target_permanent_linked_to_self")
def steal_target_permanent_linked_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Aladdin: "Gain control of target artifact for as long as you control
    this creature." The control change is a CR 613 layer-2 contribution keyed
    on Aladdin itself (not on an Aura), so ON_LEAVE_BATTLEFIELD["Aladdin"] ends
    it with end_control_changes_from when Aladdin leaves the battlefield."""
    caster = context.caster
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # Guardian Beast: "other players can't gain control of" the artifacts it
    # protects.
    target_perm = resolve_target_permanent(
        game,
        context,
        predicate=lambda p: p.has_type("artifact") and not game._untapped_artifact_protector_active(p),
    )
    if target_perm is None:
        game.log.append(f"{card.name}: no valid artifact target")
        return True, "resolved"
    if not game.take_control(target_perm, caster, source=source_permanent):
        return True, "resolved"
    game.log.append(f"{card.name} gains control of {target_perm.card.name}")
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


@effect_handler("add_corpse_counters_for_each_creature_died")
def add_corpse_counters_for_each_creature_died(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Scavenging Ghoul: "At the beginning of each end step, put a corpse counter on
    this creature for each creature that died this turn." Resolves off the stack; the
    death count is captured in trigger_context at fire time."""
    source = context.source_permanent
    count = int((context.trigger_context or {}).get("count", 0))
    if source is None or count <= 0:
        return True, "resolved"
    source.metadata["corpse_counters"] = int(source.metadata.get("corpse_counters", 0)) + count
    game.log.append(f"{source.card.name} gets {count} corpse counter(s)")
    return True, "resolved"


@effect_handler("sacrifice_if_no_creatures")
def sacrifice_if_no_creatures(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Pestilence-style: "At the beginning of the end step, if there are no creatures
    on the battlefield, sacrifice this." Resolves off the stack; the intervening-if is
    re-checked at resolution (CR 603.4)."""
    source = context.source_permanent
    if source is None:
        return True, "resolved"
    has_creatures = any(p.is_creature for p in game.all_permanents())
    if has_creatures:
        return True, "resolved"
    if game.sacrifice_permanent(source) is not None:
        game.log.append(f"{source.card.name} sacrificed at end step (no creatures)")
    return True, "resolved"


@effect_handler("end_step_damage_if_not_attacked")
def end_step_damage_if_not_attacked(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Erg Raiders: "At the beginning of your end step, if this creature
    didn't attack this turn, it deals 2 damage to you unless it came under
    your control this turn." Both guards are re-checked at resolution (CR
    603.4), matching the Pestilence intervening-if precedent."""
    source = context.source_permanent
    caster = context.caster
    if source is None or caster is None:
        return True, "resolved"
    if source.metadata.get("attacked_this_turn"):
        return True, "resolved"
    if source.metadata.get("summoning_sickness_turn") == game.turn:
        return True, "resolved"
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    game._deal_damage_to_player(
        caster, amount, source=source,
        then=lambda dealt: game.log.append(
            f"{source.card.name} dealt {dealt} damage to {caster.name}"
        ),
    )
    return True, "resolved"


@effect_handler("balance_resources")
def balance_resources(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    def _count(player, kind):
        return sum(1 for perm in game.controlled_by(player) if perm.card.primary_type == kind)

    min_lands = min(_count(p, "land") for p in game.players)
    min_creatures = min(_count(p, "creature") for p in game.players)
    min_hand = min(len(p.hand) for p in game.players)

    # Build the per-player reduction plan. Each player chooses which of their own
    # lands/creatures to sacrifice and which cards to discard down to these counts;
    # defer to a pending choice (human is prompted, AI/headless auto-resolves).
    plans: dict[int, dict] = {}
    for idx, player in enumerate(game.players):
        plan = {
            "lands": max(0, _count(player, "land") - min_lands),
            "creatures": max(0, _count(player, "creature") - min_creatures),
            "hand": max(0, len(player.hand) - min_hand),
        }
        if plan["lands"] or plan["creatures"] or plan["hand"]:
            plans[idx] = plan

    if not plans:
        game.log.append("Balance: nothing to normalize")
        return True, "resolved"

    # Each player owes their own removals, so each gets their own queued choice.
    for idx, plan in plans.items():
        game.arm_pending_choice("balance", idx, plan=plan)
    game.log.append("Balance: each player chooses what to sacrifice and discard")
    return True, "pending_balance"


# Mana symbol → the basic land type Magical Hack names. The chosen replacement
# type is passed through as the cast's "new color"; the mapping itself lives
# with the text-change API, which is what has to know the words.
_SYMBOL_TO_LAND_TYPE = LAND_TYPE_WORDS


@effect_handler("mark_text_modified")
def mark_text_modified(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    # Resolve the actual targeted permanent (default to the first one).
    target_perm = None
    if perm_idx is not None and 0 <= perm_idx < len(target.battlefield):
        target_perm = target.battlefield[perm_idx]
    elif target.battlefield:
        target_perm = target.battlefield[0]
    if target_perm is not None:
        target_perm.metadata["text_modified"] = True

    mode = instruction.payload.get("mode")
    new_symbol = (context.choices.get("new_color") or "").upper()
    old_symbol = (context.choices.get("old_color") or "").upper()

    # Magical Hack: "replacing all instances of one basic land type with
    # another". One text change (CR 612.1 / 613 layer 3), whatever the permanent
    # is: on a land the word is in the type line, so the land's subtypes and the
    # mana ability CR 305.6 gives it change; on a creature it is in the rules
    # text, so "swampwalk" becomes "islandwalk" — including inside a lord's
    # grant line. It does NOT change the permanent's color.
    if mode == "land_type":
        new_type = _SYMBOL_TO_LAND_TYPE.get(new_symbol)
        old_type = _SYMBOL_TO_LAND_TYPE.get(old_symbol)
        if old_type is None and target_perm is not None:
            # A cast that named only the replacement (a headless or AI cast, and
            # every call site before the "from" word existed): on a land the
            # word being replaced can only be the type it currently has.
            current = target_perm.basic_land_types
            old_type = current[0] if len(current) == 1 else None
        if target_perm is not None and new_type and old_type:
            # Magical Hack rewrites existing words: the old land type must
            # actually be written somewhere on the permanent. That covers a
            # printed type line ("Basic Land — Mountain"), a printed landwalk
            # (Bog Wraith's "Swampwalk") and a land word inside a granted
            # ability (Goblin King's "Other Goblins … have mountainwalk") — but
            # never grants islandwalk from nothing (White Knight). The
            # *effective* text, so a second Hack rewrites what the first wrote.
            effective = target_perm.effective_card
            written = " ".join(
                (effective.type_line, effective.oracle_text, *effective.keywords)
            ).lower()
            if old_type in written:
                change_land_word(target_perm, old_type, new_type, label=card.name)
                game.log.append(
                    f"{card.name} changed {old_type} to {new_type} in {target_perm.card.name}'s text"
                )
                game._recalculate_lord_buffs()
            else:
                game.log.append(
                    f"{card.name} had no effect: {target_perm.card.name} has no"
                    f" {old_type.title()} land type in its text"
                )
        return True, "resolved"

    # Sleight of Mind: replace one color word with another in the target's text.
    # Recorded as an ordered layer-3 contribution and applied once, by
    # Permanent.effective_card. It does NOT recolor the permanent.
    if mode == "color_word":
        if target_perm is not None and change_color_word(
            target_perm, old_symbol, new_symbol, label=card.name
        ):
            game.log.append(f"{card.name} changed {old_symbol} text to {new_symbol} on {target_perm.card.name}")
        return True, "resolved"

    game.log.append(f"{card.name} applied a text change effect")
    return True, "resolved"


@effect_handler("recolor_target_from_text")
def recolor_target_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    symbol = str(instruction.payload.get("target_color", ""))
    # "Target spell or permanent becomes [color]" — a spell on the stack is a
    # legal target (the Lace cards). Recolor it via the stack item's color override.
    if context.stack_target is not None and symbol:
        context.stack_target.choices["new_color"] = symbol
        game.log.append(f"{context.stack_target.card.name} (on the stack) became {symbol}")
        return True, "resolved"
    target = context.target
    perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
    changed = game._apply_color_override(target, symbol, target_permanent_index=perm_idx) if symbol else False
    game.log.append("Changed target color" if changed else "No valid permanent to recolor")
    return True, "resolved"


@effect_handler("change_target_land_type")
def change_target_land_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Honor a specifically chosen land (e.g. a player selected the target land
    # in the UI). Fall back to the first land the target player controls.
    target_land = resolve_target_permanent(
        game, context, predicate=lambda p: p.card.primary_type == "land"
    )
    if target_land is not None:
        land_type = str(instruction.payload.get("land_type", "forest"))
        # "...until this creature leaves the battlefield." The contribution is
        # keyed on the source, so the revert hook drops exactly this one and
        # whatever else says the land is something (an Evil Presence Swamp)
        # reasserts itself (CR 611.3).
        source = context.source_permanent
        change_land_type(
            target_land, land_type, source=source, label=context.card.name
        )
        game.log.append(f"{target_land.card.name} became a Forest")
        if source is not None:
            forested = source.metadata.setdefault("forested_lands", [])
            if not any(land is target_land for land in forested):
                forested.append(target_land)
        # Forest count just changed; recompute characteristic-defining P/T now so
        # Gaea's Liege reflects the new total immediately (not at the next step).
        game._refresh_dynamic_creatures()
    else:
        game.log.append("No target land for Forest effect")
    return True, "resolved"


def _is_swamp(perm: Permanent) -> bool:
    return perm.has_type("swamp")


@effect_handler("add_mire_counter_to_target_land")
def add_mire_counter_to_target_land(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Cyclopean Tomb: "Put a mire counter on target non-Swamp land. That land is
    a Swamp for as long as it has a mire counter on it."

    The mire counter both flags the land and overrides its type to Swamp (CR 305.7).
    The source artifact records each land it mires so its rest-of-game cleanup
    trigger (see ON_LEAVE_BATTLEFIELD) knows which lands to undo when it dies.
    """
    # Honor the explicitly chosen land when one was targeted.
    target_land = resolve_target_permanent(
        game, context, predicate=lambda p: p.card.primary_type == "land" and not _is_swamp(p)
    )
    if target_land is None:
        game.log.append("No valid non-Swamp land for mire counter")
        return True, "resolved"

    target_land.metadata["mire_counter"] = True
    # Keyed on the counter, not on the Tomb: "for as long as it has a mire
    # counter on it" outlives the artifact that put it there.
    change_land_type(
        target_land, "swamp", source=MIRE_COUNTER, label=context.card.name
    )
    game.log.append(f"{target_land.card.name} got a mire counter and became a Swamp")

    # Remember this land on the activating artifact so its death trigger can later
    # remove the mire counter "for the rest of the game".
    source = context.source_permanent
    if source is not None:
        mired = source.metadata.setdefault("mired_lands", [])
        if target_land not in mired:
            mired.append(target_land)
    return True, "resolved"


#: The one record a self-animation leaves, read by the CR 613 layer bridge and
#: swept at cleanup. A dict rather than a flag because the animation carries what
#: the permanent *becomes* — a creature, of some subtypes, with some keywords —
#: and a flag could only say that it became something.
ANIMATE_UNTIL_EOT = "animate_until_end_of_turn"


@effect_handler("animate_self_until_eot")
def animate_self_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…becomes a 3/3 Sphinx creature with flying in addition to its other
    types until end of turn." (Riddleform, CR 613 layers 4, 6 and 7b.)

    The P/T is set through `engine/pt.py`, the single write API; everything else
    is *recorded* and read back by the layer bridge, so nothing is stashed and
    restored — the animation ends by the record being swept at cleanup, and the
    permanent's own types were never touched.

    "In addition to its other types" is why the record adds rather than
    replaces: the enchantment is still an enchantment while it is a creature.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    payload = instruction.payload
    set_base_pt(source, int(payload.get("power", 0)), int(payload.get("toughness", 0)))
    source.metadata[ANIMATE_UNTIL_EOT] = {
        "subtypes": list(payload.get("subtypes") or ()),
        "keywords": list(payload.get("keywords") or ()),
    }
    game.log.append(
        f"{context.card.name} becomes a "
        f"{payload.get('power', 0)}/{payload.get('toughness', 0)} creature until end of turn"
    )
    return True, "resolved"


@effect_handler("animate_self_until_end_of_combat")
def animate_self_until_end_of_combat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    set_base_pt(
        source_permanent,
        int(instruction.payload.get("power", 0)),
        int(instruction.payload.get("toughness", 0)),
    )
    source_permanent.metadata["animate_until_end_of_combat"] = True
    game.log.append(f"{card.name} is animated until end of combat")
    return True, "resolved"


@effect_handler("create_copy_token")
def create_copy_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Create a token that's a copy of target creature you control."
    (Sublime Epiphany.)

    What a token is and what a copy is are two rules, and both live one layer
    down: ``Game.create_token_copy`` performs them, because CR 613 layer 1 is
    applied in exactly one module and this handler is not it.

    What is decided *here* is the printed phrase. The filter is enforced rather
    than trusted, and the target is strict (CR 608.2b): a target that has left,
    or that no longer answers "creature you control", makes no token at all.
    There is nothing sensible to fall back to — a copy of some other creature is
    not a smaller version of this effect, it is a different one.
    """
    from ..subject_filters import subject_matches

    caster = context.caster
    controller_index = game.players.index(caster)
    described = dict(instruction.payload.get("filter") or {})

    def _legal(perm) -> bool:
        return not described or subject_matches(
            game, perm, described,
            observer=controller_index, source=context.source_permanent,
        )

    # No ``fallback_players``: a scan for *some* legal creature is what makes an
    # illegal choice quietly succeed, and CR 608.2b says an illegal target makes
    # that part of the spell do nothing. Copying a different creature is not a
    # smaller version of this effect.
    source = resolve_target_permanent(
        game, context, fallback_on_invalid_choice=False, predicate=_legal,
    )
    if source is None:
        game.log.append(f"{context.card.name}: no legal creature to copy")
        return True, "resolved"

    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    for _ in range(max(0, count)):
        game.create_token_copy(controller_index, source)
        game.log.append(
            f"{context.card.name} created a token copy of {source.card.name}"
        )
    return True, "resolved"


@effect_handler("create_token")
def create_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Generic token creation: payload carries name / P/T / type_line / colors /
    keywords / count ("x" resolves to the cast's X). Tokens are stamped
    ``is_token`` so they cease to exist instead of hitting the graveyard
    (CR 704.5d / 111.7)."""
    caster = context.caster
    card = context.card
    payload = instruction.payload
    controller_index = game.players.index(caster)
    # "Its controller creates …" (Angelic Ascension, Secure the Scene): the
    # token goes to the controller the exile step of this same resolution
    # recorded. No record means nothing was exiled — the referent never
    # existed, so no token either (CR 608.2b's "does as much as it can" cuts
    # both ways: there is no controller to hand a token to).
    if payload.get("recipient") == "exiled_permanent_controller":
        recorded = context.results.get("exiled_permanent_controller")
        if not isinstance(recorded, int):
            game.log.append(f"{card.name}: nothing was exiled, so no token is created")
            return True, "resolved"
        controller_index = recorded
    # A predefined token (a Treasure) carries its own printed text and has no
    # P/T at all — CR 208.1 gives P/T to creatures, and 0/0 would be a creature
    # card that dies the moment anything animates it.
    printed_power = payload.get("power")
    printed_toughness = payload.get("toughness")
    # "Create an **X/X** … token, where X is the number of …" (Experimental
    # Overload). The where-clause's count is already resolved into the context's
    # X by the time this runs, so both halves read the one number. Taken **now**
    # and then fixed onto the token's card: a token has no
    # characteristic-defining ability, so a card later leaving the graveyard
    # does not shrink it (CR 608.2 counts at resolution).
    if printed_power == "x" or printed_toughness == "x":
        counted = max(0, int(context.x_value or 0))
        printed_power = counted if printed_power == "x" else printed_power
        printed_toughness = counted if printed_toughness == "x" else printed_toughness
    token_card = make_token_card(
        str(payload.get("name", "Token")),
        None if printed_power is None else int(printed_power),
        None if printed_toughness is None else int(printed_toughness),
        str(payload.get("type_line", "Creature — Token")),
        colors=tuple(payload.get("colors") or ()),
        keywords=tuple(payload.get("keywords") or ()),
        oracle_text=payload.get("oracle_text"),
        image_source=card,
    )
    # "that many" — a delayed attack trigger's batch count (Basri Ket's −2),
    # carried in the firing event's trigger context.
    raw_count = payload.get("count", 1)
    if raw_count == "trigger_count":
        tctx = context.trigger_context or {}
        count = int(tctx.get("trigger_count", context.results.get("trigger_count", 0)))
    elif isinstance(raw_count, dict) and "history" in raw_count:
        # "…for each nontoken creature that died this turn" (Gadrak): the game's
        # own tally, because the objects counted are exactly the ones no zone
        # still holds. Which tally the phrase named is settled at lowering; an
        # unknown one makes no tokens rather than falling back to a wider count.
        count = int(getattr(game, str(raw_count["history"]), 0) or 0)
    else:
        count = resolve_amount(raw_count, context.x_value)
    # "**Each opponent** creates …" (Pursued Whale). Who gets the tokens, which
    # for every earlier token card is the effect's own controller. A seat that
    # has left the game gets none (CR 800.4a).
    recipients = [controller_index]
    who = payload.get("recipient_players")
    if who == "each_opponent":
        recipients = list(game.opponents_of(controller_index))
    elif who == "each_player":
        recipients = [i for i, p in enumerate(game.players) if not p.lost]
    for seat in recipients:
      for _ in range(count):
        token = Permanent(card=token_card, metadata={"is_token": True})
        game._put_permanent_onto_battlefield(seat, token, None)
        # "…that are tapped and attacking" (Basri Ket): entry state, not an
        # attack declaration — the tokens join the combat the trigger saw
        # (CR 111.10c-style entry), attacking whatever seat is already under
        # attack.
        if payload.get("tapped"):
            token.tapped = True
        if payload.get("attacking") and game.current_turn_phase == "combat":
            defending = (context.trigger_context or {}).get("trigger_defending_player_index")
            if not isinstance(defending, int):
                defending = next(iter(sorted(game.combat_defending_players())), None)
            if isinstance(defending, int):
                slot = game.battlefield_index_of(token)
                if slot is not None:
                    game.combat_attackers[slot] = defending
                    token.attacking = True
                    token.defending_player_index = defending
    if count == 1:
        game.log.append(f"{card.name} created a {token_card.name} token")
    elif count > 1:
        game.log.append(f"{card.name} created {count} {token_card.name} tokens")
    return True, "resolved"


@effect_handler("cast_face_down_creature")
def cast_face_down_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Illusionary Mask: arm a pending choice for the controller to pick a creature
    card in hand whose mana cost X could pay (cmc <= X), to cast face down as a 2/2.
    The actual cast happens in confirm_face_down_cast; the choice is optional."""
    caster = context.caster
    card = context.card
    controller_index = game.players.index(caster)
    max_cmc = max(0, int(context.x_value or 0))
    eligible = [c for c in caster.hand if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc]
    if not eligible:
        game.log.append(f"{card.name}: no eligible creature in hand to cast face-down (X={max_cmc})")
        return True, "resolved"
    game.arm_pending_choice(
        "face_down_cast", controller_index, max_cmc=max_cmc, card_name=card.name
    )
    game.log.append(f"{card.name}: choose a creature (mana value <= {max_cmc}) to cast face down")
    return True, "resolved"


@effect_handler("remove_loyalty_from_each_planeswalker")
def remove_loyalty_from_each_planeswalker(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Remove two loyalty counters from each planeswalker." (Pestilent Haze's
    second mode.) Loyalty is its counters (CR 306.5c); the walkers this
    empties are collected by the state-based sweep (CR 704.5i) after the
    spell finishes, not here."""
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    touched = 0
    for permanent in game.all_permanents():
        if not permanent.has_type("planeswalker"):
            continue
        current = int(permanent.metadata.get("loyalty_counters", 0))
        permanent.metadata["loyalty_counters"] = max(0, current - amount)
        touched += 1
        game.log.append(
            f"{context.card.name}: {permanent.card.name} loses {amount} loyalty "
            f"({permanent.metadata['loyalty_counters']} left)"
        )
    if not touched:
        game.log.append(f"{context.card.name}: no planeswalkers to strip")
    return True, "resolved"


@effect_handler("add_named_counter_to_self")
def add_named_counter_to_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a soul counter on this Equipment." (Malefic Scythe.)

    CR 122.1: a counter with no rules meaning of its own. What it means is
    whatever the card's *other* lines say about it — here, +1/+1 to the equipped
    creature per counter, read by the layer bridge off this same store. The
    counter is the state; the meaning is elsewhere, which is why this handler
    knows nothing but the word.
    """
    from ..named_counters import add_counters

    source = context.source_permanent
    if source is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    total = add_counters(source, counter, count)
    game.log.append(
        f"{source.card.name} gets a {counter} counter ({total} total)"
    )
    return True, "resolved"


@effect_handler("remove_counter_from_self")
def remove_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Armageddon Clock: "Remove a doom counter from this artifact."

    The counter's name is payload, matching the accumulation side
    (phases/upkeep_effects.py), so the pair is one template rather than a card.
    Removing from zero is a no-op, not a negative count.
    """
    permanent = context.source_permanent
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "doom"))
    key = f"{counter}_counters"
    current = int(permanent.metadata.get(key, 0))
    if current <= 0:
        game.log.append(f"{permanent.card.name} has no {counter} counter to remove")
        return True, "resolved"
    permanent.metadata[key] = current - 1
    game.log.append(
        f"Removed a {counter} counter from {permanent.card.name} "
        f"({permanent.metadata[key]} left)"
    )
    return True, "resolved"


@effect_handler("sacrifice_matching_permanent")
def sacrifice_matching_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Sacrifice a creature" / "sacrifice another creature" as an effect a
    player performs (Dire Fleet Warmonger's accepted cost; Goremand's entry
    trigger; Run Afoul's "a creature of their choice with flying"). Routed
    through ``arm_forced_sacrifice``: a human seat picks which through the
    standing prompt, everyone else takes the deterministic heuristic.

    ``who`` names the payers — absent means the effect's own controller, which
    is what a bare imperative means (CR 109.5). "Each opponent" arms the same
    prompt for each of them, still living, in seat order so the AI simulation
    stays seed-reproducible. The two targeted forms are the seat the spell
    already chose; they stay apart in the payload because CR 115.4 makes "target
    opponent" and "target player" different spells, and only the picker cares.

    An unrecognized ``who`` fails the instruction rather than defaulting to the
    controller: silently sacrificing the caster's own creature instead of the
    named player's is the wrong direction to guess in.
    """
    caster_index = game.players.index(context.caster)
    exclude = context.source_permanent if instruction.payload.get("exclude_self") else None
    who = instruction.payload.get("who")
    if who is None:
        payers = [caster_index]
    elif who == "each_opponent":
        payers = list(game.opponents_of(caster_index))
    elif who in ("target_opponent", "target_player"):
        payers = [game.players.index(context.target)]
    else:
        return False, f"unsupported sacrifice payer {who!r}"
    for seat in payers:
        game.arm_forced_sacrifice(
            seat, 1,
            filter=dict(instruction.payload.get("filter") or {}),
            exclude=exclude,
            reason=context.card.name,
        )
    return True, "resolved"


@effect_handler("gain_type")
def gain_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ashnod's Transmogrant: "That creature becomes an artifact in addition to
    its other types." Xenic Poltergeist: "Until your next upkeep, target
    noncreature artifact becomes an artifact creature with power and toughness
    each equal to its mana value."

    Nothing on the permanent's own card is touched. The gained type is a record
    the CR 613 bridge reads on every recompute (`layer_bridge.GAINED_TYPES`),
    so the permanent stops being an artifact by the record going away rather
    than by anything being restored — the same shape Animate Artifact and the
    board-wide statics already use, and the reason none of them has to stash an
    original type line.

    A duration of "permanent" is the absent one, and it is what Ashnod's
    Transmogrant prints: the creature is still an artifact long after the
    Transmogrant has been sacrificed to pay for it.
    """
    payload = instruction.payload
    filters = (payload.get("targets") or {}).get("filter") or {}

    def _eligible(perm: Permanent) -> bool:
        return permanent_matches_filter(perm, filters)

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_players=(context.target, context.caster)
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"

    record = {
        "card_types": list(payload.get("card_types") or ()),
        "duration": str(payload.get("duration", "permanent")),
        "pt_from_mana_value": bool(payload.get("pt_from_mana_value")),
        "source": context.card.name if context.card else "effect",
        # "…until **your** next upkeep" — whose upkeep ends it. Recorded when
        # the ability resolves rather than looked up when it expires: by then
        # the source may be gone, and CR 109.5 makes this the controller of the
        # ability, not of the permanent it was pointed at.
        "seat": game.players.index(context.caster) if context.caster in game.players else 0,
    }
    target_perm.metadata.setdefault(GAINED_TYPES, []).append(record)
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} becomes "
        + " ".join(record["card_types"])
    )
    return True, "resolved"
