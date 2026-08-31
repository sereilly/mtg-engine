"""What the X of a **cost** is, when the card defines it instead of the player.

CR 601.2b: the activating player announces the value of X. A handful of cards
take that choice away by printing a definition instead -- Voodoo Doll's

    {X}{X}, {T}: This artifact deals damage equal to the number of pin counters
    on it to any target. **X is the number of pin counters on this artifact.**

-- so the cost is not a number the player picks but one the board decides.

This is the twin of ``engine/activation_restrictions.py`` and it is a table for
the same reason: the sentence reads the same on any card that prints it, so the
counter's kind and the noun are payload. It is genuinely textual, not per-card.

**Both readers read this table.** The grammar consumes the sentence
(``_parse_cost_x_definition``, beside the "Activate only ..." reader it copies)
and refuses a definition no row here implements, so a card cannot be admitted
with the clause dropped; the activation path charges the cost from the same
table. A definition consumed by one and unknown to the other is an ability whose
{X}{X} costs whatever the activator felt like announcing -- nothing, most of the
time -- which is the quiet failure this file exists to prevent.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent


def _counters_on_source(
    game: "Game", source: "Permanent", match: re.Match, target=None
) -> int | None:
    from .named_counters import counters_on

    return max(0, counters_on(source, match.group(1)))


def _twice_target_spell_mana_value(
    game: "Game", source: "Permanent", match: re.Match, target=None
) -> int | None:
    """"X is twice the mana value of that spell." (Reflecting Mirror.)

    "That spell" is the one the ability **targets**, so the number is not on the
    board at all: it is on the stack, and only the activation knows which object
    was named. That is why every reader here takes the chosen stack object
    beside the source — a definition that could only see the permanent would
    have to answer 0, which for a cost is the difference between an ability that
    prices itself off its victim and a free one.

    ``None`` when no spell was named, and ``None`` is refused by the activation
    rather than treated as zero (CR 107.2 is about a number that *can't* be
    determined; here the ability simply has not chosen its target yet).

    The mana value is read through ``targeting.stack_object_mana_value``, so an
    {X} spell on the stack is priced at what its controller announced
    (CR 202.3b) rather than at the 0 its printed cost carries.
    """
    if target is None:
        return None
    from .targeting import stack_object_mana_value

    return 2 * stack_object_mana_value(target)


#: ``(pattern, reader)``. The pattern matches the whole sentence, lowercased and
#: stripped of its full stop; the reader turns the ability's own source into the
#: number. One row today, and the noun it ends on is any permanent word, because
#: which type the card happens to be is not part of the question.
COST_X_DEFINITIONS: tuple[tuple[re.Pattern[str], Callable[..., int]], ...] = (
    (
        # The noun a card calls itself by. An Aura is an enchantment and an
        # Equipment an artifact (CR 205.3), but the printed word is the subtype
        # — Chromatic Armor says "on this **Aura**" and reached nothing at all
        # while this alternation listed only the card types, which is the same
        # one-word gap `enter_effects.chooses_color_on_enter` had.
        re.compile(
            r"^x is the number of ([a-z]+) counters on this "
            r"(?:artifact|aura|creature|enchantment|equipment|land|permanent)$"
        ),
        _counters_on_source,
    ),
    (
        re.compile(r"^x is twice the mana value of that spell$"),
        _twice_target_spell_mana_value,
    ),
)


# ---------------------------------------------------------------------------
# The cast half (CR 601.2b / CR 107.3c)
# ---------------------------------------------------------------------------
#
# The same rule about a spell rather than an activated ability. It is a second
# table rather than a second row, because the two readers are handed different
# things: an ability's definition is answered from its *source permanent* and a
# spell's from its *caster* — a spell on the stack has no permanent at all, and
# giving the rows above an optional source would let a definition that needs one
# be matched by a caller that has none, and answer from nothing.


def _opponent_graveyard_count(game, caster_index: int, match: re.Match) -> int | None:
    """"X is the number of artifact and/or creature cards in **an opponent's**
    graveyard as you cast this spell." (Spoils of War.)

    "An opponent's" is a choice the caster makes as the spell is cast, and this
    engine has no channel for one: the cast wire names targets, not the
    non-target choices of CR 601.2b. With a single opponent there is nothing to
    choose and the answer is theirs; with several, ``None`` refuses the cast
    rather than picking a graveyard for the caster — an engine that quietly
    chose the largest would be playing a better card than the one printed, and
    one that chose the first would be playing a worse one.
    """
    wanted = tuple(word.strip() for word in match.group(1).split(" and/or "))
    opponents = [
        player for seat, player in enumerate(game.players) if seat != caster_index
    ]
    if len(opponents) != 1:
        return None
    return sum(
        1
        for card in opponents[0].graveyard
        if any(kind in (card.type_line or "").lower() for kind in wanted)
    )


#: ``(pattern, reader)`` for a **spell's** X, read off the card's own line. The
#: reader takes ``(game, caster seat, match)``.
CAST_X_DEFINITIONS: tuple[tuple[re.Pattern[str], Callable[..., int | None]], ...] = (
    (
        re.compile(
            r"^x is the number of ([a-z]+(?: and/or [a-z]+)*) cards? in an "
            r"opponent's graveyard as you cast this spell$"
        ),
        _opponent_graveyard_count,
    ),
)


def cast_x_definition_line(line: str) -> bool:
    """Whether one printed *line* is a cast-time X definition this file reads.

    The grammar's claim and the support gate's, so a definition nothing computes
    leaves the card unsupported rather than admitted with the caster free to
    announce X — which on a spell whose X is its whole effect is any number they
    like.
    """
    return _match_cast(line) is not None


def defines_cast_x(oracle_text: str) -> bool:
    """Whether any line of *oracle_text* defines the spell's X (CR 107.3c).

    Separate from :func:`cast_x_value` for :func:`cost_x_is_defined`'s reason,
    one table up: "the card defines no X" and "it defines one this cast cannot
    compute" are different answers, and folding them into one ``None`` makes the
    second look like the first — which on an {X} spell hands the caster the
    choice the card took away.
    """
    return any(_match_cast(line) is not None for line in (oracle_text or "").splitlines())


def cast_x_value(game, caster_index: int, oracle_text: str) -> int | None:
    """The X a spell's own text defines, or None.

    ``None`` covers both "the card defines no X" and "it defines one this cast
    cannot compute", and the caller tells them apart with
    :func:`cast_x_definition_line` — the same split :func:`cost_x_is_defined`
    makes one table up, and for the same reason: folding them together makes the
    uncomputable case look like the ordinary one, which on an {X} spell means
    the caster picks.
    """
    for line in (oracle_text or "").splitlines():
        matched = _match_cast(line)
        if matched is not None:
            pattern_match, reader = matched
            return reader(game, caster_index, pattern_match)
    return None


def _match_cast(line: str) -> tuple[re.Match, Callable[..., int | None]] | None:
    cleaned = " ".join(line.lower().split()).strip(" .")
    if not cleaned.startswith("x is "):
        return None
    for pattern, reader in CAST_X_DEFINITIONS:
        found = pattern.match(cleaned)
        if found is not None:
            return found, reader
    return None


# ---------------------------------------------------------------------------
# The cast **ceiling** (CR 601.2b)
# ---------------------------------------------------------------------------
#
# A third table, and the third question. ``COST_X_DEFINITIONS`` and
# ``CAST_X_DEFINITIONS`` both *take the announcement away* -- the card says what
# X is and the player never picks. A ceiling does not: "X can't be greater than
# the number of snow lands you control" (Winter's Chill) leaves CR 601.2b's
# announcement exactly where it was and puts a **bound** on it. Folding the two
# would be the difference between a spell whose X is fixed at the board's number
# and one the caster may still cast for less, which on Winter's Chill is every
# cast of it.
#
# The bound is enforced at the announcement, before any cost is paid, and it is
# reported to the picker so the browser never offers an illegal number. A clause
# parsed and dropped is a spell cast for more X than the board allows -- silent,
# and in the caster's favour, which is the direction this file exists to stop.

_X_CEILING_RE = re.compile(r"^x can't be greater than the number of (?P<board>.+)$")


@lru_cache(maxsize=None)
def cast_x_ceiling_line(line: str) -> "tuple[dict, str] | None":
    """"X can't be greater than the number of snow lands you control."
    (Winter's Chill.)

    Returns ``(filter payload, the printed noun phrase)``, or None when the line
    is not this bound or names a board the matcher cannot test.

    The noun phrase goes through **the grammar's noun parser**, exactly as
    ``cast_restrictions.cast_condition_line`` does one file over and for that
    function's reason: ``subject_matches`` is what counts the board at every
    cast, and a second reader of "snow lands you control" would be free to
    disagree with it about what one is. A phrase carrying a key
    ``subject_matches`` cannot test is refused rather than approximated -- a
    dropped narrowing here *raises* the ceiling, which is the direction that
    hands the caster a bigger spell than the card prints.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    match = _X_CEILING_RE.match(" ".join(line.lower().split()).strip(" ."))
    if match is None:
        return None
    board = match.group("board")
    stream = TokenStream(tokenize(board).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload, board


def caps_cast_x(oracle_text: str) -> bool:
    """Whether any line of *oracle_text* bounds the X the caster may announce.

    The gate's half of the question, split from :func:`cast_x_ceiling` for
    :func:`defines_cast_x`'s reason: "this card prints no bound" and "it prints
    one this cast cannot count" are different answers, and only the first of
    them means the caster may announce whatever they like.
    """
    return any(
        cast_x_ceiling_line(line) is not None
        for line in (oracle_text or "").splitlines()
    )


def cast_x_ceiling(game, caster_index: int, oracle_text: str) -> "tuple[int, str] | None":
    """The largest X *caster_index* may announce for this card, with the printed
    noun phrase that bounds it -- or None when the card prints no bound.

    CR 109.5's observer is the casting seat, so a "you" inside the noun phrase
    means the same player the announcement does. Counted over the whole board
    rather than over the caster's own permanents, because the seat is the
    phrase's to state: a bound naming what an *opponent* controls is the same
    sentence and must not be silently re-seated.
    """
    from .subject_filters import subject_matches

    for line in (oracle_text or "").splitlines():
        read = cast_x_ceiling_line(line)
        if read is None:
            continue
        payload, board = read
        return sum(
            1
            for perm in game.all_permanents()
            if subject_matches(game, perm, payload, observer=caster_index)
        ), board
    return None


def cost_x_definition_readable(sentence: str) -> bool:
    """Whether a row implements this printed "X is ..." sentence.

    The grammar's gate. A sentence nothing implements leaves the line refused,
    so the card reports unsupported naming the clause rather than being admitted
    with an X nobody computes.
    """
    return _match(sentence) is not None


def cost_x_is_defined(ability_line: str) -> bool:
    """Whether the ability's own text defines X (CR 107.3c).

    Separate from :func:`cost_x_value` because the two answers are different
    questions and the activation needs both: a card that defines X and whose
    definition cannot be computed *here* must refuse, where a card that defines
    no X lets its activator announce one. Folding them into one ``None`` made
    the uncomputable case look exactly like the ordinary one — which on an {X}
    ability means free.
    """
    return any(_match(sentence) is not None for sentence in (ability_line or "").split("."))


def cost_x_value(
    game: "Game", source: "Permanent", ability_line: str, *, target=None
) -> int | None:
    """The X the ability's cost uses, or None when there is no number to give.

    ``None`` is not zero, and it now covers two cases the caller has to tell
    apart with :func:`cost_x_is_defined`: the card defines no X at all (the
    player announces it, CR 601.2b — every ability in the pool but these), or it
    defines one that this activation cannot compute.

    *target* is the object the ability targeted, for a definition that reads
    something other than the source ("twice the mana value of **that spell**").
    """
    for sentence in (ability_line or "").split("."):
        matched = _match(sentence)
        if matched is not None:
            pattern_match, reader = matched
            return reader(game, source, pattern_match, target)
    return None


def _match(sentence: str) -> tuple[re.Match, Callable[..., int]] | None:
    cleaned = " ".join(sentence.lower().split()).strip(" .")
    if not cleaned.startswith("x is "):
        return None
    for pattern, reader in COST_X_DEFINITIONS:
        found = pattern.match(cleaned)
        if found is not None:
            return found, reader
    return None


__all__ = [
    "CAST_X_DEFINITIONS",
    "COST_X_DEFINITIONS",
    "caps_cast_x",
    "cast_x_ceiling",
    "cast_x_ceiling_line",
    "cast_x_definition_line",
    "defines_cast_x",
    "cast_x_value",
    "cost_x_definition_readable",
    "cost_x_is_defined",
    "cost_x_value",
]
