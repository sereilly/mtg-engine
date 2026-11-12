"""Conditional static power/toughness bonuses (CR 613 layer 7c).

"This creature gets +N/+N as long as <condition>" — Sedge Troll, Kird Ape,
Giant Tortoise. The bonus size and the condition's subject are both data, and
the clause is printed in **two word orders**:

    This creature gets +1/+1 as long as you control a Swamp.
    As long as you control a Swamp, this creature gets +1/+1.

Only the first was ever dispatched. The second was admitted by a whitelist
literal in the compiler's support gate that spelled out *Swamp*, so a card
printed that way reported `supported` and then never got the bonus — while the
identical sentence naming any other land type was reported unsupported. Gate
and dispatch derive from this one table now, so both orders work for every
type and an unrecognized wording fails loud.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .graveyard_statics import GraveyardSource, source_in_its_graveyard
from .oracle_types import _NUMBER_WORDS
from .handlers._amounts import evaluate_count
from .handlers._conditions import _compare_count
from .handlers._filters import permanent_state_holds
from .handlers._targets import attached_host
from .late_modules import LateModules
from .named_counters import counters_on
from .object_colors import of_each_color

_late = LateModules(__package__)

# Desert is included alongside the five basics: Arabian Nights prints
# "as long as you control a Desert", and the check this feeds
# (_refresh_dynamic_creatures) matches by type, not by basic-ness.
BASIC_LAND_WORDS = ("plains", "island", "swamp", "mountain", "forest", "desert")
_LAND_ALTERNATION = "|".join(BASIC_LAND_WORDS)

_BONUS = r"gets \+(?P<power>\d+)/\+(?P<toughness>\d+)"


@dataclass(frozen=True)
class StaticBonus:
    """An instruction kind the P/T refresh dispatches on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind). Each condition appears twice — trailing and leading — because
# both are printed. Writing them as one table is what keeps the two orders from
# drifting into "one is implemented, the other is whitelisted".
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(rf"{_BONUS} as long as you control an? (?P<land_type>{_LAND_ALTERNATION})\b"),
        "conditional_land_bonus",
    ),
    (
        re.compile(
            rf"^as long as you control an? (?P<land_type>{_LAND_ALTERNATION}), "
            rf".*?{_BONUS}$"
        ),
        "conditional_land_bonus",
    ),
    (
        re.compile(rf"{_BONUS} as long as (?:it's|this creature is) untapped\b"),
        "conditional_untapped_bonus",
    ),
    (
        re.compile(rf"^as long as (?:it's|this creature is) untapped, .*?{_BONUS}$"),
        "conditional_untapped_bonus",
    ),
)


def static_bonus_for(normalized_line: str) -> StaticBonus | None:
    """The conditional static ability *normalized_line* grants, or None.

    Takes an already-normalized line (``line_normalization.normalize_creature_line``).
    The two legacy kinds are tried first so their payloads stay byte-identical;
    everything newer rides the general ``conditional_static`` shape below.
    """
    for pattern, kind in _PATTERNS:
        match = pattern.search(normalized_line)
        if match is None:
            continue
        groups = match.groupdict()
        payload: dict[str, object] = {
            "power": int(groups["power"]),
            "toughness": int(groups["toughness"]),
        }
        if groups.get("land_type"):
            payload["land_type"] = groups["land_type"]
        return StaticBonus(kind, payload)
    return conditional_static_for(normalized_line)


# ---------------------------------------------------------------------------
# The general conditional static: <effect> as long as <condition>
# ---------------------------------------------------------------------------
#
# One instruction kind, ``conditional_static``, with the condition and the
# effect both payload — the legacy kinds above baked the condition into the
# kind, which is one dispatch branch per condition per effect class and grows
# multiplicatively. Who consumes which half is split by layer: the P/T delta
# is contributed by ``_refresh_dynamic_creatures`` (layer 7c's derived
# channel), keyword grants by ``_recalculate_lord_buffs`` (layer 6's derived
# grants, whose clear/rebuild that pass owns), and "can't be blocked" is asked
# at block-legality time — a condition can change between recomputes, and the
# blocking check is the read that matters.

_DRAWN_CONDITION = re.compile(
    r"^you've drawn (?P<count>[a-z]+) or more cards this turn$"
)
_CONTROLS_PLANESWALKER_CONDITION = re.compile(
    r"^you control an? (?P<subtype>[a-z]+) planeswalker$"
)
_HAS_PLUS1_CONDITION = re.compile(r"^it has a \+1/\+1 counter on it$")
# "you control a creature with power 4 or greater" (Drowsing Tyrannodon). The
# threshold is data, and the noun phrase is lowered to the *same* filter payload
# the grammar produces for Turret Ogre's intervening-if — so the phrase has one
# meaning in the engine (``handlers/_filters.permanent_matches_filter``'s ``power``
# comparison) rather than a second regex that happens to agree today.
_CONTROLS_POWER_CONDITION = re.compile(
    r"^you control a creature with power (?P<power>\d+) or greater$"
)

#: "as long as **it's attacking**" (Purraj of Urborg, Spirit of the Night). A
#: state of the permanent itself rather than of a board — and the *only*
#: condition in this table that is, which is why it was missing: every row
#: above asks what its controller has.
#:
#: ``conditional_static_holds`` has answered ``is_state`` since Snow Devil, but
#: that payload only ever arrived from the grammar's **attached** path (an
#: Aura's "enchanted creature has first strike as long as it's blocking"). The
#: same-subject spelling refuses in the grammar with the reason "derived by
#: engine/static_bonuses.py", and this table did not derive it — the evaluator
#: built at one end and connected at neither, which is the refusal-can-expire
#: shape one row down had already been caught in.
#:
#: The words are exactly ``_STATE_TESTS``', because that is what will answer
#: this at every recompute; an unlisted one refuses the line rather than
#: producing a condition nothing can test.
#: ``enchanted`` joined the alternation with Urza's Destiny's "enchanted
#: matters" cycle (Fledgling Osprey, Metathran Elite, Thran Golem). It is the
#: same shape as every other word here — a state read off the permanent itself
#: — and its test lives beside them in ``_STATE_TESTS``, which is what stops
#: "is an Aura attached?" being answered twice. ``equipped`` (CR 301.5a)
#: joined with Mirrodin's Skyhunter Cub and Leonin Den-Guard, the same
#: question asked of the other kind of attachment.
_STATE_CONDITION = re.compile(
    r"^(?:it's|this creature is) "
    r"(?P<state>tapped|untapped|attacking|blocking|blocked|unblocked|enchanted|equipped)$"
)

# "as long as an opponent has eight or more cards in their graveyard"
# (Thieves' Guild Recruiter cycle). A zone *size*, not a set of objects: nothing
# is matched, so it is its own condition kind rather than a `controls` payload
# with a graveyard filter — and the seat it asks about is printed, because "an
# opponent" and "you" are different questions with different answers.
#: "as long as **a card exiled with this creature has flying**" (Death-Mask
#: Duplicant). A question about the cards the permanent's own imprint exiled
#: (CR 607.2a), answered by ``linked_exile_keywords.linked_exile_has``; the
#: quality is an implemented keyword or one of the two families (landwalk,
#: protection) that module reads as "any member", and anything else refuses.
_LINKED_EXILE_CONDITION = re.compile(
    r"^a card exiled with (?:this creature|it) has (?P<quality>[a-z ]+)$"
)

_GRAVEYARD_SIZE_CONDITION = re.compile(
    r"^(?P<who>an opponent|you) ha(?:s|ve) (?P<count>\w+) or more cards in "
    r"(?:their|your) graveyard$"
)

# The keyword group admits commas because the printed list uses them: "it gets
# +2/+2 and has **flying, first strike, and trample**" (Thran Golem). The
# character class was `[a-z ]+`, which is the two-keyword spelling only — a
# three-keyword grant fell out of the pattern entirely and the whole line
# refused, which reads as an unimplemented effect rather than as a missing
# comma. Nothing is admitted by widening it: `_keyword_list` splits on the same
# commas and holds every word to `IMPLEMENTED_KEYWORDS`, so a comma-joined list
# containing a word with no behaviour behind it still refuses.
_EFFECT_PT = re.compile(
    r"^gets \+(?P<power>\d+)/\+(?P<toughness>\d+)(?: and has (?P<keywords>[a-z, ]+))?$"
)
_EFFECT_KEYWORDS = re.compile(r"^has (?P<keywords>[a-z, ]+)$")
# "…this creature **has protection from white**" (Escaped Shapeshifter). Read
# before the keyword form above would see it: "protection from white" is not a
# word `IMPLEMENTED_KEYWORDS` holds, so `_keyword_list` refuses it and the whole
# line refused with it — correctly, because a keyword grant of the bare word
# "protection" is protection from everything.
#
# Its own payload key rather than a keyword, and read by
# ``_protection_qualities`` rather than by the derived-grant channel
# ``add_derived_grant`` owns: protection carries a **quality**, and the grant
# channel is one word per grant with nowhere to put it.
_EFFECT_PROTECTION = re.compile(r"^has protection from (?P<quality>[a-z ]+)$")
_EFFECT_UNBLOCKABLE = re.compile(r"^can't be blocked$")
# 'This creature has **"{B}: Regenerate this creature"** as long as you control
# a Zombie.' (Tribal Golem's fifth clause, once ``line_rewrites`` has written
# its list out.) A whole printed ability in quotes (CR 113.3) where the rows
# above read words, carried on the ``ability_lines`` key the grammar's own
# conditional statics already hand ``_recalculate_lord_buffs`` (Wayward Angel)
# — so the line is granted on the derived-ability channel while the condition
# holds and is gone, with nothing to undo, when it stops. Admitted only when
# the quote compiles on a card that says nothing else
# (``granted_abilities.granted_ability_supported``), the question every other
# reader of a granted line asks: an unreadable quote is refused here rather
# than folded onto a creature it would make unsupported.
_EFFECT_ABILITY = re.compile(r'^has "(?P<ability>[^"]+)"$')
# "can attack as though it didn't have defender" (Drowsing Tyrannodon).
# CR 609.4: an "as though" permission applies to the stated effect ONLY. The
# creature still HAS defender for every other purpose, so this is a payload the
# attack-legality check reads — never a keyword removal, which would also change
# what "creatures with defender" matches and what a Wall-referencing card sees.
_EFFECT_IGNORES_DEFENDER = re.compile(
    r"^can attack as though it didn't have defender$"
)


@lru_cache(maxsize=1)
def _implemented_keywords() -> frozenset[str]:
    # Lazy for the same reason lord_buffs' vocabulary is: the grammar package
    # imports this module, and the keyword set belongs to the engine's one
    # registry rather than a copy here.
    from .grammar import vocabulary

    return vocabulary.IMPLEMENTED_KEYWORDS


def _parse_condition_text(text: str) -> dict[str, object] | None:
    match = _DRAWN_CONDITION.match(text)
    if match is not None:
        count = _NUMBER_WORDS.get(match.group("count"))
        if count is None:
            return None
        return {"kind": "drawn_cards_this_turn", "count": count}
    match = _CONTROLS_PLANESWALKER_CONDITION.match(text)
    if match is not None:
        return {"kind": "controls_planeswalker", "subtype": match.group("subtype")}
    if _HAS_PLUS1_CONDITION.match(text) is not None:
        return {"kind": "has_plus1_counter"}
    match = _GRAVEYARD_SIZE_CONDITION.match(text)
    if match is not None:
        count = _NUMBER_WORDS.get(match.group("count"))
        if count is None:
            # The number word is read, not compared — an unreadable one refuses
            # the whole condition rather than defaulting, because a threshold
            # that quietly becomes zero is a static that always holds.
            return None
        return {
            "kind": "graveyard_size",
            "who": "opponent" if match.group("who") == "an opponent" else "you",
            "count": count,
        }
    match = _STATE_CONDITION.match(text)
    if match is not None:
        return {"kind": "is_state", "state": match.group("state")}
    described = _self_noun_condition(text)
    if described is not None:
        return described
    match = _CONTROLS_POWER_CONDITION.match(text)
    if match is not None:
        return {
            "kind": "controls",
            "who": "you",
            "filter": {
                "type_filter": "creature",
                "power": {"op": "ge", "value": int(match.group("power"))},
            },
        }
    match = _LINKED_EXILE_CONDITION.match(text)
    if match is not None:
        from .linked_exile_keywords import FAMILIES, LINKED_EXILE_HAS

        quality = match.group("quality").strip()
        if quality not in FAMILIES and quality not in _implemented_keywords():
            return None
        return {"kind": LINKED_EXILE_HAS, "quality": quality}
    return _controls_noun_condition(text)


#: "as long as **you control a snow land**" (Woolly Mammoths), "…**a Plains**"
#: (Dire Wolves). The general form of the two hand-written ``you control …``
#: rows above, and the one the specific rows are special cases of.
#:
#: This was refused rather than read, and the refusal had **expired**: the
#: grammar declines a conditional static about your own board with the reason
#: "derived by engine/static_bonuses.py", which was true of the five conditions
#: this table already knew and of nothing else. So "as long as you control a
#: snow land" was read by nobody at all — the grammar pointing at a table that
#: pointed nowhere, with no test able to notice because both halves are
#: individually correct. (SET_PLAYBOOK Phase 3: "a refusal can expire without
#: anything failing".)
#:
#: **And the seat is read, not assumed.** "as long as **an opponent controls** a
#: creature with flying" (Escaped Shapeshifter) is the same condition about the
#: other side of the table, and ``conditional_static_holds`` has answered
#: ``who="opponent"`` for the ``controls`` payload since the grammar started
#: producing one — the trailing word order compiles it today. Only this table's
#: anchor was "you", so the *fronted* order of the very same sentence refused.
#: That is the two-front-ends failure one file over: an evaluator that answers a
#: seat and a reader that cannot spell one.
_CONTROLS_NOUN_CONDITION = re.compile(
    r"^(?:(?P<you>you) control|an (?P<opponent>opponent) controls) (?P<phrase>.+)$"
)


#: "This creature has defender as long as **it's a Wall**." (Mistform Wall.)
#: What the permanent itself *is*, asked of the source — the same-subject twin
#: of the grammar's ``attached_matches`` ("as long as enchanted land is a basic
#: Mountain", Goblin Caves), and answered the same way: the noun phrase is read
#: by the grammar's noun parser and tested through ``subject_matches``, so the
#: layers answer it. A Mistform Wall that has become a Goblin until end of turn
#: is no Wall, and its defender goes with the type (CR 613.1d before 613.1f).
_SELF_NOUN_CONDITION = re.compile(
    r"^(?:it's|this creature is) (?:a|an) (?P<phrase>.+)$"
)


def _self_noun_condition(text: str) -> dict[str, object] | None:
    """"it's a <noun phrase>" as a ``self_matches`` payload, or None.

    :func:`_controls_noun_condition`'s reading of the phrase, for its reason: a
    second reader of "a Wall" would be free to disagree with the matcher about
    what a Wall is. A phrase the parser cannot read, or one carrying a key the
    matcher cannot test, refuses — and so does a phrase that narrows nothing,
    which would be a condition that always holds.
    """
    match = _SELF_NOUN_CONDITION.match(text)
    if match is None:
        return None
    payload = _noun_phrase_payload(match.group("phrase"))
    if not payload:
        return None
    return {"kind": "self_matches", "filter": payload}


def _noun_phrase_payload(phrase: str) -> dict[str, object] | None:
    """*phrase* read by the grammar's noun parser as a testable filter
    payload, or None when it does not read in full or carries a key
    ``subject_matches`` cannot test."""
    from .grammar.errors import GrammarError
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .grammar.lexer import tokenize
    from .subject_filters import untestable_filter_keys

    stream = TokenStream(tokenize(phrase).tokens)
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


def _controls_noun_condition(text: str) -> dict[str, object] | None:
    """"you control <noun phrase>" as a ``controls`` payload, or None.

    The phrase is read by **the grammar's noun parser**, not by a regex here:
    ``subject_matches`` is what will answer this condition at every recompute,
    and a second reader of "a snow land" would be free to disagree with it about
    what a snow land is. A phrase the parser cannot read, or one carrying a key
    the matcher cannot test, refuses — a dropped narrowing is a static that
    holds on a board the card does not name.
    """
    match = _CONTROLS_NOUN_CONDITION.match(text)
    if match is None:
        return None
    who = "you" if match.group("you") else "opponent"
    # The article is the quantifier, and it is what the printed clause means:
    # "you control **a** snow land" is a presence test, which is the default the
    # consumer applies when no count rides the payload. "Two or more" is a
    # threshold this branch does not read and must not silently answer as
    # presence, so it still refuses.
    #
    # "…as long as you control **no** untapped lands" (Prophecy's Scoria Cat,
    # Spur Grappler, Fen Stalker, Vintara Snapper) is the one other quantifier
    # read here, as the absence it says: ``count 0, op eq`` — the payload the
    # grammar's condition lowering already builds for Angelic Voices' "you
    # control no nonartifact, nonwhite creatures", and the one
    # ``conditional_static_holds`` already compares. Read as presence it would
    # be its own negation, which is why it refused until it carried a count.
    phrase = match.group("phrase")
    article, _, rest = phrase.partition(" ")
    if not rest:
        return None
    counted: dict[str, object] = {}
    other: dict[str, object] = {}
    if article == "no":
        counted = {"count": 0, "op": "eq"}
    elif article == "another" and who == "you":
        # "…as long as you control **another** artifact creature" (Darksteel's
        # Drill-Skimmer). The article carries CR 113.7's source exclusion —
        # the grammar's condition reader folds the same word onto
        # ``other_than_source`` (``condition_counts``), whose payload is
        # ``exclude_self`` — and ``conditional_static_holds`` hands the pivot
        # to ``subject_matches`` as *source*, so the creature never counts
        # itself. Your own board only: the opponent iteration scopes by seat
        # and asks no observer, and "an opponent controls another …" is a
        # sentence nothing prints.
        other = {"exclude_self": True}
    elif article not in ("a", "an"):
        return None
    payload = _noun_phrase_payload(rest)
    if not payload:
        return None
    return {
        "kind": "controls", "who": who, "filter": {**payload, **other}, **counted,
    }


def _parse_effect_text(text: str) -> dict[str, object] | None:
    match = _EFFECT_PT.match(text)
    if match is not None:
        effect: dict[str, object] = {
            "power": int(match.group("power")),
            "toughness": int(match.group("toughness")),
        }
        if match.group("keywords"):
            keywords = _keyword_list(match.group("keywords"))
            if keywords is None:
                return None
            effect["keywords"] = keywords
        return effect
    match = _EFFECT_PROTECTION.match(text)
    if match is not None:
        qualities = _protection_list(match.group("quality"))
        if qualities is None:
            return None
        return {"protection_from": qualities}
    match = _EFFECT_KEYWORDS.match(text)
    if match is not None:
        keywords = _keyword_list(match.group("keywords"))
        if keywords is None:
            return None
        return {"keywords": keywords}
    match = _EFFECT_ABILITY.match(text)
    if match is not None:
        from .granted_abilities import granted_ability_supported

        ability = match.group("ability").strip()
        if not granted_ability_supported(ability):
            return None
        return {"ability_lines": [ability]}
    if _EFFECT_UNBLOCKABLE.match(text) is not None:
        return {"cant_be_blocked": True}
    if _EFFECT_IGNORES_DEFENDER.match(text) is not None:
        return {"ignores_defender": True}
    return None


def _protection_list(text: str) -> list[str] | None:
    """The protection qualities *text* names, or None if one is unmodelled.

    CR 702.16g: "protection from A and from B" is shorthand for two abilities,
    so the clause is split the way ``_protection_qualities`` splits a printed
    one. The words are validated through ``keywords.protection_quality`` — the
    same reader that answers the board — so a quality the shield cannot model
    refuses the line instead of compiling into a static that protects nobody.

    A member may be CR 702.16h/i shorthand for several abilities — "…has
    protection from artifacts and **from each color**" (Pristine Angel) — so
    each is asked of ``keywords.protection_qualities_named``, the reader the
    printed-line gate and ``mixins/protection._protection_qualities`` both
    ask, rather than of the one-quality reader beneath it: the gate and the
    shield then read one sentence out of one phrase.
    """
    from .keywords import protection_qualities_named

    words = [part.strip() for part in re.split(r",|\band from\b|\band\b", text)]
    words = [word for word in words if word]
    if not words or any(protection_qualities_named(word) is None for word in words):
        return None
    return words


def _keyword_list(text: str) -> list[str] | None:
    """The keyword abilities *text* names — every one must be implemented,
    because a conditional grant of a word without behaviour is a grant of
    nothing and the line must refuse instead."""
    words = [part.strip() for part in re.split(r",| and ", text) if part.strip()]
    if not words or any(word not in _implemented_keywords() for word in words):
        return None
    return words


def conditional_static_for(normalized_line: str) -> StaticBonus | None:
    """"<effect> as long as <condition>", in both printed word orders — and the
    third spelling, where the condition is a *timing* clause printed first
    ("During your turn, this creature has first strike", Radha).

    That one is the same static wearing different words: "during your turn" is a
    condition like any other, and reading it as a duration instead would make
    the ability something a resolution grants rather than something the
    permanent has.
    """
    line = normalized_line.strip().rstrip(".")
    subject = "this creature "
    if line.startswith("during your turn, "):
        effect_clause = line[len("during your turn, "):]
        if not effect_clause.startswith(subject):
            return None
        effect = _parse_effect_text(effect_clause[len(subject):])
        if effect is None:
            return None
        return StaticBonus(
            "conditional_static", {**effect, "condition": {"kind": "your_turn"}}
        )
    if line.startswith("as long as "):
        # "As long as <condition>, this creature <effect>" (Gnarled Sage) —
        # and "As long as this creature is enchanted, **it** gets +2/+2 and has
        # flying, first strike, and trample" (Thran Golem), where the fronted
        # condition has already named the subject and the effect half wears a
        # pronoun. Both spellings are the same sentence about the same
        # permanent: the condition is read off the source and so is the effect,
        # so the pronoun has exactly one referent and admitting it adds no
        # ambiguity. (The trailing word order is the mirror image and has
        # always read the pronoun — "this creature gets +2/+2 as long as
        # **it's** untapped" — so refusing it here was the two-orders drift
        # this table's own docstring exists to prevent.)
        rest = line[len("as long as "):]
        condition_text, separator, effect_clause = rest.partition(", ")
        if not separator:
            return None
        for pronoun in (subject, "it "):
            if effect_clause.startswith(pronoun):
                effect_text = effect_clause[len(pronoun):]
                break
        else:
            return None
    else:
        # "This creature <effect> as long as <condition>" (Sigiled Contender,
        # Tome Anima, Predatory Wurm).
        if not line.startswith(subject):
            return None
        remainder = line[len(subject):]
        effect_text, separator, condition_text = remainder.partition(" as long as ")
        if not separator:
            return None
    condition = _parse_condition_text(condition_text)
    # The family reading first: "landwalk" and "protection" are in
    # ``IMPLEMENTED_KEYWORDS`` as the family words a printed quality joins, so
    # the keyword reading below would grant the bare word.
    effect = (
        _linked_family_effect(condition, effect_text) if condition is not None else None
    )
    if effect is None:
        effect = _parse_effect_text(effect_text)
    if condition is None or effect is None:
        return None
    return StaticBonus("conditional_static", {**effect, "condition": condition})


def _linked_family_effect(condition: dict, effect_text: str) -> dict | None:
    """"…this creature **has landwalk**" / "…**has protection**" behind "as
    long as a card exiled with this creature has" the same family (Death-Mask
    Duplicant): every member of the family those cards print, which is a
    grant only that condition can name. Read before the keyword effect, which
    would grant the bare family word — a landwalk naming no land, protection
    from no quality."""
    from .linked_exile_keywords import (FAMILIES, LINKED_EXILE_FAMILY,
                                        LINKED_EXILE_HAS)

    quality = condition.get("quality")
    if (
        condition.get("kind") != LINKED_EXILE_HAS
        or quality not in FAMILIES
        or effect_text != f"has {quality}"
    ):
        return None
    return {LINKED_EXILE_FAMILY: quality}


#: The ``subject`` a ``controls`` condition carries when its pronoun is **each
#: permanent an anthem reaches** rather than the anthem's source: "Basic lands
#: each player controls have shroud as long as **that player** controls three
#: or fewer lands" (Sheltering Prayers). Such a condition has no answer until a
#: recipient is named, so :func:`conditional_static_holds` answers it only when
#: handed one, and the lord-buff recompute asks it per permanent
#: (``_lord_buff_matches``) instead of once per source.
RECIPIENT_SUBJECT = "recipient"


def condition_is_per_recipient(condition) -> bool:
    """Whether *condition* is asked of each buffed permanent, not of the source."""
    return isinstance(condition, dict) and condition.get("subject") == RECIPIENT_SUBJECT


def conditional_static_holds(
    game, seat: int, source, condition: dict, *, recipient=None
) -> bool:
    """Whether a ``conditional_static`` payload's condition holds right now.

    Beside the table that produces the payloads so the vocabulary has one
    definition; *game* and *source* are duck-typed (the control seam and the
    permanent's own state are all it reads).

    *recipient* is the permanent a per-recipient condition is being asked
    about (:data:`RECIPIENT_SUBJECT`); every other condition ignores it.
    """
    kind = condition.get("kind")
    # "…as long as **it's blocking and you control a snow land**" (Snow Devil).
    # Every conjunct, through this same function — the lowering refused any part
    # it does not answer, so a False here is a clause that is genuinely false
    # rather than one nobody read.
    if kind == "all_of":
        return all(
            conditional_static_holds(game, seat, source, part, recipient=recipient)
            for part in condition.get("conditions") or ()
        )
    # "As long as **this card is in your graveyard** and you control a
    # Mountain, …" (Anger). CR 113.6b's statement of where the ability
    # functions, answered of the source itself: true of a card gathered from
    # its owner's graveyard and still at that position, false of a permanent —
    # so an Incarnation on the battlefield grants nothing. The same payload a
    # trigger's intervening-if carries (Pyre Zombie), and "above" is read by the
    # module that owns it (``graveyard_order.satisfies_above``).
    if kind == "self_in_graveyard_with_cards_above":
        return source_in_its_graveyard(game, source, condition)
    # Every other clause about a static that functions from a graveyard is
    # about the *board* — "you control a Mountain", whose seat is already
    # *seat* (CR 108.4a, the owner). A card in a graveyard is no permanent for
    # "another" or "its" to be measured against, so the clauses below are
    # asked with no source rather than with a stand-in for one; the lowering
    # refuses the clauses that would need it before this is reached.
    if isinstance(source, GraveyardSource):
        source = None
    # "As long as **a card exiled with this creature has flying**, …"
    # (Death-Mask Duplicant): the cards its imprint exiled and still in exile,
    # asked now (CR 611.3a).
    if kind == "linked_exile_has":
        linked_exile_has = _late.linked_exile_keywords.linked_exile_has

        return linked_exile_has(game, source, str(condition.get("quality") or ""))
    # "…as long as **it's** blocking / attacking / untapped". A state read off
    # one permanent, and *which* permanent is payload: an Aura's "it" is the
    # creature it enchants (an Aura never blocks), and a creature's own "it" is
    # itself. The state word is the permanent's own field, the same reading
    # `handlers/control_flow.evaluate_condition` gives an intervening-if — so
    # the phrase means one thing in the engine.
    if kind == "is_state":
        subject = source
        if condition.get("subject") == "attached":
            subject = attached_host(game, source, last_known=False)
        state = condition.get("state")
        if subject is None or not state:
            return False
        value = permanent_state_holds(subject, state)
        return (not value) if condition.get("negated") else value
    # "**During your turn**" (Radha). Whose turn it is, which is a fact about
    # the game rather than about the permanent — and the seat asked is the
    # ability's controller (CR 109.5), not the permanent's owner.
    if kind == "your_turn":
        # "**During turns other than yours**, creatures you control get -0/-2."
        # (Vibrating Sphere.) The same question negated, which is why it is a
        # flag on this branch rather than a second kind: "other than yours" is
        # not "an opponent's turn", and two branches would eventually answer the
        # three-seat board differently.
        mine = game.active_player_index == seat
        return not mine if condition.get("negated") else mine
    if kind == "drawn_cards_this_turn":
        player = game.players[seat]
        return len(player.cards_drawn_this_turn) >= int(condition.get("count", 0))
    if kind == "controls_planeswalker":
        subtype = condition.get("subtype")
        return any(
            perm.has_type("planeswalker") and perm.has_type(subtype)
            for perm in game.controlled_by(seat)
        )
    if kind == "color_is_most_common":
        # "…as long as **white is the most common color among all permanents**
        # or is tied for most common" (the Invasion Djinns). The census is
        # ``engine/color_census.py``'s — one count, also asked by the two
        # spells that test their target against it and by Call to Arms over a
        # narrower set — and it reads colours through the layers, so a Lace on
        # anything moves the answer at the next recompute with nothing to undo.
        color_is_most_common = _late.color_census.color_is_most_common

        return color_is_most_common(
            game, str(condition.get("color") or ""),
            tied=bool(condition.get("tied", True)),
        )
    if kind == "shares_most_common_color":
        # "…unless **it shares a color with the most common color among all
        # permanents** or a color tied for most common." (Heroic Defiance.)
        # The same census asked of one permanent's own colours — the two
        # spells that print the clause ask it of their target, and here "it" is
        # the sentence's subject: the enchanted creature for an Aura, the
        # source itself otherwise. Colourless shares nothing (CR 105.2), and a
        # board with no coloured permanent has no most common colour.
        shares_most_common_color = _late.color_census.shares_most_common_color

        subject = source
        if condition.get("subject") == "attached":
            subject = attached_host(game, source, last_known=False)
        if subject is None:
            return False
        return shares_most_common_color(game, subject)
    if kind == "all_share_a_color":
        # "Nonartifact creatures get +2/+2 **as long as they all share a
        # color**." (Common Cause.) CR 105.2 makes an object's colours a set, so
        # "all share a color" is a non-empty **intersection** across the whole
        # set — not "no two differ", which would be true of a board of one white
        # and one blue creature.
        #
        # The set is the anthem's own filter, copied onto this payload by the
        # lowering, and it is read through the layer-aware colour accessor
        # (CR 613.1e): a creature Painter's Servant has made black shares black,
        # and a colourless one shares nothing — which is what makes an artifact
        # creature able to switch this off, and why the card says "nonartifact".
        #
        # An empty board is vacuously true and buffs nobody either way; saying
        # so explicitly keeps the intersection loop from having to mean it.
        subject_matches = _late.subject_filters.subject_matches

        described = condition.get("filter") or {}
        shared: set[str] | None = None
        for permanent in game.all_permanents():
            if not subject_matches(
                game, permanent, dict(described), observer=seat, source=source
            ):
                continue
            colors = set(game._effective_colors(permanent))
            shared = colors if shared is None else (shared & colors)
            if not shared:
                return False
        return True
    if kind == "attached_matches":
        # "As long as enchanted land is a basic Mountain, …" (Goblin Caves,
        # Goblin Shrine.) The question is about the permanent the source is
        # attached to, and it is asked through ``subject_matches`` — the one
        # reader of what a printed noun phrase means — so the layers answer it:
        # a land Conversion has turned into a Plains stops being a Mountain and
        # the anthem switches off with nothing to undo, and a nonbasic land
        # Blood Moon has made a Mountain is still not a *basic* one.
        subject_matches = _late.subject_filters.subject_matches

        # The live record, not last-known information: this answers a
        # continuous ability on every recompute (CR 611.3b).
        host = attached_host(game, source, last_known=False)
        if host is None:
            return False
        return subject_matches(
            game, host, condition.get("filter") or {}, observer=seat, source=source
        )
    if kind == "self_matches":
        # "…as long as **it's a Wall**." (Mistform Wall.) ``attached_matches``
        # asked of the source itself rather than of its host, through the same
        # reader, so the type is read through layer 4 on every recompute: a
        # Mistform Wall that became a Goblin stops having defender with nothing
        # to undo, and gets it back when the change ends at cleanup.
        subject_matches = _late.subject_filters.subject_matches

        if source is None:
            return False
        return subject_matches(
            game, source, condition.get("filter") or {}, observer=seat, source=source
        )
    if kind == "has_plus1_counter":
        return int(source.metadata.get("plus_counters", 0)) > 0
    if kind == "source_counter_count":
        # "As long as there is exactly one tide counter on this creature, it
        # gets -1/-1." (Homarid; Tidal Influence prints it about a set of
        # creatures instead.) The count is read through the one counter reader
        # `named_counters.counters_on`, which asks `pt.pt_counter_key` — this
        # file's own spelling of the key would answer zero for every counter
        # that also has rules meaning, silently, because a missing key is a
        # legal zero.
        #
        # The comparison is read off the payload rather than assumed, exactly
        # as `handlers/control_flow.evaluate_condition` reads it for the same
        # payload: an at-least test answered as an equality is a bonus that
        # switches off again on the next counter.
        if source is None:
            return False
        held = counters_on(source, str(condition.get("counter", "")))
        wanted = int(condition.get("count", 0))
        if str(condition.get("comparison", "exactly")) == "at_least":
            return held >= wanted
        return held == wanted
    if kind == "cards_in_zones":
        # "…as long as **there are seven or more cards in your graveyard**"
        # (Odyssey's threshold, CR 207.2c — an ability word, so the sentence is
        # the whole rule) and "…as long as there are **no** cards in your
        # graveyard" (Gorilla Titan). The payload is the one
        # ``lowering/conditions`` builds for the same words behind a spell's
        # "if", and it is answered here by the same two functions
        # ``handlers/control_flow.evaluate_condition`` answers it with: the
        # count through ``evaluate_count`` — the recompute's own reader, which
        # needs no resolution — and the printed comparison through
        # ``_compare_count``. So the phrase is one count and one comparison
        # whether it gates a spell's sentence or a permanent's static.
        #
        # "Your" is *seat*: CR 109.5's controller of the ability, which is the
        # Aura's controller for an Aura and whoever controls the creature now
        # for a creature that was stolen. ``graveyard_size`` one branch down is
        # the other printed sentence about a graveyard ("**an opponent has**
        # eight or more cards in **their** graveyard"), whose existential seat
        # this payload cannot say.
        return _compare_count(
            evaluate_count(
                game, game.players[seat], dict(condition.get("count") or {}),
                source=source,
            ),
            str(condition.get("op", "")),
            condition.get("value"),
        )
    if kind == "graveyard_size":
        # "**An** opponent" is any one of them, not all — so it is an `any` over
        # the opponents rather than a sum, and a game with more than two seats
        # answers what the card says.
        wanted = int(condition.get("count", 0))
        if condition.get("who") == "opponent":
            return any(
                len(player.graveyard) >= wanted
                for index, player in enumerate(game.players)
                if index != seat and not player.lost
            )
        return len(game.players[seat].graveyard) >= wanted
    if kind == "controls":
        # The same payload shape ``engine/grammar/lowering/conditions._lower_condition``
        # produces, answered by the same matcher — ``subject_matches`` is the one
        # place a printed noun phrase is tested against a permanent, so "a
        # creature with power 4 or greater" cannot mean one thing on a trigger's
        # intervening-if and another on a continuous ability.
        subject_matches = _late.subject_filters.subject_matches

        described = condition.get("filter") or {}
        who = condition.get("who", "you")
        # **The permanent this clause is a pronoun of.** "…as long as **its**
        # controller controls **another** creature" (Favorable Destiny) says
        # both halves about the creature the static is about — the enchanted
        # one for an Aura, the source itself otherwise — and the lowering
        # stamps ``subject: "attached"`` on exactly the clauses that carry such
        # a pronoun. One pivot for both halves, because they are one referent:
        # answering the seat off the host and "another" off the Aura would
        # count the host as the other creature and hold on a board with just
        # the one.
        pivot = source
        if condition.get("subject") == "attached":
            pivot = attached_host(game, source, last_known=False)
            if pivot is None:
                return False
        # "…as long as **that player** controls three or fewer lands"
        # (Sheltering Prayers): the pronoun is each land the anthem reaches, so
        # the pivot is the permanent being asked about. Asked with no recipient
        # — of the source alone — the clause has no referent, and answering it
        # off the source would read "that player" as the anthem's own
        # controller, which is the one seat the card does not mean.
        if condition.get("subject") == RECIPIENT_SUBJECT:
            pivot = recipient
            if pivot is None:
                return False
        # "…as long as you control **no** nonartifact, nonwhite creatures"
        # (Angelic Voices) — a printed threshold rather than presence. Read as
        # presence it would be its own negation, which is why the lowering
        # refused a counted condition until this branch existed. The bare
        # sentence is "at least one", so an absent comparison is `ge 1` and the
        # two spellings go through one comparator (engine/search_filters.py's,
        # the same table every other counted payload is answered by).
        wanted = condition.get("count")
        op = str(condition.get("op") or "ge")
        if wanted is None:
            wanted, op = 1, "ge"
        pivot_seat: int | None = None
        if who == "you":
            seats = [seat]
        elif who == "controller":
            # CR 109.5's seat read off the *permanent* rather than off the
            # ability: an Aura's controller and its host's controller part
            # company the moment either is stolen, and this clause follows the
            # host. Through the control seam, which is the one answer to who
            # controls a permanent.
            pivot_seat = (
                game.controller_index_of(pivot) if pivot is not None else None
            )
            if pivot_seat is None:
                return False
            seats = [pivot_seat]
        elif who in ("opponent", "each_opponent"):
            seats = [
                index
                for index, player in enumerate(game.players)
                if index != seat and not player.lost
            ]
        else:
            # A payload this cannot evaluate must not be silently answered False
            # from inside a matcher loop that looks like it tried — but an
            # unknown seat word can only arrive from a payload no gate admitted.
            return False
        if condition.get("of_each_color"):
            # "As long as you control a permanent **of each color**, …"
            # (Spirit of Resistance.) A relation over the matching set rather
            # than a count of it, so it is answered before the comparator: the
            # five colours must each be found among the permanents the noun
            # names, a gold one answering for each of its own (CR 105.2b). The
            # lowering admits the key for "you" alone; any other seat word is
            # a payload nobody built, and it answers False rather than pooling
            # several boards into one rainbow.
            if who != "you":
                return False

            return of_each_color(game, (
                perm for perm in game.controlled_by(seat)
                if subject_matches(
                    game, perm, described, observer=seat, source=pivot
                )
            ))
        return _controls_count_holds(
            game, seats, described, int(wanted), op,
            # "**No** opponent controls …" (Kavu Runner) is one statement about
            # every opponent, where "**an** opponent controls …" is about any
            # one of them: the first is a single tally over all their boards,
            # the second an `any` over the seats. With one opponent they are
            # the same number, which is why only a third seat can tell.
            pooled=(who == "each_opponent"),
            observer=(
                seat if who == "you"
                else pivot_seat if who == "controller"
                else None
            ),
            # The pivot, not the raw source: "another" is CR 113.7 measured
            # against the permanent the sentence is about. For every clause
            # that carries no pronoun the two are the same object, so nothing
            # that worked changes.
            source=pivot,
        )
    return False


def _controls_count_holds(
    game, seats, described: dict, wanted: int, op: str, *, observer, source,
    pooled: bool = False,
) -> bool:
    """Whether **any one** of *seats* controls a matching count satisfying *op*.

    An `any` over the seats rather than a sum, because that is the article the
    cards print: "as long as **an** opponent controls a nontoken red permanent"
    (Ivory Guardians) is one opponent's board, and a game with more than two
    seats answers what the card says. With a single seat in the list — the "you"
    reading — the `any` is that seat's own answer.

    *observer* is passed only for the controller's own board: a relative key
    ("another", "you control") is a question about a seat, and the opponent
    iteration already scopes by controller, so the lowering refused any relative
    key an observer would be for on that side.
    """
    from .search_filters import _COMPARE
    from .subject_filters import subject_matches

    compare = _COMPARE.get(op)
    if compare is None:
        # An unreadable comparison must not fall through to "0 matches", which
        # for a "no such permanent" clause is the condition always holding.
        return False
    tallies = [
        sum(
            1
            for perm in game.controlled_by(index)
            if subject_matches(
                game, perm, described, observer=observer, source=source
            )
        )
        for index in seats
    ]
    if pooled:
        # *pooled* is the ``each_opponent`` seat: one total across every seat
        # in the list, compared once. The lowering admits it only with a
        # printed zero, where the total and each seat's own count agree.
        return compare(sum(tallies), wanted)
    return any(compare(found, wanted) for found in tallies)


def singular_land_type(word: str) -> str:
    """The land subtype *word* names, however it was pluralised.

    Four of the five basic types pluralise with a trailing "s"; Plains is
    spelled identically singular and plural, so stripping one unconditionally
    produces "plain" — a subtype no land has. Checking the known types first
    means the shape of the word never has to be guessed.
    """
    lowered = word.strip().lower()
    if lowered in BASIC_LAND_WORDS:
        return lowered
    trimmed = lowered.rstrip("s")
    return trimmed if trimmed in BASIC_LAND_WORDS else lowered
