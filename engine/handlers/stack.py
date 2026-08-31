from __future__ import annotations

from typing import TYPE_CHECKING

from ..card_hooks import ON_SPELL_COUNTERED
from ..game_types import StackItem
from ..mana_payment import total_pips
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("copy_triggering_spell")
def copy_triggering_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Copy that spell. You may choose new targets for the copy."
    (Double Vision.)

    "That spell" is the one the trigger fired on. Located on the stack by the
    card the event recorded — not by taking the topmost instant or sorcery,
    which is the same object only while nothing has been cast in response, and a
    different one the moment something has.

    A spell that has already left the stack is copied by nothing: CR 707.10
    copies an object, and by then there is none. That is the honest outcome
    rather than reaching for whatever else is up there.
    """
    caster = context.caster
    cast_card = (context.trigger_context or {}).get("cast_card")
    copied = next(
        (item for item in reversed(game.stack) if item.card is cast_card), None
    )
    if copied is None:
        game.log.append(f"{context.card.name}: that spell is no longer on the stack")
        return True, "resolved"
    caster_index = game.players.index(caster)
    game._stack_push(
        # CR 707.10: a copy has the original's targets (or the ones the
        # copying effect changed them to). It does not choose again.
        targets_already_chosen=True,
        item=StackItem(
            card=copied.card,
            caster_index=caster_index,
            target_player_index=copied.target_player_index,
            target_permanent_index=copied.target_permanent_index,
            x_value=copied.x_value,
            # CR 707.10: the copy has the original's choices. New targets are
            # the copy controller's option and are not chosen here — the AI and
            # the headless path keep the original's, which is the legal default.
            choices=dict(copied.choices),
            chosen_mode_index=copied.chosen_mode_index,
            target_stack_item=copied.target_stack_item,
            is_copy=True,
        )
    )
    game.log.append(f"{context.card.name} copied {copied.card.name}")
    return True, "resolved"


@effect_handler("copy_top_stack_spell")
def copy_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Fork: "Copy target instant or sorcery spell... You may choose new targets for
    # the copy." Copy the chosen spell if one was targeted, otherwise the topmost
    # instant or sorcery on the stack (Fork itself has already been popped to
    # resolve). The copy is put onto the stack under Fork's controller so it
    # resolves independently, and gets new targets if the Fork caster chose them.
    caster = context.caster
    card = context.card
    copied = None
    chosen = context.stack_target
    if chosen is not None and chosen in game.stack and chosen.card.primary_type in ("instant", "sorcery"):
        copied = chosen
    if copied is None:
        copied = next(
            (item for item in reversed(game.stack) if item.card.primary_type in ("instant", "sorcery")),
            None,
        )
    if copied is None:
        game.log.append(f"{card.name} resolved with no instant or sorcery spell to copy")
        return True, "resolved"

    caster_index = game.players.index(caster)
    # "You may choose new targets for the copy." When the Fork caster supplied a
    # new target (a creature/permanent index, optionally on a specific player),
    # the copy uses it; otherwise the copy keeps the original spell's targets.
    if context.target_permanent_index is not None:
        new_target_player_index = game.players.index(context.target) if context.target is not None else copied.target_player_index
        new_target_permanent_index = context.target_permanent_index
    else:
        new_target_player_index = copied.target_player_index
        new_target_permanent_index = copied.target_permanent_index

    game._stack_push(
        # CR 707.10: a copy has the original's targets (or the ones the
        # copying effect changed them to). It does not choose again.
        targets_already_chosen=True,
        item=StackItem(
            card=copied.card,
            caster_index=caster_index,
            target_player_index=new_target_player_index,
            target_permanent_index=new_target_permanent_index,
            x_value=copied.x_value,
            # CR 707.10: the copy has the same choices as the original, so this
            # is one assignment rather than one per choice the original made.
            choices=dict(copied.choices),
            chosen_mode_index=copied.chosen_mode_index,
            target_stack_item=copied.target_stack_item,
            is_copy=True,
        )
    )
    game.log.append(f"{card.name} copied {copied.card.name} (copy put on the stack)")
    return True, "resolved"


#: How a stack object's recorded ``ability_effect_kind`` says which kind of
#: ability it is. `engine/effect_labels.py` produces these prefixes and
#: `web/serialization.py` already reads the triggered one to set `is_triggered`;
#: reading them here rather than keeping a third opinion is what stops the
#: three drifting.
_ABILITY_KIND_PREFIXES = {"triggered": "triggered_", "activated": "activated_"}


def _stack_ability_kind(item) -> str | None:
    """Which kind of ability *item* is, or None when it is not one.

    A spell is not an ability however it was put on the stack, and the test is
    the presence of an ``ability_instruction`` rather than the absence of a
    card: a triggered ability carries the source permanent's card for its
    display name (CR 113.7a gives the ability no card of its own).
    """
    if item.ability_instruction is None:
        return None
    label = item.ability_effect_kind or ""
    for kind, prefix in _ABILITY_KIND_PREFIXES.items():
        if label.startswith(prefix):
            return kind
    # An ability whose label says neither. It is still an ability on the stack,
    # and "activated or triggered" is every ability a player can respond to
    # (CR 113.3a–c: the third kind is static and never uses the stack), so
    # reporting None here would make a real object uncounterable.
    return "triggered" if item.trigger_context is not None else "activated"


@effect_handler("counter_stack_ability")
def counter_stack_ability(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Counter target activated or triggered ability." (Sublime Epiphany.)

    CR 701.5a: the object is removed from the stack and does nothing. Nothing
    else happens — an ability has no card, so there is no graveyard move to
    make and no "exile it instead" rider to honour.

    Strict about its target (CR 608.2b): the chosen object is countered or
    nothing is. Falling back to the top of the stack, the way the spell counter
    does, would let this counter the *ability that put this spell's own effect
    there* on a board where the chosen one had already resolved.
    """
    card = context.card
    chosen = context.stack_target
    if instruction.payload.get("bound_to_trigger"):
        # "**Counter that ability.**" (Imprison.) The ability is the one the
        # trigger fired on, found on the stack by identity — CR 603.3 put this
        # trigger *above* it, so the stack top is this ability's own object and
        # anything activated in response sits between the two. The same shape
        # `counter_top_stack_spell` uses for "counter it", and by identity for
        # the same reason: two activations of the same ability are two objects.
        bound = (context.trigger_context or {}).get("activated_ability_item")
        chosen = next((item for item in game.stack if item is bound), None)
    if chosen is None or chosen not in game.stack:
        game.log.append(f"{card.name}: the targeted ability is no longer on the stack")
        return True, "resolved"
    kind = _stack_ability_kind(chosen)
    wanted = tuple(instruction.payload.get("ability_kinds") or ())
    if kind is None or (wanted and kind not in wanted):
        game.log.append(
            f"{card.name}: {chosen.card.name} is not "
            f"{' or '.join(wanted) if wanted else 'an'} ability, cannot counter"
        )
        return True, "resolved"
    # "…from an **artifact** source" (Rust). The ability has no card of its own
    # (CR 113.7a), so the type is asked of the permanent it came from — through
    # `card_has_type`, the one reader of "does this card have this type", because
    # `primary_type` picks one type off a list and would miss an artifact
    # creature's activated ability.
    source_types = tuple(instruction.payload.get("source_card_types") or ())
    if source_types:
        source = chosen.source_permanent
        if source is None or not _spell_is_one_of(source.effective_card, source_types):
            game.log.append(
                f"{card.name}: that ability is not from "
                f"{' or '.join(source_types)} source, cannot counter"
            )
            return True, "resolved"
    # "…unless that ability's controller pays {W}" (Ayesha Tanaka). The ability
    # waits on the stack while its controller decides, exactly as a spell does
    # under Power Sink — what waits is a stack object, and an ability is one
    # (CR 113.7a). `countered_object` is how the resolver knows not to bin a
    # card: this object has none, and `chosen.card` is the *source permanent's*
    # card, which never left the battlefield.
    cost = instruction.payload.get("unless_pays_cost")
    if cost:
        game.arm_pending_choice(
            "mana_payment", chosen.caster_index,
            cost=dict(cost), amount=total_pips(cost),
            card_name=card.name, counter_card=card,
            stack_item=chosen, countered_object="ability",
            # The marker the headless/AI path keys on to resolve this
            # deterministically the moment the resolution that armed it ends
            # (mixins/stack/resolution.py). Without it the prompt arms, nobody
            # answers it, and the object it was supposed to gate resolves
            # anyway — which is the counter silently never happening.
            _new=True,
        )
        return True, "resolved"
    game.stack.remove(chosen)
    game.log.append(f"{card.name} countered {chosen.card.name}'s {kind} ability")
    return True, "resolved"


def _spell_is_one_of(card, card_types) -> bool:
    """Whether a spell on the stack is any of *card_types* (CR 205.2).

    Through the one reader of that question (``search_filters.card_has_type``):
    a card has every type its line names, and asking ``primary_type`` picks one
    of them by the order of a list. It picked "creature", so Goblin Artisans —
    whose whole ability is countering an artifact spell — refused every artifact
    creature in the set.
    """
    from ..search_filters import card_has_type

    return any(card_has_type(card, wanted) for wanted in card_types)


def _spell_is_one_of_classes(card, classes) -> bool:
    """Whether a spell on the stack is any of *classes* — "instant **or Aura**
    spell" (Avoid Fate, Ring of Immortals).

    A union whose alternatives sit on two different axes (CR 205.2 against
    CR 205.3), so each entry carries the axis it was read on and is asked of
    that half of ``printed_shape``. Asking one substring test of the whole type
    line would answer both, and would also answer for a card whose *other* axis
    happens to print the same word — the axis is free to carry, and a matcher
    that has to guess is a matcher that can guess wrong.

    ``printed_shape`` rather than ``has_type``: a spell on the stack is not a
    permanent, so CR 613 has nothing to say about it and the printed line is the
    whole of what there is.
    """
    from ..layer_bridge import printed_shape

    types, subtypes = printed_shape(card)
    for axis, name in classes:
        if axis == "card_type" and name in types:
            return True
        if axis == "subtype" and name in subtypes:
            return True
    return False


def _spell_targets_matching(
    game, item, described: dict, observer: int, source=None
) -> bool:
    """Whether the spell *item* chose a permanent the filter *described* names —
    "…that targets a permanent you control" (Avoid Fate, Ring of Immortals).

    *source* is the ability's own permanent, and passing it narrows the question
    to "…that targets **this creature**" (Mistfolk). An identity, not a
    description, so it is compared by ``permanent_id`` rather than folded into
    the filter — the lowering lifts the word out of the noun phrase for the same
    reason. ``None`` asks the unnarrowed question, which is every other card
    printing this clause.

    Read off the stack item's recorded target *ids* (CR 601.2c), never its
    indices: time passes between the spell being cast and this counter
    resolving, and an index recorded then can address a different permanent now.
    A target that has since left the battlefield answers None and simply is not
    one of the permanents this counter's narrowing can see — which is the honest
    reading, since the counter is legal only while some target still qualifies.

    ``subject_matches`` is the one reader of "what does this noun phrase mean",
    so "you control" here is the same seat question every other narrowing asks,
    measured against the counter's own controller (CR 109.5).
    """
    from ..subject_filters import subject_matches

    recorded = getattr(item, "target_permanent_id", None)
    ids = recorded if isinstance(recorded, list) else [recorded]
    for permanent_id in ids:
        found = game.permanent_by_id(permanent_id)
        if found is None:
            continue
        if source is not None and found is not source:
            continue
        if subject_matches(
            game, found, described, observer=observer, source=source
        ):
            return True
    return False


@effect_handler("counter_top_stack_spell")
def counter_top_stack_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    # The filter arrives already rewritten when a text change applies: the
    # ability was compiled from the permanent's effective card, so Lifeforce's
    # "counter target black spell" is parsed as "red" once Sleight of Mind has
    # said so (CR 613 layer 3). Remapping it again here applied layer 3 twice.
    color_filter = instruction.payload.get("color_filter")
    if game.stack:
        # Counter the chosen spell if one was targeted, otherwise the top of stack.
        chosen = context.stack_target
        if instruction.payload.get("bound_to_trigger"):
            # "Whenever a player casts a spell, counter **it**." (Nether Void,
            # Presence of the Master, In the Eye of Chaos.) The spell is the one
            # the trigger fired on, found on the stack by identity — CR 603.3
            # puts the trigger *above* it, so the stack top is this ability's
            # own object and everything cast in response sits between them.
            cast_card = (context.trigger_context or {}).get("cast_card")
            chosen = next(
                (item for item in game.stack if item.card is cast_card), None
            )
            if chosen is None:
                # Countered, exiled or already resolved while the trigger waited
                # (CR 608.2b's shape: the object is gone, the rest happens).
                game.log.append(
                    f"{card.name}: the spell it would counter is no longer on the stack"
                )
                return True, "resolved"
        target = chosen if (chosen is not None and chosen in game.stack) else game.stack[-1]
        if color_filter and color_filter not in game._stack_item_colors(target):
            game.log.append(f"{card.name}: {target.card.name} is not color {color_filter}, cannot counter")
            return True, "resolved"
        # Miscast: "counter target instant or sorcery spell" — the union the
        # payload carries is tested against the chosen spell's primary type,
        # the same shape as the colour gate above.
        card_types = instruction.payload.get("card_types")
        if card_types and not _spell_is_one_of(target.card, card_types):
            game.log.append(
                f"{card.name}: {target.card.name} is not "
                f"{' or '.join(card_types)}, cannot counter"
            )
            return True, "resolved"
        # "counter target **instant or Aura** spell" (Avoid Fate, Ring of
        # Immortals): the cross-axis union, tested whole. Beside `card_types`
        # rather than folded into it — the two payload keys mean different
        # questions and a phrase produces exactly one of them.
        any_classes = instruction.payload.get("any_classes")
        if any_classes and not _spell_is_one_of_classes(
            target.card, [tuple(entry) for entry in any_classes]
        ):
            game.log.append(
                f"{card.name}: {target.card.name} is not "
                f"{' or '.join(str(entry[1]) for entry in any_classes)}, cannot counter"
            )
            return True, "resolved"
        # "…**that targets a permanent you control**" (Avoid Fate, Ring of
        # Immortals). A restriction on what the chosen spell itself chose, so it
        # is asked of the stack item's recorded targets rather than of the card.
        targets_filter = instruction.payload.get("targets_filter")
        # "…that targets **this creature**" (Mistfolk). The second half of the
        # same question, asked with the ability's own source in hand. With the
        # source already gone there is no permanent the spell could still be
        # targeting, and the counter finds nothing — which is CR 608.2b's
        # answer, not a missing check.
        targets_source = (
            context.source_permanent
            if instruction.payload.get("targets_source") else None
        )
        if (
            (targets_filter or targets_source is not None)
            and not _spell_targets_matching(
                game, target, dict(targets_filter or {}),
                game.players.index(context.caster), source=targets_source,
            )
        ):
            game.log.append(
                f"{card.name}: {target.card.name} does not target a matching "
                "permanent, cannot counter"
            )
            return True, "resolved"
        # "…**if it would destroy a land you control**" (Equinox). A condition
        # about the chosen spell's *own effect*, which nothing on the stack item
        # records — so it is answered by reading that spell's compiled program
        # (engine/counter_conditions.py), through the same table the grammar
        # admitted the line with. CR 608.2 puts the question here rather than at
        # activation: the board can change while the ability waits.
        only_if = instruction.payload.get("only_if")
        if only_if is not None:
            from ..counter_conditions import counter_condition_holds

            if not counter_condition_holds(
                str(only_if), game, target, game.players.index(context.caster)
            ):
                game.log.append(
                    f"{card.name}: {target.card.name} would not "
                    f"{str(only_if).replace('it would ', '')}, cannot counter"
                )
                return True, "resolved"
        # "counter target artifact spell **you control**" (Goblin Artisans).
        # Whose spell it is, asked of the seat that put it on the stack.
        if instruction.payload.get("controller") == "you":
            if target.caster_index != game.players.index(context.caster):
                game.log.append(
                    f"{card.name}: {target.card.name} is not a spell you control, "
                    "cannot counter"
                )
                return True, "resolved"
        # "…that isn't the target of an ability from another creature named ~"
        # (Goblin Artisans): a guard against two copies aiming at the same
        # spell. Asked of the stack, because the abilities pointing at that
        # spell are objects on it (CR 113.7a) and nothing about the spell itself
        # records who is aiming at it. "Another" is by identity — an ability of
        # *this* permanent is the one now resolving, and excluding it is what
        # keeps the card from countering nothing at all.
        if instruction.payload.get("not_ability_targeted_by_same_name"):
            source = context.source_permanent
            rival = next(
                (
                    item
                    for item in game.stack
                    if item.target_stack_item is target
                    and item.source_permanent is not None
                    and item.source_permanent is not source
                    and source is not None
                    and item.source_permanent.card.name == source.card.name
                ),
                None,
            )
            if rival is not None:
                game.log.append(
                    f"{card.name}: {target.card.name} is already the target of "
                    f"another {rival.source_permanent.card.name}'s ability, cannot counter"
                )
                return True, "resolved"
        # Spell Blast: X must equal the target spell's mana value. When no X was
        # chosen (None, or 0 auto-inferred from an empty pool), assume the caster
        # chose the matching value.
        if instruction.payload.get("mv_equals_x") and context.x_value:
            # CR 202.3b: while a spell is on the stack, an X in its mana cost is
            # the value its controller announced — so a Fireball cast for X=3
            # has mana value 4, not the 1 its printed cost carries. Read through
            # the one function that knows that (``targeting``), which is also
            # what prices Reflecting Mirror's {X}.
            from ..targeting import stack_object_mana_value

            target_mv = stack_object_mana_value(target)
            if int(context.x_value) != target_mv:
                game.log.append(
                    f"{card.name}: X={context.x_value} does not match {target.card.name}'s mana value {target_mv}, cannot counter"
                )
                return True, "resolved"
        # Power Sink: "Counter target spell unless its controller pays {X}." The
        # targeted spell's controller is asked to pay {X} (X chosen by Power Sink's
        # caster) to keep their spell. Rather than auto-paying, arm a pending mana
        # payment: the target spell stays on the stack while its controller decides
        # (a human taps lands and pays/declines via the prompt; headless/AI play is
        # auto-resolved deterministically). Paying {0} always succeeds, so X=0 never
        # counters — resolve that immediately without a prompt.
        if instruction.payload.get("unless_pays_x") or instruction.payload.get("unless_pays_amount"):
            # Power Sink sizes the cost from its caster's chosen X; Miscast
            # prints it. Everything after the amount is one flow.
            if instruction.payload.get("unless_pays_x"):
                cost = max(0, int(context.x_value or 0))
            else:
                cost = max(0, int(instruction.payload["unless_pays_amount"]))
            # "If you control a creature with flying, counter that spell unless
            # its controller pays {4} **instead**." (Lofty Denial.) One counter
            # with a replacement amount, asked here rather than lowered into two
            # branches, because CR 608.2 puts the question at resolution: a flier
            # that dies in response to this spell changes what its victim owes.
            conditional = instruction.payload.get("unless_pays_if")
            # Imported here rather than at module scope: control_flow dispatches
            # back through EFFECT_HANDLERS, so a module-level import closes the
            # cycle through engine/handlers/__init__.py. The same reason
            # engine/oracle.py imports subject_filters inside its function.
            from .control_flow import evaluate_condition

            if conditional and evaluate_condition(
                game, context, conditional.get("condition") or {}
            ):
                cost = max(0, int(conditional["amount"]))
            if cost == 0:
                game.log.append(
                    f"{game.players[target.caster_index].name} pays {{0}}; "
                    f"{target.card.name} is not countered by {card.name}"
                )
                return True, "resolved"
            game.arm_pending_choice(
                "mana_payment", target.caster_index,
                amount=cost, card_name=card.name, counter_card=card,
                stack_item=target, _new=True,
            )
            game.log.append(
                f"{card.name}: {game.players[target.caster_index].name} must pay "
                f"{{{cost}}} or {target.card.name} is countered"
            )
            return True, "resolved"

        game.stack.remove(target)
        countered = target
        # "…add an amount of {C} equal to **that spell's** mana value." (Mana
        # Drain.) The countered spell's mana value, recorded in the resolution
        # scratchpad the moment it is known: the next sentence creates a
        # delayed ability that will not fire until a later phase, by which time
        # the card is in a graveyard and the stack item is gone (CR 608.2h).
        # CR 202.3b again: Mana Drain on a Fireball cast for X=3 makes {C}{C}{C}{C}.
        from ..targeting import stack_object_mana_value

        context.results["countered_spell_mana_value"] = stack_object_mana_value(countered)
        if countered.is_copy:
            # 704.5e: a countered copy of a spell ceases to exist instead of
            # going to a graveyard — it has no physical card to put there.
            game.log.append(f"{card.name} countered {countered.card.name} (copy), which ceases to exist")
        else:
            game._bin_spell_card(
                game.players[countered.caster_index], countered.card,
                exile_instead=countered.exile_instead_of_graveyard,
                verb=f"was countered by {card.name}",
            )
        counter_hook = ON_SPELL_COUNTERED.get(card.name)
        if counter_hook is not None:
            counter_hook(game, card, countered)
    else:
        game.log.append(f"{card.name} resolved with no spell to counter")
    return True, "resolved"


@effect_handler("copy_this_spell")
def copy_this_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…they may copy this spell and may choose a new target for that copy."
    (Chain Lightning.)

    Three things separate this from ``copy_top_stack_spell`` next door, and the
    first is why it cannot reuse it:

    1. **"This spell" is not on the stack.** ``mixins/stack/resolution`` pops a
       stack object *before* executing it, so while Chain Lightning is
       resolving the topmost instant or sorcery up there is somebody else's —
       and a copy-the-top handler would copy that one. The resolving object is
       ``Game.resolving_items``, which is pushed around exactly this window;
       matched by card identity so a nested resolution cannot be mistaken for
       the outer one.
    2. **The copy is not the caster's.** CR 707.10a: the copy is controlled by
       whoever the effect says, and here that is the player who paid — read off
       the payload the sentence's printed subject lowered to, never assumed.
    3. **The re-aiming is that seat's choice**, offered as a pending choice so
       an interactive player answers it and a non-interactive one takes the
       stated default at once (see ``arm_copy_spell_target``).
    """
    who = instruction.payload.get("controller", "you")
    # "you" is the resolving spell's controller (CR 109.5); every other printed
    # subject this sentence can carry names the seat an earlier step recorded,
    # which is what `context.target` holds.
    holder = context.caster if who == "you" else (context.target or context.caster)
    seat = game.players.index(holder)

    # CR 707.10: the copy starts with the original's characteristics and
    # choices. They come from the **resolution context**, not from a stack
    # object, and that is the whole difficulty of "this spell": by the time an
    # instruction of a spell runs, this engine has popped that spell off
    # ``Game.stack``, and by the time an *optional* branch of it runs — the
    # branch a player had to be asked about — the spell may have finished
    # resolving and be in a graveyard. A scan of either place finds the wrong
    # object or none. The context is the one thing that outlives both, and it
    # carries every choice a copy needs.
    #
    # ``resolving_items`` is preferred where it still has the object, because it
    # additionally carries what the context does not (the mode chosen, a spell
    # this one targeted); it is a refinement of the answer, never the answer.
    original = next(
        (
            item
            for item in reversed(getattr(game, "resolving_items", None) or ())
            if item.card is context.card
        ),
        None,
    )
    copy = StackItem(
        card=context.card,
        caster_index=seat,
        target_player_index=(
            original.target_player_index if original is not None
            else game.players.index(context.target) if context.target is not None
            else None
        ),
        target_permanent_index=(
            original.target_permanent_index if original is not None
            else context.target_permanent_index
        ),
        target_permanent_id=(
            original.target_permanent_id if original is not None
            else context.target_permanent_id
        ),
        x_value=original.x_value if original is not None else context.x_value,
        choices=dict(original.choices if original is not None else context.choices),
        chosen_mode_index=original.chosen_mode_index if original is not None else None,
        target_stack_item=(
            original.target_stack_item if original is not None
            else context.stack_target
        ),
        is_copy=True,
    )
    game._stack_push(item=copy, targets_already_chosen=True)
    game.log.append(
        f"{game.players[seat].name} copied {context.card.name} (copy put on the stack)"
    )
    if instruction.payload.get("may_choose_new_target"):
        game.arm_copy_spell_target(seat, copy)
    return True, "resolved"


# ---------------------------------------------------------------------------
# CR 115.7 — changing what a spell on the stack points at
# ---------------------------------------------------------------------------


def _retarget_subject(game: Game, context: OracleExecutionContext, instruction):
    """The spell this retarget may still change, or None with the reason logged.

    CR 608.2b asked at the moment the rule asks it. The ability chose its target
    when it was activated, and the whole point of the stack is that time passes:
    the spell can be countered, can resolve, or can have its own target changed
    by something else in between. So every condition the picker checked is
    checked again here, against the object as it stands now.

    Located by **identity**, never by ``in``: ``StackItem`` compares by value, so
    two copies of one spell aimed at one player are equal and ``in`` would find
    the wrong one — the look-alike bug that ``permanent_id`` solves on the
    battlefield.
    """
    from ..targeting import single_player_target

    card_name = getattr(context.card, "name", "")
    item = context.stack_target
    if item is None or not any(waiting is item for waiting in game.stack):
        game.log.append(
            f"{card_name}: the spell it would retarget is no longer on the stack"
        )
        return None
    if instruction.payload.get("current_target") != "you":
        # Lowering admits no other value; a payload that carried one would be a
        # restriction nothing here can test.
        return None
    seat = single_player_target(game, item)
    if seat is None or seat != game.players.index(context.caster):
        game.log.append(
            f"{card_name}: {item.card.name} no longer has a single target that is you"
        )
        return None
    return item


def _legal_new_player_targets(game: Game, item: StackItem) -> list[int]:
    """The players *item* could legally have been aimed at instead (CR 115.7a).

    Read through ``_enumerate_targets`` — the one list the picker and the cast
    gate already share — so "another legal target" means for this spell exactly
    what it meant when the spell was cast. Word of Command's "target opponent"
    therefore offers only its own caster's opponents, which is why a spell
    aimed at you by the player it may not aim at themselves simply cannot be
    moved.

    The kind is forced to ``player``: the question is which *faces* are legal,
    and asking a wider spec would walk both battlefields probing every
    permanent for an answer this never uses.
    """
    from ..oracle import compile_card_oracle
    from ..targeting import derive_cast_spec

    spec = derive_cast_spec(item.card, compile_card_oracle(item.card))
    if spec is None:
        return []
    entries = game._enumerate_targets(
        item.caster_index, item.card, {**spec, "kind": "player"}, for_cast=True
    )
    return [
        entry["seat"] for entry in entries
        if entry.get("kind") == "player" and not game.players[entry["seat"]].lost
    ]


@effect_handler("choose_new_target_player")
def choose_new_target_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"The new target must be a player." — who replaces you (CR 115.7a).

    The first of the retarget's two steps. It is its own step for the reason
    Backdraft's player choice is one (``handlers/player_choices.py``): the
    decision is made *during* this resolution and the step behind it reads the
    answer, so an interactive seat can be asked and the resolution suspended
    until it answers.

    The key is written before anything else, so the step behind this one finds
    ``None`` rather than a key error when there was nobody to choose — "no legal
    new target" is an outcome CR 115.7a names ("the original target is
    unchanged"), not a failure.

    **Another** legal target, which is what the rule says: the player the spell
    already points at is not among the candidates, so a retarget with nowhere
    else to go leaves the spell exactly as it was. A single candidate is taken
    without asking, the shortcut ``choose_player_who_cast`` states — the card
    makes the choice forced, and prompting would ask a question with one answer.
    """
    key = str(instruction.payload["result_key"])
    context.results[key] = None
    card_name = getattr(context.card, "name", "")
    item = _retarget_subject(game, context, instruction)
    if item is None:
        return True, "resolved"
    current = game.players.index(context.caster)
    seats = [seat for seat in _legal_new_player_targets(game, item) if seat != current]
    if not seats:
        game.log.append(
            f"{card_name}: {item.card.name} has no other legal player to target"
        )
        return True, "resolved"
    if len(seats) == 1:
        context.results[key] = seats[0]
        return True, "resolved"
    game.arm_player_choice(
        current,
        card_name=card_name,
        prompt=f"Choose the new target for {item.card.name}.",
        result_key=key,
        seats=seats,
        context=context,
    )
    return True, "resolved"


@effect_handler("change_target_spell_target")
def change_target_spell_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Change the target of target spell …" (Reflecting Mirror, CR 115.7a).

    The spell keeps everything else it announced — its controller, its X, its
    modes — and only what it points at moves. That is why this writes the item's
    target fields rather than re-announcing the spell: CR 115.7a changes a
    choice, it does not re-cast anything.

    ``divided_targets`` is rewritten alongside, because for a spell that
    recorded one it is the list that decides (CR 601.2d's division travels with
    the targets, and CR 115.7f keeps the division itself unchanged — with a
    single target there is only one share to keep). Writing the seat and leaving
    that list behind would log a redirect the damage step then ignored.
    """
    key = str(instruction.payload["result_key"])
    card_name = getattr(context.card, "name", "")
    seat = context.results.get(key)
    item = _retarget_subject(game, context, instruction)
    if item is None:
        return True, "resolved"
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(
            f"{card_name}: {item.card.name}'s target is unchanged"
        )
        return True, "resolved"
    item.target_player_index = seat
    divided = (item.choices or {}).get("divided_targets")
    if divided:
        item.choices["divided_targets"] = [(seat, None)]
    game.log.append(
        f"{card_name}: {item.card.name} now targets {game.players[seat].name}"
    )
    return True, "resolved"
