"""When a conditional counter actually counters — "Counter target spell **if it
would destroy a land you control**." (Equinox.)

CR 608.2: a spell's effect is worked out as it resolves, so a counter that
carries a condition asks it *then*, of the spell still sitting on the stack.
What the condition asks about is that spell's own effect, which nothing on the
stack item records: the answer has to be read out of the spell's compiled
program.

**A table, and both sides read it.** The grammar records which condition a card
printed and refuses one no row here answers (``counter_condition_readable``),
and the handler asks the same rows at resolution (``counter_condition_holds``).
A condition consumed by the parser and unknown to the handler is a counter that
fires unconditionally, which on this card means countering every spell on the
stack — the failure that looks like a working card.

Deliberately not a general "simulate the spell and see" — that is a different
engine. What a row can answer is what a row claims, and a printed condition
outside them leaves its card unsupported, loudly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem

#: The instruction kinds that destroy something, and how to tell whether the
#: land in question is among what they would destroy. Derived from the
#: destruction family in ``engine/grammar/lowering/categories.py`` rather than
#: guessed: a kind added there and not here reads as "would destroy nothing",
#: which is the failing-safe direction — the counter declines rather than
#: countering a spell the card does not name.
_MASS_LAND_DESTRUCTION = frozenset({
    "destroy_all_lands",
    "destroy_all_lands_of_type",
})


def _would_destroy_a_land_you_control(
    game: "Game", spell: "StackItem", observer: int
) -> bool:
    """Whether *spell* resolving would destroy a land seat *observer* controls.

    Two shapes, because a card destroys a land in exactly two ways. A **sweep**
    ("Destroy all lands", Armageddon) destroys every land there is, so the
    question is only whether the observer has one. A **targeted** destruction
    names its victim as it is cast (CR 601.2c), and the stack item records
    which permanent that is — so the question is whether that permanent is a
    land the observer controls.

    ``destroy_all_matching`` is a sweep whose filter is payload, so it is asked
    the same question every other filter is asked: does the phrase admit a land
    this seat controls? Reading it as "not one of the two land sweeps" would
    have missed "Destroy all lands and all creatures" printed the general way.
    """
    from .oracle import compile_card_oracle
    from .subject_filters import subject_matches

    program = compile_card_oracle(spell.card)
    kinds = _instruction_kinds(program.instructions)
    own_lands = [
        perm for perm in game.controlled_by(observer) if perm.has_type("land")
    ]
    if not own_lands:
        return False
    if kinds & _MASS_LAND_DESTRUCTION:
        return True
    for instruction in _flatten(program.instructions):
        if instruction.kind == "destroy_all_matching":
            filters = dict(instruction.payload.get("targets", {}).get("filter", {}))
            if not filters:
                filters = dict(instruction.payload.get("filter") or {})
            if any(
                subject_matches(game, perm, filters, observer=observer)
                for perm in own_lands
            ):
                return True
        elif instruction.kind == "destroy_target_permanent":
            chosen = _targeted_permanent(game, spell)
            if chosen is not None and any(chosen is land for land in own_lands):
                return True
    return False


def _targeted_permanent(game: "Game", spell: "StackItem"):
    """The permanent *spell* chose, by id and never by slot.

    An index held across anything leaving the battlefield names whichever
    permanent slid into the slot (CR 400.7), which on this question would let a
    counter fire for a land the spell was never aimed at.
    """
    ids = getattr(spell, "target_permanent_id", None)
    for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
        if permanent_id is None:
            continue
        found = game.permanent_by_id(permanent_id)
        if found is not None:
            return found
    return None


def _flatten(instructions):
    """Every instruction, ``sequence`` wrappers opened out.

    A card's destruction can be the second step of a sentence
    ("… , then destroy target land"), and a wrapper hides it from a flat scan.
    """
    for instruction in instructions or ():
        if instruction.kind == "sequence":
            yield from _flatten(instruction.payload.get("steps") or ())
        else:
            yield instruction


def _instruction_kinds(instructions) -> frozenset[str]:
    return frozenset(step.kind for step in _flatten(instructions))


#: The printed conditions a counter may carry, as the sentence a card prints
#: (lowercased, no trailing stop) mapped to the predicate that answers it.
COUNTER_CONDITIONS: dict[str, Callable[..., bool]] = {
    "it would destroy a land you control": _would_destroy_a_land_you_control,
}


def counter_condition_readable(sentence: str) -> bool:
    """Whether a row answers this printed condition — the grammar's gate."""
    return _key(sentence) in COUNTER_CONDITIONS


def counter_condition_key(sentence: str) -> str | None:
    """The payload key for *sentence*, or None when no row answers it."""
    key = _key(sentence)
    return key if key in COUNTER_CONDITIONS else None


def counter_condition_holds(
    key: str, game: "Game", spell: "StackItem", observer: int
) -> bool:
    """Whether the condition named by *key* holds for *spell* right now.

    An unknown key holds *false*: a counter whose condition nothing can answer
    must decline rather than fire, and the grammar's gate is what stops such a
    card being admitted in the first place.
    """
    predicate = COUNTER_CONDITIONS.get(key)
    if predicate is None:
        return False
    return predicate(game, spell, observer)


def _key(sentence: str) -> str:
    return " ".join((sentence or "").lower().split()).strip(" .")


__all__ = [
    "COUNTER_CONDITIONS",
    "counter_condition_holds",
    "counter_condition_key",
    "counter_condition_readable",
]
