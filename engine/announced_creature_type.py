"""A creature type the caster announces as a spell is cast, narrowing what
the spell may target.

"Return up to three target creature cards **of the creature type of your
choice** from your graveyard to your hand." (Aphetto Dredging.) The card's
ruling (2004-10-04): "You need to choose the creature type before choosing the
targets." So the word is CR 601.2b's announcement — the same one Caller of the
Hunt's "As an additional cost to cast this spell, choose a creature type"
makes, read off the same request field (``chosen_creature_type``), defaulted by
the same ``Game._default_cast_creature_type`` and carried to resolution on the
same ``StackItem.choices`` key — and CR 601.2c's targets are then chosen
*under* it.

What is here is the vocabulary every reader of that narrowing shares: the
flag the lowering writes on the return's payload (and the spec builder copies
onto the target spec), and :func:`with_announced_creature_type`, which turns a
flagged description into the printed-subtype narrowing
``handlers/_filters.graveyard_card_matches`` already reads ("target **Griffin**
card", Mtenda Griffin). One substitution, asked by each of the four readers
with the word it holds:

* the picker (``Game.cast_target_spec(chosen_creature_type=)``) — the word the
  client sent, or the default;
* the cast gates (``_validate_cast_targets``, ``cast_target_refusal``) — the
  word the cast announced;
* the handler at resolution — the word the stack object carries (CR 608.2b:
  a card is re-checked against the type it was chosen under).

A description still carrying the flag — a reader that was handed no word —
matches **nothing** (``graveyard_card_matches`` refuses it): an unanswerable
narrowing must never widen to "any creature card", which is what the card did
when the phrase was dropped.

Imports nothing from the engine, so the lowering may import it.
"""

from __future__ import annotations

#: The payload and spec flag: "the creature cards this names are of the type
#: the caster announced as it cast the spell" (Aphetto Dredging).
GRAVEYARD_ANNOUNCED_CREATURE_TYPE = "graveyard_announced_creature_type"

#: The ``StackItem.choices`` key the announcement rides to resolution on —
#: the one ``mixins/stack/casting.py`` has written for a choice-shaped cost
#: since Caller of the Hunt, so one cast that made both choices made one.
CHOSEN_CREATURE_TYPE_CHOICE = "chosen_creature_type"


def narrows_by_announced_type(described) -> bool:
    """Whether *described* (a payload or a target spec) is narrowed by the
    creature type announced at cast."""
    return isinstance(described, dict) and bool(
        described.get(GRAVEYARD_ANNOUNCED_CREATURE_TYPE)
    )


def with_announced_creature_type(described: dict, word: "str | None") -> dict:
    """*described* as it reads once *word* has been announced: the flag
    replaced by ``graveyard_subtypes: [word]``, the narrowing the graveyard
    matcher reads for a printed subtype.

    *described* unchanged when it carries no flag, and when *word* is None —
    still flagged, so it matches nothing rather than every creature card.
    """
    if not narrows_by_announced_type(described) or not word:
        return described
    resolved = {
        key: value for key, value in described.items()
        if key != GRAVEYARD_ANNOUNCED_CREATURE_TYPE
    }
    resolved["graveyard_subtypes"] = [str(word).strip().lower()]
    return resolved


def announced_word(choices) -> "str | None":
    """The creature type a cast announced, off its ``choices`` (a stack item's
    or the resolution context's), or None."""
    word = (choices or {}).get(CHOSEN_CREATURE_TYPE_CHOICE)
    return str(word) if word else None
