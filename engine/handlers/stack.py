"""Spells and abilities on the stack: countered, exiled, bid over, protected.

The handler side of ``engine/grammar/lowering/stack.py``: countering a spell
(CR 701.6, with every rider a counterspell prints — "unless its controller
pays", a spell's class or targets, where the countered card goes) or an
ability, a spell exiled from the stack and the card put back onto it as a copy
of the original (Ertai's Meddling, from the announcement the exile froze), a
spell that can't be countered, a bid of life over a spell, the madness cast an
exiled card is offered, and the two targeting rules a resolution can arm (a
shroud waived for one seat, targeting banned outright).

Split at the 2,000-line cap's split round: copying a spell is
``spell_copies.py``'s, and changing what a spell or ability points at is
``retargeting.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..card_hooks import ON_SPELL_COUNTERED
from ..color_changes import forget_spell_color_change
from ..counter_conditions import (cant_be_countered,
                                  promise_next_spell_uncounterable)
from ..exiled_records import (EXILE_RECORD_KEY, EXILED_SPELL_CONTROLLER_KEY,
                              StackAnnouncement, is_live, record_exiled_card,
                              record_in_context)
from ..game_types import StackItem
from ..faces import is_face, spell_named, whole_card
from ..flashback import leaves_stack_to_exile
from ..mana_payment import mana_cost_label, total_pips
from ..oracle_types import (COUNTERED_ABILITY_SOURCE, COUNTERED_SPELL_CONTROLLER,
                            COUNTERED_SPELL_NAME)
from ._amounts import count_from_payload, resolve_amount
from ._filters import _card_matches_filter
from ._targets import triggering_spell
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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
        # Through the one reader, so "was the flashback cost paid for this
        # object" means here what it means to every site that moves it.
        flashback=leaves_stack_to_exile(item),
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
        # A **copy** of the original spell (CR 707.2): its choices, and not a
        # colour an effect gave the original while it was on the stack
        # (forgotten below).
        choices=dict(announcement.choices),
        chosen_mode_index=announcement.chosen_mode_index,
        chosen_modes=announcement.chosen_modes,
        target_stack_item=announcement.target_stack_item,
        # CR 707.10 copies "additional or alternative costs" with the other
        # decisions, and a paid flashback cost is the one that still has
        # something to say: CR 702.34a exiles this card "instead of putting it
        # anywhere else any time it would leave the stack". Both stamps a
        # flashback cast carries — the wide one every hand-or-library site
        # asks, and the graveyard rider every bin site routes on — because the
        # physical card is this object and has somewhere to go.
        flashback=announcement.flashback,
        exile_instead_of_graveyard=announcement.flashback,
        # ``cast_from_zone`` is deliberately left at its default. CR 707.10: "a
        # copy of a spell isn't cast" — so the honest answer to "was this spell
        # cast from somewhere other than your hand" is *no*, and that is what
        # the default gives. Stamping "exile" because the card came from there
        # would answer *yes* to a question about a casting that never happened.
    )
    forget_spell_color_change(copy)
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
    from ..stack_targets import permanent_spell_targets_nothing
    from ..subject_filters import subject_matches

    if permanent_spell_targets_nothing(item):
        # CR 115.1: a permanent spell that is not an Aura targets nothing. The
        # ids it carries are its entry trigger's, named as it is cast — read
        # here they made a Man-o'-War "a spell that targets a creature", which
        # Confound, Intervene, Mistfolk and Diplomatic Escort then countered.
        return False
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
            # The identity is the stack object's, not its card's
            # (``triggering_spell``): the second of two Bolts is not the first.
            chosen = triggering_spell(game, context)
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
        if chosen is not None and not any(item is chosen for item in game.stack):
            # CR 608.2b for every object that **named** a spell: the target has
            # left the stack, so nothing is countered. The fallback below is
            # the headless convention for a caller that named *none*; taken for
            # one that named a spell which is gone, it counters a bystander. A
            # counterspell never reached here that way (the stack removes a
            # spell whose every target is illegal before its instructions run),
            # but an ability did: Mystic Snake's trigger, its named Shock
            # countered in response, countered the Lightning Bolt under it. By
            # identity, for the reason the branch above gives.
            game.log.append(
                f"{card.name}: the spell it would counter is no longer on the stack"
            )
            return True, "resolved"
        target = chosen if chosen is not None else game.stack[-1]
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
        #
        # …and "**Creature spells** can't be countered." (Gaea's Herald) is the
        # same question asked of the battlefield instead of the spell — one
        # predicate with both halves behind it, so no counter path can come to
        # ask only one of them.
        uncounterable = cant_be_countered(game, target.card, target)
        if uncounterable is not None:
            game.log.append(f"{card.name}: {uncounterable}")
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
        # "…with mana value 3 or less" (Liquify): the printed bound, asked of
        # the spell's mana value on the stack. The picker and CR 608.2b ask it
        # through the stack enumeration first; this is the handler's own
        # reading for the path that reaches it without that gate (a copy, a
        # retargeted object), as every narrowing above has one.
        bound = instruction.payload.get("mana_value")
        if bound:
            from ..targeting import stack_object_mana_value
            from ._filters import _comparison_holds

            target_mv = stack_object_mana_value(target)
            if not _comparison_holds(bound, target_mv):
                game.log.append(
                    f"{card.name}: {target.card.name}'s mana value is {target_mv}, cannot counter"
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
            # "…pays {1} **for each basic land type among lands you control**."
            # (Evasive Action.) The rate over a count of the board, taken now
            # (CR 608.2h) through the evaluator every counted amount shares —
            # "you" is this counter's controller, whose lands they are, and a
            # land that changed type in response is counted as it stands. No
            # basic land type at all is a price of {0}: nothing is countered,
            # which is what a domain of zero says.
            per_counted = instruction.payload.get("unless_pays_per")
            if per_counted is not None:
                cost *= max(0, count_from_payload(game, context, dict(per_counted)))
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
                # "…If that spell is countered this way, exile it instead of
                # putting it into its owner's graveyard." (Syncopate.) Where
                # the card goes if the price is not paid, carried to the
                # decline path that does the countering - with whose
                # counterspell it was, for the one destination that names a
                # controller. Absent when the card prints no tail.
                **(
                    {
                        "countered_destination": str(
                            instruction.payload["countered_destination"]
                        ),
                        "countered_filter": instruction.payload.get(
                            "countered_filter"
                        ),
                        "counterer_index": (
                            game.players.index(context.caster)
                            if context.caster in game.players else None
                        ),
                    }
                    if instruction.payload.get("countered_destination") else {}
                ),
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
    if leaves_stack_to_exile(countered):
        # CR 702.34a: "If the flashback cost was paid, exile this card instead
        # of putting it **anywhere else** any time it would leave the stack."
        # Two replacements want the same event — this card's own, and the
        # counterspell's "put it on top of its owner's library instead" — and
        # whichever is applied first, the other then finds the card bound for
        # somewhere that is not a graveyard and still sends it to exile
        # (CR 616.1: flashback's applies to *any* destination, the
        # counterspell's only to the graveyard). So the answer does not depend
        # on the order and is asked here, ahead of every destination below.
        game._bin_spell_card(
            owner, countered.card, exile_instead=True,
            verb=f"was countered by {card.name}",
        )
        return
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
    stamp a flag at all. ``legality_enumeration._enumerate_targets`` is the reader, which
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


@effect_handler("offer_madness_cast")
def offer_madness_cast(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this card is exiled this way, its owner may cast it by paying
    [cost] rather than paying its mana cost. If that player doesn't, they put
    this card into their graveyard." — CR 702.35a's second ability.

    The cast happens **during this resolution** (CR 608.2g): it is the
    ``madness_cast`` prompt's answer, and the prompt holds this object on the
    stack until it is given, so the spell lands above the ability and the
    ability then finishes. A non-interactive seat answers as the prompt is
    armed (``default_at_arm``), which is the same moment.

    The card is the one the static ability exiled (``madness_card``), asked
    for by identity in its owner's exile: one that has left since is a new
    object (CR 400.7), and neither the cast nor "put this card into their
    graveyard" can find it.
    """
    from ..madness import offer_permission, offered_card_in_exile

    card = (context.trigger_context or {}).get("madness_card") or context.card
    seat = next(
        (i for i, seated in enumerate(game.players) if seated is context.caster),
        None,
    )
    if seat is None or card is None or not offered_card_in_exile(game, seat, card):
        game.log.append(
            f"{getattr(card, 'name', 'The card')} is no longer in exile, so it "
            f"can't be cast for its madness cost"
        )
        return True, "resolved"
    cost = str(instruction.payload.get("cost") or "")
    permission = offer_permission(game, seat, card, cost)
    game.arm_pending_choice(
        "madness_cast", seat,
        card_name=card.name,
        cost=cost,
        _card=card,
        _permission=permission,
    )
    return True, "resolved"


@effect_handler("make_next_spell_uncounterable")
def make_next_spell_uncounterable(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"The next instant or sorcery spell you cast this turn can't be
    countered." (Overmaster, Insist.)

    Records the promise for the resolving spell's controller (CR 109.5's
    "you"); the cast path spends it on that seat's next matching spell and
    every counter asks it through ``counter_conditions.cant_be_countered``.
    """
    seat = game.players.index(context.caster)
    card_types = tuple(instruction.payload.get("card_types") or ())
    promise_next_spell_uncounterable(game, seat, card_types, context.card.name)
    game.log.append(
        f"The next {' or '.join(card_types)} spell {context.caster.name} casts "
        f"this turn can't be countered ({context.card.name})"
    )
    return True, "resolved"
