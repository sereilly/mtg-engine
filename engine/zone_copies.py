"""A continuous copy whose source is a **position in a zone** (CR 613.1a).

"As long as the top card of your graveyard is a creature card, this creature has
the full text of that card and has the text "{2}: Discard a card.""
(Volrath's Shapeshifter.)

Every other copy in this pool is *set*: something enters, or a trigger fires, and
``engine/copies.py`` records what was copied at that moment (CR 707.2b — changing
the original afterwards does not change the copy). This one has no such moment.
The static ability asks a question about a zone, and the answer changes when a
card is discarded, when a creature dies, when a spell finishes resolving — with
no trigger, no event and nothing for a fire site to hang off. So the
contribution is **derived**: ``engine/copies.py`` resolves it out of the live
zone every time layer 1 is folded, exactly as ``engine/global_statics.py``
derives a board-wide static's effect off the source permanent on every read
rather than materialising it onto the affected object.

CR 707.2c ("if a static ability generates a continuous effect that's a copy
effect, the copiable values that effect grants are determined only at the time
that effect first starts to apply") is what makes that the right shape rather
than a shortcut: the effect stops applying the moment its condition stops being
true, and starts applying anew — against whatever the top card is *then* — the
moment it becomes true again. Deriving on every read is that rule with no edge
to miss, where a recorded contribution would need a fire site at every path that
can reorder a graveyard.

**A table, not a hook.** The sentence is parameterised on the zone, on the card
type the position must have, and on the ability the copy is granted alongside
(CR 707.9a), so a card printed with any other filling of those three needs no
code here — the same argument ``engine/land_animation.py`` makes for "All
<type>s are P/T creatures that are still lands". Reached only after every
grammar production has refused the line in full
(``engine/grammar/derived.py``), so it cannot shadow a production.

Which end of the list "top" means is :mod:`engine.zone_positions`' one answer,
because a library and a graveyard disagree about it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .search_filters import card_has_type
from .zone_positions import ORDERED_ZONES, top_card

#: The instruction kind this table compiles to. One kind for the family: the
#: zone, the card type and the granted ability are payload, so a second printing
#: of the template adds no dispatch.
ZONE_TOP_COPY_KIND = "copy_top_card_of_zone"


@dataclass(frozen=True)
class ZoneTopCopy:
    """What one printing of the template says.

    zone         -- the ordered zone the position is in ("graveyard")
    zone_owner   -- whose, as CR 109.5's word: only "you" is printed today, and
                    the field exists so a card saying "an opponent's graveyard"
                    refuses here rather than silently reading the wrong pile.
    card_type    -- the card type the top card must have for the copy to apply
    grants_text  -- CR 707.9a's "and has the text ...": printed lines the copy
                    has *in addition to* the copied card's, as oracle text the
                    compiler reads like any other line.
    """

    zone: str
    zone_owner: str
    card_type: str
    grants_text: tuple[str, ...] = ()


_REMINDER = re.compile(r"\([^)]*\)")

# Anchored at both ends. A line saying anything more than this carries a rider
# nothing would perform, and admitting it would be the loose-gate/strict-dispatch
# defect this whole family of tables exists to remove.
_PATTERN = re.compile(
    r"^as long as the top card of (?P<owner>your) (?P<zone>[a-z]+) "
    r"is an? (?P<type>[a-z]+) card, "
    r"this creature has the full text of that card"
    r"(?: and has the text \"(?P<granted>[^\"]+)\")?$"
)


def _normalized(line: str) -> str:
    """*line* as this table reads it: reminder text gone, lowercased, collapsed.

    Reminder text is stripped **here** rather than assumed absent. The two
    callers reach this table with different strings — the grammar's fallback
    hands over the raw printed line and the support gate hands over
    ``oracle.normalize_creature_line``'s output, which has already dropped the
    parenthetical — and Volrath's Shapeshifter is the first line to reach a
    derivation table carrying one. A table that only worked from one of the two
    would be a card that compiles and never dispatches.
    """
    return " ".join(_REMINDER.sub("", line or "").split()).strip().lower().rstrip(".")


def _recase(text: str) -> str:
    """*text* with its first letter capitalised, as oracle text is printed.

    The matcher works on a lowercased line, so the quoted ability comes out of
    it as "{2}: discard a card." — which compiles identically but reads back
    wrong everywhere a card's text is shown. One rule rather than a second copy
    of the printed string: an oracle sentence begins with a capital.
    """
    for index, char in enumerate(text):
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1:]
    return text


def _card_type(word: str) -> str | None:
    """*word* if it is a card type (CR 205.2a), else None."""
    # Imported lazily: the grammar package imports this module through
    # ``grammar/derived.py``, so a module-level import would close a cycle.
    from .grammar import vocabulary

    return word if word in vocabulary.CARD_TYPES else None


def zone_top_copy_for(normalized_line: str) -> ZoneTopCopy | None:
    """The continuous copy *normalized_line* imposes, or None."""
    match = _PATTERN.match(_normalized(normalized_line))
    if match is None:
        return None
    zone = match.group("zone")
    if zone not in ORDERED_ZONES:
        # "the top card of your **deck**" is not a zone this engine keeps an
        # order for. Refusing leaves the card unsupported and loud rather than
        # copying out of a pile nobody named.
        return None
    card_type = _card_type(match.group("type"))
    if card_type is None:
        return None
    granted = match.group("granted")
    return ZoneTopCopy(
        zone=zone,
        zone_owner=match.group("owner"),
        card_type=card_type,
        grants_text=(_recase(granted),) if granted else (),
    )


def zone_top_copy_payload(spec: ZoneTopCopy) -> dict[str, object]:
    """*spec* as an ``OracleInstruction`` payload."""
    return {
        "zone": spec.zone,
        "zone_owner": spec.zone_owner,
        "card_type": spec.card_type,
        "grants_text": list(spec.grants_text),
    }


def zone_top_copy_from_payload(payload: dict) -> ZoneTopCopy:
    """Rebuild the spec a ``copy_top_card_of_zone`` instruction carries."""
    return ZoneTopCopy(
        zone=str(payload.get("zone", "graveyard")),
        zone_owner=str(payload.get("zone_owner", "you")),
        card_type=str(payload.get("card_type", "creature")),
        grants_text=tuple(payload.get("grants_text") or ()),
    )


def copied_card_for(cards: list, spec: ZoneTopCopy) -> Any | None:
    """The card *spec* currently copies out of *cards*, or None.

    None is "the condition is false", which is the whole of what the sentence
    says about an empty zone or a top card of the wrong type: the copy simply
    does not apply and the permanent is what it was printed as.

    ``card_has_type`` rather than ``primary_type``: CR 205.2b gives an object
    every type its line names, so an artifact creature card on top of a
    graveyard answers "is a creature card" — which ``primary_type`` would deny
    for the 77 artifact creatures in this pool, because it returns the first
    word of a fixed list.
    """
    card = top_card(spec.zone, cards)
    if card is None or not card_has_type(card, spec.card_type):
        return None
    return card


__all__ = [
    "ZONE_TOP_COPY_KIND",
    "ZoneTopCopy",
    "copied_card_for",
    "zone_top_copy_for",
    "zone_top_copy_from_payload",
    "zone_top_copy_payload",
]
