from __future__ import annotations

from typing import TYPE_CHECKING

from ..continuous import next_timestamp
from ..delayed_triggers import (END_OF_TURN, DelayedTrigger,
                                arm_delayed_trigger)
from ..land_types import MIRE_COUNTER, change_land_type
from ..layer_bridge import GAINED_TYPES
from ..models import CardDefinition, Permanent
from ..oracle_types import (CHOSEN_TARGET_PERMANENTS, COUNTERS_REMOVED,
                            LAST_TARGET_CONTROLLER,
                            X_FROM_COUNT_PER_RECIPIENT, OracleInstruction)
from ..exiled_records import source_object
from ..named_counters import counters_on, remove_counters
from ..pt import pt_counter_key, set_base_pt
from ..text_changes import LAND_TYPE_WORDS, change_color_word, change_land_word
from ..tokens import (CREATED_TOKEN_RESULT_KEY, CREATED_WITH_PERMANENT_ID,
                     make_token_card, tokens_created_with)
from ._common import (BLOCK_PAIR_SUBJECT, SUBJECT_FROM_TRIGGER,
                      block_pair_permanents, bound_permanent, evaluate_count,
                      permanent_matches_filter,
                      resolve_amount, resolve_target_permanent,
                      resolve_target_permanents, seats_matching_deed)
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


@effect_handler("choose_target_permanent")
def choose_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose target creature." (Reincarnation, Glyph of Life.)

    Nothing happens here, and nothing should: the target was chosen as the
    spell was cast (CR 601.2c), and this sentence prints no effect. The
    instruction exists so ``engine/targeting.py`` can see what the spell
    targets in the compiled program — the sentence that *uses* the chosen
    creature is the next one, which reads the same context.

    It still refuses when the target is gone (CR 608.2b), so the log says the
    spell found nothing rather than saying nothing at all.
    """
    if resolve_target_permanent(game, context) is None:
        game.log.append(f"{context.card.name} had no legal target")
        return True, "no target"
    return True, "resolved"


@effect_handler("choose_target_permanents")
def choose_target_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose X target attacking creatures." (Winter's Chill.)

    The plural of :func:`choose_target_permanent`, and it records where that one
    does not have to: the sentence behind a single choice reads the target off
    the context the way every handler does, and a *set* has nowhere to be read
    from — nothing about a board says which attacking creatures a spell named,
    and by the time the loop runs one of them may no longer be attacking.

    Each slot is re-checked against the printed noun phrase, which is CR 608.2b
    at resolution: a creature that has left combat is no longer a legal target
    and simply is not in the set. An empty set is a legal outcome (every target
    illegal is refused above the instructions, in ``legality``), and the loop
    behind this walks nothing.
    """
    described = dict((instruction.payload.get("targets") or {}).get("filter") or {})
    chosen = resolve_target_permanents(
        game, context,
        predicate=lambda perm: permanent_matches_filter(perm, described),
    )
    context.results[CHOSEN_TARGET_PERMANENTS] = chosen
    if (instruction.payload.get("targets") or {}).get("same_controller"):
        # "…**controlled by the same opponent**. **That player** chooses and
        # sacrifices one of those creatures." (Retribution.) The sentence names
        # a player, and this step is the only one that can say which: the
        # relation is what makes the answer a single seat, and by the sentence
        # after it one of the creatures is on its way to a graveyard. Written
        # under the key every other "the player this effect chose" is written
        # under (`_chooser_seat`'s ``chosen_player``), so the prompt behind it
        # needs no reader of its own.
        seats = {game.controller_index_of(perm) for perm in chosen}
        if len(seats) == 1:
            seat = seats.pop()
            if seat is not None:
                # The literal every other handler that writes this key spells
                # (`control_changes`, `damage`); it is declared in
                # `grammar/lowering/_events.CHOSEN_PLAYER`, which the handler
                # layer does not import from.
                context.results["chosen_player"] = seat
    if not chosen:
        game.log.append(f"{context.card.name} had no legal targets")
        return True, "no target"
    game.log.append(
        f"{context.card.name} chose "
        + ", ".join(perm.card.name for perm in chosen)
    )
    return True, "resolved"


@effect_handler("create_delayed_trigger")
def create_delayed_trigger(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A resolving spell or ability creating a delayed triggered ability
    (CR 603.7) — Basri Ket's −2, Mana Drain's mana, Reincarnation's death
    watch. Every field of the entry is payload; what it is *about* is bound
    here, while the creating effect still knows.

    ``engine/delayed_triggers.py`` holds the entry, the registry of events that
    have a fire site, and the one routine that fires them.
    """
    payload = instruction.payload
    seat = game.players.index(context.caster)
    # CR 603.7c: "that creature" is the permanent this spell targeted, read now
    # — by resolution time of the *delayed* ability it may be in a graveyard,
    # and an index would by then address whatever slid into its slot.
    bound_id = None
    watched_id = None
    # "…when **Stangg** leaves the battlefield" / "…when **that token** leaves
    # the battlefield" (Stangg). The opener names an object this effect already
    # holds rather than one it chose, so there is no target to resolve: the
    # source is on the context, and the token is the id the token maker wrote
    # to the scratchpad a step ago.
    #
    # An id that is not there arms **nothing**. Left unbound the entry would
    # match the *first* permanent to leave the battlefield, which is the
    # widening every bound-object payload in this engine exists to prevent.
    watches = payload.get("watches")
    if watches is not None:
        if watches == "source":
            watched_id = (
                context.source_permanent.permanent_id
                if context.source_permanent is not None else None
            )
        elif watches == "created_token":
            recorded = (context.results or {}).get(CREATED_TOKEN_RESULT_KEY)
            watched_id = recorded if isinstance(recorded, int) else None
        if watched_id is None:
            game.log.append(
                f"{context.card.name} had no permanent to watch"
            )
            return True, "no object"
    recorded_key = payload.get("binds_recorded")
    if recorded_key is not None:
        # "…**Exile it** at the beginning of the next end step." (Shallow
        # Grave, Zirilan of the Claw.) CR 603.7c's object, read out of the
        # record an earlier step of *this* resolution wrote — the permanent
        # it put onto the battlefield, which nothing targeted and which does
        # not exist until that step runs.
        #
        # An empty record arms **nothing**, for `watches`' reason one branch
        # up: an unbound entry would answer to the first permanent the event
        # names, which is the widening every bound payload here prevents.
        ids = (context.results or {}).get(str(recorded_key))
        if isinstance(ids, int):
            ids = (ids,)
        bound_id = next(
            (found for found in (ids or ()) if isinstance(found, int)), None
        )
        if bound_id is None:
            game.log.append(
                f"{context.card.name} had no permanent to be about"
            )
            return True, "no object"
    elif payload.get("binds_target"):
        # The **innermost** binding, not the resolution's target list: inside
        # "for each of those creatures, … destroy that creature at end of
        # combat" (Winter's Chill) the ability is created once per creature and
        # is about that one. Outside a loop this is the target the spell chose,
        # which is every other card that arms one.
        bound = bound_permanent(game, context)
        if bound is None:
            # The target is gone (CR 608.2b): there is nothing for the delayed
            # ability to be about, so none is created.
            game.log.append(f"{context.card.name} had no creature to watch")
            return True, "no target"
        bound_id = bound.permanent_id
    # The two roles are one object on every card that names only one, which is
    # every card but War Barge. Collapsed here rather than at the comparison, so
    # the entry states outright what it watches and what it is about instead of
    # leaving one of them to be inferred.
    if bound_id is None:
        bound_id = watched_id
    if watched_id is None:
        watched_id = bound_id
    # CR 608.2h's last-known information, frozen at creation. The resolution
    # scratchpad *is* what
    # this effect's earlier steps knew — Mana Drain's countered spell and its
    # mana value — and by the time the ability fires, a phase or a turn later,
    # not one of those objects is still where it was. Frozen whole rather than
    # key by key, because a list of which values a delayed ability might read
    # is a list that goes stale the moment a new one prints.
    # What the *creating* ability knew is both halves: its own scratchpad and
    # the context its fire site froze. "Whenever a creature dealt damage by this
    # creature this turn dies, put that card onto the battlefield … at the
    # beginning of the next end step" (Seraph) reads the dead card out of the
    # second half, and only the second half — a trigger's context is not a
    # resolution record and nothing had ever carried it across a delay.
    #
    # The trigger context goes *under* the scratchpad, so a value this
    # resolution actually produced wins over one the event merely reported.
    captured = {**(context.trigger_context or {}), **(context.results or {})}
    # "Choose target opponent. … When it regenerates this way, **that player**
    # may draw a card." (Soldevi Sentry.) The seat an earlier step of this same
    # resolution chose, read out of the scratchpad under the one key a chosen
    # player is ever written to. An entry that binds a player and has none
    # arms nothing, for the reason a bound *object* that is gone does: the
    # ability would otherwise be about whichever seat the firing resolution
    # happened to carry.
    bound_seat = None
    binds_player = payload.get("binds_player")
    if binds_player:
        # The literal, for the reason `choose_permanent` above spells it: the
        # key is declared in `grammar/lowering/_events.CHOSEN_PLAYER`, and the
        # handler layer does not import from the grammar's lowering package.
        #
        # "…at the beginning of **their** next upkeep" (Sabertooth Cobra) binds
        # a seat the creating *trigger* named rather than one an earlier step
        # chose, so the key says which record — the damage event's frozen
        # recipient, stamped by `damage_events._announce`. Two records, one
        # field, and the payload is what says which: read as the chosen-player
        # one it would find nothing and arm no ability at all.
        recorded = (
            (context.trigger_context or {}).get("defending_player_index")
            if binds_player == "damaged_player"
            else (context.results or {}).get("chosen_player")
        )
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{context.card.name} had no player to watch")
            return True, "no player"
        bound_seat = recorded
    arm_delayed_trigger(game, DelayedTrigger(
        bound_player_index=bound_seat,
        controller_index=seat,
        event=payload.get("event", "creatures_attack"),
        instruction=payload.get("instruction"),
        source_name=context.card.name,
        card=context.card,
        bound_permanent_id=bound_id,
        watched_permanent_id=watched_id,
        # CR 603.7d's source, frozen now: an activated ability's own permanent
        # is what "this creature" means when the delay finally fires.
        source_permanent_id=(
            context.source_permanent.permanent_id
            if context.source_permanent is not None else None
        ),
        captured=captured,
        # "…whenever **a creature you control with power 2 or less** attacks"
        # (Subira). The narrowing travels as the same filter payload every
        # other one does; the fire sites ask `subject_matches`, which has the
        # seat "you control" needs. Empty means no narrowing.
        subject_filter=dict(payload.get("subject_filter") or {}),
        agent_filter=dict(payload.get("agent_filter") or {}),
        once=bool(payload.get("once")),
        duration=payload.get("duration", END_OF_TURN),
        batch=bool(payload.get("batch")),
        nontoken=bool(payload.get("nontoken")),
    ))
    game.log.append(f"{context.card.name} created a delayed triggered ability")
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
    # "target **white enchantment you control that doesn't have cumulative
    # upkeep**" (Balduvian Shaman). The Lace cycle prints no narrowing at all
    # and carries no description, so this is the whole of the check for it; a
    # card that does print one is held to it here as well as at the picker, for
    # the reason the grant handlers next door state — a picker and a resolution
    # that disagree are a target the player may announce and the effect then
    # declines to affect.
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    if described and not subject_matches(
        game, target_perm, described,
        # CR 109.5: "you control" is the seat whose ability this is, and
        # `context.caster` is that seat for a spell and an activation alike.
        observer=game.seat_index(context.caster),
        source=context.source_permanent,
    ):
        game.log.append(f"{card.name}: no legal permanent to change the text of")
        return True, "resolved"
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
    # "…replacing all instances of one color word with another **or** one basic
    # land type with another." (Mind Bend.) The card offers both vocabularies
    # and its controller picks (CR 612.1) — a decision made as the spell
    # resolves, so it goes on the pending-choice queue rather than being
    # guessed here. The words themselves were already named at the cast, and
    # both readings of a mana symbol are legal: "R" is red *and* Mountain.
    if mode == "color_word_or_land_type":
        if target_perm is None:
            game.log.append(f"{card.name}: no permanent to change the text of")
            return True, "resolved"
        game.arm_text_change_vocabulary(
            game.seat_index(context.caster), target_perm,
            old_symbol, new_symbol, card.name,
        )
        return True, "resolved"

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
    # "…that creature becomes green" on a block trigger (Aisling Leprechaun):
    # nobody targeted it, the firing bound it, and which half fired decides how
    # it is found — `block_pair_permanents` is the one reader of that.
    if instruction.payload.get(SUBJECT_FROM_TRIGGER) == BLOCK_PAIR_SUBJECT:
        # The permanent is already in hand, so the indefinite colour channel is
        # written directly — `_apply_color_override` beside it takes a *player*
        # and picks a permanent off their battlefield, which is the wrong
        # question once the trigger has named one. Same channel, same layer 5
        # read (`engine/layer_bridge.py`), and no duration: Aisling Leprechaun's
        # reminder text says the effect lasts indefinitely.
        recoloured = block_pair_permanents(game, context) if symbol else []
        for perm in recoloured:
            perm.metadata["color_override"] = symbol
            game.log.append(f"{perm.card.name} became {symbol} ({context.card.name})")
        if not recoloured:
            game.log.append(f"{context.card.name}: no creature to recolour")
        return True, "resolved"
    # The Lace cycle's permanent half, resolved by id — "target permanent", so
    # the predicate is every permanent rather than the resolver's creature
    # default. The index it used to pass named a slot, and a slot is not a
    # target once anything has left the battlefield (CR 400.7).
    changed = game._apply_color_override(
        resolve_target_permanent(
            game, context, player=context.target, predicate=lambda p: True,
        ),
        symbol,
    ) if symbol else False
    game.log.append("Changed target color" if changed else "No valid permanent to recolor")
    return True, "resolved"


@effect_handler("recolor_target_chosen_color")
def recolor_target_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target permanent you control becomes the color of your choice."
    (Alchor's Tomb.)

    A colour *replacement* like the lace kind beside it, and indefinite like
    Aisling Leprechaun's — the difference is only where the colour comes from.
    CR 609.3 makes the choice part of the effect, so nothing in the text names
    it and the answer arrives on ``context.choices["new_color"]``, the same
    channel Feat of Resistance's "protection from the color of your choice"
    reads. An unanswered choice recolours nothing rather than defaulting to a
    colour: a permanent that became a colour nobody picked is the wrong colour,
    and doing nothing is the honest failure.

    The printed noun phrase is enforced here, not assumed. The filter travels on
    the payload and is asked through ``subject_matches`` because "you control" is
    a seat rather than a property of the card — dropping it would let the ability
    recolour an opponent's permanent, which is a restriction the picker showed
    and the resolution ignored.
    """
    from ..subject_filters import subject_matches

    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = game.players.index(context.caster)
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(game, perm, filters, observer=observer),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent to recolour")
        return True, "resolved"
    if instruction.payload.get("several"):
        # "Target permanent becomes the color **or colors** of your choice."
        # (Prismatic Lace.) A *set* is offered, and the activation wire carries
        # one symbol — so the question goes on the standing queue, the same
        # prompt Shyft's trigger already uses one branch over. Asked here
        # rather than read off ``choices["new_color"]`` because a single symbol
        # is one legal answer to the offer and not the offer itself: taking it
        # would quietly make "or colors" mean "a color" on every printing.
        # "**Your** choice" is the spell's controller (CR 109.5), never the
        # permanent's — Prismatic Lace is aimed at any permanent on the table
        # and the colour is picked by whoever cast it.
        game.arm_color_set_choice(
            observer,
            permanent=target,
            card_name=context.card.name,
            several=True,
        )
        return True, "resolved"
    symbol = game._normalize_mana_color((context.choices or {}).get("new_color"))
    if symbol is None:
        game.log.append(
            f"{context.card.name}: no colour was chosen, so nothing is recoloured"
        )
        return True, "resolved"
    target.metadata["color_override"] = symbol
    game.log.append(f"{target.card.name} became {symbol} ({context.card.name})")
    return True, "resolved"


@effect_handler("recolor_self_chosen_color")
def recolor_self_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may have this creature become the color or colors of your choice."
    (Shyft.)

    The third subject in the chosen-colour family, and the only one whose choice
    is made during a *triggered* ability's resolution — the other two are
    activated, so their colour rides the activation on ``choices["new_color"]``
    and is in hand by the time the handler runs. Nothing announces a trigger's
    colour, so this one asks: the standing ``color_set_choice`` prompt, on the
    ability's controller.

    The prompt takes a **set**, because "the color **or colors**" offers one
    (CR 105.2 makes a two-coloured object one object). Layer 5 has written a
    tuple since Dream Coat; what did not exist was a way for a player to name
    more than one.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    seat = game.controller_index_of(source_permanent)
    if seat is None:
        return True, "resolved"
    game.arm_color_set_choice(
        seat,
        permanent=source_permanent,
        card_name=context.card.name,
        several=bool(instruction.payload.get("several")),
    )
    return True, "resolved"


@effect_handler("recolor_enchanted_chosen_color")
def recolor_enchanted_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Enchanted creature becomes the color or colors of your choice."
    (Dream Coat.)

    The sibling of ``recolor_target_chosen_color`` above, differing only in
    *which* permanent it recolours: an Aura's activated ability acts on what it
    is attached to (CR 303.4), which the activator does not choose. Read as a
    target the sentence refused and the ability compiled to nothing.

    CR 609.3 puts the colour choice in the resolution, so the answer arrives on
    ``context.choices["new_color"]`` — the same channel every other chosen
    colour in the engine reads. ``several`` says the card offered a *set*
    (CR 105.2, "the color **or colors**"): the write takes any number, so a
    channel carrying "WU" makes a white-and-blue creature, and the one symbol
    the activation wire carries today is one legal answer to that offer rather
    than a narrowing of it. An unanswered choice recolours nothing, because a
    permanent that became a colour nobody picked is the wrong colour.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    enchanted = source_permanent.metadata.get("attached_to")
    if enchanted is None:
        return False, "aura not attached to a permanent"
    answer = (context.choices or {}).get("new_color")
    parts = answer if isinstance(answer, (list, tuple)) else [answer]
    symbols = [
        symbol for symbol in (game._normalize_mana_color(part) for part in parts)
        if symbol
    ]
    if not symbols:
        game.log.append(
            f"{context.card.name}: no colour was chosen, so nothing is recoloured"
        )
        return True, "resolved"
    # A tuple whenever the card offered a set, so layer 5 writes every colour
    # rather than the first — and a bare symbol otherwise, which is what every
    # writer before this one put on the channel.
    enchanted.metadata["color_override"] = (
        tuple(symbols) if instruction.payload.get("several") else symbols[0]
    )
    game.log.append(
        f"{enchanted.card.name} became {'/'.join(symbols)} ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("recolor_targets_until_eot")
def recolor_targets_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"One or more target creatures become <colour> until end of turn."
    (Dwarven Song, Heaven's Gate, Sea Kings' Blessing, Sylvan Paradise, Touch of
    Darkness.)

    A colour *replacement* like the Lace cycle above (CR 105.2: "becomes" is
    not "in addition"), but with a duration and with several targets. It writes
    the until-end-of-turn channel, which layer 5 reads beside the indefinite one
    and the cleanup step sweeps — so a creature laced permanently earlier in the
    game keeps its colour when this wears off.

    A target that is no longer legal is simply skipped (CR 608.2b); the rest of
    the effect still happens, which is what `resolve_target_permanents` gives
    without a per-slot fallback that would recolour the same creature twice.
    """
    written = _colour_override_value(instruction.payload.get("target_color"))
    if written is None:
        return True, "resolved"
    targets = resolve_target_permanents(game, context)
    if not targets:
        game.log.append(f"{context.card.name}: no creature to recolour")
        return True, "resolved"
    for perm in targets:
        perm.metadata["color_override_until_eot"] = written
        game.log.append(
            f"{perm.card.name} became {_colour_override_word(written)} until end "
            f"of turn ({context.card.name})"
        )
    return True, "resolved"


def _colour_override_value(printed):
    """What a "becomes <colour>" payload writes into the layer-5 channel.

    A mana symbol for a colour, and the **empty tuple** for colourless: CR 105.2c
    makes colourless the absence of colour, so the object is given no colours
    rather than a sixth one. That is why `collect_color_effects` tests the key
    against None rather than for truthiness — an empty set of colours is a real
    answer, and every writer of the channel already refuses to write a falsy
    symbol by accident.

    None when the payload names nothing at all, which is the "do nothing" the
    truthiness test used to give and the one case that is not a colour change.
    """
    from ..grammar.ast import COLORLESS

    if printed == COLORLESS:
        return ()
    symbol = str(printed or "")
    return symbol or None


def _colour_override_word(written) -> str:
    """The channel value as the log should print it."""
    return "colorless" if written == () else str(written)


@effect_handler("recolor_self_until_eot")
def recolor_self_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{2}: This creature becomes colorless until end of turn." (Raging Spirit.)

    The source-subject twin of ``recolor_targets_until_eot``: same channel, same
    sweep, and no target to resolve because the sentence names none.
    """
    written = _colour_override_value(instruction.payload.get("target_color"))
    source = context.source_permanent
    if written is None or source is None:
        return True, "resolved"
    source.metadata["color_override_until_eot"] = written
    game._recompute_continuous_effects()
    game.log.append(
        f"{source.card.name} became {_colour_override_word(written)} until end of turn"
    )
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

#: Its indefinite twin (Mishra's Groundbreaker, CR 611.2a). A **second key**
#: rather than a flag inside the record above, because what separates the two is
#: exactly which sweep can see it: `mixins/_constants._EOT_METADATA_KEYS` clears
#: the first at cleanup and knows nothing about the second. A flag would have
#: meant teaching that sweep to read the record it is deleting, which is the one
#: thing a key list cannot do.
ANIMATE_INDEFINITELY = "animate_indefinitely"


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
        "card_types": list(payload.get("card_types") or ()),
    }
    _record_animation_colors(source, payload, until_eot=True)
    game.log.append(
        f"{context.card.name} becomes a "
        f"{payload.get('power', 0)}/{payload.get('toughness', 0)} creature until end of turn"
    )
    return True, "resolved"


#: How long a recorded land-type change lasts, as the untap step reads it.
#: "Until its controller's next untap step" (Orcish Farmer) — the sweep is in
#: `engine/phases/untap_step.py`, and a record with no sweep behind it would be
#: a land permanently something else.
LAND_TYPE_UNTIL_UNTAP = "until_controllers_next_untap_step"

#: Its twin, one turn boundary earlier. "Target land becomes the basic land
#: type of your choice **until end of turn**" (Jinx) — the sweep is in
#: `engine/phases/cleanup_step.py`, beside every other until-end-of-turn record,
#: and the same rule holds: the lowering admits this duration only because that
#: sweep exists.
LAND_TYPE_UNTIL_EOT = "until_end_of_turn"


@effect_handler("animate_target_indefinitely")
def animate_target_indefinitely(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target land becomes a 3/3 artifact creature that's still a land. (This
    effect lasts indefinitely.)" (Mishra's Groundbreaker, CR 611.2a.)

    The same animation as its until-end-of-turn twin below, written to the key
    the cleanup sweep does not clear and with the P/T on the **persistent**
    channel rather than the ``_until_eot`` one. Those are the only two
    differences, and both of them are the duration: a record on the swept key
    would end the effect the turn it started, and a P/T on the swept channel
    would leave a land that is a creature with no size — a 0/0 CR 704.5f puts
    in the graveyard at the next state-based check.

    Sharing the twin's body through :func:`_animate_target`, because which
    permanent it reaches, which narrowing it tests and what it logs are one
    question asked twice; only the record differs.
    """
    return _animate_target(
        game, instruction, context,
        record_key=ANIMATE_INDEFINITELY, until_eot=False, duration="indefinitely",
    )


@effect_handler("animate_target_until_eot")
def animate_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target snow land becomes a 2/2 creature until end of turn. It's still a
    land." (Balduvian Conjurer, CR 613 layers 4 and 7b.)

    The targeted twin of ``animate_self_until_eot`` above and the *same*
    record: an animation is one metadata entry the layer bridge reads, so
    animating something else is that entry on a different permanent and not a
    second mechanism. `engine/land_animation.py` is the third spelling of the
    same idea — a board-wide static recomputed from the board — and it is a
    table rather than an instruction for exactly that reason.

    "It's still a land" needs no code: the record *adds* types (CR 613 layer 4
    addition, not CR 305.7's replacement), so the land keeps everything it had.

    The P/T goes on the ``_until_eot`` channel, which the cleanup sweep clears
    alongside the type record — the source-animating sibling writes the
    persistent one, which is harmless on a permanent that stops being a
    creature the same moment but would leave a stamp on someone else's land.
    """
    return _animate_target(
        game, instruction, context,
        record_key=ANIMATE_UNTIL_EOT, until_eot=True, duration="until end of turn",
    )


def _record_animation_colors(perm, payload: dict, *, until_eot: bool) -> None:
    """"…becomes a 2/2 **green** creature" (Quirion Druid): CR 613 layer 5 of
    an animation sentence.

    A separate channel from the animation record because it is a separate
    layer, and the *same* channel the laces write — "what colour is this
    permanent?" has one answer (``layer_bridge.collect_color_effects``), and an
    animation inventing a second would be two opinions about CR 105.3.

    Which of the two colour channels is the animation's own duration, for the
    reason the P/T write takes ``until_eot``: an indefinite animation whose
    colour wore off at cleanup would leave a green creature that is no longer
    green, and a turn-long one whose colour did not would leave the colour
    behind on a land that had stopped being a creature.

    Absent ``colors`` writes nothing at all. A sentence that named no colour
    said nothing about colour, which is not CR 105.2c's colourless — and
    writing an empty override would make every animated Assembly-Worker
    forcibly colourless.
    """
    colors = list(payload.get("colors") or ())
    if not colors:
        return
    perm.metadata["color_override_until_eot" if until_eot else "color_override"] = colors


def _animate_target(
    game: Game,
    instruction: OracleInstruction,
    context: OracleExecutionContext,
    *,
    record_key: str,
    until_eot: bool,
    duration: str,
) -> tuple[bool, str]:
    """Both targeted animations: find the target, write the record, log it.

    One body because the two kinds differ only in *how long* — which permanent
    is reached, which narrowing is tested and what the log says are the same
    question either way, and a second copy of the target resolution is a second
    chance to disagree about what the printed noun phrase names.
    """
    from ..subject_filters import subject_matches

    filt = (instruction.payload.get("targets") or {}).get("filter") or {}
    target = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: subject_matches(
            game, perm, filt,
            observer=game.controller_index_of(context.source_permanent)
            if context.source_permanent is not None else None,
            source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no land to animate")
        return True, "resolved"
    payload = instruction.payload
    power, toughness = int(payload.get("power", 0)), int(payload.get("toughness", 0))
    set_base_pt(target, power, toughness, until_eot=until_eot)
    target.metadata[record_key] = {
        "subtypes": list(payload.get("subtypes") or ()),
        "keywords": list(payload.get("keywords") or ()),
        "card_types": list(payload.get("card_types") or ()),
    }
    _record_animation_colors(target, payload, until_eot=until_eot)
    game.log.append(
        f"{target.card.name} becomes a {power}/{toughness} creature "
        f"{duration} ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("animate_matching_until_eot")
def animate_matching_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Forests you control become 2/3 creatures until end of turn. They're
    still lands." (Thelonite Druid, CR 613 layers 4 and 7b.)

    The swept twin of ``animate_target_until_eot`` above and the *same* record:
    an animation is one metadata entry the layer bridge reads, so animating a
    described set is that entry on every member and not a second mechanism.

    Which permanents is asked of ``subject_matches``, not of the pure matcher:
    "Forests **you control**" is a seat comparison no read of the land alone can
    make, and the observer is CR 109.5's — the controller of the ability, never
    whoever controls what it reaches. The lowering gates on the same key set, so
    a phrase this cannot test never arrives here; a dropped narrowing on a sweep
    is not an animation that does less, it is one that takes the board.

    CR 611.2c fixes the set when the ability resolves: a Forest played
    afterwards is not animated, and one that leaves takes its own record with
    it. The P/T goes on the ``_until_eot`` channel, which the cleanup sweep
    clears alongside the type record.
    """
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items()
        if key not in (
            "power", "toughness", "subtypes", "keywords", "card_types", "colors",
        )
    }
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    payload = instruction.payload
    power, toughness = int(payload.get("power", 0)), int(payload.get("toughness", 0))
    record = {
        "subtypes": list(payload.get("subtypes") or ()),
        "keywords": list(payload.get("keywords") or ()),
        "card_types": list(payload.get("card_types") or ()),
    }
    animated = []
    for permanent in game.all_permanents():
        if not subject_matches(
            game, permanent, described,
            observer=observer, source=context.source_permanent,
        ):
            continue
        set_base_pt(permanent, power, toughness, until_eot=True)
        permanent.metadata[ANIMATE_UNTIL_EOT] = dict(record)
        _record_animation_colors(permanent, payload, until_eot=True)
        animated.append(permanent)
    if not animated:
        game.log.append(f"{context.card.name}: nothing to animate")
        return True, "resolved"
    game.log.append(
        f"{context.card.name} animated "
        + ", ".join(perm.card.name for perm in animated)
        + f" as {power}/{toughness} creatures until end of turn"
    )
    return True, "resolved"


@effect_handler("change_land_type_until")
def change_land_type_until(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target land becomes a Swamp until its controller's next untap step."
    (Orcish Farmer, CR 305.7 / CR 613 layer 4.)

    A *replacement* of the land's basic land types, recorded as a contribution
    keyed on this ability's source — so when the untap step drops it, whatever
    else says the land is something (an Evil Presence Swamp) reasserts itself
    rather than the printed type line coming back.

    The source is the **permanent**, but the record has to survive that
    permanent leaving: "until its controller's next untap step" says nothing
    about the Farmer. So the contribution is keyed on a per-activation label
    rather than on the permanent, and the untap sweep drops it by that label.
    """
    from ..subject_filters import subject_matches

    filt = (instruction.payload.get("targets") or {}).get("filter") or {}
    seat = (
        game.controller_index_of(context.source_permanent)
        if context.source_permanent is not None else None
    )
    target = resolve_target_permanent(
        game,
        context,
        predicate=lambda perm: subject_matches(
            game, perm, filt, observer=seat, source=context.source_permanent
        ),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no land to change")
        return True, "resolved"
    land_type = str(instruction.payload.get("land_type", ""))
    duration = str(instruction.payload.get("duration", "permanent"))
    if duration == LAND_TYPE_UNTIL_UNTAP:
        # A label, not the permanent: the change outlives its source, and two
        # activations of the same Farmer aimed at two lands must not have the
        # second replace the first's contribution.
        source = f"{LAND_TYPE_UNTIL_UNTAP}:{next_timestamp()}"
    elif duration == LAND_TYPE_UNTIL_EOT:
        # A label for the same reason, and one this duration cannot do without:
        # Jinx is an *instant*, so ``context.source_permanent`` is None and two
        # copies would both key their contribution on None — the second
        # replacing the first, on a different land.
        source = f"{LAND_TYPE_UNTIL_EOT}:{next_timestamp()}"
    else:
        source = context.source_permanent
    if instruction.payload.get("choose_land_type"):
        # "…becomes **the basic land type of your choice**" (Jinx). CR 609.3
        # puts the choice inside the resolution, so nothing is recorded until
        # the seat answers — the prompt holds priority, and the change is made
        # by the resolver rather than here. The land travels by
        # ``permanent_id``: an index renumbers when anything leaves, and the
        # answer arrives after this handler has returned.
        game.arm_pending_choice(
            "land_type_choice", game.players.index(context.caster),
            card_name=context.card.name,
            land_permanent_id=target.permanent_id,
            land_type_source=source,
        )
        game.log.append(
            f"{context.card.name}: choose a basic land type for {target.card.name}"
        )
        return True, "resolved"
    change_land_type(target, land_type, source=source, label=context.card.name)
    game.log.append(
        f"{target.card.name} became a {land_type.title()} ({context.card.name})"
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
        token = game.create_token_copy(controller_index, source)
        # "When this enchantment leaves the battlefield, exile **the token**."
        # (Dance of Many.) Which permanent made this one, stamped for the same
        # reason `create_token` beside it stamps it: the sentences that name
        # the token belong to *other* abilities of the same permanent, fired
        # turns after the resolution that made it, so the resolution scratchpad
        # is long gone and nothing about the token itself records its maker.
        if context.source_permanent is not None:
            token.metadata[CREATED_WITH_PERMANENT_ID] = (
                context.source_permanent.permanent_id
            )
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
    if payload.get("recipient") == LAST_TARGET_CONTROLLER:
        recorded = context.results.get(LAST_TARGET_CONTROLLER)
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
    # "Create a black Spirit creature token. **Its power is equal to that
    # creature's power and its toughness is equal to that creature's
    # toughness.**" (Broken Visage.) Each half names a scratchpad key an earlier
    # step of this same resolution wrote — the destroy froze both numbers about
    # the creature it was aimed at, because by now that creature is a card in a
    # graveyard with no computed characteristics at all (CR 613.1).
    #
    # A key nothing wrote reads as zero, and a 0/0 creature token dies to
    # CR 704.5a the moment it arrives. That is the honest outcome and not a
    # silent one: the lowering refuses the sentence unless a step of the effect
    # declares the record, so the only way to reach it is a target that was
    # already gone when the spell resolved (CR 608.2b), where nothing should be
    # created anyway.
    for key, field in (("power_from", "power"), ("toughness_from", "toughness")):
        recorded = payload.get(key)
        if recorded is None:
            continue
        value = max(0, int(context.results.get(recorded, 0) or 0))
        if field == "power":
            printed_power = value
        else:
            printed_toughness = value
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
    elif isinstance(raw_count, dict) and "source_record" in raw_count:
        # "…for each time it regenerated this turn" (Spiny Starfish). A record
        # on the permanent whose ability this is, not a game-wide tally — so it
        # is read off the source rather than off the game, and a resolution with
        # no source permanent makes nothing rather than falling back to one.
        source = context.source_permanent
        count = (
            0 if source is None
            else int(source.metadata.get(str(raw_count["source_record"]), 0) or 0)
        )
    elif isinstance(raw_count, dict) and "history" in raw_count:
        # "…for each nontoken creature that died this turn" (Gadrak): the game's
        # own tally, because the objects counted are exactly the ones no zone
        # still holds. Which tally the phrase named is settled at lowering; an
        # unknown one makes no tokens rather than falling back to a wider count.
        count = int(getattr(game, str(raw_count["history"]), 0) or 0)
    elif isinstance(raw_count, dict) and "per_each" in raw_count:
        # "…for each untapped Forest **they** control" (Waiting in the Weeds).
        # A board count rather than a tally, and the one count here that is
        # taken **per recipient**: "they" is each player the sentence
        # distributes over, so the number is different for each of them and
        # cannot be computed in front of the loop. Left to the loop below,
        # which passes the seat it is making tokens for.
        count = 0
    else:
        count = resolve_amount(raw_count, context.x_value)
    # "**Each opponent** creates …" (Pursued Whale). Who gets the tokens, which
    # for every earlier token card is the effect's own controller. A seat that
    # has left the game gets none (CR 800.4a).
    recipients = [controller_index]
    who = payload.get("recipient_players")
    if who == "each_opponent":
        recipients = list(game.opponents_of(controller_index))
    elif who == "target_opponent":
        # "**Target** opponent creates …" (Phantasmal Sphere, Phelddagrif). The
        # seat chosen when the ability went on the stack (CR 115.4), read off
        # the context rather than guessed — with no target chosen there is
        # nobody the card names, and creating the token for the controller
        # instead would be the opposite of what it says.
        chosen = context.target
        recipients = [] if chosen is None else [game.seat_index(chosen)]
    elif who == "each_player":
        recipients = [i for i, p in enumerate(game.players) if not p.lost]
    elif who == "target_opponent":
        # "**Target opponent** creates a 1/1 green Hippo creature token."
        # (Phelddagrif.) One chosen seat rather than every opponent, read the
        # way every other targeted-seat handler reads it. A target that has
        # left the game makes no token (CR 800.4a) rather than falling back to
        # the controller, which would hand the tokens to the wrong side of the
        # card's own drawback.
        chosen = context.target
        recipients = (
            [game.players.index(chosen)]
            if chosen is not None and chosen in game.players and not chosen.lost
            else []
        )
    for seat in recipients:
      # The per-recipient count, evaluated here rather than above: "for each
      # untapped Forest **they** control" is a different number for each seat,
      # and evaluating it once would make every player create as many tokens as
      # the caster's own board carried. ``per_recipient`` false is the same
      # spec taken on the caster's board every time (nothing prints it yet, and
      # refusing it in the lowering would refuse a sentence this can answer).
      if isinstance(raw_count, dict) and "per_each" in raw_count:
          owner = game.players[seat] if raw_count.get("per_recipient") else caster
          count = evaluate_count(
              game, owner, raw_count["per_each"],
              source=context.source_permanent,
          )
      for _ in range(count):
        metadata: dict = {"is_token": True}
        # "…any number of tokens **created with this creature**." (Tetravus.)
        # Which permanent made the token is a fact about its history that
        # nothing about the token itself records, and it is stamped by
        # `permanent_id` rather than by identity: a Tetravus that leaves and
        # comes back is a new object (CR 400.7), and its old Tetravites were
        # not created with *it*.
        if context.source_permanent is not None:
            metadata[CREATED_WITH_PERMANENT_ID] = context.source_permanent.permanent_id
        token = Permanent(card=token_card, metadata=metadata)
        game._put_permanent_onto_battlefield(seat, token, None)
        # "…that are tapped and attacking" (Basri Ket): entry state, not an
        # attack declaration — the tokens join the combat the trigger saw
        # (CR 111.10c-style entry), attacking whatever seat is already under
        # attack.
        if payload.get("tapped"):
            token.tapped = True
        # "Create Stangg Twin, a … token. **Exile that token** when …"
        # (Stangg.) Which permanent this step made, for the sentences behind it
        # in the same resolution: a token is a new object with a fresh id
        # (CR 400.7), so nothing about it can be looked up afterwards.
        #
        # Written for every token maker, and deliberately the *last* one when
        # several are made: the phrase "that token" is singular, and the
        # lowering admits it only behind a maker — a card printing it after a
        # plural maker would be a card this engine has not met, and it would
        # arrive as one token addressed rather than as a silently wider effect.
        context.results[CREATED_TOKEN_RESULT_KEY] = token.permanent_id
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
    # "Put **X** charge counters on this artifact." (Ventifact Bottle.) The
    # cast's announced X, resolved through the same reader every other
    # amount in this engine uses — a printed number passes through it
    # unchanged, so every payload written before this is untouched.
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if count <= 0:
        # X may be announced as zero, which CR 122.1 places no counters for.
        return True, "resolved"
    total = add_counters(source, counter, count)
    game.log.append(
        f"{source.card.name} gets a {counter} counter ({total} total)"
    )
    return True, "resolved"


@effect_handler("add_named_counter_to_target")
def add_named_counter_to_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a matrix counter on target creature." (Life Matrix.)

    The chosen-permanent twin of ``add_named_counter_to_self``, and the same
    ignorance: the counter's word is payload and what it *means* is whatever the
    card's other lines — here, an ability the same sentence grants — say about
    it.

    The printed noun phrase is enforced here as well as at announcement,
    through ``subject_matches`` rather than a property read, because "you
    control" and "another" are questions about the board rather than about the
    card. A picker and a resolution that disagree are a target the player may
    announce and the effect then declines to affect.
    """
    from ..named_counters import add_counters
    from ..subject_filters import subject_matches
    from ._common import resolve_role_permanent, roles_still_legal

    from ._common import permanent_matches_filter

    observer = game.players.index(context.caster)
    source = context.source_permanent
    subject_role = instruction.payload.get("subject_role")
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        # "…return it to the battlefield under your control **and put a death
        # counter on it**." (Bogardan Phoenix.) Nothing was targeted: the
        # permanent did not exist when the trigger went on the stack, and the
        # step in front of this one is the only thing that can say which one it
        # is. The same ``permanents_from`` channel the P/T twin reads, through
        # the one reader that decides its arity.
        #
        # Nothing recorded is a legal outcome (the card was no longer in a
        # graveyard), not an error.
        from ._common import recorded_permanent_ids

        placed = 0
        for permanent_id in recorded_permanent_ids(context, recorded_key):
            returned = game.permanent_by_id(permanent_id)
            if returned is None:
                continue
            counter = str(instruction.payload.get("counter", ""))
            total = add_counters(
                returned,
                counter,
                resolve_amount(instruction.payload.get("count", 1), context.x_value),
            )
            placed += 1
            game.log.append(
                f"{returned.card.name} gets a {counter} counter ({total} total)"
            )
        if not placed:
            game.log.append(
                f"{context.card.name}: nothing was left to put a counter on"
            )
        return True, "resolved"
    if instruction.payload.get("on_event_subject"):
        # "Whenever a permanent becomes tapped, put a wind counter on **it**."
        # (Freyalise's Winds.) Nothing was chosen: the object is the one the
        # event was about, read by the id the announcement froze (CR 603.10) —
        # by resolution the permanent may have moved, and a board search would
        # find a look-alike. Kudzu's destroy reads the same key.
        subject_id = (context.trigger_context or {}).get(
            "event_subject_permanent_id"
        )
        target = (
            game.permanent_by_id(subject_id) if subject_id is not None else None
        )
        wanted = instruction.payload.get("filter") or {}
        if target is not None and wanted and not permanent_matches_filter(
            target, wanted
        ):
            target = None
    elif instruction.payload.get("on_block_pair"):
        # "Whenever this creature blocks a creature, put four fungus counters
        # on **that creature**." (Mindbender Spores.) The other half of the
        # block the trigger froze, read through the one function that knows how
        # the two fire sites bind it: on the *blocks* half the stack item's
        # target is the blocker itself, so the ordinary target resolution below
        # would put the counters on the source.
        from ._common import block_pair_permanents

        wanted = instruction.payload.get("filter") or {}
        target = next(
            (
                perm for perm in block_pair_permanents(game, context)
                if game.is_on_battlefield(perm)
                and (not wanted or permanent_matches_filter(perm, wanted))
            ),
            None,
        )
    elif subject_role is not None:
        # "Put X glyph counters on target creature that target Wall blocked
        # this turn" (Glyph of Delusion). Two targets of different kinds, so
        # which one takes the counters is the *role* the lowering named rather
        # than "the first slot" — and both are re-checked here, because CR
        # 608.2b re-checks every target and the relation between them is a
        # record either of them can take off the battlefield with it.
        target = resolve_role_permanent(
            game, context, instruction.payload, subject_role
        )
        if target is not None and not roles_still_legal(
            game, context, instruction.payload, observer=observer
        ):
            game.log.append(
                f"{context.card.name}: its targets are no longer legal"
            )
            return True, "resolved"
    else:
        filters = (instruction.payload.get("targets") or {}).get("filter") or {}
        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, filters, observer=observer, source=source
            ),
        )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent for a counter")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    total = add_counters(target, counter, count)
    game.log.append(
        f"{target.card.name} gets a {counter} counter ({total} total)"
        f" ({context.card.name})"
    )
    return True, "resolved"


#: The scratchpad key the combat-pair counter placement records its recipients
#: under. Spelled here and again in ``grammar/lowering/_events.py`` rather than
#: imported across the seam — a lowering may not reach into the handlers and a
#: handler may not reach into the grammar, and ``lowering/_records._PRODUCES``
#: is the declaration that holds the two spellings together.
PERMANENTS_GIVEN_COUNTERS = "permanents_given_counters"


@effect_handler("add_named_counter_to_creatures_in_combat_with_source")
def add_named_counter_to_creatures_in_combat_with_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put a paralyzation counter on each creature blocking or blocked by this
    creature." (Dread Wight.)

    The set is a combat relation to the ability's own source (CR 509), read
    from the combat maps rather than from any characteristic of the candidates
    — the same set ``destroy_creatures_in_combat_with_source`` (Abu Ja'far) and
    ``grant_keyword_to_creatures_in_combat_with_source`` (Spitting Slug) act on.

    It **records what it marked**, by id, because every sentence after it on
    this card names that set and none of them can work it out again: the
    trigger resolves during the end-of-combat step, and CR 511.2 removes every
    creature from combat as that step ends — so a second reading of the combat
    maps is a set that may already be empty.
    """
    from ..named_counters import add_counters

    # The relation as the fire site froze it (CR 603.10). Dread Wight's trigger
    # resolves in the priority window at the end of the end-of-combat step, and
    # CR 511.2 has taken every creature out of combat by then — so the combat
    # maps are the wrong place to ask, and the capture is the only right one.
    # The live read stays as the fallback for a source asked outside such a
    # trigger, which is what Spitting Slug's keyword twin does all the time.
    source = context.source_permanent
    victims = (context.trigger_context or {}).get("combat_opponents")
    if victims is None:
        if source is None:
            game.log.append(
                f"{context.card.name}: no source to read the combat from"
            )
            context.results[PERMANENTS_GIVEN_COUNTERS] = ()
            return True, "resolved"
        victims = game.creatures_in_combat_with(source)
    counter = str(instruction.payload.get("counter", ""))
    count = int(instruction.payload.get("count", 1))
    marked = []
    for perm in victims:
        # A creature that died to combat damage in the same event is gone; a
        # counter on it would be a counter on nothing, and it must not be
        # recorded for the sentences behind this one either.
        if not game.is_on_battlefield(perm):
            continue
        add_counters(perm, counter, count)
        marked.append(perm)
    # Written whether or not anything was marked: the record is what the
    # sentences behind this one read, and an *absent* key is a back-reference
    # with no producer, which is a different thing from a producer that found
    # nobody.
    context.results[PERMANENTS_GIVEN_COUNTERS] = tuple(
        perm.permanent_id for perm in marked
    )
    game.log.append(
        f"{context.card.name}: {len(marked)} creature(s) in combat with it get "
        f"a {counter} counter"
    )
    return True, "resolved"


@effect_handler("add_named_counter_to_attached")
def add_named_counter_to_attached(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…tap enchanted creature and put X sleep counters on **it**." (Venarian
    Gold.)

    The named-counter twin of ``add_pt_counters_to_attached``: the recipient is
    the permanent this Aura enchants — no target was chosen — and the counter's
    word is payload. The count may be "x", resolved against the cast's X the
    way every amount path resolves it; Venarian Gold's {X} is stamped on the
    Aura at cast and threaded to its enters trigger by the fire site.
    """
    from ..named_counters import add_counters
    from ._common import attached_host

    attached = attached_host(game, context.source_permanent)
    if attached is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    count = resolve_amount(instruction.payload.get("count", 1), context.x_value)
    if count <= 0:
        game.log.append(f"{context.card.name}: no {counter} counters to place")
        return True, "resolved"
    total = add_counters(attached, counter, count)
    game.log.append(
        f"{context.card.name}: {attached.card.name} gets "
        + (f"a {counter} counter" if count == 1 else f"{count} {counter} counters")
        + f" ({total} total)"
    )
    return True, "resolved"


@effect_handler("remove_counter_from_self")
def remove_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Armageddon Clock: "Remove a doom counter from this artifact."

    The counter's name is payload, matching the accumulation side
    (phases/upkeep_effects.py), so the pair is one template rather than a card.
    Removing from zero is a no-op, not a negative count.

    The source may be a card in **exile** rather than a permanent — All
    Hallow's Eve's upkeep trigger takes a scream counter off a card in a zone
    with no objects in it. ``exiled_records.source_object`` is the one reader
    that answers for both, and it answers with something carrying ``.card`` and
    ``.metadata``, which is all this function ever needed. The gate on the
    optional spelling of this same removal (``control_flow._action_is_takeable``)
    reads it too, so "is there a counter to remove" and "remove the counter"
    cannot disagree about where the counters are.
    """
    permanent = source_object(context)
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "doom"))
    # Through the one counter reader, not this file's own spelling of the key.
    # ``counters_on`` asks ``pt.pt_counter_key``, which is where a counter with
    # rules meaning is recorded (CR 122.1a) — reading ``"<kind>_counters"``
    # here would answer zero for exactly those kinds, silently, because a
    # missing key is a legal zero.
    current = counters_on(permanent, counter)
    if current <= 0:
        # The record "if you can't" reads (Cocoon): removing from zero is a
        # no-op, and it is also the removal *not happening*.
        context.results["removed_counter"] = False
        game.log.append(f"{permanent.card.name} has no {counter} counter to remove")
        return True, "resolved"
    context.results["removed_counter"] = True
    # Through the one removal seam (`named_counters.remove_counters`), which is
    # also what records that this was the *last* counter of its kind — Divine
    # Intervention's trigger reads that record from the state-based sweep.
    left = remove_counters(permanent, counter)
    game.log.append(
        f"Removed a {counter} counter from {permanent.card.name} "
        f"({left} left)"
    )
    return True, "resolved"


@effect_handler("move_counter_from_self")
def move_counter_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Move a +1/+1 counter from this enchantment onto target creature."
    (Afiya Grove.)

    **CR 121.6 makes this one action**, and that is the whole reason it is one
    handler rather than a ``sequence`` of the removal and the placement beside
    it: with no counter on the source the move does not happen at all, where
    two composed steps would put a counter on the target anyway — an Afiya
    Grove that never runs dry.

    The order is the rule too. The counter comes off first, so the number
    placed is the number actually taken; a source holding fewer than the
    sentence names gives up what it has and the target receives exactly that.

    Reads and writes through the shared counter seams
    (``named_counters.counters_on`` / ``remove_counters`` and
    ``Game.place_pt_counters``), so a P/T counter brings its layer 7c
    contribution with it in both directions (CR 122.1a) and the last-counter
    record every state trigger reads is written where it always is.
    """
    source = context.source_permanent
    if source is None:
        game.log.append(f"{context.card.name}: no permanent to move a counter from")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+1/+1"))
    wanted = int(instruction.payload.get("count", 1) or 1)
    held = counters_on(source, counter)
    if held <= 0:
        # CR 121.6: nothing to move means nothing happens — to *either* end.
        game.log.append(
            f"{source.card.name} has no {counter} counter to move"
        )
        return True, "resolved"
    moving = min(held, wanted)
    # The printed noun phrase, through the one reader the picker enumerated
    # with — Reality Ripple's lesson: a handler that pins a type the payload
    # does not say declines targets the picker legitimately offered.
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    creature = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, described,
            observer=game.players.index(context.caster), source=source,
        ),
    )
    if creature is None:
        # The destination has left (CR 608.2b). The counter stays where it is:
        # a move with nowhere to land is not a removal.
        game.log.append(f"{context.card.name}: nothing left to move a counter onto")
        return True, "no target"
    remove_counters(source, counter, moving)
    game.place_pt_counters(creature, counter, moving)
    game.log.append(
        f"Moved {moving} {counter} counter(s) from {source.card.name} "
        f"onto {creature.card.name}"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_bound")
def remove_all_counters_from_bound(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature leaves the battlefield or becomes untapped, remove
    all -1/-1 counters from the creature." (Giant Oyster.)

    :func:`remove_all_counters_from_self`'s bound-object twin, and its own kind
    for the reason ``destroy_bound_permanent`` is one: the object is the one the
    *creating* ability bound (CR 603.7c), carried by id in the delayed trigger's
    context, and the self-reading handler would empty the ability's own source
    instead — the Oyster rather than the creature it locked down.

    Through the same one removal seam (``named_counters.remove_counters``), so
    the P/T the counters were carrying (CR 122.1a, layer 7d) comes off with them
    and the emptied-kind record every state trigger reads is written.

    A creature already gone has no counters to take off, which is CR 608.2b
    doing as much as it can.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    held = counters_on(victim, counter)
    if held <= 0:
        game.log.append(
            f"{victim.card.name} has no {counter} counters to remove"
        )
        return True, "resolved"
    remove_counters(victim, counter, held)
    game.log.append(
        f"Removed all {held} {counter} counters from {victim.card.name} "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("remove_counters_from_bound")
def remove_counters_from_bound(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…remove a +1/+1 counter from **that creature** at the beginning of the
    next cleanup step." (Bounty of the Hunt.)

    :func:`remove_all_counters_from_bound`'s counted twin, and its own kind for
    that pair's stated reason one way round: "all" is a number nobody knows
    until the permanent is looked at, and a printed count lowered onto that
    handler would empty a permanent the card says to decrement by one.

    Through the same one removal seam (``named_counters.remove_counters``), so
    the P/T the counters were carrying (CR 122.1a, layer 7d) comes off with them
    and the emptied-kind record every state trigger reads is written.

    Takes as many as are there when fewer remain, which is CR 608.2b doing as
    much as it can — the creature may have lost counters to something else since
    the ability was created, and a creature already gone has none to take off.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    wanted = max(0, int(instruction.payload.get("amount", 1)))
    taking = min(wanted, counters_on(victim, counter))
    if taking <= 0:
        game.log.append(
            f"{victim.card.name} has no {counter} counters to remove"
        )
        return True, "resolved"
    remove_counters(victim, counter, taking)
    game.log.append(
        f"Removed {taking} {counter} counter(s) from {victim.card.name} "
        f"({context.card.name})"
    )
    return True, "resolved"


@effect_handler("remove_all_counters_from_self")
def remove_all_counters_from_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Remove all tide counters from it." (Homarid, Tidal Influence.)

    The emptying twin of :func:`remove_counter_from_self`, and its own kind
    because "all" is a number nobody knows until the permanent is looked at.
    Through the same one removal seam (``named_counters.remove_counters``), so
    the *last counter removed* record every state trigger reads is written here
    too — a hand-rolled ``metadata[key] = 0`` would empty the store and tell
    nobody.

    Removing from zero is a no-op, not a failure: CR 608.2b does as much as
    possible, and the rest of the resolution still runs.
    """
    permanent = source_object(context)
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", ""))
    held = counters_on(permanent, counter)
    if held <= 0:
        context.results["removed_counter"] = False
        # Zero is a real answer, and it has to be *written*: "add {C} for
        # each charge counter removed this way" over an empty artifact adds
        # nothing, and a missing record and a recorded zero must not be told
        # apart by the sentence behind this one.
        context.results[COUNTERS_REMOVED] = 0
        game.log.append(f"{permanent.card.name} has no {counter} counters to remove")
        return True, "resolved"
    context.results["removed_counter"] = True
    # "…remove all charge counters from it. **Add {C} for each charge counter
    # removed this way.**" (Ventifact Bottle.) How many came off, for the
    # sentence behind this one: by the time it runs the counters are gone, so
    # counting the artifact would be the exact complement of what it asks.
    context.results[COUNTERS_REMOVED] = held
    remove_counters(permanent, counter, held)
    game.log.append(
        f"Removed all {held} {counter} counters from {permanent.card.name}"
    )
    return True, "resolved"


@effect_handler("sacrifice_self")
def sacrifice_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…sacrifice it." where "it" is the ability's own source (Cocoon's
    hatch).

    Through ``Game.sacrifice_permanent`` — CR 701.21a's one transition — so the
    owner lookup, token cessation, would-die replacements, Aura teardown and
    death counts all happen. A source already gone is nothing to sacrifice
    (CR 608.2b does as much as possible), not a failure: the rest of the
    resolution still runs.

    Whether it happened is recorded under ``sacrificed_self``, the same shape
    ``exile_self`` uses and for the same reason: "Sacrifice this artifact. **If
    you do**, …" (Knowledge Vault) asks about the step before it, and a step
    that records nothing gives the branch nothing to test — the whole ability
    refuses to lower rather than guessing that it always happened.

    This kind used to have **no handler at all**: every card compiling it was
    a "when you control no Islands/lands" state trigger the CR 603.8 sweep in
    ``mixins/game_ending.py`` performs itself, and the generic dispatch
    reported "resolved without state mutation". That sweep still owns those
    triggers — it never executes instructions, so nothing fires twice.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to sacrifice")
        return True, "resolved"
    if game.sacrifice_permanent(source) is not None:
        context.results["sacrificed_self"] = True
        game.log.append(f"{context.card.name} was sacrificed")
    return True, "resolved"


@effect_handler("remove_any_number_of_counters_from_self")
def remove_any_number_of_counters_from_self(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Tetravus: "Remove **any number of** +1/+1 counters from this creature."

    Its own handler rather than a count on the one above, because the number is
    not on the card: its controller picks it at resolution, bounded by what is
    actually there (CR 701.x — you cannot remove counters that are not on the
    permanent). The choice suspends the resolution, so the sentence after it —
    "create **that many** … tokens" — runs against the answer rather than
    against a number nobody has given yet.

    What is removed is recorded under ``trigger_count``, which is the key the
    token maker's "that many" already reads.
    """
    permanent = context.source_permanent
    if permanent is None:
        return True, "resolved"
    counter = str(instruction.payload.get("counter", "+1/+1"))
    if counter != "+1/+1":
        # Only the +1/+1 store has a counted remover; a named counter would be
        # taken off a record this handler does not reach.
        game.log.append(
            f"{permanent.card.name}: no counted remover for {counter} counters"
        )
        return True, "resolved"
    available = int(permanent.metadata.get("plus_counters", 0))
    seat = game.controller_index_of(permanent)
    if seat is None or available <= 0:
        context.results["trigger_count"] = 0
        return True, "resolved"
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        minimum=0, maximum=available,
        # The "may" in front of this sentence has already asked whether to do it
        # at all, so a seat that got here said yes — and the default that keeps
        # faith with that answer is "all of them", not "none", which would make
        # accepting the offer do nothing.
        default_number=available,
        remove_counters=True, results=context.results,
    )
    return True, "resolved"


@effect_handler("exile_any_number_of_own_tokens")
def exile_any_number_of_own_tokens(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Tetravus: "Exile **any number of** tokens created with this creature."

    The set is found here rather than picked by a target picker, because the
    phrase names no target at all (CR 115.1b) — it names a set the game can
    identify, and asks its controller how many of it to take.

    **How many, not which.** Every token in that set was made by the same
    ability off the same permanent with the same characteristics, so which ones
    go is not a difference the game can observe; the ones taken are the
    oldest first, by `permanent_id`, so a replay is a replay. A card whose
    tokens could differ from one another would need a real picker, which is why
    the lowering admits this phrase and nothing wider.
    """
    source = context.source_permanent
    if source is None:
        return True, "resolved"
    owned = tokens_created_with(game, source)
    seat = game.controller_index_of(source)
    if seat is None or not owned:
        context.results["trigger_count"] = 0
        return True, "resolved"
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=source.card.name, permanent=source,
        minimum=0, maximum=len(owned),
        # The "may" in front of the sentence already asked whether to do this
        # at all; a seat that got here said yes, so the default takes all of
        # them rather than making the answer mean nothing.
        default_number=len(owned),
        exile_own_tokens=True, results=context.results,
    )
    return True, "resolved"




@effect_handler("sacrifice_permanents_totalling")
def sacrifice_permanents_totalling(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…sacrifice **any number of creatures with total power 12 or greater**."
    (Phyrexian Dreadnought.)

    Its own handler rather than a count on the forced-sacrifice prompt beside
    it, because the seat is being asked a different question: not "give up N of
    these" but "give up any set of these whose power adds up", which no number
    expresses — a set of five may pay where a set of six does not.

    The controller alone is asked (CR 109.5's bare imperative), and the price is
    checked against the *aggregate* rather than the count, through the same
    accessor every other reader of a creature's power uses so a pumped creature
    counts for what CR 613 says it is.
    """
    seat = game.players.index(context.caster)
    payload = dict(instruction.payload)
    payload["_source"] = context.source_permanent
    game.arm_aggregate_sacrifice(seat, payload, context)
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
    ``event_subject_player`` is the seat a trigger's own condition named
    (Mana Vortex's "each player's upkeep, **that player** sacrifices"), read
    off the context the fire site froze; ``event_subject_controller`` is the
    seat that controlled the *object* the event was about (Earthlink's "that
    creature's controller"), off the same context.

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
    elif who == "each_player":
        # "Each player sacrifices a third of the creatures they control of
        # their choice." (Pox.) `each_opponent` plus the caster, in seat order
        # so the AI simulation stays seed-reproducible — the same list the
        # branch above builds, over one more seat.
        payers = [
            seat for seat, player in enumerate(game.players) if not player.lost
        ]
    elif who in ("target_opponent", "target_player"):
        payers = [game.players.index(context.target)]
    elif who == "that_player":
        # "Target opponent loses 2 life unless **that player** sacrifices a
        # permanent of their choice." (Forbidden Ritual.) A back-reference to a
        # player the same *sentence* named, on a line no event fired — so the
        # seat is the resolution's own chosen player, which is the read
        # ``discard_target_cards`` gives the identical pronoun and the read
        # ``control_flow._offered_seats`` gives it when it decides who is being
        # offered this very price. Three readers, one seat.
        #
        # Verified rather than trusted: a resolution that chose nobody leaves
        # ``context.target`` empty or holding a permanent, and indexing it would
        # raise. Nobody chosen is nobody asked, which is the honest outcome the
        # frozen-seat branches below already give.
        chosen = context.target
        if chosen not in game.players:
            return False, "no player was chosen for 'that player'"
        payers = [game.players.index(chosen)]
    elif who == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** sacrifices
        # a land of their choice." (Mana Vortex.) The seat the trigger's own
        # condition named, frozen into the trigger's context by the fire site
        # (CR 603.10) — not the source's controller, which is the wrong seat on
        # every upkeep but their own. An absent key is a trigger nobody froze a
        # seat for, and guessing one is the failure the lowering's gate exists
        # to prevent, so the instruction fails rather than falling back.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that player'"
        payers = [seat]
    elif who == "event_subject_controller":
        # "Whenever a creature dies, **that creature's controller** sacrifices
        # a land of their choice." (Earthlink.) The branch above one question
        # over: the seat that *controlled* what the event was about, frozen by
        # the same fire site and read the same way — a graveyard card cannot
        # say who controlled it, and under a control-change effect that is not
        # its owner. An absent key fails for the reason it fails above.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False, "no seat was frozen for 'that creature's controller'"
        payers = [seat]
    else:
        return False, f"unsupported sacrifice payer {who!r}"
    # "…**each player who tapped a land for mana this turn** sacrifices a land
    # of their choice." (Desolation.) The printed relative clause, applied to
    # the list the branches above built rather than inside each of them: what
    # the clause narrows is *which of the payers*, and which payers there are
    # is the only thing those branches disagree about.
    payers = seats_matching_deed(
        game, context, payers, instruction.payload.get("who_did")
    )
    # "…a third of the creatures **they** control" (Pox): one number per payer,
    # so it cannot be the printed count — a fraction of a board has a different
    # answer for every seat asked. Evaluated against each payer through the same
    # evaluator every other computed count uses, so the fraction and its
    # rounding are applied in one place (CR 107.2/107.3).
    per_seat = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)
    count = int(instruction.payload.get("count", 1))
    # "Sacrifice two Swamps. **If you can't**, …" (Infernal Denizen.) Whether
    # the sacrifice could be performed at all, recorded here rather than after
    # the prompt: an interactive seat answers a queued choice long after this
    # instruction has returned, so the only moment at which the answer exists
    # synchronously is before the prompt is armed. What it records is the
    # question CR 701.17b asks — does the payer control the printed number of
    # permanents the phrase describes — which is the same predicate
    # ``_action_is_takeable`` puts in front of an *optional* sacrifice, so an
    # offer and a mandatory action cannot disagree about what "can't" means.
    #
    # True when nobody owed anything, because a step that asked for nothing is
    # not a step that failed.
    could_pay = True
    for seat in payers:
        owed = (
            evaluate_count(game, game.players[seat], per_seat)
            if per_seat is not None else count
        )
        if owed <= 0:
            # CR 608.2's "as much as possible": a seat that owes none is not
            # asked, rather than being handed a prompt with no answer.
            continue
        described = dict(instruction.payload.get("filter") or {})
        if len(game._sacrifice_candidate_indices(
            game.players[seat], described, exclude
        )) < owed:
            # The printed count is indivisible: a player with one of the two
            # Swamps sacrifices neither, and the "if you can't" branch behind
            # this step is what the card says happens instead.
            could_pay = False
            continue
        game.arm_forced_sacrifice(
            seat, owed,
            filter=described,
            exclude=exclude,
            reason=context.card.name,
            # "If you sacrifice a **snow** Forest this way, …" (Gargantuan
            # Gorilla). What went, recorded as it goes — the branch that reads
            # it runs after this, and by then the permanent is a card in a
            # graveyard and a different object (CR 400.7, CR 608.2h). The
            # scratchpad is the resolution's own, so a step of some other
            # effect cannot see it, and `_run`'s `run_resumable` is what carries
            # the reading step across an interactive seat's prompt.
            record=context.results,
        )
    context.results["sacrificed_this_way"] = could_pay
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


@effect_handler("change_supertype")
def change_supertype(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Arcum's Weathervane: "{2}, {T}: Target nonsnow basic land becomes snow."
    and "{2}, {T}: Target snow land is no longer snow."

    CR 205.4a's half of the type line, changed in CR 613 layer 4 — the same two
    channels :func:`gain_type` writes, with the supertype in the record instead
    of a card type. Nothing on the permanent's own card is touched, so the land
    stops being snow by the record going away rather than by anything being
    restored.

    The polarity is payload, so one handler answers both printed sentences. It
    reaches the *computed* readers — ``Permanent.has_supertype`` and the eight
    call sites that ask it — which is what makes a thawed Snow-Covered Forest
    stop satisfying snow forestwalk and stop counting for Drift of the Dead.
    """
    from ..layer_bridge import LOST_TYPES

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

    word = str(payload.get("supertype", "")).lower()
    gained = bool(payload.get("gained", True))
    record = {
        "supertypes": [word],
        "duration": str(payload.get("duration", "permanent")),
        "source": context.card.name if context.card else "effect",
        "seat": game.players.index(context.caster) if context.caster in game.players else 0,
    }
    target_perm.metadata.setdefault(
        GAINED_TYPES if gained else LOST_TYPES, []
    ).append(record)
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} "
        + (f"becomes {word}" if gained else f"is no longer {word}")
    )
    return True, "resolved"


@effect_handler("rebalance_lands")
def rebalance_lands(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Natural Balance's whole paragraph.

    "Each player who controls six or more lands chooses five lands they control
    and sacrifices the rest. Each player who controls four or fewer lands may
    search their library for up to X basic land cards and put them onto the
    battlefield, where X is five minus the number of lands they control. Then
    each player who searched their library this way shuffles."

    Two halves and one number. A seat over the target sacrifices down to it; a
    seat under it may tutor up towards it; a seat *on* it is in neither
    sentence, which is why the memberships are read rather than a difference
    being taken.

    **Both memberships are read off the same board, before anything moves**, and
    that is a rules answer rather than a convenience. The sets are disjoint —
    a seat that sacrifices down to the target has five lands and can never be in
    the "four or fewer" half — and one player's sacrifices change nobody else's
    count, so a board read after the first sentence would give the same answer.
    Reading it once says so; reading it twice would leave the question of what
    an intervening replacement effect did, which the card does not ask.

    Every decision is a prompt of the seat that owes it, queued through the
    standing machinery: `arm_forced_sacrifice` for the removals, the ordinary
    library search for the tutor. Nothing here is a new mechanism — which is the
    point, because "chooses N and sacrifices the rest" and "search for up to N
    basic land cards" are what those two prompts already are.
    """
    keep = int(instruction.payload.get("keep", 5))
    counts = [
        sum(
            1 for perm in game.controlled_by(seat)
            if perm.card.primary_type == "land"
        )
        for seat in range(len(game.players))
    ]
    over = [(seat, held) for seat, held in enumerate(counts) if held > keep]
    under = [(seat, held) for seat, held in enumerate(counts) if held < keep]
    if not over and not under:
        game.log.append(
            f"{context.card.name}: every player already controls {keep} lands"
        )
        return True, "resolved"
    for seat, held in over:
        game.arm_forced_sacrifice(
            seat, held - keep,
            filter={"card_types": ("land",)},
            reason=context.card.name if context.card is not None else "Rebalance",
        )
    for seat, held in under:
        # "**may** search their library for **up to** X basic land cards": an
        # offer with a ceiling, which is what `up_to` on the search prompt means
        # — a seat may find fewer, none included (CR 701.23b), and declining is
        # the fail-to-find every search already answers.
        #
        # The searching seat is its own chooser and its own zone owner, so no
        # seat key rides the prompt; that is the ordinary case the flow
        # defaults to, and it is what makes "their library" every player's own.
        game.arm_pending_choice(
            "search_library", seat,
            count=keep - held,
            card_type="land",
            zones=("library",),
            restrictions={"supertypes": ("basic",)},
            destination="battlefield",
            # One slot per find, all to the same place — the shape a counted
            # search whose finds share a destination already takes.
            destinations=["battlefield"] * (keep - held),
            tapped=[False] * (keep - held),
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=True,
            reveal=False,
            # **No record.** Every other search hands over the resolution's
            # scratchpad so a later sentence can name what it found; this
            # paragraph has no later sentence, and the scratchpad is one dict
            # shared by every seat this instruction armed — so a record here
            # would be several players' finds in one channel, which is the
            # two-value-shapes hazard rather than a feature.
        )
    if over:
        game.log.append(
            f"{context.card.name}: "
            + ", ".join(
                f"{game.players[seat].name} sacrifices {held - keep} land(s)"
                for seat, held in over
            )
        )
    if under:
        game.log.append(
            f"{context.card.name}: "
            + ", ".join(
                f"{game.players[seat].name} may search for {keep - held} basic land(s)"
                for seat, held in under
            )
        )
    return True, "pending_rebalance_lands"


@effect_handler("swap_land_types_until_eot")
def swap_land_types_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a land type and a basic land type. Each land of the first chosen
    type becomes the second chosen type until end of turn." (Vision Charm's
    third mode, CR 305.7 / CR 609.3.)

    The handler arms the prompt and the **resolver** performs the swap, which is
    Jinx's arrangement one land at a time: CR 609.3 puts the choice inside the
    resolution, and the set the sweep reaches is named by the answer, so nothing
    can be recorded until the seat has answered.

    A deterministic default is computed here, against the board as it stands, so
    a headless or AI seat is never blocked — and so the default is a real answer
    rather than "the first word in the catalog": the pair that turns the most of
    the caster's *opponents'* lands into a type they do not already have.
    """
    caster_seat = game.seat_index(context.caster)
    first_basic = bool(instruction.payload.get("first_basic"))
    second_basic = bool(instruction.payload.get("second_basic"))
    default_from, default_to = _default_land_type_swap(
        game, caster_seat, first_basic=first_basic, second_basic=second_basic
    )
    game.arm_pending_choice(
        "land_type_swap", caster_seat,
        card_name=context.card.name,
        first_basic=first_basic, second_basic=second_basic,
        duration=LAND_TYPE_UNTIL_EOT,
        default_from=default_from, default_to=default_to,
    )
    return True, "resolved"


def _default_land_type_swap(
    game: Game, seat: int, *, first_basic: bool, second_basic: bool
) -> tuple[str, str]:
    """The pair a seat that is not asked gets.

    Read off the board rather than taken from the head of a catalog, because a
    catalog's first word is a choice no player would make and this engine's
    AI-simulation regressions are seeded runs of exactly such answers. The
    policy: swap **from** the land type the seat's opponents have most of,
    **to** the basic type fewest of those lands already have — the pair that
    changes the most colours of mana on the other side of the table.

    Ties keep catalog order both times, which is what makes a seeded run
    reproducible.
    """
    from ..grammar.vocabulary import LAND_TYPES

    basics = ("plains", "island", "swamp", "mountain", "forest")
    first_pool = sorted(basics if first_basic else LAND_TYPES)
    second_pool = sorted(basics if second_basic else LAND_TYPES)
    theirs = [
        perm for other in range(len(game.players)) if other != seat
        for perm in game.controlled_by(other)
        if perm.card.primary_type == "land"
    ]
    counts = {word: sum(1 for land in theirs if land.has_type(word)) for word in first_pool}
    chosen_from = max(first_pool, key=lambda word: (counts.get(word, 0), -first_pool.index(word)))
    to_counts = {
        word: sum(1 for land in theirs if land.has_type(word)) for word in second_pool
    }
    for word in second_pool:
        # Never the type it already is: a swap onto itself is a resolution that
        # did nothing, which is the one answer the card cannot mean.
        if word != chosen_from and to_counts[word] == min(
            count for other, count in to_counts.items() if other != chosen_from
        ):
            return chosen_from, word
    return chosen_from, next(w for w in second_pool if w != chosen_from)
