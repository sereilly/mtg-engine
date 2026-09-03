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


#: The printed battlefield, as a ``scope`` value. A table rather than a chain of
#: conditionals because the phrase is data: a card printing a fifth one adds a
#: row here and a branch in the one counter that reads it.
_WHOSE_BATTLEFIELD: dict[str, str] = {
    "you": "you",
    "your opponents": "opponents",
    # "the chosen player" (Lost Order of Jarkeld) — the seat this permanent
    # chose as it entered (CR 614.1c), recorded on the permanent itself, which
    # is why the counter reads it off the permanent it is refreshing rather than
    # off the game.
    "the chosen player": "chosen_player",
}


def _type_count_plus(match: re.Match) -> dict[str, object]:
    """Gaea's Avenger. A card-type tally on a named battlefield, plus a printed
    constant — three payload keys rather than three templates."""
    return {
        "count": "card_type",
        "card_type": match.group("card_type"),
        "scope": _WHOSE_BATTLEFIELD[match.group("whose")],
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
        # Not "otherwise": `handlers/control_flow.py` owns that key for the
        # *else branch of a `may`*, and the guards that walk a composed
        # effect recurse into it expecting a list of steps. Angry Mob put a
        # bare number there and `test_front_end_safety` crashed trying to
        # iterate a 2. A payload key means one thing across the engine.
        "otherwise_value": int(match.group("otherwise")),
    }


def _same_name_count(match: re.Match) -> dict[str, object]:
    return {"count": "same_name", "scope": "all"}


#: Which printed half of the P/T a clause defines, by the words it uses. The
#: third row carries no key at all, because "power and toughness are each" is
#: what ``set_base_pt`` already does when neither is named — and an absent key
#: is what every payload here says for "the sentence did not narrow this".
_DEFINED_HALF: dict[str, str | None] = {
    "power and toughness are each": None,
    "power is": "power",
    "toughness is": "toughness",
}


def _counted_noun_phrase(match: re.Match) -> dict[str, object] | None:
    """"…equal to **1 plus the number of green creatures on the battlefield**."
    (An-Havva Constable; Aysen Crusader prints the same shape over both halves
    and a two-subtype union.)

    The counted set is a printed noun phrase, so it is read by the noun parser
    and turned into the count every other computed amount in the engine uses —
    ``lowering/_amounts.count_spec``. Nothing about the phrase is spelled into
    the pattern, which is what makes this one row rather than one row per
    printed noun: a colour, a creature type, a union of two, and the scope
    ("you control" against CR 403.1's shared battlefield) are all things that
    reader already answers.

    That shared count is also the point of the row rather than a convenience.
    An-Havva Inn prints An-Havva Constable's exact count as a life gain
    ("…where X is the number of green creatures on the battlefield"), and a
    second counter written here would be a second answer to one sentence — the
    drift ``count_spec`` exists to prevent, with a card on each side of it.

    Returns None — leaving the card unsupported — where either half refuses: a
    noun phrase the parser cannot read, or a count that reader cannot take
    (a zone, a controller narrowing, a restriction with no payload form). A
    characteristic-defining ability is recomputed continuously, so a payload
    the counter cannot answer is not a card that does less, it is a creature
    whose P/T is silently wrong every time anything looks at it.

    The printed constant rides as the count's ``offset``, which is the key
    ``_scaled`` already adds in one place for "…beyond the first" — so "1 plus"
    and "2 plus" are one arithmetic with one number changed, and there is no
    second site where a constant could be honoured or forgotten.
    """
    from .grammar.errors import LoweringError
    from .grammar.lowering._amounts import count_spec
    from .grammar.phrases import parse_subject_filter

    filt = parse_subject_filter(match.group("counted"), plural=True)
    if filt is None:
        return None
    # The printed constant is optional. "**Maro's** power and toughness are each
    # equal to the number of cards in your hand" is this sentence with no offset
    # at all, and every row above it counts a *battlefield* — so before the
    # "<N> plus" was made optional the only CDAs that could count a zone were
    # the ones that happened to print a constant in front of it. Zero is the
    # absent constant's value, and ``count_spec`` omits a zero offset, so the
    # payload a card with no constant produces is the payload it would have had
    # if this row had never carried one.
    try:
        spec = count_spec(filt, None, offset=int(match.group("plus") or 0))
    except LoweringError:
        return None
    payload: dict[str, object] = {"count_spec": spec}
    half = _DEFINED_HALF[match.group("half")]
    if half is not None:
        payload["defines"] = half
    return payload


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


def _snow_land_count(match: re.Match) -> dict[str, object]:
    """Drift of the Dead: "…equal to the number of **snow lands** you control."

    A land count narrowed by a **supertype** rather than a subtype (CR 205.4),
    which is one more payload key rather than one more counter: "snow Swamps"
    is the same sentence with both narrowings, and the counter asks
    `subject_matches` about each.
    """
    payload: dict[str, object] = {
        "count": "land", "scope": "you", "supertype": match.group("supertype"),
    }
    if match.group("land_type"):
        payload["land_type"] = match.group("land_type")
    return payload


def _all_graveyards_type_count(match: re.Match) -> dict[str, object]:
    """Lhurgoyf: "…power is equal to the number of creature cards in **all
    graveyards** and its toughness is equal to **that number plus 1**."

    Two clauses in one row for the reason Angry Mob's and Gaea's Liege's are:
    a rule claiming the first would leave the second unread, and Lhurgoyf is
    printed */1+* — the toughness clause is half the card. What it adds is a
    printed constant, so it rides the payload as `toughness_plus`.

    Counted through ``evaluate_count`` like Kinetic Augur's row, because the
    objects are cards in a zone and have no computed characteristics at all
    (CR 613.1) — a different question of a different matcher.
    """
    types = [word.strip() for word in match.group("types").split(" and ")]
    return {
        "defines": "power",
        "toughness_plus": int(match.group("plus")),
        "count_spec": {
            "zone": "graveyard",
            "owner": "all",
            "filter": {"type_filter": types},
        },
    }


def _other_subtype_count(match: re.Match) -> dict[str, object]:
    """Pestilence Rats: "…power is equal to the number of **other Rats** on the
    battlefield."

    Every battlefield (the sentence names no controller), the source itself
    excluded — which is what "other" means (CR 109.5) and is why it is a
    separate key rather than a subtype filter that would count the Rat asking.
    The printed toughness stands (Pestilence Rats is */3), exactly as it does
    for Kinetic Augur.
    """
    return {
        "defines": "power",
        "count": "subtype",
        "subtype": match.group("subtype"),
        "scope": "all",
        "exclude_self": True,
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
        #
        # "…1 plus the number of creatures **the chosen player** controls."
        # (Lost Order of Jarkeld.) A fourth value for the battlefield the
        # sentence names, and nothing else: the offset it needs was already
        # payload, so the card differs from Gaea's Avenger by one alternative.
        re.compile(
            rf"^{_SUBJECT} power and toughness are each equal to "
            r"(?P<plus>\d+) plus the number of "
            r"(?P<card_type>artifact|creature|enchantment|land)s "
            r"(?P<whose>you|your opponents|the chosen player) controls?$"
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
        # Drift of the Dead. Read before the plain land row below, which its
        # tail is a suffix of: matched there, "snow" would be dropped and the
        # Wall would count every land.
        re.compile(
            rf"^{_SUBJECT} {_PT} (?P<supertype>snow) "
            rf"(?:(?P<land_type>{_LAND_ALTERNATION})s|lands) you control$"
        ),
        _snow_land_count,
    ),
    (
        # Lhurgoyf.
        re.compile(
            rf"^{_SUBJECT} power is equal to the number of "
            r"(?P<types>[a-z]+(?: and [a-z]+)*) cards in all graveyards and "
            r"its toughness is equal to that number plus (?P<plus>\d+)$"
        ),
        _all_graveyards_type_count,
    ),
    (
        # Pestilence Rats.
        re.compile(
            rf"^{_SUBJECT} power is equal to the number of other "
            r"(?P<subtype>[a-z]+)s on the battlefield$"
        ),
        _other_subtype_count,
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
    (
        # "**An-Havva Constable's toughness is equal to 1 plus the number of
        # green creatures on the battlefield.**" and "**Aysen Crusader's power
        # and toughness are each equal to 2 plus the number of Soldiers and
        # Warriors you control.**"
        #
        # The constant is optional, which is what lets "**Maro's** power and
        # toughness are each equal to the number of cards in your hand" reach
        # this row at all. Every pattern above counts a battlefield, so a
        # constant-less count of a *zone* had nowhere to land — the sentence is
        # An-Havva Constable's with one word missing, and reading it as a
        # different template would be a second answer to one printed count.
        #
        # The general row, and read **last** on purpose: every pattern above is
        # a prefix or a special case of this shape, and each one already emits
        # the payload its counter branch reads. A row that claimed them would
        # not be wrong so much as it would be a second answer to a question
        # that already has one — and Angry Mob's two-sentence form would lose
        # its second half to the ``.+$`` here.
        #
        # What it counts is not spelled into the pattern at all: the noun phrase
        # goes to the same parser every other reader of a printed noun phrase
        # uses, and the count it becomes is ``count_spec``, the same one a
        # ", where X is the number of …" clause produces. That is the whole
        # point of the row — An-Havva Inn prints An-Havva Constable's count as
        # a life gain, and the two must be one number or the pair is two
        # readings of one sentence.
        re.compile(
            rf"^{_SUBJECT} (?P<half>power and toughness are each|power is|"
            r"toughness is) equal to (?:(?P<plus>\d+) plus )?the number of "
            r"(?P<counted>.+)$"
        ),
        _counted_noun_phrase,
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
        payload = build(match)
        # A builder may refuse. The general row above reads its own noun phrase
        # and its own count, and either can fail on a line whose *shape* matched
        # — which is a card this file cannot answer, not a card with no
        # characteristic-defining ability, so it leaves the line to whatever
        # else might read it and the card is reported unsupported naming the
        # clause.
        if payload is None:
            return None
        return DynamicPT("dynamic_pt_count", payload)
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
