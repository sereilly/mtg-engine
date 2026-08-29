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

from .oracle_types import _NUMBER_WORDS

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

    Takes an already-normalized line (``oracle.normalize_creature_line``).
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
# meaning in the engine (``handlers/_common.permanent_matches_filter``'s ``power``
# comparison) rather than a second regex that happens to agree today.
_CONTROLS_POWER_CONDITION = re.compile(
    r"^you control a creature with power (?P<power>\d+) or greater$"
)

# "as long as an opponent has eight or more cards in their graveyard"
# (Thieves' Guild Recruiter cycle). A zone *size*, not a set of objects: nothing
# is matched, so it is its own condition kind rather than a `controls` payload
# with a graveyard filter — and the seat it asks about is printed, because "an
# opponent" and "you" are different questions with different answers.
_GRAVEYARD_SIZE_CONDITION = re.compile(
    r"^(?P<who>an opponent|you) ha(?:s|ve) (?P<count>\w+) or more cards in "
    r"(?:their|your) graveyard$"
)

_EFFECT_PT = re.compile(
    r"^gets \+(?P<power>\d+)/\+(?P<toughness>\d+)(?: and has (?P<keywords>[a-z ]+))?$"
)
_EFFECT_KEYWORDS = re.compile(r"^has (?P<keywords>[a-z ]+)$")
_EFFECT_UNBLOCKABLE = re.compile(r"^can't be blocked$")
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
_CONTROLS_NOUN_CONDITION = re.compile(r"^you control (?P<phrase>.+)$")


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
    from .grammar.errors import GrammarError
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .grammar.lexer import tokenize
    from .subject_filters import untestable_filter_keys

    # The article is the quantifier, and it is what the printed clause means:
    # "you control **a** snow land" is a presence test, which is the default the
    # consumer applies when no count rides the payload. Anything else — "two or
    # more", "no" — is a threshold this branch does not read and must not
    # silently answer as presence, so only the articles are stripped.
    phrase = match.group("phrase")
    article, _, rest = phrase.partition(" ")
    if article not in ("a", "an") or not rest:
        return None
    stream = TokenStream(tokenize(rest).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return {"kind": "controls", "who": "you", "filter": payload}


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
    match = _EFFECT_KEYWORDS.match(text)
    if match is not None:
        keywords = _keyword_list(match.group("keywords"))
        if keywords is None:
            return None
        return {"keywords": keywords}
    if _EFFECT_UNBLOCKABLE.match(text) is not None:
        return {"cant_be_blocked": True}
    if _EFFECT_IGNORES_DEFENDER.match(text) is not None:
        return {"ignores_defender": True}
    return None


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
        # "As long as <condition>, this creature <effect>" (Gnarled Sage).
        rest = line[len("as long as "):]
        condition_text, separator, effect_clause = rest.partition(", ")
        if not separator or not effect_clause.startswith(subject):
            return None
        effect_text = effect_clause[len(subject):]
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
    effect = _parse_effect_text(effect_text)
    if condition is None or effect is None:
        return None
    return StaticBonus("conditional_static", {**effect, "condition": condition})


def conditional_static_holds(game, seat: int, source, condition: dict) -> bool:
    """Whether a ``conditional_static`` payload's condition holds right now.

    Beside the table that produces the payloads so the vocabulary has one
    definition; *game* and *source* are duck-typed (the control seam and the
    permanent's own state are all it reads).
    """
    kind = condition.get("kind")
    # "**During your turn**" (Radha). Whose turn it is, which is a fact about
    # the game rather than about the permanent — and the seat asked is the
    # ability's controller (CR 109.5), not the permanent's owner.
    if kind == "your_turn":
        return game.active_player_index == seat
    if kind == "drawn_cards_this_turn":
        player = game.players[seat]
        return len(player.cards_drawn_this_turn) >= int(condition.get("count", 0))
    if kind == "controls_planeswalker":
        subtype = condition.get("subtype")
        return any(
            perm.has_type("planeswalker") and perm.has_type(subtype)
            for perm in game.controlled_by(seat)
        )
    if kind == "attached_matches":
        # "As long as enchanted land is a basic Mountain, …" (Goblin Caves,
        # Goblin Shrine.) The question is about the permanent the source is
        # attached to, and it is asked through ``subject_matches`` — the one
        # reader of what a printed noun phrase means — so the layers answer it:
        # a land Conversion has turned into a Plains stops being a Mountain and
        # the anthem switches off with nothing to undo, and a nonbasic land
        # Blood Moon has made a Mountain is still not a *basic* one.
        from .handlers._common import attached_host
        from .subject_filters import subject_matches

        host = attached_host(game, source)
        if host is None:
            return False
        return subject_matches(
            game, host, condition.get("filter") or {}, observer=seat, source=source
        )
    if kind == "has_plus1_counter":
        return int(source.metadata.get("plus_counters", 0)) > 0
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
        # The same payload shape ``engine/grammar/lower._lower_condition``
        # produces, answered by the same matcher — ``subject_matches`` is the one
        # place a printed noun phrase is tested against a permanent, so "a
        # creature with power 4 or greater" cannot mean one thing on a trigger's
        # intervening-if and another on a continuous ability.
        from .subject_filters import subject_matches

        described = condition.get("filter") or {}
        who = condition.get("who", "you")
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
        if who == "you":
            seats = [seat]
        elif who == "opponent":
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
        return _controls_count_holds(
            game, seats, described, int(wanted), op,
            observer=seat if who == "you" else None, source=source,
        )
    return False


def _controls_count_holds(
    game, seats, described: dict, wanted: int, op: str, *, observer, source
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
    for index in seats:
        found = sum(
            1
            for perm in game.controlled_by(index)
            if subject_matches(
                game, perm, described, observer=observer, source=source
            )
        )
        if compare(found, wanted):
            return True
    return False


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
