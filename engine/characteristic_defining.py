"""Characteristic-defining power/toughness templates (CR 604.3).

"*<name>*'s power and toughness are each equal to the number of X" is a printed
template. The possessive subject is the card's **own name**, which
``normalize_creature_line`` does not replace — so every one of these used to be
listed as a literal containing that name, in two places: a whitelist entry
gating support, and an ``elif`` in the compiler emitting a per-card instruction
kind. Three edits per card (whitelist line, ``elif`` branch, counter registry
row), and a functionally identical card under any other name compiled as
**unsupported**.

Matching the subject loosely turns each into what it always was — one template
with a parameter. The parameter (land type, excluded creature type, whose
battlefield to count) rides on the payload, so one instruction kind,
``dynamic_pt_count``, covers all of them and
``engine/mixins/permanent_state.py`` holds the single counter that reads it.

Payload vocabulary
------------------
``count``  what to tally: ``"land"`` | ``"creature"`` | ``"same_name"``
``scope``  whose battlefield: ``"you"`` (controller) | ``"all"`` (every player)
           | ``"defender_when_attacking"`` (the controller's, except while this
           creature is attacking, when it is the defending player's)
``land_type``     with ``count="land"``, the basic type to match
``exclude_type``  with ``count="creature"``, a type that disqualifies (Keldon
                  Warlord's "non-Wall")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Basic land types a "number of <type>s you control" clause can name.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")
_LAND_ALTERNATION = "|".join(_LAND_TYPES)

# The possessive subject: the card's own name, matched loosely on purpose. It is
# never read — the counter works from the permanent it is refreshing — so the
# only thing anchoring it to the card would be a whitelist that needs a new
# entry per reprint.
_SUBJECT = r".+?'s"

# "its power and toughness", used by the two-clause attacking split where the
# subject is stated once in the leading "as long as" qualifier.
_ITS_PT = "its power and toughness are each equal to the number of"
_PT = "power and toughness are each equal to the number of"


@dataclass(frozen=True)
class DynamicPT:
    """A characteristic-defining P/T: the instruction kind, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


def _land_count(match: re.Match) -> dict[str, object]:
    return {"count": "land", "land_type": match.group("land_type"), "scope": "you"}


def _creature_count(match: re.Match) -> dict[str, object]:
    payload: dict[str, object] = {"count": "creature", "scope": "you"}
    excluded = match.groupdict().get("excluded")
    if excluded:
        payload["exclude_type"] = excluded
    return payload


def _graveyard_type_count(match: re.Match) -> dict[str, object]:
    """"…equal to the number of instant and sorcery cards in your graveyard."
    (Kinetic Augur.)

    Counted through ``evaluate_count`` rather than the battlefield tally beside
    it, because the objects are *cards in a zone*: they have no computed
    characteristics at all (CR 613.1), so the question is a different one asked
    of a different matcher. Emitting the spec every other computed amount uses
    is what keeps "the number of instant and sorcery cards in your graveyard"
    meaning one thing whichever sentence prints it.
    """
    types = [word.strip() for word in match.group("types").split(" and ")]
    return {
        "defines": "power",
        "count_spec": {
            "zone": "graveyard",
            "owner": "you",
            "filter": {"type_filter": types},
        },
    }


def _same_name_count(match: re.Match) -> dict[str, object]:
    return {"count": "same_name", "scope": "all"}


def _attacking_split_land_count(match: re.Match) -> dict[str, object]:
    return {
        "count": "land",
        "land_type": match.group("land_type"),
        "scope": "defender_when_attacking",
    }


# (pattern, payload builder). Ordered: the attacking-split form contains a
# plain land-count clause as its first half, so it must be tried first or the
# generic pattern would claim half the line and drop the rest — the dropped-
# rider bug class. Anchored at both ends for the same reason.
_PATTERNS: tuple[tuple[re.Pattern[str], object], ...] = (
    (
        # Gaea's Liege: one line, two clauses, same land type in each — the
        # second names the *defending* player's battlefield.
        re.compile(
            rf"^as long as .+? isn't attacking, {_ITS_PT} "
            rf"(?P<land_type>{_LAND_ALTERNATION})s you control\. "
            rf"as long as .+? is attacking, {_ITS_PT} "
            rf"(?P=land_type)s defending player controls$"
        ),
        _attacking_split_land_count,
    ),
    (
        # Nightmare.
        re.compile(rf"^{_SUBJECT} {_PT} (?P<land_type>{_LAND_ALTERNATION})s you control$"),
        _land_count,
    ),
    (
        # Plague Rats. The counted name must be the subject's own — a card
        # counting creatures named something *else* is a different ability, and
        # refusing it here reports it unsupported rather than quietly counting
        # the wrong creatures.
        re.compile(
            rf"^(?P<subject>.+?)'s {_PT} creatures named (?P<named>.+?) on the battlefield$"
        ),
        _same_name_count,
    ),
    (
        # Kinetic Augur. "**Power** is", not "power and toughness are each": the
        # printed toughness stands, so this is the one entry that defines half a
        # CDA — and the half it defines is on the payload rather than in the
        # kind, because a card printed the other way round is the same template.
        re.compile(
            rf"^{_SUBJECT} power is equal to the number of "
            rf"(?P<types>[a-z]+(?: and [a-z]+)*) cards in your graveyard$"
        ),
        _graveyard_type_count,
    ),
    (
        # Keldon Warlord, and the unqualified "creatures you control" form.
        re.compile(
            rf"^{_SUBJECT} {_PT} (?:non-(?P<excluded>[a-z]+) )?creatures you control$"
        ),
        _creature_count,
    ),
)


def dynamic_pt_for(normalized_line: str) -> DynamicPT | None:
    """The characteristic-defining P/T *normalized_line* defines, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``).
    """
    for pattern, build in _PATTERNS:
        match = pattern.match(normalized_line)
        if match is None:
            continue
        groups = match.groupdict()
        # Self-reference check for the same-name form: "creatures named X" only
        # means "creatures named like me" when X is the subject.
        if "named" in groups and groups.get("subject") != groups.get("named"):
            return None
        return DynamicPT("dynamic_pt_count", build(match))
    return None
