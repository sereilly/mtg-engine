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
``land_type``     with ``count="land"``, the basic type to match — absent when
                  the sentence names none ("the number of **lands** you
                  control", Dakkon Blackblade), which counts every land
``exclude_type``  with ``count="creature"``, a type that disqualifies (Keldon
                  Warlord's "non-Wall")

Two values of ``count`` tally nothing on any battlefield — ``chosen_number`` is
a number a player picked as the permanent entered, and ``sacrificed_as_entered``
is how many permanents they gave up doing it. They are here because what they
*define* is a characteristic-defining P/T like every other row, and CR 604.3
does not care where the number comes from.
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
    payload: dict[str, object] = {"count": "land", "scope": "you"}
    # "…the number of **Swamps** you control" (Nightmare) narrows by subtype;
    # "…the number of **lands** you control" (Dakkon Blackblade) names the card
    # type and narrows by nothing. The key is omitted rather than set to None
    # for the reason every payload here omits what the sentence does not say:
    # an absent key is the counter's "no restriction".
    if match.group("land_type"):
        payload["land_type"] = match.group("land_type")
    return payload


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


def _type_count_plus(match: re.Match) -> dict[str, object]:
    """Gaea's Avenger. A card-type tally on a named battlefield, plus a printed
    constant — three payload keys rather than three templates."""
    return {
        "count": "card_type",
        "card_type": match.group("card_type"),
        "scope": "opponents" if match.group("whose") == "your opponents" else "you",
        "plus": int(match.group("plus")),
    }


def _toughness_land_count(match: re.Match) -> dict[str, object]:
    """People of the Woods: "…**toughness** is equal to the number of Forests
    you control."

    The mirror of Kinetic Augur's row one axis over, and payload for the same
    reason: which half a CDA defines is part of the sentence, not part of the
    counting. The printed power stands (People of the Woods is 0/*), which
    ``set_base_pt``'s None expresses exactly.
    """
    payload: dict[str, object] = {
        "defines": "toughness", "count": "land", "scope": "you",
    }
    if match.group("land_type"):
        payload["land_type"] = match.group("land_type")
    return payload


def _turn_split_land_count(match: re.Match) -> dict[str, object]:
    """Angry Mob: "During **your** turn, …are each equal to 2 plus the number of
    Swamps your opponents control. During turns other than yours, …are each 2."

    One row rather than two, for the reason Gaea's Liege's attacking split is
    one: a rule claiming the first sentence alone would leave the second
    unclaimed and the creature would carry the count on every turn, which is
    the half of the card that makes it playable against nobody.

    Both the constant and the off-turn value are payload — they are printed
    numbers, and a card printing "3 plus … otherwise 3" is this template — and
    so is the counted land type and whose battlefield it sits on. ``only_during``
    is what the counter reads to decide which of the two answers applies; it is
    a *turn* question, so it cannot be folded into ``scope``, which is a
    question about a battlefield.
    """
    return {
        "count": "land",
        "land_type": match.group("land_type"),
        "scope": "opponents" if match.group("whose") == "your opponents" else "you",
        "plus": int(match.group("plus")),
        "only_during": "your_turn",
        "otherwise": int(match.group("otherwise")),
    }


def _same_name_count(match: re.Match) -> dict[str, object]:
    return {"count": "same_name", "scope": "all"}


def _chosen_number(match: re.Match) -> dict[str, object]:
    """Shapeshifter. The only CDA in the pool that counts nothing: its value is
    a number a player chose (CR 614.1c as it enters, and again each upkeep).

    ``complement`` is what the toughness clause subtracts from — printed as
    "7 minus that number" and read as data, so a card splitting a different
    total is the same template. It is on the payload rather than in the kind
    for the reason every other parameter here is.
    """
    return {"count": "chosen_number", "complement": int(match.group("total"))}


def _life_paid_on_entry_count(match: re.Match) -> dict[str, object]:
    """Nameless Race. The life its controller paid as it entered, which is not
    on any battlefield either - the same shape Wood Elemental's row has, one
    resource over."""
    return {"count": "life_paid_as_entered"}


def _sacrificed_on_entry_count(match: re.Match) -> dict[str, object]:
    """Wood Elemental. The tally its own entry sacrifice recorded."""
    return {"count": "sacrificed_as_entered"}


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
        # Nightmare, and — with the subtype absent — Dakkon Blackblade. The
        # head noun is required either way, so a sentence counting something
        # this cannot name still leaves the alternation unmatched and refuses.
        re.compile(
            rf"^{_SUBJECT} {_PT} "
            rf"(?:(?P<land_type>{_LAND_ALTERNATION})s|lands) you control$"
        ),
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
        # Gaea's Avenger: "…are each equal to **1 plus** the number of
        # **artifacts your opponents control**." The constant, the card type
        # and whose battlefield are all payload, so the three ways this card
        # differs from Nightmare cost no code beyond this row.
        re.compile(
            rf"^{_SUBJECT} power and toughness are each equal to "
            r"(?P<plus>\d+) plus the number of "
            r"(?P<card_type>artifact|creature|enchantment|land)s "
            r"(?P<whose>you|your opponents) controls?$"
        ),
        _type_count_plus,
    ),
    (
        # People of the Woods. "**Toughness** is", not "power and toughness are
        # each": the printed power stands, the same way Kinetic Augur's printed
        # toughness does.
        re.compile(
            rf"^{_SUBJECT} toughness is equal to the number of "
            rf"(?:(?P<land_type>{_LAND_ALTERNATION})s|lands) you control$"
        ),
        _toughness_land_count,
    ),
    (
        # Angry Mob. Both halves in one pattern, for Shapeshifter's reason: a
        # rule claiming the first sentence would leave the second standing
        # unread, and the card would count Swamps on every turn instead of only
        # its controller's.
        re.compile(
            rf"^during your turn, {_SUBJECT} power and toughness are each equal "
            r"to (?P<plus>\d+) plus the number of "
            rf"(?P<land_type>{_LAND_ALTERNATION})s "
            r"(?P<whose>you|your opponents) controls?\. "
            r"during turns other than yours, .+?'s power and toughness are "
            r"each (?P<otherwise>\d+)$"
        ),
        _turn_split_land_count,
    ),
    (
        # Keldon Warlord, and the unqualified "creatures you control" form.
        re.compile(
            rf"^{_SUBJECT} {_PT} (?:non-(?P<excluded>[a-z]+) )?creatures you control$"
        ),
        _creature_count,
    ),
    (
        # Wood Elemental: "…equal to the number of **Forests sacrificed as it
        # entered**". The number is not on any battlefield — the Forests are in
        # a graveyard, and are different objects there (CR 400.7) — so it is
        # counted where it happened, by the entry sacrifice
        # (engine/enter_effects.sacrifice_any_number_on_enter), and read back
        # off the permanent here.
        #
        # The noun is captured and checked as a noun phrase but is not part of
        # the payload: the record is a count of what that card's own entry line
        # gave up, and the two sentences are one printed idiom. A card whose two
        # halves named *different* things would be a card this reads wrongly,
        # which is why the head noun has to parse at all rather than being ".+".
        re.compile(
            rf"^{_SUBJECT} {_PT} (?P<phrase>.+?) sacrificed as it entered$"
        ),
        _sacrificed_on_entry_count,
    ),
    (
        # Nameless Race: "…are each equal to **the life paid as it entered**".
        # Beside Wood Elemental's row and for its reason - the number is not on
        # any battlefield, so it is recorded where it happened (the entry
        # payment) and read back off the permanent here.
        re.compile(rf"^{_SUBJECT} {_PT.replace(' the number of', '')} the life "
                   r"paid as it entered$"),
        _life_paid_on_entry_count,
    ),
    (
        # Shapeshifter. Both halves in one pattern, because the second is not a
        # rider: a rule claiming the power clause alone would leave a printed
        # toughness of 0 standing and the creature would die on arrival.
        re.compile(
            rf"^{_SUBJECT} power is equal to the last chosen number and "
            r"its toughness is equal to (?P<total>\d+) minus that number$"
        ),
        _chosen_number,
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
        # "…the number of **<noun phrase>** sacrificed as it entered": the noun
        # has to be one the engine can read, or the sentence is one it does not
        # understand and the card is reported unsupported rather than counted
        # against a phrase nobody parsed.
        if "phrase" in groups and _names_objects(groups["phrase"] or "") is False:
            return None
        return DynamicPT("dynamic_pt_count", build(match))
    return None


def _names_objects(phrase: str) -> bool:
    """Whether *phrase* is a printed noun phrase the engine reads.

    Asked of the counted half of Wood Elemental's sentence. Through the same
    noun parser the entry sacrifice uses, so "the number of Forests" and
    "sacrifice any number of untapped Forests" are read by one reader — a second
    one here is how a card compiles supported and then counts something else.
    """
    from .grammar.phrases import parse_subject_filter

    return parse_subject_filter(phrase, plural=True) is not None
