"""Shared helpers for scanning battlefields for triggered abilities and
building the event dicts consumed by ``_enqueue_triggered_batch``.

Module-level functions (taking ``game``) rather than mixin methods so both
``engine/phases`` and ``engine/mixins`` can use them without touching the
Game MRO, and so they are unit-testable standalone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Container, Iterator, Sequence

from .oracle import compile_card_oracle

if TYPE_CHECKING:
    from .models import CardDefinition, Permanent, PlayerState
    from .oracle_types import OracleInstruction, ParsedTriggeredAbility


def matching_triggers(
    card: CardDefinition,
    *,
    condition_kinds: Container[str],
    instruction_kinds: Container[str] | None = None,
) -> Iterator[ParsedTriggeredAbility]:
    """The card's triggered abilities (with a parsed instruction) whose
    condition — and optionally instruction — kind matches."""
    for trig in compile_card_oracle(card).triggered_abilities:
        if trig.instruction is None:
            continue
        if trig.condition.kind not in condition_kinds:
            continue
        if instruction_kinds is not None and trig.instruction.kind not in instruction_kinds:
            continue
        yield trig


def iter_triggered_abilities(
    game,
    *,
    condition_kinds: Container[str],
    instruction_kinds: Container[str] | None = None,
    players: Sequence[PlayerState] | None = None,
    use_effective_card: bool = True,
    first_match_only: bool = False,
) -> Iterator[tuple[int, Permanent, ParsedTriggeredAbility]]:
    """Scan battlefields for matching triggered abilities, yielding
    ``(controller_index, permanent, trig)`` in player-then-battlefield order
    (the order ``_enqueue_triggered_batch`` expects). ``controller_index`` is
    always the permanent controller's index into ``game.players``, also when a
    ``players`` subset is scanned.

    ``first_match_only`` caps the scan at one trigger per permanent. CR 603.3
    says every ability whose condition is met triggers, so the default is off;
    a permanent with two upkeep triggers fires both. Pass True only where a
    call site genuinely wants a single representative match (a presence check
    rather than a firing)."""
    for controller in (players if players is not None else game.players):
        controller_index = game.players.index(controller)
        for permanent in list(controller.battlefield):
            # No CR 305.7 skip here, and there was one: a land whose type an
            # effect had set was passed over whole. That took the triggered
            # abilities another effect had *granted* it along with its own
            # (a land creature under The Tabernacle at Pendrell Vale, a land
            # wearing Farmstead), which the rule keeps — and it was one scan
            # of many, so every site that reads a permanent's triggers without
            # coming through here still fired the land's own. The effective
            # card below is the land with its own text struck and what it was
            # granted left in (``Permanent.effective_card``).
            card = permanent.effective_card if use_effective_card else permanent.card
            for trig in matching_triggers(
                card, condition_kinds=condition_kinds, instruction_kinds=instruction_kinds
            ):
                yield controller_index, permanent, trig
                if first_match_only:
                    break


def bound_event_object(instruction, permanent) -> int | None:
    """The id a fire site records as the permanent its trigger is **about**
    (``StackItem.about_permanent_id``), or None. *permanent* is the event's
    object, or its id where the fire site holds only that (an event payload).

    The object the event named — the attacker itself, the creature on the
    other side of a block, the permanent a damage event damaged — is what a
    trigger's effect acts on when the printed line names **no target of its
    own**: "that creature becomes green" (Aisling Leprechaun), "destroy that
    Wall" (Battering Ram), "remove this creature from combat" (Mijae Djinn).
    CR 603.3d then has nothing to choose, and the context builder hands the
    effect this object instead (``_ability_execution_context``).

    A line that says "target" (CR 115.1d) chooses one as the ability is put on
    the stack, and the event's object is no answer to that choice: "you may tap
    target creature" (Seasoned Marshal), "…to target creature" (the
    Laccoliths), "target opponent gains control of it" (Goblin Cadets),
    "…deals 1 damage to any target" (Close Quarters). So none is recorded, and
    the sentence's "it" is its source. ``announces_a_target`` is the
    lowering's own record of the word, the one the trigger picker asks.

    One rule for every fire site, because each of them used to decide it on
    its own — or not at all: the becomes-blocked site asked, the attack and
    block sites left it to the picker (which asked only when the object was
    the source itself), and a board-wide block or a damage event never asked.
    """
    if permanent is None:
        return None
    from .targeting import announces_a_target

    if announces_a_target(instruction):
        return None
    permanent_id = (
        permanent if isinstance(permanent, int)
        else getattr(permanent, "permanent_id", None)
    )
    if isinstance(permanent_id, bool) or not isinstance(permanent_id, int):
        return None
    return permanent_id


def bound_event_seat(instruction, seat) -> int | None:
    """:func:`bound_event_object`'s rule for a fire site that hands over the
    **seat** its event was about in ``target_player_index`` — "that player
    loses 5 life" (Psychic Purge) is the player who caused the discard — or
    None where the line prints a target of its own and CR 603.3d chooses it.

    The seat channel still holds either a choice or such a seat, and this
    keeps the two from meeting on one ability: an event's seat in that field
    is what ``_trigger_target_candidates`` reads as a choice already made, so
    Guerrilla Tactics ("…it deals 4 damage to **any target**") shot the causer
    with nothing chosen. A field of its own for "the player this trigger is
    about", beside ``StackItem.about_permanent_id``, is the rest of that
    separation.
    """
    if seat is None:
        return None
    from .targeting import announces_a_target

    return None if announces_a_target(instruction) else seat


_UNSET = object()


def make_trigger_event(
    controller_index: int,
    permanent: Permanent,
    trig: ParsedTriggeredAbility,
    *,
    instruction: OracleInstruction | None = None,
    effect_kind: str | None = None,
    ability_text: object = _UNSET,
    trigger_context: dict | None = None,
) -> dict:
    """The standard event dict for ``_enqueue_triggered_batch``. Fields default
    to the trigger's own instruction/effect_kind/source_line; pass overrides for
    synthetic instructions (e.g. ``deal_damage_to_player``)."""
    event = {
        "controller_index": controller_index,
        "source_permanent": permanent,
        "instruction": instruction if instruction is not None else trig.instruction,
        "effect_kind": effect_kind if effect_kind is not None else trig.effect_kind,
        "ability_text": trig.source_line if ability_text is _UNSET else ability_text,
    }
    if trigger_context is not None:
        event["trigger_context"] = trigger_context
    return event
