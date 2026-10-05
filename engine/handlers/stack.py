from __future__ import annotations

from typing import TYPE_CHECKING

from ..card_hooks import ON_SPELL_COUNTERED
from ..counter_conditions import spell_cant_be_countered
from ..divided_damage import DIVIDED_TARGETS, divided_entry
from ..exiled_records import (EXILE_RECORD_KEY, EXILED_SPELL_CONTROLLER_KEY,
                              StackAnnouncement, is_live, record_exiled_card,
                              record_in_context)
from ..game_types import StackItem
from ..faces import is_face, spell_named, whole_card
from ..mana_payment import mana_cost_label, total_pips
from ..oracle_types import (COUNTERED_ABILITY_SOURCE, COUNTERED_SPELL_CONTROLLER,
                            COUNTERED_SPELL_NAME)
from ..resumption import run_resumable
from ._common import _card_matches_filter, count_from_payload, resolve_amount
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
    if context.target_permanent_index is not None:
        # CR 707.10c: "You may choose new targets for the copy" — and this
        # caster did. A copy that kept the original's targets chose nothing,
        # which is why ``_stack_push`` announces no copy on its own.
        game.announce_targets_chosen(game.stack[-1], chooser=caster_index)
    return True, "resolved"


# ---------------------------------------------------------------------------
# CR 406 — a spell that leaves the stack for exile, and the card that comes back
# ---------------------------------------------------------------------------


def _stack_announcement(item: StackItem) -> StackAnnouncement:
    """CR 707.10's copiable decisions, frozen off *item* while it still exists.

    Read here rather than in ``exiled_records`` so the record's schema does not
    have to know what a ``StackItem`` is; this module is the one that already
    does.
    """
    return StackAnnouncement(
        caster_index=item.caster_index,
        target_player_index=item.target_player_index,
        target_permanent_index=item.target_permanent_index,
        target_permanent_id=item.target_permanent_id,
        target_graveyard_card=item.target_graveyard_card,
        x_value=item.x_value,
        chosen_mode_index=item.chosen_mode_index,
        chosen_modes=item.chosen_modes,
        target_stack_item=item.target_stack_item,
        choices=dict(item.choices),
        face_name=item.card.name if is_face(item.card) else None,
    )


@effect_handler("exile_target_spell")
def exile_target_spell(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target spell's controller exiles it with X delay counters on it."
    (Ertai's Meddling.)

    **Not a counter.** CR 701.6a's countering removes a spell from the stack and
    puts its card into its owner's graveyard; this moves the same object to
    exile instead, and the difference is the whole card — "can't be countered"
    does not stop it, and nothing that watches for a countered spell fires.
    So it is its own kind rather than a destination payload on
    ``counter_top_stack_spell``, whose every step (the "unless its controller
    pays" offer, the counter hooks, the countered-spell records) is about the
    rule this one does not use.

    The card is registered in ``engine/exiled_records.py`` with the counters the
    sentence names, and with CR 707.10's **announcement** — the decisions a copy
    of the spell has to inherit, frozen now because CR 400.7 destroys the stack
    object the moment the card leaves. Both go into the resolution scratchpad,
    where the delayed ability the next sentence creates freezes them
    (CR 608.2h).

    A copy has no card to exile, so it ceases to exist instead — CR 707.10a,
    the same answer the countering path gives one function up.
    """
    target = context.stack_target
    if target is None or not any(item is target for item in game.stack):
        # CR 608.2b: the spell is no longer there to be exiled. Nothing is
        # recorded, so the delayed ability the next sentence creates binds no
        # record and arms nothing — the loud direction rather than an ability
        # that fires every upkeep about a card nobody exiled.
        game.log.append(f"{context.card.name}: that spell is no longer on the stack")
        return True, "resolved"
    for index, item in enumerate(game.stack):
        # By identity: ``StackItem`` compares by value, so two copies of one
        # spell aimed at one player are equal and ``list.remove`` would take the
        # wrong one — the look-alike this engine keeps finding.
        if item is target:
            del game.stack[index]
            break
    if target.is_copy:
        # CR 707.10a: a copy of a spell in any zone other than the stack ceases
        # to exist. There is no card to exile, no record to keep and nothing for
        # the delay to be about.
        game.log.append(
            f"{context.card.name} removed {target.card.name} (copy) from the "
            "stack, and it ceases to exist"
        )
        return True, "resolved"
    # CR 400.3/406.1: the card goes to its **owner's** exile — the stack
    # object's ``owner_index`` (CR 108.3), which is the caster only when the
    # caster owns the card. A spell cast out of an opponent's exile (Grinning
    # Totem) goes back to that opponent's pile, and the record names them.
    owner_index = target.owner_index
    owner = game.players[owner_index]
    counters = {
        str(name): resolve_amount(count, context.x_value)
        for name, count in (instruction.payload.get("counters") or {}).items()
    }
    game._bin_spell_card(
        owner, target.card, exile_instead=True,
        verb=f"was exiled by {context.card.name}",
    )
    record = record_exiled_card(
        # The card as exile holds it (CR 709.4): ``_bin_spell_card`` put the
        # *whole* card there, and the register is keyed on that object.
        game, whole_card(target.card), owner_index,
        # CR 108.4 gives a card in exile no controller, so its own abilities
        # belong to its owner. The printed possessive ("**that player's**
        # upkeeps") is a different seat once the two come apart — the *spell's*
        # controller, recorded on its own key below.
        controller_index=owner_index,
        counters=counters,
        announcement=_stack_announcement(target),
    )
    # The record goes into the resolution scratchpad under the key
    # ``record_in_context`` reads: ``create_delayed_trigger`` freezes the whole
    # scratchpad into the entry's ``captured`` and
    # ``DelayedTrigger.trigger_event`` merges that into the trigger context, so
    # "remove a delay counter from **it**" reaches the card in exile with no
    # second channel (CR 608.2h).
    context.results[EXILE_RECORD_KEY] = record
    # "Target spell's **controller** … each of **that player's** upkeeps" — the
    # seat that controlled the spell (CR 108.4), which is its caster, and which
    # is the owner only when the caster owns the card.
    context.results[EXILED_SPELL_CONTROLLER_KEY] = target.caster_index
    if counters:
        game.log.append(
            f"{target.card.name} was exiled with "
            + ", ".join(
                f"{count} {name} counter" + ("s" if count != 1 else "")
                for name, count in counters.items()
            )
        )
    return True, "resolved"


@effect_handler("put_exiled_card_onto_stack_as_copy")
def put_exiled_card_onto_stack_as_copy(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…the player puts it onto the stack as a copy of the original spell."
    (Ertai's Meddling.)

    The card comes out of exile and goes onto the stack carrying CR 707.10's
    copied decisions — the modes, the targets and the value of X the original
    was announced with, read off the :class:`StackAnnouncement` the exiling step
    froze. There is nowhere else they could come from: CR 400.7 destroyed the
    original stack object, and the card in exile is a bare ``CardDefinition``.

    ``is_copy`` is **not** set, and that is the rule rather than an oversight.
    The flag means "a copy with no card of its own", which resolves and ceases
    to exist (CR 707.10a) — but here the physical card is the object on the
    stack, so CR 608.2n's owner's graveyard is where it goes when it resolves.
    Setting the flag would delete a real card from the game.

    Nothing is *cast* (CR 707.10), so this goes straight onto the stack rather
    than through the cast path: no cast trigger fires and no cost is paid, and
    the targets are already chosen.
    """
    record = record_in_context(context)
    if record is None or not is_live(game, record):
        # CR 608.2b's shape one zone over: the card the ability is about is not
        # in exile any more, so there is nothing to put anywhere. The gate the
        # printed sentence states ("if that card is exiled") answers this too;
        # asked again here because an ability on the stack is independent of the
        # object it is about (CR 608.2), and between the two the card can move.
        game.log.append(f"{context.card.name}: that card is no longer exiled")
        return True, "resolved"
    announcement = record.announcement
    if announcement is None:
        # A record with no announcement speaks for a card that was never a
        # spell on the stack — there are no copiable decisions, and guessing at
        # targets nobody chose is the widening every bound payload in this
        # engine refuses.
        game.log.append(
            f"{context.card.name}: nothing was announced for {record.card.name}"
        )
        return True, "resolved"
    # CR 707.10: "a copy of a spell is controlled by the player under whose
    # control it was put on the stack" — the player the sentence names, which
    # for a delayed ability is the seat its creating effect bound.
    seat = announcement.caster_index
    chosen = context.target
    if chosen is not None and any(seat_player is chosen for seat_player in game.players):
        seat = game.players.index(chosen)
    game.take_card_from_exile(
        game.players[record.owner_index], record.card, record=record
    )
    copy = StackItem(
        # CR 707.10 copies "the characteristics of the spell", and for a split
        # card those are one half's (CR 709.3b) — the half the announcement
        # recorded, since the card in exile is the whole card again.
        card=(
            spell_named(record.card, announcement.face_name)
            if announcement.face_name is not None else None
        ) or record.card,
        caster_index=seat,
        # The physical card is the object (see the docstring), so CR 608.2n
        # bins it to its **owner's** graveyard — the seat whose exile it just
        # left, whoever puts it on the stack.
        owner_index=record.owner_index,
        target_player_index=announcement.target_player_index,
        target_permanent_index=announcement.target_permanent_index,
        target_permanent_id=announcement.target_permanent_id,
        target_graveyard_card=announcement.target_graveyard_card,
        x_value=announcement.x_value,
        choices=dict(announcement.choices),
        chosen_mode_index=announcement.chosen_mode_index,
        chosen_modes=announcement.chosen_modes,
        target_stack_item=announcement.target_stack_item,
        # ``cast_from_zone`` is deliberately left at its default. CR 707.10: "a
        # copy of a spell isn't cast" — so the honest answer to "was this spell
        # cast from somewhere other than your hand" is *no*, and that is what
        # the default gives. Stamping "exile" because the card came from there
        # would answer *yes* to a question about a casting that never happened.
    )
    game._stack_push(item=copy, targets_already_chosen=True)
    game.log.append(
        f"{game.players[seat].name} put {record.card.name} onto the stack as a "
        "copy of the original spell"
    )
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

    CR 701.6a: the object is removed from the stack and does nothing. Nothing
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
            # The life half of one offer, as the spell counter below sends it.
            **(
                {"life": int(instruction.payload["unless_pays_life"])}
                if instruction.payload.get("unless_pays_life") else {}
            ),
            # The marker the headless/AI path keys on to resolve this
            # deterministically the moment the resolution that armed it ends
            # (mixins/stack/resolution.py). Without it the prompt arms, nobody
            # answers it, and the object it was supposed to gate resolves
            # anyway — which is the counter silently never happening.
            _new=True,
        )
        return True, "resolved"
    # The same seam the spell counter uses: an ability is countered by the same
    # rule (CR 701.6a) and the seam is what knows an ability makes no
    # announcement, so this handler does not have to.
    game.counter_stack_object(chosen)
    # "**That permanent's** activated abilities can't be activated this turn."
    # (Interdict.) The permanent the countered ability came from, recorded here
    # because this is the only step that knows it: the spell targeted the
    # ability, and an ability on the stack has no card of its own (CR 113.7a),
    # so once it is off the stack nothing else can be asked which permanent it
    # came from.
    if chosen.source_permanent is not None:
        context.results[COUNTERED_ABILITY_SOURCE] = chosen.source_permanent
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


def _counter_targets_refusal(game, instruction, context, target) -> bool:
    """Whether the chosen object fails the counter's "…that targets …" rider.

    "…that targets a permanent you control" (Avoid Fate, Ring of Immortals),
    "…that targets **this creature**" (Mistfolk), "…that targets a creature"
    (Diplomatic Escort). One reader, because it is one question and a spell is
    not the only object that can be asked it: a spell announced its targets at
    CR 601.2c and an ability announced its own at CR 602.2b, and the union
    counter below reaches this from its own branch. Two copies would be a rider
    honoured on the spell half of an offer and dropped on the ability half,
    which is the whole of Diplomatic Escort's printed narrowing.

    ``targets_source`` is Mistfolk's half, asked with the ability's own
    permanent in hand — with the source gone there is no permanent the object
    could still be aimed at, and the counter finds nothing, which is CR 608.2b's
    answer rather than a missing check.
    """
    targets_filter = instruction.payload.get("targets_filter")
    targets_source = (
        context.source_permanent
        if instruction.payload.get("targets_source") else None
    )
    if not targets_filter and targets_source is None:
        return False
    return not _spell_targets_matching(
        game, target, dict(targets_filter or {}),
        game.players.index(context.caster), source=targets_source,
    )


def _counter_controller_refusal(game, instruction, context, target) -> str | None:
    """Why *target* is not an object this counter may name by its controller,
    or None.

    "counter target artifact spell **you control**" (Goblin Artisans) and
    "counter target spell or ability **an opponent controls**" (Teferi's
    Response): one question with the answer turned over, asked of the seat that
    put the object on the stack. CR 112.2 makes that a spell's controller and
    CR 113.8 an ability's, so ``caster_index`` answers for both kinds and this
    is read on **both** sides of the card/no-card divide below — it was asked
    of spells alone, which was the whole pool until a union printed it.
    """
    wanted = instruction.payload.get("controller")
    if wanted is None:
        return None
    mine = target.caster_index == game.players.index(context.caster)
    if wanted == "you" and not mine:
        return "you control"
    if wanted == "opponent" and mine:
        return "an opponent controls"
    return None


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
        if instruction.payload.get("bound_to_target"):
            # "…If you win the bidding, counter **that spell**." (Mages'
            # Contest.) A back-reference to the object the announcement chose,
            # not a second choice — so it is that object or nothing. The
            # fallback below takes the top of the stack when the chosen spell
            # is gone, which is right for a caller that named none and wrong
            # here: by identity (``StackItem`` compares by value, and two
            # casts of one card at one target are equal), and with no
            # substitute.
            if chosen is None or not any(item is chosen for item in game.stack):
                game.log.append(
                    f"{card.name}: the spell it would counter is no longer on the stack"
                )
                return True, "resolved"
        target = chosen if (chosen is not None and chosen in game.stack) else game.stack[-1]
        # **The one place this engine decides which kind of object it
        # countered.** CR 701.6a counters a spell and an ability alike, and
        # CR 113.7a is the entire difference between them: a countered spell's
        # card goes to its owner's graveyard, and an ability has no card at all
        # — so every step below this one is a question about a card, and
        # ``target.card`` on an ability is the *source permanent's* card, which
        # answers all of them wrongly. Asked here, ahead of them, so a branch
        # is needed exactly once rather than at each gate.
        #
        # ``also_ability`` is "Counter target spell **or ability**"
        # (Diplomatic Escort); the lowering refuses every card question beside
        # that union, so the rider below is all there is left to ask.
        #
        # **Without the union the answer is to counter nothing**, and that is
        # not defensive tidiness: the fallback above takes the top of the stack
        # when the chosen object is gone, and the top of the stack is very often
        # an activated ability. Reaching CR 701.6a's graveyard from there would
        # put the *source permanent's* card into a graveyard while the permanent
        # itself stayed on the battlefield — a card conjured out of a counter
        # that had nothing to counter.
        if target.is_ability:
            if not instruction.payload.get("also_ability"):
                game.log.append(
                    f"{card.name}: the top of the stack is "
                    f"{target.card.name}'s ability, not a spell; nothing is countered"
                )
                return True, "resolved"
            if _counter_targets_refusal(game, instruction, context, target):
                game.log.append(
                    f"{card.name}: {target.card.name}'s ability does not target "
                    "a matching permanent, cannot counter"
                )
                return True, "resolved"
            whose = _counter_controller_refusal(game, instruction, context, target)
            if whose is not None:
                game.log.append(
                    f"{card.name}: {target.card.name}'s ability is not one "
                    f"{whose}, cannot counter"
                )
                return True, "resolved"
            # The same seam the spell path ends with, and the whole of the
            # effect here: CR 701.6a removes the object from the stack, and
            # there is no card to bin, no "exile it instead" rider to honour
            # and no destination to redirect.
            game.counter_stack_object(target)
            # "If **a permanent's ability** is countered this way, destroy that
            # permanent." (Teferi's Response.) The record Interdict's counter
            # writes, written here for the same reason: this is the only step
            # that knows which permanent the ability came from, and once the
            # object is off the stack nothing else can be asked (CR 113.7a).
            # A source that has already left the battlefield is not "a
            # permanent" any more (CR 110.1), so it is not recorded — the
            # destroy behind this would otherwise chase an id nothing holds.
            source = target.source_permanent
            if source is not None and game.is_on_battlefield(source):
                context.results[COUNTERED_ABILITY_SOURCE] = source
            game.log.append(f"{card.name} countered {target.card.name}'s ability")
            return True, "resolved"
        # What this step **chose**, recorded the moment it is known and not
        # where the counter succeeds. CR 608.2 does as much of the effect as it
        # can: "Counter target instant or sorcery spell. Search its controller's
        # graveyard, hand, and library for all cards with the same name as
        # **that spell** and exile them" (Quash) searches whether or not the
        # spell could be countered, and so does Arcane Denial's "**its
        # controller** may draw up to two cards" — an uncounterable spell, a
        # colour the payload declines, or a controller who pays the "unless"
        # cost all leave the sentence behind this one with the same object to
        # talk about.
        #
        # Both keys together, because they describe one object: a seat written
        # without the name would let Quash open the right library and search for
        # nothing, which is the half-effect that reports resolved.
        context.results[COUNTERED_SPELL_NAME] = target.card.name
        context.results[COUNTERED_SPELL_CONTROLLER] = target.caster_index
        # "This spell can't be countered." (Scragnoth.) CR 113.6g: the ability
        # functions while the object is on the stack, so it is asked here — at
        # CR 608.2, the one moment the spell exists to be asked — and **before**
        # every narrowing below, including the "unless its controller pays"
        # prompt. Arming that prompt for a spell nothing can counter would ask a
        # player to pay to prevent something that was never going to happen.
        #
        # Not a targeting restriction: Counterspell prints "target spell", not
        # "target spell that can be countered", so the uncounterable spell is a
        # legal choice (CR 115.1) and the counter simply does nothing.
        # `effective_card` is the wrong reader here and deliberately unused —
        # that is a `Permanent`'s accessor for what a permanent says, and this
        # object is a card on the stack (CR 613.1: its printed face is all there
        # is).
        if spell_cant_be_countered(target.card):
            game.log.append(
                f"{card.name}: {target.card.name} can't be countered"
            )
            return True, "resolved"
        if color_filter and color_filter not in game._stack_item_colors(target):
            game.log.append(f"{card.name}: {target.card.name} is not color {color_filter}, cannot counter")
            return True, "resolved"
        # "counter target **red or green** spell" (Tidal Control). The colour
        # union, asked through the same reader the single colour is — a spell is
        # counterable while it is *any* of the printed colours (CR 105.2), so
        # this is an `any`, never a second `in` against a joined string.
        any_colors = instruction.payload.get("any_colors")
        if any_colors:
            item_colors = game._stack_item_colors(target)
            if not any(colour in item_colors for colour in any_colors):
                game.log.append(
                    f"{card.name}: {target.card.name} is not "
                    f"{' or '.join(any_colors)}, cannot counter"
                )
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
        # "counter target **noncreature** spell" (Null Brooch). The complement
        # of the union above, tested through the same reader (CR 205.2: a card
        # has *every* type its line names, so an artifact creature is excluded
        # by "noncreature") and negated here rather than in the payload — a
        # "noncreature" word inside `card_types` would have countered exactly
        # the spells the card refuses.
        excluded_types = instruction.payload.get("excluded_types")
        if excluded_types and _spell_is_one_of(target.card, excluded_types):
            game.log.append(
                f"{card.name}: {target.card.name} is "
                f"{' or '.join(excluded_types)}, cannot counter"
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
        if _counter_targets_refusal(game, instruction, context, target):
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
        # "counter target artifact spell **you control**" (Goblin Artisans),
        # "…spell or ability **an opponent controls**" (Teferi's Response).
        # Whose spell it is, asked of the seat that put it on the stack.
        whose = _counter_controller_refusal(game, instruction, context, target)
        if whose is not None:
            game.log.append(
                f"{card.name}: {target.card.name} is not a spell {whose}, "
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
                    # The *effective* names (CR 707.2): a Clone copying Goblin
                    # Artisans is a creature named Goblin Artisans, and its
                    # ability locks the spell out like any other rival's.
                    and item.source_permanent.effective_card.name
                    == source.effective_card.name
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
        printed_cost = instruction.payload.get("unless_pays_cost")
        if (
            instruction.payload.get("unless_pays_x")
            or instruction.payload.get("unless_pays_amount")
            or printed_cost
        ):
            # Power Sink sizes the cost from its caster's chosen X; Miscast
            # prints it; Thrull Wizard prints a coloured one with a second way
            # to cover it. Everything after the amount is one flow.
            alternatives = [
                dict(alt)
                for alt in instruction.payload.get("unless_pays_cost_alternatives") or ()
            ]
            if printed_cost:
                cost = total_pips(printed_cost)
                symbols: dict[str, int] | None = dict(printed_cost)
            else:
                symbols = None
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
            # "…pays {1} **for each card revealed this way**." (Brine Seer,
            # Scent of Brine.) The printed cost is a *rate*: what the payer
            # owes is that price once per unit an earlier step of this same
            # resolution recorded. Read here, where CR 608.2 takes the count —
            # the reveal happened a step ago and its record is in this
            # resolution's scratchpad, which nothing at lowering time could see.
            #
            # Nought revealed is a price of {0}, which every board covers: the
            # spell is not countered, which is exactly what the card says a
            # Seer that showed nothing does.
            per_recorded = instruction.payload.get("unless_pays_per_recorded")
            if per_recorded is not None:
                cost *= count_from_payload(game, context, per_recorded)
            # "…and 1 life" (Mundungu). The life half of one offer, sent on
            # the same prompt: what the payer decides is whether to pay the
            # whole price, so a second prompt would be a second decision and a
            # second counter.
            life = int(instruction.payload.get("unless_pays_life", 0) or 0)
            if cost == 0 and not life:
                game.log.append(
                    f"{game.players[target.caster_index].name} pays {{0}}; "
                    f"{target.card.name} is not countered by {card.name}"
                )
                return True, "resolved"
            game.arm_pending_choice(
                "mana_payment", target.caster_index,
                amount=cost, card_name=card.name, counter_card=card,
                stack_item=target,
                # Absent for the two numeric forms, so their prompt data is
                # byte-identical to what it was; ``_mana_payment_cost`` falls
                # back to ``generic_cost(amount)`` when there is no symbol dict.
                **({"cost": symbols} if symbols is not None else {}),
                **({"cost_alternatives": alternatives} if alternatives else {}),
                # Absent when the card prints no life, so every prompt written
                # before this existed carries byte-identical data.
                **({"life": life} if life else {}),
                _new=True,
            )
            game.log.append(
                f"{card.name}: {game.players[target.caster_index].name} must pay "
                f"{mana_cost_label(symbols) if symbols is not None else f'{{{cost}}}'}"
                + "".join(f" or {mana_cost_label(alt)}" for alt in alternatives)
                + (f" and {life} life" if life else "")
                + f" or {target.card.name} is countered"
            )
            return True, "resolved"

        # CR 701.6a's cancel, through the one seam that makes it — which also
        # announces it, so "whenever a spell you've cast is countered" fires
        # here without this handler knowing the condition exists.
        game.counter_stack_object(target)
        countered = target
        # "…add an amount of {C} equal to **that spell's** mana value." (Mana
        # Drain.) The countered spell's mana value, recorded in the resolution
        # scratchpad the moment it is known: the next sentence creates a
        # delayed ability that will not fire until a later phase, by which time
        # the card is in a graveyard and the stack item is gone (CR 608.2h).
        # CR 202.3b again: Mana Drain on a Fireball cast for X=3 makes {C}{C}{C}{C}.
        from ..targeting import stack_object_mana_value

        context.results["countered_spell_mana_value"] = stack_object_mana_value(countered)
        # "**Its controller** may draw up to two cards at the beginning of the
        # next turn's upkeep." (Arcane Denial.) The other thing about the
        # countered spell that only the counter can write down — CR 108.4 gives
        # a card in a graveyard no controller, and by the time the delayed
        # ability fires, a turn later on a different player's upkeep, the stack
        # item is long gone. Written **above**, where the spell is chosen, for
        # the reason recorded there: the sentence behind the counter runs
        # whether or not the counter itself did anything.
        destination = instruction.payload.get("countered_destination")
        # "**If an artifact or creature spell** is countered this way…"
        # (Desertion.) CR 614.1's replacement is conditional on the countered
        # spell's class, so a spell outside it takes CR 701.6a's ordinary
        # graveyard — the destination is dropped rather than the counter.
        # Tested with ``_card_matches_filter``: what was countered is a *card*
        # with no battlefield object, so its characteristics are the printed
        # ones (CR 613.1).
        described = instruction.payload.get("countered_filter")
        if destination is not None and described:
            if not _card_matches_filter(countered.card, described):
                destination = None
        if countered.is_copy:
            # 704.5e: a countered copy of a spell ceases to exist instead of
            # going to a graveyard — it has no physical card to put there. Also
            # the answer for a redirected destination: a copy has no card to
            # put on a library either, and CR 707.10 makes the copy cease to
            # exist wherever the replacement would have sent it.
            game.log.append(f"{card.name} countered {countered.card.name} (copy), which ceases to exist")
        elif destination is not None:
            _redirect_countered_card(
                game, card, countered, str(destination), counterer=context.caster
            )
        else:
            # CR 701.6a: "its **owner's** graveyard" (CR 108.3).
            game._bin_spell_card(
                game.players[countered.owner_index], countered.card,
                exile_instead=countered.exile_instead_of_graveyard,
                verb=f"was countered by {card.name}",
            )
        counter_hook = ON_SPELL_COUNTERED.get(card.name)
        if counter_hook is not None:
            counter_hook(game, card, countered)
    else:
        game.log.append(f"{card.name} resolved with no spell to counter")
    return True, "resolved"


def _redirect_countered_card(
    game: Game, card, countered, destination: str, counterer=None
) -> None:
    """"…put it on top of its owner's library instead of into that player's
    graveyard." (Memory Lapse.)

    CR 614.1 replacing the destination CR 701.6a would otherwise give the card,
    so it happens *instead of* ``_bin_spell_card`` rather than after it — a
    graveyard visit that is then undone is a zone change other replacements and
    triggers would have seen.

    Through ``Game.put_card_into_library`` / ``put_card_into_hand`` and not a
    raw ``library.insert``: those are the two seams CR 903.9b has to be asked at
    and they have no single fire site, which is why every "put a card into a
    hand or a library" in this engine goes through them. Each answers False
    when something diverted the card, and the log says which happened.

    The **owner**, not the caster: CR 404.3's destination is the owner's zone
    and this replaces only *which* zone, not whose. ``StackItem.owner_index``
    (CR 108.3) is that seat, and it is not the caster for a spell cast out of
    another player's zone (Psychic Theft, Grinning Totem).
    """
    owner = game.players[countered.owner_index]
    if destination == "battlefield_your_control":
        # "…put that card onto the battlefield **under your control** instead
        # of into its owner's graveyard." (Desertion.) The one destination on
        # this list whose seat is not the countered card's owner: CR 110.2's
        # battlefield is shared, and the sentence names the *counterspell's*
        # controller, so the card changes hands. Through the ordinary
        # enters-the-battlefield path, because it is one (CR 603.6a): the card
        # arrives as a new object with a new ``permanent_id``, and anything
        # watching for a permanent entering sees it.
        seat = game.players.index(counterer) if counterer in game.players else 0
        from ..models import Permanent

        stolen = Permanent(card=countered.card)
        # CR 108.3: the owner is the player who started the game with the card,
        # and nothing here changes it — only who controls it. Recorded on the
        # permanent because ``owner_index_of`` otherwise reads the seat the
        # permanent *entered* under, which for every other card in this pool is
        # its owner and for this one is the thief; without it the stolen
        # creature would die into the wrong graveyard (CR 400.3). The same
        # channel reanimation uses for the same reason.
        stolen.metadata["owner_player_index"] = game.players.index(owner)
        game._put_permanent_onto_battlefield(seat, stolen, None)
        game.log.append(
            f"{countered.card.name} was countered by {card.name} and put onto "
            f"the battlefield under {game.players[seat].name}'s control "
            "instead of into their graveyard"
        )
        return
    if destination == "exile":
        # "…exile it instead of putting it into its owner's graveyard."
        # (Dissipate.) Exile is one shared zone (CR 406.1), so there is no
        # owner's copy of it to reach and none of the CR 903.9b seams applies —
        # the rule is about a hand or a library. ``_bin_spell_card`` already
        # knows the move: the card never touches a graveyard either way, which
        # is what makes this a replacement of the destination rather than a
        # graveyard visit somebody then undoes.
        game._bin_spell_card(
            owner, countered.card, exile_instead=True,
            verb=f"was countered by {card.name} and exiled",
        )
        return
    if destination == "hand":
        arrived = game.put_card_into_hand(owner, countered.card)
        where = "their hand"
    else:
        position = "top" if destination == "library_top" else "bottom"
        arrived = game.put_card_into_library(owner, countered.card, position=position)
        where = f"the {position} of their library"
    if arrived:
        game.log.append(
            f"{countered.card.name} was countered by {card.name} and put on "
            f"{where} instead of into their graveyard"
        )


@effect_handler("bid_life")
def bid_life(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You and target spell's controller bid life." (Mages' Contest.)

    Illicit Auction's round of offers among the seats the payload names, with
    nothing handed over at the end of it: the high bidder loses the high bid
    and the seat is **recorded** (``BIDDING_WINNER``), which is what the next
    step of the sequence — "if you win the bidding, …" — reads.

    The round itself is not run here, for ``bid_life_for_control``'s reason: a
    bid is a decision a seat owes, so the auction is a chain of prompts
    (``Game.begin_life_auction``) and this step ends after arming the first.
    The prompt kind ``suspends``, so the steps behind this one wait for the
    last answer (``engine/resumption.py``).

    **Who bids.** ``you`` is the resolving seat (CR 109.5). ``target spell's
    controller`` is read off the object the announcement chose, by identity,
    and a spell that has left the stack has no controller to ask — CR 608.2b
    has already taken a spell whose only target is gone off the stack above
    this handler, so that branch is the headless path's backstop. A seat named
    twice bids once: Mages' Contest aimed at its caster's own spell is an
    auction of one, which the opening bid wins.

    **The order** is CR 101.4's turn order (``_offered_seats``, the one reader
    of it) narrowed to those seats. "**You** start the bidding" makes the
    resolving seat the opening high bidder at the printed number, and the
    round goes on from the seat after it.
    """
    from .control_flow import _offered_seats

    card_name = context.card.name
    caster = game.players.index(context.caster)
    bidders: list[int] = []
    for who in instruction.payload.get("bidders") or ():
        if who == "you":
            seat = caster
        elif who == "target_spells_controller":
            target = context.stack_target
            if target is None or not any(item is target for item in game.stack):
                game.log.append(
                    f"{card_name}: the spell whose controller would bid is no "
                    "longer on the stack"
                )
                return True, "resolved"
            seat = int(target.caster_index)
        else:
            # The lowering admits exactly the two seats above; a third is a
            # payload nothing here can seat, and bidding without it would be
            # an auction among the wrong players.
            game.log.append(f"{card_name}: no seat for bidder {who!r}")
            return True, "resolved"
        if seat not in bidders and not game.players[seat].lost:
            bidders.append(seat)
    order = [
        seat for seat in _offered_seats(game, "each_player", context)
        if seat in bidders
    ]
    if caster not in order:  # pragma: no cover - the resolving seat has lost
        return True, "resolved"
    game.begin_life_auction(
        card_name=card_name,
        permanent_id=None,
        opening_bidder=caster,
        starting_bid=int(instruction.payload.get("starting_bid", 0)),
        order=order,
        results=context.results,
    )
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
    """``(spell, its one current target)`` for a retarget that may still be
    made, or None with the reason logged.

    CR 608.2b asked at the moment the rule asks it. The effect chose its target
    when it was put on the stack, and the whole point of the stack is that time
    passes: the spell can be countered, can resolve, or can have its own target
    changed by something else in between. So every condition the picker checked
    is checked again here, against the object as it stands now.

    The current target comes back beside the spell because both callers need it
    and neither should ask twice: the choosing step excludes it from the
    candidates (CR 115.7a's "**another** legal target") and the changing step
    would otherwise have to re-derive what it is replacing.

    Located by **identity**, never by ``in``: ``StackItem`` compares by value, so
    two copies of one spell aimed at one player are equal and ``in`` would find
    the wrong one — the look-alike bug that ``permanent_id`` solves on the
    battlefield.
    """
    from ..legality import _single_target_is
    from ..targeting import single_spell_target

    card_name = getattr(context.card, "name", "")
    item = context.stack_target
    if item is None or not any(waiting is item for waiting in game.stack):
        game.log.append(
            f"{card_name}: the spell it would retarget is no longer on the stack"
        )
        return None
    chosen = single_spell_target(game, item)
    if chosen is None:
        game.log.append(
            f"{card_name}: {item.card.name} no longer has a single target"
        )
        return None
    required = instruction.payload.get("current_target")
    # None is Deflection: the sentence asks nothing about who the spell points
    # at now. Lowering admits no value but "you" beside it, so a payload
    # carrying another would be a restriction nothing here can test.
    if required is not None and not (
        required == "you"
        and chosen.get("kind") == "player"
        and chosen.get("seat") == game.seat_index(context.caster)
    ):
        game.log.append(
            f"{card_name}: {item.card.name} no longer has a single target that is you"
        )
        return None
    # "…and **that target is a creature**" (Meddle), "…that targets only **a
    # player**" (Rebound). CR 608.2b asked a second time about the *other*
    # object's target, through the reader the picker used — the same
    # arrangement the seat question above has, and the one this restriction did
    # not: it was checked when the ability was activated and never again, so a
    # spell re-aimed at a face in between was still retargeted by a card that
    # only ever named one pointed at a creature.
    wanted_type = instruction.payload.get("current_target_type")
    if wanted_type is not None and not _single_target_is(
        game, chosen, wanted_type, source=context.source_permanent
    ):
        # "…that targets only **this creature**" (Silver Wyvern) is an identity
        # rather than a type, so it is named as one: "no longer a source" is not
        # a sentence, and the seat reading the log is being told which
        # permanent the object stopped pointing at.
        described = (
            context.source_permanent.card.name
            if wanted_type == "source" and context.source_permanent is not None
            else f"a {wanted_type}"
        )
        game.log.append(
            f"{card_name}: {item.card.name}'s target is no longer {described}"
        )
        return None
    return item, chosen


def _same_target(left: dict, right: dict) -> bool:
    """Whether two target descriptors name the same object or face."""
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "player":
        return left.get("seat") == right.get("seat")
    return left.get("permanent_id") == right.get("permanent_id")


def _legal_new_targets(game: Game, item: StackItem, bound) -> list[dict]:
    """The targets *item* could legally have been aimed at instead (CR 115.7a).

    Read through ``_enumerate_targets`` — the one list the picker and the cast
    gate already share — so "another legal target" means for this spell exactly
    what it meant when the spell was cast. Word of Command's "target opponent"
    therefore offers only its own caster's opponents, which is why a spell
    aimed at you by the player it may not aim at themselves simply cannot be
    moved.

    *bound* is the retargeting card's own "The new target must be a …"
    sentence, or None where it prints none. ``"player"`` forces the kind, which
    is both the restriction and an economy: the question is which *faces* are
    legal and a wider spec would walk both battlefields for an answer that card
    never uses. None asks the spell's **own** spec, so Deflection offers exactly
    what that spell could have chosen — a creature for a Lightning Bolt, a face
    for a Mind Twist.

    Each permanent is carried by ``permanent_id``, never by the slot the
    enumeration named it in: a prompt sits between this list and the write, and
    an index is what renumbers underneath one.
    """
    from ..legality import targeting_instruction
    from ..targeting import stack_object_target_spec

    # The object's own spec, which for an **ability** is not the card's. Silver
    # Wyvern re-aims "target spell or ability", and ``derive_cast_spec`` asked of
    # an ability's stack item answers about whatever that *card* does when it is
    # cast — for a creature's activated ability that is a different list or no
    # list at all, so the ability would have been offered the wrong candidates
    # or none. One reader for both kinds, in ``targeting``, so the count asked
    # by ``single_spell_target`` and the candidates offered here cannot disagree.
    spec = stack_object_target_spec(item)
    if spec is None:
        return []
    if bound == "player":
        spec = {**spec, "kind": "player"}
    # "…change that spell's target to **another creature**" (Meddle). The
    # opposite forcing to the one above and for the same reason: the question is
    # which *permanents* are legal, and asking the spell's own spec would offer
    # the faces a Lightning Bolt may also choose. It narrows rather than widens
    # — a spell whose own spec offers no creature offers none here either,
    # because ``_enumerate_targets`` still answers for that card.
    elif bound == "creature":
        spec = {**spec, "kind": "creature"}
    # An ability's own restriction ("target **tapped** creature", "target
    # non-Wall creature") and its source travel with it, for the reason the
    # activation picker passes them: CR 115.7a's replacement must be a target
    # the object *could legally have chosen*, and a narrowing left behind here
    # would offer one it could not. A spell carries neither and passes None,
    # which is exactly what it passed before.
    ability_instruction = (
        targeting_instruction(item.ability_instruction)
        if item.ability_instruction is not None
        else None
    )
    entries = game._enumerate_targets(
        item.caster_index, item.card, spec, for_cast=True,
        ability_instruction=ability_instruction,
        ability_source=item.source_permanent,
        source_permanent=item.source_permanent,
    )
    candidates: list[dict] = []
    for entry in entries:
        if entry.get("kind") == "player":
            seat = entry.get("seat")
            if not isinstance(seat, int) or game.players[seat].lost:
                continue
            candidates.append(
                {"kind": "player", "seat": seat, "name": game.players[seat].name}
            )
            continue
        # A permanent answer is dropped when the card bounds the new target to
        # a **player** — Reflecting Mirror could only ever have offered a face.
        # A creature bound is the other way round: the spec above already
        # narrowed the enumeration to creatures, so what comes back is the list
        # to offer.
        if entry.get("kind") != "permanent" or bound not in (None, "creature"):
            continue
        # The enumeration names a battlefield slot; the seam's bridge turns it
        # into a permanent once, here, and everything downstream carries the id.
        found = game.permanent_at(entry.get("seat"), entry.get("index"))
        permanent_id = None if found is None else game.permanent_id_of(found)
        if permanent_id is None:
            continue
        candidates.append({
            "kind": "permanent",
            "permanent_id": permanent_id,
            "name": entry.get("name", ""),
        })
    return candidates


@effect_handler("choose_new_spell_target")
def choose_new_spell_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Which legal target replaces the one the spell announced (CR 115.7a).

    The first of the retarget's two steps. It is its own step for the reason
    Backdraft's player choice is one (``handlers/player_choices.py``): the
    decision is made *during* this resolution and the step behind it reads the
    answer, so an interactive seat can be asked and the resolution suspended
    until it answers.

    The key is written before anything else, so the step behind this one finds
    ``None`` rather than a key error when there was nobody to choose — "no legal
    new target" is an outcome CR 115.7a names ("the original target is
    unchanged"), not a failure.

    **Another** legal target, which is what the rule says: the target the spell
    already points at is not among the candidates, so a retarget with nowhere
    else to go leaves the spell exactly as it was. A single candidate is taken
    without asking, the shortcut ``choose_player_who_cast`` states — the card
    makes the choice forced, and prompting would ask a question with one answer.
    """
    key = str(instruction.payload["result_key"])
    context.results[key] = None
    card_name = getattr(context.card, "name", "")
    subject = _retarget_subject(game, context, instruction)
    if subject is None:
        return True, "resolved"
    item, current = subject
    candidates = [
        candidate
        for candidate in _legal_new_targets(
            game, item, instruction.payload.get("new_target")
        )
        if not _same_target(candidate, current)
    ]
    if not candidates:
        # Named by the bound the card printed, because that is what the seat is
        # being told: Reflecting Mirror could only ever have offered a player,
        # so "no other legal target" would read as a wider search than it made.
        bounded = "player" if instruction.payload.get("new_target") == "player" else "target"
        game.log.append(
            f"{card_name}: {item.card.name} has no other legal {bounded}"
        )
        return True, "resolved"
    if len(candidates) == 1:
        context.results[key] = candidates[0]
        return True, "resolved"
    game.arm_retarget_choice(
        game.seat_index(context.caster),
        card_name=card_name,
        prompt=f"Choose the new target for {item.card.name}.",
        result_key=key,
        options=candidates,
        context=context,
    )
    return True, "resolved"


@effect_handler("change_target_spell_target")
def change_target_spell_target(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Change the target of target spell …" (Deflection, Reflecting Mirror —
    CR 115.7a).

    The spell keeps everything else it announced — its controller, its X, its
    modes — and only what it points at moves. That is why this writes the item's
    target fields rather than re-announcing the spell: CR 115.7a changes a
    choice, it does not re-cast anything.

    **All three target fields are written together**, whichever way the new
    target points. A spell re-aimed from a creature onto a face that kept its
    stale ``target_permanent_id`` would be resolved against the creature by
    every handler that prefers the id, and the log would say otherwise.

    ``divided_targets`` is rewritten alongside, because for a spell that
    recorded one it is the list that decides (CR 601.2d's division travels with
    the targets, and CR 115.7f keeps the division itself unchanged — with a
    single target there is only one share to keep). Writing the seat and leaving
    that list behind would log a redirect the damage step then ignored.
    """
    key = str(instruction.payload["result_key"])
    card_name = getattr(context.card, "name", "")
    chosen = context.results.get(key)
    subject = _retarget_subject(game, context, instruction)
    if subject is None:
        return True, "resolved"
    item, _current = subject
    unchanged = f"{card_name}: {item.card.name}'s target is unchanged"
    if not isinstance(chosen, dict):
        game.log.append(unchanged)
        return True, "resolved"
    if chosen.get("kind") == "permanent":
        found = game.find_permanent_by_id(chosen.get("permanent_id"))
        if found is None:
            # It left between the choice and this step. CR 115.7a: a target
            # that can't be changed to another legal target stays as it was.
            game.log.append(unchanged)
            return True, "resolved"
        seat, permanent = found
        item.target_player_index = seat
        item.target_permanent_id = game.permanent_id_of(permanent)
        item.target_permanent_index = game.battlefield_index_of(permanent)
        game.log.append(
            f"{card_name}: {item.card.name} now targets {permanent.card.name}"
        )
        # CR 115.7a: the retargeting effect's controller chose a new target for
        # the object, which is a player choosing a target.
        game.announce_targets_chosen(item, chooser=game.seat_index(context.caster))
        return True, "resolved"
    seat = chosen.get("seat")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(unchanged)
        return True, "resolved"
    item.target_player_index = seat
    item.target_permanent_id = None
    item.target_permanent_index = None
    divided = (item.choices or {}).get(DIVIDED_TARGETS)
    if divided:
        # CR 115.7f keeps the division unchanged, so the one surviving target
        # keeps the share it was announced with. Only when the spell named one
        # target is there a share to carry across; a list this collapses to one
        # face has no single announcement to keep, and an even split of one is
        # the whole amount either way.
        share = divided_entry(divided[0])[2] if len(divided) == 1 else None
        item.choices[DIVIDED_TARGETS] = (
            [(seat, None)] if share is None else [(seat, None, share)]
        )
    game.log.append(
        f"{card_name}: {item.card.name} now targets {game.players[seat].name}"
    )
    game.announce_targets_chosen(item, chooser=game.seat_index(context.caster))
    return True, "resolved"


#: Scratchpad key each slot's prompt answers into, in turn. Private to the
#: handler below: it is read by the step behind the prompt and cleared there.
_EVENT_TARGET_PICK = "event_target_change_pick"


def _target_option(game: Game, target) -> dict:
    """One candidate as a ``retarget_choice`` option.

    The public keys are the ones that prompt has always carried (``kind``,
    ``seat`` / ``permanent_id``, ``name``); the descriptor itself rides under a
    private key so the answer is the very object ``change_options`` offered and
    not a second reading of it.
    """
    from ..stack_targets import target_label

    return {
        "kind": target.kind,
        "seat": target.seat,
        "permanent_id": target.permanent_id,
        "name": target_label(game, target),
        "_stack_item": target.stack_item,
        "_stamp": target.stamp,
        "_target": target,
    }


@effect_handler("change_event_object_targets")
def change_event_object_targets(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…may change the target or targets." (Psychic Battle — CR 115.7a.)

    The object is the one **the firing event was about** — the spell or ability
    a player just chose targets for, frozen by identity when the ability
    triggered (CR 603.10). The seat that chooses is payload: this effect's
    controller for the bare sentence, or the seat "the player who reveals the
    card with the greatest mana value" names, through the one reader an offer
    to that seat goes through (``control_flow._offered_seats``) — and where
    that names nobody (a tie, nothing revealed) nothing is changed.

    CR 115.7a, each sentence of it:

    * "each target can be changed only to **another legal target**" — the
      candidates are ``stack_targets.change_slots``', enumerated through the
      list the object's own picker and announcement gate read, minus the
      target the slot already names;
    * "if all the targets aren't changed to other legal targets, **none of them
      are changed**" — every slot is chosen before anything is written, each
      pick is offered only while the slots behind it can still be filled
      (``change_options``), and ``apply_target_change`` writes all of them or
      nothing;
    * CR 115.7e — only the final set is judged, which is why a two-target
      spell may have its targets exchanged.

    One prompt per target, in announcement order, each suspending this
    resolution until it is answered (``run_resumable``). Where the sentence
    says *may*, the first prompt carries "leave the targets as they are" as an
    answer — one decision, not a yes/no in front of a picker. A
    **non-interactive** seat is not asked: ``ai_policy.choose_target_change``
    is its stated policy, read on the spot, and "leave it" is one of its
    answers. On the spot matters: the object is the next thing to resolve, and
    a queued offer drained after the stack empties would be answered too late
    (``lowering/control_flow._offered_target_change``).

    The change is a player choosing targets, so it is announced through the
    one seam — silenced for permanents sharing this one's name when the card
    prints that sentence.
    """
    from ..stack_targets import (
        TARGETS_CHOSEN_ITEM, apply_target_change, change_options, change_slots,
        target_label,
    )

    card_name = getattr(context.card, "name", "")
    item = (context.trigger_context or {}).get(TARGETS_CHOSEN_ITEM)
    if item is None or not any(waiting is item for waiting in game.stack):
        game.log.append(
            f"{card_name}: the spell or ability whose targets were chosen is "
            "no longer on the stack"
        )
        return True, "resolved"
    subject = item.card.name
    unchanged = f"{card_name}: {subject}'s targets remain unchanged"
    slots = change_slots(game, item)
    if isinstance(slots, str):
        game.log.append(f"{unchanged} ({slots})")
        return True, "resolved"
    if not change_options(slots, []):
        game.log.append(f"{unchanged} (it has no other legal targets)")
        return True, "resolved"
    who = instruction.payload.get("chooser", "you")
    if who == "you":
        chooser = game.seat_index(context.caster)
    else:
        from .control_flow import _offered_seats

        seats = _offered_seats(game, who, context)
        if not seats:
            game.log.append(unchanged)
            return True, "resolved"
        chooser = seats[0]
    optional = bool(instruction.payload.get("optional"))
    chooser_name = game.players[chooser].name
    picks: list = []

    def finish() -> None:
        before = ", ".join(target_label(game, slot.current) for slot in slots)
        if len(picks) != len(slots) or not apply_target_change(game, item, slots, picks):
            game.log.append(unchanged)
            return
        after = ", ".join(target_label(game, pick) for pick in picks)
        game.log.append(
            f"{card_name}: {chooser_name} changed {subject}'s "
            f"target{'s' if len(slots) > 1 else ''} from {before} to {after}"
        )
        silently_for = None
        if instruction.payload.get("silent_for_same_name"):
            # "…permanents **named** <this one>": the name this permanent has
            # *now* (CR 707.2 — a copy is named what it copies), and the
            # card's printed name once the permanent is gone.
            source = context.source_permanent
            silently_for = (
                source.effective_card.name if source is not None else card_name
            )
        game.announce_targets_chosen(item, chooser=chooser, silently_for=silently_for)

    if chooser not in game.interactive_seats:
        from ..ai_policy import choose_target_change

        chosen = choose_target_change(game, chooser, item, slots) if optional else None
        if chosen is None and not optional:
            # A change the sentence orders: the first complete one, in the
            # order the enumeration lists the candidates.
            chosen = []
            while len(chosen) < len(slots):
                chosen.append(change_options(slots, chosen)[0])
        if chosen is None:
            game.log.append(f"{card_name}: {chooser_name} left {subject}'s targets as they were")
            return True, "resolved"
        picks.extend(chosen)
        finish()
        return True, "resolved"

    state = {"abandoned": False}

    def absorb() -> None:
        # The answer to the slot before this step, exactly once.
        if _EVENT_TARGET_PICK not in context.results:
            return
        answer = context.results.pop(_EVENT_TARGET_PICK)
        if isinstance(answer, dict) and answer.get("_target") is not None:
            picks.append(answer["_target"])
        else:
            # "Leave them as they are", or every candidate left between the
            # question and the answer (``_resolve_retarget_choice``). CR 115.7a
            # either way: nothing is changed.
            state["abandoned"] = True
            state["declined"] = isinstance(answer, dict) and answer.get("kind") == "keep"

    def step(position) -> None:
        absorb()
        if position is None:
            if state.get("declined"):
                game.log.append(
                    f"{card_name}: {chooser_name} left {subject}'s targets as they were"
                )
            elif state["abandoned"]:
                game.log.append(unchanged)
            else:
                finish()
            return
        if state["abandoned"]:
            return
        options = change_options(slots, picks)
        if not options:
            state["abandoned"] = True
            return
        # Declining is offered once, with the first target: after it, the
        # change is under way and CR 115.7a leaves no half of one to keep.
        may_decline = optional and position == 0
        if len(options) == 1 and not may_decline:
            # A choice with one answer is not a question (``choose_new_spell_target``).
            context.results[_EVENT_TARGET_PICK] = _target_option(game, options[0])
            return
        current = target_label(game, slots[position].current)
        game.arm_retarget_choice(
            chooser,
            card_name=card_name,
            prompt=(
                f"Choose the new target for {subject} (now {current})."
                if len(slots) == 1 else
                f"Choose the new target for {subject}: target {position + 1} "
                f"of {len(slots)} (now {current})."
            ),
            result_key=_EVENT_TARGET_PICK,
            options=(
                [{"kind": "keep", "name": "Leave the targets as they are"}]
                if may_decline else []
            ) + [_target_option(game, option) for option in options],
            context=context,
        )

    # One step per slot and a last one that writes. The loop is the last thing
    # this handler does, which is ``engine/resumption.py``'s other half.
    run_resumable(game, [*range(len(slots)), None], step)
    return True, "resolved"


@effect_handler("waive_shroud_for_target_player")
def waive_shroud_for_target_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, Autumn Willow can be the target of spells and
    abilities controlled by **target player** as though it didn't have shroud."

    CR 609.4's "as though" cutting a hole in CR 702.18 for one seat. The record
    is a list of seats on the permanent (``target_immunity``), read by
    ``_can_be_targeted`` and swept with the turn — the creature still *has*
    shroud, so every other seat is stopped exactly as before and a lord counting
    creatures with shroud still counts it.

    The subject is the ability's **own source**, which is the sentence's subject
    and not a target: the permission is about this permanent, so a resolution
    that has lost it (the creature left the battlefield in response) waives
    nothing rather than waiving it for something else.
    """
    from ..target_immunity import waive_shroud_for_seat

    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: it has left the battlefield")
        return True, "resolved"
    target = context.target
    if target is None or target not in game.players:
        game.log.append(f"{context.card.name}: no player to waive shroud for")
        return True, "resolved"
    waive_shroud_for_seat(source, game.players.index(target))
    game.log.append(
        f"{source.card.name} can be targeted by {target.name}'s spells and "
        f"abilities this turn"
    )
    return True, "resolved"


@effect_handler("ban_targeting")
def ban_targeting(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…players and permanents can't be the targets of spells or activated
    abilities." (Peace Talks.)

    State plus a reader, never a flag stamped on each object — the same shape
    ``cant_attack_until_eot`` takes and for the same reason: a permanent that
    enters after this resolves is covered too, and a player has nowhere to
    stamp a flag at all. ``legality._enumerate_targets`` is the reader, which
    is the one list the target picker and the announcement gates share, and
    the cleanup step's countdown is what ends the window.
    """
    game.targeting_bans.append({
        "source_name": context.card.name,
        "remaining_turns": int(instruction.payload.get("remaining_turns", 1)),
    })
    game.log.append(
        f"{context.card.name}: nothing can be targeted by spells or activated "
        f"abilities"
    )
    return True, "resolved"
