"""What a permanent **is**, changed by a resolving effect (CR 205, CR 613
layer 4): a basic land type (one land, two swapped, a land mired into a Swamp),
a card type gained or set, a creature type, a supertype, a returned card that
becomes an Aura (Necromancy), and a permanent that becomes a copy of another.

Each change is a record with its own duration and timestamp — written through
``engine/type_changes.py`` (``gain_types`` / ``lose_types``) or
``engine/land_types.py`` — and the record's lifetime is what a turn step's
sweep reads: :data:`LAND_TYPE_UNTIL_UNTAP`, :data:`LAND_TYPE_UNTIL_EOT` and
:data:`LAND_TYPE_UNTIL_SOURCE_LEAVES` name three of them, and the untap and
cleanup steps end the first two.

The handler twin of ``engine/grammar/lowering/types.py``, less animation
(``animation.py``) and less the colour (``colors.py``). Split out of
``board_misc.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..continuous import next_timestamp
from ..land_types import MIRE_COUNTER, change_land_type
from ..auras import BECAME_AURA_ENCHANT, BECAME_AURA_RECORD
from ..layer_bridge import SET_CARD_TYPES
from ..type_changes import gain_types, lose_types
from ..models import Permanent
from ._amounts import resolve_amount
from ._filters import permanent_matches_filter
from ._targets import resolve_target_permanent, resolve_target_permanents
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
        game, context, predicate=lambda p: p.has_type("land") and not _is_swamp(p)
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
    # A land that became a Swamp is one a Swamp-scoped static now reaches
    # (Kormus Bell) — CR 613 layer 4, decided for the whole board, at the
    # resolution seam (``resolve_top_of_stack``) rather than here.
    game.log.append(f"{target_land.card.name} got a mire counter and became a Swamp")

    # Remember this land on the activating artifact so its death trigger can later
    # remove the mire counter "for the rest of the game".
    source = context.source_permanent
    if source is not None:
        mired = source.metadata.setdefault("mired_lands", [])
        if target_land not in mired:
            mired.append(target_land)
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

#: The window tied to the ability's own source: "Target land becomes a Forest
#: **until this creature leaves the battlefield**" (Gaea's Liege, Graceful
#: Antelope). Its sweep is the leaving transition itself
#: (``Game.remove_all_from_battlefield``), through
#: ``land_types.end_land_type_changes_tied_to``.
LAND_TYPE_UNTIL_SOURCE_LEAVES = "until_source_leaves"


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
    def _eligible(perm) -> bool:
        return subject_matches(
            game, perm, filt, observer=seat, source=context.source_permanent
        )

    # "**X target lands** become Forests until end of turn." (Deepwood Elder.)
    # The several-target reading of this same instruction, and the branch
    # `pump_target_creature_until_eot` already takes for "X target creatures":
    # the printed count rides the description and is resolved against the
    # announced X, because a printed "X" is a string until the spell is cast.
    #
    # Above the single-target read rather than beside it, because that one falls
    # back to scanning the battlefield when the chosen target no longer answers
    # — right for one land and wrong for several, which would turn "X target
    # lands" into X changes on whichever land the scan met first.
    printed_count = (instruction.payload.get("targets") or {}).get("count")
    maximum = (
        resolve_amount(printed_count, context.x_value)
        if printed_count is not None else None
    )
    land_type = str(instruction.payload.get("land_type", ""))
    duration = str(instruction.payload.get("duration", "permanent"))
    ends_with_source = duration == LAND_TYPE_UNTIL_SOURCE_LEAVES
    if ends_with_source:
        # "…until this creature leaves the battlefield." CR 611.2b: a duration
        # that has ended before the effect would first be applied means the
        # effect does nothing - "it doesn't start and immediately stop again,
        # and it doesn't last forever". Reachable whenever the source can be
        # removed in response (an activated ability, a combat-damage trigger
        # with the creature killed before it resolves), and forever is exactly
        # what a change made then would be: nothing is left to end it. A
        # phased-out source has not left (CR 702.26d).
        from ..linked_exile import until_leaves_has_ended

        if until_leaves_has_ended(game, context.source_permanent):
            game.log.append(
                f"{context.card.name} has left the battlefield; no land changes"
            )
            return True, "resolved"
    if isinstance(maximum, int) and maximum > 1:
        chosen = resolve_target_permanents(game, context, predicate=_eligible)
        if not chosen:
            game.log.append(f"{context.card.name}: no land to change")
            return True, "resolved"
        for land in chosen[:maximum]:
            # One label per land, for the reason the single-target branch below
            # gives twice: two contributions keyed on the same source would have
            # the second replace the first, and here that is one *sentence*
            # changing several lands rather than two activations.
            change_land_type(
                land, land_type,
                source=(
                    context.source_permanent if ends_with_source
                    else f"{duration}:{next_timestamp()}"
                ),
                label=context.card.name,
                ends_with_source=ends_with_source,
            )
        game.log.append(
            ", ".join(land.card.name for land in chosen[:maximum])
            + f" each became a {land_type.title()} ({context.card.name})"
        )
        return True, "resolved"

    target = resolve_target_permanent(
        game,
        context,
        predicate=_eligible,
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no land to change")
        return True, "resolved"
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
        # "…becomes **the basic land type of your choice**" (Jinx). CR 608.2d
        # puts the choice inside the resolution, so nothing is recorded until
        # the seat answers — the prompt holds priority, and the change is made
        # by the resolver rather than here. The land travels by
        # ``permanent_id``: an index renumbers when anything leaves, and the
        # answer arrives after this handler has returned.
        # "…becomes **a Plains or an Island**" (Tundra Kavu). The same choice
        # with the list the sentence printed: carried on the prompt, which is
        # what the picker offers and what the resolver checks the answer
        # against (idiom 9), so the narrowing is enforced where the type is
        # named rather than trusted to whoever asks. Absent for "the basic land
        # type of your choice", whose prompt data is byte-identical to before.
        printed_options = [
            str(option) for option in
            (instruction.payload.get("land_type_options") or ())
        ]
        game.arm_pending_choice(
            "land_type_choice", game.players.index(context.caster),
            card_name=context.card.name,
            land_permanent_id=target.permanent_id,
            land_type_source=source,
            **({"land_type_ends_with_source": True} if ends_with_source else {}),
            **({"options": printed_options} if printed_options else {}),
        )
        game.log.append(
            f"{context.card.name}: choose "
            + (
                " or ".join(option.title() for option in printed_options)
                if printed_options else "a basic land type"
            )
            + f" for {target.card.name}"
        )
        return True, "resolved"
    change_land_type(
        target, land_type, source=source, label=context.card.name,
        ends_with_source=ends_with_source,
    )
    # A land that became a Forest is one a Forest-scoped static now reaches
    # (Living Lands), and one that became a Mountain is one Conversion does —
    # each of them depends on this effect (CR 613.8a), and where a dependent
    # static applies is decided for the whole board, at the resolution seam
    # (``resolve_top_of_stack``).
    game.log.append(
        f"{target.card.name} became a {land_type.title()} ({context.card.name})"
    )
    return True, "resolved"


@effect_handler("become_copy_of_bound_permanent")
def become_copy_of_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever another creature enters, this creature becomes a copy of that
    creature, except it has this ability." (Unstable Shapeshifter, CR 707.2.)

    The copied object is the one the *firing event* froze — never a pick, and
    never a board scan: two creatures entering in one turn are two firings, and
    a scan would copy whichever one the battlefield happened to list first. The
    id is the channel, because CR 400.7 makes a permanent that has left a new
    object and the trigger resolves off the stack (CR 603.3), by which time the
    creature that entered may be gone. It leaving is a real outcome: the copy
    effect has nothing to copy and the Shapeshifter stays what it was.

    The layer-1 record is written by ``Game._apply_copy``, which is the one
    place in this engine that applies a copy — this handler decides *what* is
    copied and hands over the printed exceptions, exactly as
    ``create_token_copy`` beside it does.

    CR 707.9a's "except it has this ability" is the granting card's own printed
    line, found on the permanent's **effective** card so a Shapeshifter that is
    already a copy carries the sentence it was granted rather than the one on
    its face. Without it the copy loses the ability and the card works exactly
    once.
    """
    from ..subject_filters import subject_matches

    permanent = context.source_permanent
    if permanent is None:
        return False, "no source permanent"
    bound = (context.trigger_context or {}).get("event_subject_permanent_id")
    source = None if bound is None else game.permanent_by_id(int(bound))
    if source is None or source is permanent:
        game.log.append(f"{context.card.name}: nothing left to copy")
        return True, "resolved"
    described = dict(instruction.payload.get("filter") or {})
    seat = game.controller_index_of(permanent)
    if described and not subject_matches(
        game, source, described, observer=seat, source=permanent
    ):
        game.log.append(
            f"{context.card.name}: {source.card.name} is not what this copies"
        )
        return True, "resolved"

    grants_text = ()
    if instruction.payload.get("keeps_own_ability"):
        grants_text = _granting_lines(permanent, instruction.kind)
    game._apply_copy(permanent, source, grants_text=grants_text)
    game.log.append(
        f"{context.card.name} became a copy of {source.card.name}"
    )
    return True, "resolved"


def _granting_lines(permanent, kind: str) -> tuple[str, ...]:
    """The printed line "**this** ability" names, off *permanent*'s own text.

    Found by asking which of the permanent's triggered abilities compiled to
    *this* instruction kind, rather than by threading the line down from the
    compiler: the answer is already in the compiled program, and a second
    channel carrying it would be a second statement of which sentence is being
    resolved.

    ``effective_card`` rather than the printed face, because a Shapeshifter
    that has already copied something carries the sentence it was **granted**
    (CR 707.9a) and not the one on its card — reading the face would grant the
    line a second time under a name the board no longer has.
    """
    from ..oracle import compile_card_oracle

    return tuple(
        trig.source_line
        for trig in compile_card_oracle(permanent.effective_card).triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == kind
    )


@effect_handler("become_aura_with_enchant")
def become_aura_with_enchant(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necromancy: "it becomes an Aura with "enchant creature put onto the
    battlefield with Necromancy.""

    Two layers in one sentence, and one instruction for both because the
    permanent is not in a legal state between them. CR 613 layer 4 gives it the
    Aura subtype, through the same ``type_changes.gain_types`` :func:`gain_type`
    below writes — so every reader of "is this an Aura?" (``equipment.attachment_refusal``,
    the CR 704.5m sweep, the P/T derivation) gets one answer from the layer
    system rather than from a rewritten card. CR 613 layer 6 gives it the enchant
    ability (CR 702.5), recorded under ``auras.BECAME_AURA_ENCHANT``.

    Nothing here attaches it. That is the sentence behind this one, in the same
    resolution — which is what makes the order safe: state-based actions are
    checked when a player would receive priority (CR 704.3), and nobody does
    inside a resolution, so the Aura is never seen attached to nothing.

    A source that has already left does nothing rather than recording on a
    permanent in a graveyard, which is CR 603.10's reading of the same trigger:
    the intervening "if it's on the battlefield" is checked again on resolution,
    and this is the same question one step later.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(
            f"{context.card.name}: it is no longer on the battlefield"
        )
        return True, "resolved"
    seat = game.players.index(context.caster) if context.caster in game.players else 0
    # "…becomes an Aura **enchantment**" (the Licids) against "…becomes an Aura"
    # (Necromancy). CR 205.1a: a sentence that *sets* a card type replaces the
    # ones the permanent had, so a Licid stops being a creature and its creature
    # types go with the type they belong to. Necromancy's sentence names no card
    # type at all, so it takes none away — its enchantment was already one.
    gained_types = [str(word) for word in (instruction.payload.get("card_types") or ())]
    lost = _replaced_printed_types(source, gained_types)
    marker = {BECAME_AURA_RECORD: True} if instruction.payload.get(
        "loses_own_ability"
    ) or lost else {}
    # One sentence, one moment: the removal is stamped first and the addition
    # just after it, so the card types the sentence sets land on top of the
    # ones it replaces whatever else is on the permanent (CR 205.1a, 613.7b).
    if lost:
        lose_types(
            source, card_types=lost[0], subtypes=lost[1],
            source=context.card.name if context.card else "effect",
            seat=seat, **marker,
        )
    gain_types(
        source, card_types=gained_types, subtypes=["aura"],
        source=context.card.name if context.card else "effect",
        duration="permanent", pt_from_mana_value=False, seat=seat, **marker,
    )
    # "This creature **loses this ability**" (CR 613 layer 6). The line is the
    # one being resolved, read off the context rather than matched by text: a
    # permanent may carry two abilities whose printed words differ only in a
    # mana symbol, and the ability that ran is the one the card says loses
    # itself.
    ability_line = str(context.ability_text or "")
    if instruction.payload.get("loses_own_ability") and ability_line:
        from ..keywords import remove_ability_line

        remove_ability_line(source, ability_line)
    source.metadata[BECAME_AURA_ENCHANT] = {
        "noun": str(instruction.payload.get("noun") or "creature"),
        "origin": str(instruction.payload.get("origin") or ""),
        # What ending the effect has to give back (CR 116.2c), recorded as the
        # effect is created rather than re-derived when the offer is taken: by
        # then the permanent is an enchantment and nothing on it says which of
        # its printed lines it lost — the offer's own sentence went with the
        # ability. CR 611.2a: the effect outlives the ability that made it.
        "ability_line": ability_line if instruction.payload.get(
            "loses_own_ability"
        ) else "",
        "end_cost": _offer_to_end_this_effect(ability_line),
    }
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name} became an Aura with "
        f"\"enchant {source.metadata[BECAME_AURA_ENCHANT]['noun']}\""
    )
    return True, "resolved"


def _offer_to_end_this_effect(ability_line: str) -> dict[str, int] | None:
    """The cost "You may pay {C} to end this effect" names on *ability_line*.

    Asked of ``engine/special_actions.py``'s own table, never of a second copy
    of the sentence: that table is what will *perform* the offer, and a literal
    here would be free to drift from the words it reads.
    """
    from ..special_actions import permanent_special_action_in_line

    found = permanent_special_action_in_line(ability_line or "")
    if found is not None and found[0] == "end_own_continuous_effect":
        return found[1]
    return None


def _replaced_printed_types(source, gained: list[str]):
    """The card types and subtypes CR 205.1a takes away, or None.

    A sentence that names no card type sets none, so it replaces nothing —
    which is Necromancy, whose "becomes an Aura" adds a subtype to an
    enchantment that stays one. A sentence that does name one replaces every
    card type the permanent had, and CR 205.1a's last clause takes the subtypes
    correlated with a removed type with it: a Licid stops being a creature, so
    it stops being a Licid.

    Read off the **printed** shape rather than the computed one, because what
    this replaces is the copiable line the layer system starts from; a type
    something else granted is a separate contribution with its own timestamp
    and CR 613.7 decides between them.
    """
    if not gained:
        return None
    from ..layer_bridge import printed_shape

    card_types, subtypes = printed_shape(source.effective_card)
    removed_types = tuple(sorted(set(card_types) - set(gained)))
    if not removed_types:
        return None
    from ..grammar.vocabulary import CREATURE_TYPES

    creature_subtypes = (
        tuple(sorted(word for word in subtypes if word in CREATURE_TYPES))
        if "creature" in removed_types else ()
    )
    return removed_types, creature_subtypes


@effect_handler("gain_type")
def gain_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Ashnod's Transmogrant: "That creature becomes an artifact in addition to
    its other types." Xenic Poltergeist: "Until your next upkeep, target
    noncreature artifact becomes an artifact creature with power and toughness
    each equal to its mana value."

    Nothing on the permanent's own card is touched. The gained type is a record
    the CR 613 bridge reads on every recompute (`type_changes.gain_types`,
    stamped as the effect is created — CR 613.7b),
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

    card_types = [str(word) for word in (payload.get("card_types") or ())]
    gain_types(
        target_perm,
        card_types=card_types,
        source=context.card.name if context.card else "effect",
        duration=str(payload.get("duration", "permanent")),
        pt_from_mana_value=bool(payload.get("pt_from_mana_value")),
        # "…until **your** next upkeep" — whose upkeep ends it. Recorded when
        # the ability resolves rather than looked up when it expires: by then
        # the source may be gone, and CR 109.5 makes this the controller of the
        # ability, not of the permanent it was pointed at.
        seat=game.players.index(context.caster) if context.caster in game.players else 0,
    )
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} becomes "
        + " ".join(card_types)
    )
    return True, "resolved"


@effect_handler("set_target_creature_type")
def set_target_creature_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a creature type other than Wall. **Target creature becomes that
    type until end of turn.**" (Unnatural Selection.)

    CR 205.1a's subtype set, as one layer-4 record: the chosen creature type
    replaces the creature types the permanent has and no other subtype, and
    the record carries its own timestamp (CR 613.7b) and its own duration, so
    the cleanup step ends it by dropping it and whatever else says what the
    creature is — a Conspiracy, an Aura's "is a Knight" — reasserts itself in
    timestamp order rather than a printed line being put back.

    The type is the one the choosing step in front recorded as this ability
    resolved (CR 608.2d). An unanswered choice sets nothing: a creature that
    became a type nobody picked is the wrong creature.

    The printed noun phrase is re-asked here through ``subject_matches`` (CR
    608.2b), with no fallback: a target that stopped being a creature in
    response is not given a creature type, and no bystander is.
    """
    from ..grammar.vocabulary import CREATURE_TYPES
    from ..subject_filters import subject_matches

    name = context.card.name if context.card is not None else "Effect"
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(
            game, perm, filters, observer=observer, source=context.source_permanent
        ),
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{name}: no valid creature to change the type of")
        return True, "resolved"
    chosen = context.results.get(str(instruction.payload.get("subtype_from") or ""))
    word = str(chosen or "").strip().lower()
    if word not in CREATURE_TYPES:
        game.log.append(f"{name}: no creature type was chosen, so nothing changes")
        return True, "resolved"
    gain_types(
        target,
        subtypes=[word],
        source=name,
        duration=str(instruction.payload.get("duration") or "until_end_of_turn"),
        # CR 205.1a: a subtype *set* replaces the subtypes "from the
        # appropriate set" — the creature types, and nothing else the
        # permanent is. Read by ``layer_bridge.collect_own_type_effects``.
        replaces_creature_types=True,
    )
    # A creature that changed type is one a type-scoped static now reaches or
    # no longer does ("Other Goblins get +1/+1", "All Zombies are …"), and
    # where each applies is decided for the whole board (CR 613.8a).
    game._refresh_dynamic_creatures()
    game._recalculate_lord_buffs()
    game.log.append(
        f"{target.card.name} became a {word.title()} until end of turn ({name})"
    )
    return True, "resolved"


@effect_handler("set_card_types_self")
def set_card_types_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{0}: This permanent becomes an enchantment." (Opal Acrolith.) "Whenever
    you play a land, if this permanent is a creature, it becomes an
    enchantment." (Hidden Stag.)

    CR 205.1a's replacement, written as one record the CR 613 layer-4 collector
    reads (`layer_bridge.SET_CARD_TYPES`). Nothing is restored and the
    animation record it undoes is **not** deleted: both are layer-4
    contributions and CR 613.7 applies them in timestamp order, so the later
    one wins — which is the whole of what makes Opal Acrolith work when it
    animates a second time. Deleting the animation instead would work once and
    then lose the size the third sentence needs.

    The P/T the animation set stays on its own channel for the same reason: it
    is layer 7b, and CR 208.3 makes a non-creature's power and toughness simply
    not exist rather than something to unset. A permanent that animates again
    is the size its own sentence gave it.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    card_types = [str(word) for word in (instruction.payload.get("card_types") or ())]
    if not card_types:
        return False, "ability not implemented"
    _record_set_card_types(game, source, instruction, context)
    game.log.append(
        f"{source.card.name} becomes " + " ".join(card_types)
    )
    return True, "resolved"


def _record_set_card_types(
    game: Game, perm: Permanent, instruction: OracleInstruction,
    context: OracleExecutionContext,
) -> None:
    """Write the CR 205.1a replacement onto *perm*, with its window.

    One writer for the two kinds that produce this record — the ability's own
    source and a chosen target — so the slot's shape is decided in one place.
    That matters here more than usual: the sweep that ends the window reads
    ``duration`` off this dict, and a second writer that spelled it differently
    would be a replacement nothing could end.

    A **permanent** replacement carries no ``duration`` key at all rather than a
    ``"permanent"`` sentinel: ``event_durations.clear_set_card_types`` compares
    the key against the window that is closing, and an absent key can match
    nothing — which is exactly right for Opal Acrolith, whose own animation this
    undoes for the rest of the game.
    """
    record: dict[str, object] = {
        "card_types": [str(word) for word in (instruction.payload.get("card_types") or ())],
        "timestamp": next_timestamp(),
        "source": context.card.name if context.card else "effect",
    }
    duration = instruction.payload.get("duration")
    if duration:
        record["duration"] = str(duration)
    perm.metadata[SET_CARD_TYPES] = record
    game._refresh_dynamic_creatures()


@effect_handler("set_card_types_target")
def set_card_types_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{1}{W}, {T}: **Target creature** becomes an enchantment and loses all
    abilities until a player casts a creature spell." (Soul Sculptor.)

    :func:`set_card_types_self` aimed somewhere else, and the same record on the
    same layer-4 channel — what is different is that the permanent has to be
    resolved rather than assumed, and that the record carries a window.

    CR 205.1a *replaces* the type line, so the creature stops being a creature:
    it leaves combat, stops being able to attack or block, and its power and
    toughness cease to exist (CR 208.3). Nothing here does any of that by hand
    — every one of those is computed off the layer stack, which is the whole
    reason the change is a contribution and not a rewrite of the card.

    The printed noun phrase is applied through ``permanent_matches_filter``, the
    same read every other targeted board effect makes, so "target **creature**"
    is enforced against what the permanent is *now* (CR 613) rather than against
    what it was printed as.
    """
    payload = instruction.payload
    filters = (payload.get("targets") or {}).get("filter") or {}

    def _eligible(perm: Permanent) -> bool:
        return permanent_matches_filter(perm, filters)

    target_perm = resolve_target_permanent(
        game, context, predicate=_eligible,
        fallback_players=(context.target, context.caster),
    )
    if target_perm is None:
        game.log.append(f"{context.card.name}: no valid target")
        return True, "resolved"
    _record_set_card_types(game, target_perm, instruction, context)
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} becomes "
        + " ".join(str(word) for word in (payload.get("card_types") or ()))
    )
    return True, "resolved"


@effect_handler("change_supertype")
def change_supertype(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Arcum's Weathervane: "{2}, {T}: Target nonsnow basic land becomes snow."
    and "{2}, {T}: Target snow land is no longer snow."

    CR 205.4a's half of the type line, changed in CR 613 layer 4 — the same
    write API :func:`gain_type` goes through, with the supertype in the record
    instead of a card type. Nothing on the permanent's own card is touched, so
    the land stops being snow by the record going away rather than by anything
    being restored.

    **Each activation is its own effect with its own timestamp** (CR 613.7b),
    and that is what makes the two sentences undo each other: of "becomes
    snow" and "is no longer snow" on one land the later is what the land is,
    and against Melting's "All lands are no longer snow" a land frozen *after*
    Melting arrived is snow. Both were recorded unstamped and applied
    additions-first, so a thaw beat every freeze whichever came last.

    The polarity is payload, so one handler answers both printed sentences. It
    reaches the *computed* readers — ``Permanent.has_supertype`` and the eight
    call sites that ask it — which is what makes a thawed Snow-Covered Forest
    stop satisfying snow forestwalk and stop counting for Drift of the Dead.
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

    word = str(payload.get("supertype", "")).lower()
    gained = bool(payload.get("gained", True))
    (gain_types if gained else lose_types)(
        target_perm,
        supertypes=[word],
        source=context.card.name if context.card else "effect",
        duration=str(payload.get("duration", "permanent")),
        seat=game.players.index(context.caster) if context.caster in game.players else 0,
    )
    game._refresh_dynamic_creatures()
    game.log.append(
        f"{context.card.name}: {target_perm.card.name} "
        + (f"becomes {word}" if gained else f"is no longer {word}")
    )
    return True, "resolved"


@effect_handler("swap_land_types_until_eot")
def swap_land_types_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a land type and a basic land type. Each land of the first chosen
    type becomes the second chosen type until end of turn." (Vision Charm's
    third mode, CR 305.7 / CR 608.2d.)

    The handler arms the prompt and the **resolver** performs the swap, which is
    Jinx's arrangement one land at a time: CR 608.2d puts the choice inside the
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
        if perm.has_type("land")
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
