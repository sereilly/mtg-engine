"""Mana that may be spent only on certain spells (CR 106.6).

"Spend this mana only to cast creature spells." (Metamorphosis.) "Spend this
mana only to cast an instant or sorcery spell." (Vodalian Arcanist.) One
template with the *restriction* as its parameter, in exactly the sense
``engine/combat_restrictions.py`` means it — and the reason it is a module
rather than a flag is the reason that one is too: the engine held the first of
these as a field named ``creature_only_mana`` and a ``creature_spell: bool``
threaded to the payer, so the second wording had nowhere to go but a second
field, a second bool and a second branch in the payment.

Each entry is a printed phrase, the key it produces, and a predicate over the
**card being cast**. The predicate is what the payment asks; the phrase is what
the parser claims and what the support gate reads, so the words admitted and the
rule enforced cannot drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ManaRestriction:
    """One "spend this mana only to…" clause."""

    key: str
    #: Whether *card* is a spell this mana may pay for.
    admits: Callable[[object], bool]


def _is_creature(card) -> bool:
    return "creature" in (getattr(card, "type_line", "") or "").lower()


def _is_instant_or_sorcery(card) -> bool:
    lowered = (getattr(card, "type_line", "") or "").lower()
    return "instant" in lowered or "sorcery" in lowered


# The printed line, anchored at both ends. Anchored because a sentence saying
# more than one of these is a restriction this file does not implement, and a
# prefix match would claim it and then enforce the narrower rule — mana more
# freely spendable than the card allows.
_PATTERNS: tuple[tuple[re.Pattern[str], ManaRestriction], ...] = (
    (
        re.compile(r"^spend this mana only to cast creature spells\.?$"),
        ManaRestriction("creature", _is_creature),
    ),
    (
        re.compile(r"^spend this mana only to cast an instant or sorcery spell\.?$"),
        ManaRestriction("instant_or_sorcery", _is_instant_or_sorcery),
    ),
)

#: The keys above, for a reader that needs the set rather than a lookup.
RESTRICTION_KEYS = frozenset(r.key for _pattern, r in _PATTERNS)


def mana_restriction_for(sentence: str) -> ManaRestriction | None:
    """The restriction *sentence* imposes, or None when it is not one."""
    text = sentence.strip().lower()
    for pattern, restriction in _PATTERNS:
        if pattern.match(text):
            return restriction
    return None


def restriction_admits(key: str, card) -> bool:
    """Whether mana held under *key* may pay for *card*.

    An unknown key admits **nothing**. That is the safe direction: a key with no
    predicate behind it is mana whose restriction the engine cannot test, and
    treating it as unrestricted would spend it on anything.
    """
    for _pattern, restriction in _PATTERNS:
        if restriction.key == key:
            return bool(restriction.admits(card))
    return False


__all__ = [
    "ManaRestriction",
    "RESTRICTION_KEYS",
    "mana_restriction_for",
    "restriction_admits",
]
