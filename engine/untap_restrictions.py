"""Text-keyed untap-step restrictions (CR 502).

"Players skip their untap steps", "players can't untap more than one land
during their untap steps", "creatures with power 3 or greater don't untap
during their controllers' untap steps" — these are templates, not card
quirks. Any card printed with the phrase behaves the same way, so the
restriction is derived from oracle text here rather than registered per card
name in ``card_hooks.py``. Same model as ``cast_restrictions.py``.

The untap step reads only the derived :class:`UntapRestriction`; adding a card
that uses one of these templates requires no change anywhere. A card whose
wording is genuinely new adds one pattern to the table below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .oracle_types import _COLOR_WORD_TO_SYMBOL, _NUMBER_WORDS


@dataclass(frozen=True)
class UntapRestriction:
    """Declarative "don't untap as normal" constraint from a permanent.

    Two families, and they are different rules rather than two spellings of
    one. A **count limit** bounds how many permanents of a printed type the
    active player may untap and leaves the choice to them (Winter Orb, Smoke,
    Damping Field). A **block** says which permanents do not untap at all, and
    what it names is a printed noun phrase.

    scope      -- what a count limit applies to: "all" | "land" | "creature"
                  | "artifact"; "block" for the second family
    limit      -- max permanents of that scope the active player may untap
                  (0 with scope="all" skips the untap step entirely; None
                  means no count limit)
    blocked    -- the noun phrase a block names, as a filter payload
                  ``subject_matches`` tests: "creatures with power 3 or
                  greater" (Meekstone), "red creatures" (Magnetic Mountain),
                  "legendary creatures" (Arena of the Ancients), "creatures
                  without flying" (Mudslide), "Islands" (Curse of Marit Lage).
                  One field, because those are one sentence with the noun
                  changed -- it used to be three (``min_power``, ``color``,
                  ``supertype``), one per card that had been printed, each with
                  its own pattern, its own aggregate and its own branch in the
                  untap step. "Creatures with flying don't untap" matched none
                  of the three, so Energy Storm and Blizzard reported supported
                  with the line doing nothing at all.
    only_while_source_untapped -- the restriction is active only while the
                  source permanent itself is untapped (Winter Orb)
    """

    scope: str
    limit: int | None = None
    blocked: dict | None = None
    only_while_source_untapped: bool = False


# "As long as this artifact is untapped, ..." (Winter Orb) — a self-state
# qualifier that can precede any of the restrictions below, so it is stripped
# first rather than duplicated into every pattern.
_WHILE_UNTAPPED = re.compile(
    r"^as long as (?:this|~) [a-z ]*?is untapped, (?P<rest>.+)$"
)

_COUNT_WORD = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_COLOR_WORD = "|".join(sorted(_COLOR_WORD_TO_SYMBOL, key=len, reverse=True))


def _skip_untap_step(match: re.Match) -> UntapRestriction:
    return UntapRestriction(scope="all", limit=0)


def _limit_per_type(match: re.Match) -> UntapRestriction:
    return UntapRestriction(
        scope=match.group("type"), limit=_NUMBER_WORDS[match.group("count")]
    )


@lru_cache(maxsize=None)
def _blocked_subject(phrase: str) -> dict | None:
    """A printed plural noun phrase as a filter payload, or None.

    Read by **the grammar's noun parser**, which is the same reader
    `activation_restrictions._controlled_board_phrase` and
    `static_bonuses._controls_noun_condition` ask about the identical phrase --
    "red creatures" means one thing on this engine, and a second reader of it
    would be free to disagree. The payload must be one `subject_matches` can
    test: a narrowing parsed and then ignored would *widen* the restriction to
    every permanent, which is the one direction an untap block must never take.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    stream = TokenStream(tokenize(phrase.strip()).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload


def _subject_block(match: re.Match) -> "UntapRestriction | None":
    """"<noun phrase> don't untap during their controllers' untap steps."

    One row for what used to be three, because the three differed only in the
    noun. A phrase the parser cannot read (or the matcher cannot test) returns
    None, which leaves the line unclaimed and its card unsupported -- rather
    than admitting a sentence and then blocking nothing, or blocking everything.
    """
    blocked = _blocked_subject(match.group("subject"))
    return None if blocked is None else UntapRestriction(scope="block", blocked=blocked)


# Ordered: the first pattern whose regex matches the (qualifier-stripped) line
# wins, so more specific wordings precede more general ones.
UNTAP_RESTRICTION_PATTERNS: tuple[tuple[re.Pattern, Callable[[re.Match], UntapRestriction]], ...] = (
    # Two printed spellings of one rule (CR 500.11): the plural "Players skip
    # their untap steps" (Stasis) and the distributive "Each player skips their
    # untap step" (Sands of Time). One row, because a quantifier over the seats
    # is not a different restriction — and a second row would be a second place
    # to forget when the family grows.
    (
        re.compile(
            r"^(?:players skip their untap steps"
            r"|each player skips their untap step)$"
        ),
        _skip_untap_step,
    ),
    (
        re.compile(
            rf"^players can't untap more than (?P<count>{_COUNT_WORD}) "
            r"(?P<type>land|creature|artifact)s? during their untap steps$"
        ),
        _limit_per_type,
    ),
    (
        # "Creatures with power 3 or greater" (Meekstone), "red creatures"
        # (Magnetic Mountain), "legendary creatures" (Arena of the Ancients),
        # "creatures with flying" (Energy Storm, Blizzard), "creatures without
        # flying" (Mudslide), "Islands" (Curse of Marit Lage). One sentence with
        # the noun changed, so one row: the noun phrase is payload, read by the
        # parser that reads every other printed noun phrase.
        re.compile(
            r"^(?P<subject>.+?) don't untap "
            r"during their controllers' untap steps$"
        ),
        _subject_block,
    ),
)


def _restriction_from_line(line: str) -> UntapRestriction | None:
    qualifier = _WHILE_UNTAPPED.match(line)
    only_while_untapped = qualifier is not None
    if qualifier is not None:
        line = qualifier.group("rest")
    for pattern, build in UNTAP_RESTRICTION_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        restriction = build(match)
        # A row may decline its own match: the block row delimits any noun
        # phrase and implements only the ones the matcher can test, so an
        # unreadable one falls through rather than being admitted with the
        # narrowing dropped.
        if restriction is None:
            continue
        if only_while_untapped:
            return UntapRestriction(
                scope=restriction.scope,
                limit=restriction.limit,
                blocked=restriction.blocked,
                only_while_source_untapped=True,
            )
        return restriction
    return None


@lru_cache(maxsize=None)
def untap_restriction_for(oracle_text: str) -> UntapRestriction | None:
    """The untap-step restriction *oracle_text* imposes, or None.

    Cached on the text itself, which is immutable on a ``CardDefinition``, so
    the untap step's per-permanent scan stays a dict lookup like the name-keyed
    table it replaced. Only the first matching line counts: no printed card
    carries two untap restrictions, and silently combining them would hide a
    wording this table does not actually understand.
    """
    if "untap" not in oracle_text.lower():
        return None
    for raw_line in oracle_text.lower().split("\n"):
        line = raw_line.strip().rstrip(".")
        if not line:
            continue
        restriction = _restriction_from_line(line)
        if restriction is not None:
            return restriction
    return None


# ---------------------------------------------------------------------------
# Per-source restrictions
# ---------------------------------------------------------------------------
#
# The table above describes restrictions a permanent imposes on *other*
# permanents. A second, simpler family describes what a permanent's own text
# says about itself, and `phases/untap_step.py` enforces it by scanning each
# battlefield permanent's oracle text for these two phrases. The phrases live
# here so that scan and the whole-line matcher below are built from one string
# each — a copy in either place could drift and start claiming a wording the
# untap step does not actually honour.

# "This artifact doesn't untap during your untap step." (Basalt Monolith, Mana
# Vault, Time Vault, Brass Man, Island Fish Jasconius) — the permanent simply
# stays tapped.
SELF_DOESNT_UNTAP_PHRASE = "doesn't untap during your untap step"

# "You may choose not to untap this creature during your untap step." (Old Man
# of the Sea) — the controller may keep it tapped; the untap step honours an
# explicit choice and otherwise keeps it tapped while its linked steal is live.
SELF_MAY_KEEP_TAPPED_PHRASE = "you may choose not to untap"

_SELF_NOUN = r"(?:artifact|creature|enchantment|land|permanent)"

# Built from the phrases above and anchored at both ends. Anchoring is what
# makes a claim on one of these lines honest: the untap step's substring probe
# fires on *any* line containing the phrase, so only a line that is nothing but
# the restriction is fully implemented by it. "Enchanted creature doesn't untap
# during its controller's untap step" (Paralyze) is deliberately outside this
# table — it is one half of a fused instruction in
# mixins/oracle_instructions.py, not a self-referential line the untap step
# reads.
#: "This creature doesn't untap during your untap step **if it has a glyph
#: counter on it**." (Granted by Glyph of Delusion.) The same restriction as the
#: bare line below, under a condition the step re-asks each turn — which is why
#: it cannot be left to the loose substring probe: that probe fires on any line
#: containing the phrase, so a conditional line would freeze the creature for
#: the rest of the game and the counters the card removes one per upkeep would
#: mean nothing.
#:
#: The counter's name is payload for the reason every printed word in this file
#: is: a card printing "if it has a **paralysis** counter on it" is the same
#: restriction and must need no second row.
_SELF_UNTAP_COUNTER_CONDITION = re.compile(
    rf"^this {_SELF_NOUN} {re.escape(SELF_DOESNT_UNTAP_PHRASE)} "
    r"if it has an? (?P<counter>[a-z][a-z' -]*) counter on it$"
)


#: "This creature doesn't untap during your untap step **if it attacked during
#: your last turn**." (Goblin Rock Sled.) The third member of this family and
#: the same trap as the counter row above: the loose substring probe would see
#: the phrase, keep the Sled tapped forever and turn a card that attacks every
#: other turn into one that attacks once.
#:
#: The condition is a fact about the permanent's own attack record, not about
#: this text, so it is answered by ``turn_state.attacked_during_seats_last_turn``
#: — the one reader the declare-attackers step's Giant Turtle restriction also
#: asks. Two steps refusing on one question, not two copies of the arithmetic.
_SELF_UNTAP_ATTACKED_LAST_TURN = re.compile(
    rf"^this {_SELF_NOUN} {re.escape(SELF_DOESNT_UNTAP_PHRASE)} "
    r"if it attacked during your last turn$"
)


def self_untap_attacked_last_turn(line: str, card_name: str | None = None) -> bool:
    """Whether *line* is the attack-conditioned form of the untap restriction.

    Read by :func:`self_untap_line` — so the support gate admits the line — and
    by ``engine/phases/untap_step.py``, so the step that keeps the permanent
    tapped asks the same condition the gate claimed.
    """
    normalized = _collapse_self_name(line.strip().lower(), card_name).rstrip(".")
    return _SELF_UNTAP_ATTACKED_LAST_TURN.match(normalized) is not None


def self_untap_counter_condition(line: str, card_name: str | None = None) -> str | None:
    """The counter whose presence switches *line*'s untap restriction on, or
    None when the line states no such condition.

    Read by :func:`self_untap_line` — so the support gate admits the line — and
    by ``engine/phases/untap_step.py``, so the step that keeps the permanent
    tapped asks the same condition the gate claimed. One reader would be the
    gate saying a card works; two that disagree is the shape this file's
    docstring warns about, in the direction where the card does *more* than it
    prints.
    """
    normalized = _collapse_self_name(line.strip().lower(), card_name).rstrip(".")
    match = _SELF_UNTAP_COUNTER_CONDITION.match(normalized)
    return match.group("counter") if match is not None else None


_SELF_UNTAP_LINE_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (
        re.compile(rf"^this {_SELF_NOUN} {re.escape(SELF_DOESNT_UNTAP_PHRASE)}$"),
        "doesnt_untap",
    ),
    (
        # "This creature **enters tapped and** doesn't untap during your untap
        # step." (Leviathan.) One printed line making two claims, and both are
        # enforced: the entry half is `enter_effects.ENTERS_TAPPED`, which
        # `_initialize_permanent_state` probes as a *substring* and so already
        # applies here; this half is what keeps it tapped afterwards.
        #
        # It needs its own row because `self_untap_line` is anchored on the
        # whole line — the anchoring is deliberate, so a card cannot claim an
        # untap restriction off a sentence that merely contains the words — and
        # without a row Leviathan entered tapped and then untapped every turn,
        # with nothing failing.
        re.compile(
            rf"^this {_SELF_NOUN} enters tapped and "
            rf"{re.escape(SELF_DOESNT_UNTAP_PHRASE)}$"
        ),
        "doesnt_untap",
    ),
    (_SELF_UNTAP_COUNTER_CONDITION, "doesnt_untap_with_counter"),
    (_SELF_UNTAP_ATTACKED_LAST_TURN, "doesnt_untap_if_attacked_last_turn"),
    (
        re.compile(
            rf"^{re.escape(SELF_MAY_KEEP_TAPPED_PHRASE)} this {_SELF_NOUN} "
            r"during your untap step$"
        ),
        "may_keep_tapped",
    ),
)


def _collapse_self_name(line: str, card_name: str | None) -> str:
    """*line* with the card's own whole-word name spellings replaced by
    "this permanent".

    Pre-modern templating names the source: Rubinia Soulsinger prints "You may
    choose not to untap **Rubinia Soulsinger** during your untap step" where
    Old Man of the Sea prints "this creature". The grammar's lexer collapses
    the same references to one SELF token; this is that rule for a registry
    that matches on raw text. The forms are the full name and — for a
    legendary name with a comma — the short name before it (CR 201.4c), the
    same two ``engine/oracle.py``'s ``_self_name_forms`` reads; a copy here
    rather than an import because oracle.py imports this module.
    """
    if not card_name:
        return line
    full = card_name.strip().lower()
    forms = [full]
    if "," in full:
        forms.append(full.split(",", 1)[0].strip())
    for form in forms:
        if form:
            line = re.sub(rf"\b{re.escape(form)}\b", "this permanent", line)
    return line


def self_untap_line(line: str, card_name: str | None = None) -> str | None:
    """Name the per-source untap restriction *line* states in full, or None.

    The whole-line form of the two substring probes in
    ``phases/untap_step.py``, consulted by ``engine/grammar/registries.py``
    and the creature static-line gate — nothing dispatches on the returned
    name. *card_name* lets a line that names its own card (Rubinia
    Soulsinger) match the "this <noun>"-anchored patterns.
    """
    normalized = _collapse_self_name(line.strip().lower(), card_name).rstrip(".")
    for pattern, name in _SELF_UNTAP_LINE_PATTERNS:
        if pattern.match(normalized):
            return name
    return None
