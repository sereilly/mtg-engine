"""Shared helpers for scanning battlefields for triggered abilities and
building the event dicts consumed by ``_enqueue_triggered_batch``.

Module-level functions (taking ``game``) rather than mixin methods so both
``engine/phases`` and ``engine/mixins`` can use them without touching the
Game MRO, and so they are unit-testable standalone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Container, Iterator, Sequence

from .land_types import lost_abilities_to_type_change
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
            # CR 305.7's losing half, third of the three places an ability can
            # act. A land whose subtype an effect *set* to basic land types has
            # no abilities from its rules text, and a triggered one is read off
            # the card here rather than from the ability channel layer 6 strips
            # — so City of Brass kept its damage trigger while reading as a
            # Mountain. One predicate for all three readers (`land_types`), so
            # a land cannot lose half its abilities.
            if lost_abilities_to_type_change(permanent):
                continue
            card = permanent.effective_card if use_effective_card else permanent.card
            for trig in matching_triggers(
                card, condition_kinds=condition_kinds, instruction_kinds=instruction_kinds
            ):
                yield controller_index, permanent, trig
                if first_match_only:
                    break


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
