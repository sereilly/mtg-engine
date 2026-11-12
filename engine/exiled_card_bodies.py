"""A permanent that takes its body from **the last creature card exiled with
it** (CR 607.2a; layers 4 and 7b).

"As long as a card exiled with this creature is a creature card, this creature
has the power, toughness, and creature types of the last creature card exiled
with it. It's still a Shapeshifter." (Duplicant.)

The source of the body is the permanent's own linked exile — the card its
imprint exiled (``linked_exile.cards_still_exiled_with``) — and the answer
changes whenever that pile does, with no event for a fire site to hang off:
the exiled card can leave exile, and a card in exile with a
characteristic-defining P/T changes with its board (the 2020-08-07 ruling:
"Duplicant's power and toughness are constantly updated if the exiled card's
power and/or toughness change"). So the contribution is **derived**, exactly as
``engine/zone_copies.py`` derives Volrath's Shapeshifter's: rebuilt on every
continuous-effects refresh (:func:`refresh_exiled_card_bodies`, called by
``mixins/dynamic_creatures._refresh_dynamic_creatures`` ahead of the layer-4
pass) onto one record, :data:`EXILED_CARD_BODY`, which the two layers read:

* **layer 7b** — ``layer_bridge.collect_pt_effects`` sets the base power and
  toughness at the permanent's own timestamp (CR 613.7a), so counters and
  every 7c modification still apply on top (the 2020-08-07 ruling: "base power
  and toughness change … Counters and other effects that modify Duplicant's
  power and toughness still apply");
* **layer 4** — ``type_layer.collect_own_type_effects`` adds the creature types
  at the same timestamp. *Added*, not replacing: "It's still a Shapeshifter"
  is the printed type kept, recorded on the payload rather than dropped.

The exiled card's power and toughness are read as a card outside the
battlefield is read (``Game.card_pt_outside_battlefield``): its printed numbers,
or what its characteristic-defining ability says in exile — and nothing that
merely modifies P/T, which applies to no card in exile (the ruling's Crusader
of Odric / Death's Shadow pair). Its creature types are the off-battlefield
reader's (``object_creature_types.card_creature_types``).

**A table, not a hook**, reached only once every grammar production has
refused the line (``engine/grammar/derived.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .late_modules import LateModules
from .object_creature_types import card_creature_types

_late = LateModules(__package__)

#: The instruction kind the line compiles to: a record the layer readers ask
#: for, never a handler that runs (the shape ``copy_top_card_of_zone`` has).
EXILED_CARD_BODY_KIND = "adopt_exiled_creature_body"

#: Where the refresh writes the body on the permanent: ``{"power",
#: "toughness", "subtypes", "card_name"}``, absent while no creature card is
#: exiled with it.
EXILED_CARD_BODY = "exiled_card_body"


@dataclass(frozen=True)
class ExiledCardBody:
    """What one printing says: the creature type it keeps ("It's still a
    Shapeshifter")."""

    keeps_subtype: str


# Anchored at both ends: a line saying anything more carries a rider nothing
# would perform.
_PATTERN = re.compile(
    r"^as long as a card exiled with this creature is a creature card, "
    r"this creature has the power, toughness, and creature types of the last "
    r"creature card exiled with it\. it'?s still an? (?P<kept>[a-z]+)$"
)


def exiled_card_body_for(line: str) -> ExiledCardBody | None:
    """The template one normalized *line* states, or None."""
    match = _PATTERN.match(line or "")
    if match is None:
        return None
    from .grammar.vocabulary import CREATURE_TYPES

    kept = match.group("kept")
    if kept not in CREATURE_TYPES:
        return None
    return ExiledCardBody(keeps_subtype=kept)


def exiled_card_body_payload(body: ExiledCardBody) -> dict[str, Any]:
    return {"keeps_subtype": body.keeps_subtype}


def last_exiled_creature_card(game, permanent) -> "tuple[Any, int] | None":
    """``(card, owner_index)`` of the **last** creature card exiled with
    *permanent* that is still in exile — or None. "Last" is the record's order
    (``linked_exile.link_exiled_card`` appends), so a second imprint (a copied
    trigger, CR 607.3) is the one read."""
    from .linked_exile import cards_still_exiled_with
    from .search_filters import card_has_type

    found = None
    for card, owner in cards_still_exiled_with(game, permanent):
        if card_has_type(card, "creature", game=game, owner=owner):
            found = (card, owner)
    return found


def refresh_exiled_card_bodies(game, permanents) -> None:
    """Rebuild :data:`EXILED_CARD_BODY` on every permanent in *permanents*:
    written where its effective program carries the line and a creature card
    is exiled with it, popped everywhere else (a permanent that lost the
    ability, CR 613.1f, keeps no body)."""
    compile_card_oracle = _late.oracle.compile_card_oracle

    for permanent in permanents:
        permanent.metadata.pop(EXILED_CARD_BODY, None)
        program = compile_card_oracle(permanent.effective_card)
        if not any(i.kind == EXILED_CARD_BODY_KIND for i in program.instructions):
            continue
        found = last_exiled_creature_card(game, permanent)
        if found is None:
            continue
        card, owner = found
        power, toughness = game.card_pt_outside_battlefield(card, owner)
        permanent.metadata[EXILED_CARD_BODY] = {
            "power": int(power),
            "toughness": int(toughness),
            "subtypes": sorted(card_creature_types(game, card, owner)),
            "card_name": card.name,
        }


def exiled_card_body(permanent) -> "dict | None":
    """The body the last refresh gave *permanent*, or None."""
    return (permanent.metadata or {}).get(EXILED_CARD_BODY)


__all__ = [
    "EXILED_CARD_BODY",
    "EXILED_CARD_BODY_KIND",
    "ExiledCardBody",
    "exiled_card_body",
    "exiled_card_body_for",
    "exiled_card_body_payload",
    "last_exiled_creature_card",
    "refresh_exiled_card_bodies",
]
