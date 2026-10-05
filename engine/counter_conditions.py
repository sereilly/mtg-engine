"""When a counter actually counters — both ends of the question.

The **counter's** end is a printed condition: "Counter target spell **if it
would destroy a land you control**." (Equinox.) The **victim's** end is a static
ability of the object on the stack: "This spell can't be countered."
(Scragnoth, CR 113.6g.) One module, because the counter path has to ask both and
a path that asked one of them would be a restriction parsed and dropped — the
last section of this file is the second half.

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

import re
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


# ---------------------------------------------------------------------------
# The other half of "does this counter counter": what the *victim* says
# ---------------------------------------------------------------------------
#
# Everything above is a condition the **counter** prints about the spell it
# chose. "This spell can't be countered." (Scragnoth) is the same question asked
# from the other end — a static ability of the object on the stack, CR 113.6g:
# "An object's ability that states it can't be countered or can't be copied
# functions on the stack." So it lives beside them rather than in a file of its
# own: one module answers "is this spell countered", and a counter path that
# asked only half of it would be the parsed-and-dropped restriction this repo
# refuses.
#
# It is **not** a targeting restriction. Counterspell says "target spell", not
# "target spell that can be countered", so Scragnoth is a legal target
# (CR 115.1) and the counter simply does nothing when it resolves. Enforcing it
# at the picker would refuse a cast the rules allow.

#: The whole line, anchored, so a sentence that *contains* these words without
#: being them cannot claim the immunity — the substring reading is how a
#: whitelist comes to claim what it does not implement.
_UNCOUNTERABLE = re.compile(r"^this spell can't be countered$")

#: The claim name ``oracle._derived_static_claims`` reports for it. Its own name
#: rather than "counter_conditions", because that one says what a *counter*
#: may ask and this says what a spell answers.
UNCOUNTERABLE_CLAIM = "uncounterable"


def uncounterable_line(line: str) -> bool:
    """Whether *line* is the printed "This spell can't be countered."

    The **table's own** answer to "is this my sentence?", read by the support
    gate (``oracle._is_supported_static_creature_line`` and
    ``_derived_static_claims``), by the grammar's parse claim and by
    ``scripts/parse_coverage.py`` — so what is claimed and what is enforced are
    one function rather than three copies of a phrase.
    """
    return _UNCOUNTERABLE.match(_key(line)) is not None


def spell_cant_be_countered(card) -> bool:
    """Whether *card*'s own text makes it uncounterable (CR 113.6g).

    Asked of the card on the stack at the moment a counter resolves (CR 608.2),
    which is the only moment it can be asked: a spell has no permanent to read a
    layer off, so the printed face is the whole of what there is — and reading
    it any earlier would be reading it before the spell existed.

    **Half of the question.** A spell is also uncounterable when a permanent
    says so about its whole class (:func:`spells_made_uncounterable_by`), and
    the counter path asks both through :func:`cant_be_countered` — this half is
    kept on its own because it is the only one a caller with no game can ask.
    """
    return any(
        uncounterable_line(line)
        for line in (getattr(card, "oracle_text", "") or "").split("\n")
    )


# --- The board half: a permanent that says it about a class of spells -------
#
# "**Creature spells** can't be countered." (Gaea's Herald.) The same immunity
# from the other direction: not a static ability of the object on the stack
# (CR 113.6g) but of a permanent on the battlefield, naming every spell of a
# card type — whoever is casting it, which is the whole of what separates this
# from a "spells you control" wording that the row below does not read and
# therefore refuses. It is to Scragnoth's line what ``cast_restrictions``'
# board-wide "Creature spells can't be cast." is to a spell's own timing gate,
# and it is asked at the same moment as Scragnoth's: CR 608.2, as the counter
# resolves, of the board as it stands then — a Herald that has left by then
# protects nothing.
#
# The card **type** is payload, for ``cast_restrictions._GLOBAL_CAST_BAN``'s
# reason: "Artifact spells can't be countered." is the same sentence and must
# need no second row.
_UNCOUNTERABLE_SPELL_TYPES = (
    r"(?:artifact|creature|enchantment|instant|sorcery|planeswalker|battle)"
)
_CLASS_UNCOUNTERABLE = re.compile(
    rf"^(?P<type>{_UNCOUNTERABLE_SPELL_TYPES}) spells can't be countered$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own rather than :data:`UNCOUNTERABLE_CLAIM`, because that
#: one is what a *spell* says about itself and this is what a permanent does to
#: everybody's spells.
CLASS_UNCOUNTERABLE_CLAIM = "class_uncounterable"


def uncounterable_class_line(line: str) -> str | None:
    """The card type whose spells *line* makes uncounterable, or None.

    One reader, every caller: the grammar's parse claim, the two support gates
    in ``engine/oracle.py``, ``scripts/parse_coverage.py`` and the counter path
    below all ask it, so what is claimed and what is enforced cannot drift.
    Anchored on the whole line — a sentence that merely contains the words
    ("Creature spells **you control** can't be countered") names a narrower set
    and refuses here rather than being admitted with the narrowing dropped.
    """
    match = _CLASS_UNCOUNTERABLE.match(_key(line))
    return match.group("type") if match is not None else None


def spells_made_uncounterable_by(game: "Game", card) -> str | None:
    """The name of a permanent whose static makes *card* uncounterable, or None.

    Every battlefield and no seat comparison: the sentence names nobody, so it
    covers an opponent's creature spells as surely as its controller's.
    ``effective_card`` rather than the printed face, because what a permanent
    says is what layer 1 and layer 3 have made of it (CR 707.2, CR 612.1). The
    type test is ``search_filters.card_has_type`` — a card has **every** type
    its line names (CR 205.2), so an artifact creature spell is a creature
    spell.
    """
    from .search_filters import card_has_type

    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            protected = uncounterable_class_line(raw_line)
            if protected is not None and card_has_type(card, protected):
                return permanent.effective_card.name
    return None


def cant_be_countered(game: "Game", card) -> str | None:
    """Why the spell *card* can't be countered right now, or None if it can.

    **The one question the counter path asks**, with both halves behind it: the
    spell's own printed line (CR 113.6g) and a permanent's static about its
    class. The return value is the reason as the log prints it, so a caller
    cannot tell the two apart by accident and has nothing to format.
    """
    if spell_cant_be_countered(card):
        return f"{getattr(card, 'name', 'that spell')} can't be countered"
    source = spells_made_uncounterable_by(game, card)
    if source is not None:
        return (
            f"{getattr(card, 'name', 'that spell')} can't be countered ({source})"
        )
    return None


__all__ = [
    "CLASS_UNCOUNTERABLE_CLAIM",
    "COUNTER_CONDITIONS",
    "UNCOUNTERABLE_CLAIM",
    "cant_be_countered",
    "counter_condition_holds",
    "counter_condition_key",
    "counter_condition_readable",
    "spell_cant_be_countered",
    "spells_made_uncounterable_by",
    "uncounterable_class_line",
    "uncounterable_line",
]
