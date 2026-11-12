"""A deck-construction rule a card prints about itself (CR 100.2a).

"A deck can have any number of cards named Relentless Rats." CR 100.2a holds a
constructed deck to "no more than four of any card with a particular English
name other than basic land cards"; this sentence is the card lifting that limit
for its own name. It is not an ability and does nothing while a game is running
(CR 113.6a: an instruction that functions outside the game), so there is no
instruction to lower — its enforcement site is deck construction,
``web/deck_legality.effective_max_copies``, which asks :func:`allows_any_number`
here.

One reader for the three places that ask: the grammar's parse claim
(``grammar.registries.registry_for_line``), the support gate
(``static_line_support._is_supported_static_creature_line``) and
``scripts/parse_coverage.py``'s card channel — so what lifts the limit and what
claims the line cannot come to describe different text. The same arrangement
``engine/ante.py`` keeps for the other deck-construction line the pool prints.

**The name must be the card's own.** The sentence's force is about the card that
prints it; a printing naming some other card would be a different rule (and a
substring check would lift the limit on the card that printed it rather than on
the one it named). So a line is claimed only beside the name it names, and a
caller with no name in hand is answered no.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

#: The label the grammar's registry claim gives the line (``ast.RegistryLine``).
CLAIM = "deck_construction"

_ANY_NUMBER = re.compile(r"^a deck can have any number of cards named (?P<name>.+)$")


def _normalized(line: str) -> str:
    return " ".join((line or "").split()).strip().lower().rstrip(".").replace("’", "'")


def any_number_line(line: str, card_name: str | None) -> bool:
    """Whether *line* is, in full, *card_name*'s "any number of cards named
    <its own name>" — CR 100.2a's four-of limit lifted for that name."""
    if not card_name:
        return False
    match = _ANY_NUMBER.match(_normalized(line))
    return match is not None and match.group("name") == _normalized(card_name)


def allows_any_number(card: Mapping[str, Any] | Any) -> bool:
    """Whether *card* — a catalog entry or a ``CardDefinition`` — prints the
    line about itself, so a deck may hold any number of copies of it."""
    if isinstance(card, Mapping):
        name, text = card.get("name"), card.get("oracle_text")
    else:
        name, text = getattr(card, "name", None), getattr(card, "oracle_text", None)
    return any(
        any_number_line(line, str(name or "")) for line in str(text or "").splitlines()
    )


__all__ = ["CLAIM", "allows_any_number", "any_number_line"]
