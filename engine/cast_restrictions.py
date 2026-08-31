"""Text-keyed casting restrictions ("Cast this spell only ...", CR 601.3).

These are genuinely textual (not name-keyed): the restriction is the same for
any card printed with the phrase, so a data table keyed by canonical phrase —
not a per-card hook — is the right extension point. cast_from_hand loops this
table once; a new timing-restricted card is one entry.

Two families, because two things can finish the sentence. Most of the pool
names a **moment** ("only during your declare attackers step"), which is a
whole phrase and a predicate over the turn structure. Blizzard names a
**board** instead — "Cast this spell only if you control a snow land" — and
there the noun phrase is payload: a card printed about an artifact, a creature
with flying or an opponent's Island is this restriction with one phrase
changed, so the phrase is read by the grammar's own noun parser and answered by
``subject_matches``, exactly as `activation_restrictions._controlled_board_phrase`
reads the identical clause after "Activate only if you control".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game

# (game, caster_index) -> True if casting is currently legal.
TimingPredicate = Callable[["Game", int], bool]


@dataclass(frozen=True)
class CastRestriction:
    phrase: str                # canonical lowercase oracle-text phrase
    is_legal: TimingPredicate
    denial_message: str


def _during_own_declare_attackers(game: "Game", caster_index: int) -> bool:
    return game.current_step == "declare_attackers" and game.active_player_index == caster_index


def _during_declare_attackers(game: "Game", caster_index: int) -> bool:
    # Teleport: "the declare attackers step", not "your" — whoever is the
    # active player, the window is that step. The seat is deliberately not
    # consulted; the sibling above reads it because its own line says "your".
    return game.current_step == "declare_attackers"


def _before_blockers_are_declared(game: "Game", caster_index: int) -> bool:
    # Rapid Fire: no phase floor at all — anything earlier in the turn than the
    # declare blockers step qualifies, so the test is that the turn has not
    # reached it. (`_during_combat_before_blockers` is the *narrower* sibling:
    # its line says "during combat before blockers are declared", which adds a
    # combat-phase floor this one does not have.)
    past_blockers = (
        game.current_turn_phase in ("postcombat_main", "ending")
        or (
            game.current_turn_phase == "combat"
            and game.current_step in ("declare_blockers", "combat_damage", "end_of_combat")
        )
    )
    return not past_blockers


def _after_combat(game: "Game", caster_index: int) -> bool:
    # Glyph of Reincarnation: after the combat *phase* has ended, so the
    # postcombat main phase and the ending phase. The end of combat step is
    # still combat.
    return game.current_turn_phase in ("postcombat_main", "ending")


def _during_declare_blockers(game: "Game", caster_index: int) -> bool:
    return game.current_turn_phase == "combat" and game.current_step == "declare_blockers"


def _during_combat_before_blockers(game: "Game", caster_index: int) -> bool:
    # Blaze of Glory: legal during beginning-of-combat and declare-attackers
    # (attackers may still be declared / blockers not yet declared).
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
    )


def _own_combat_before_blockers(game: "Game", caster_index: int) -> bool:
    # Melee: the window `_during_combat_before_blockers` names, plus the seat
    # its line prints and that one's does not ("during combat **on your turn**
    # before blockers are declared"). The same pairing `_during_own_declare_attackers`
    # and `_during_declare_attackers` already are a few rows up: one clause says
    # whose turn and the other deliberately does not, so the seat is read in one
    # and never consulted in the other.
    return (
        game.active_player_index == caster_index
        and _during_combat_before_blockers(game, caster_index)
    )


def _before_combat_damage_step(game: "Game", caster_index: int) -> bool:
    # Berserk: illegal once the turn has reached the combat damage step —
    # during it, after it (end of combat, postcombat main), or in the ending phase.
    past_combat_damage = (
        game.current_turn_phase in ("postcombat_main", "ending")
        or (
            game.current_turn_phase == "combat"
            and game.current_step in ("combat_damage", "end_of_combat")
        )
    )
    return not past_combat_damage


def _opponents_turn_before_attackers(game: "Game", caster_index: int) -> bool:
    if game.active_player_index == caster_index:
        return False
    if game.current_turn_phase == "combat":
        return (
            game.current_step in ("beginning_of_combat", "declare_attackers")
            and not game.combat_attackers_locked
        )
    return game.current_turn_phase in ("beginning", "precombat_main")


def _opponents_turn_after_upkeep(game: "Game", caster_index: int) -> bool:
    # Reset: legal only during an opponent's turn, and only once that player's
    # upkeep step has ended — "after their upkeep step" excludes the upkeep
    # itself, so the window opens at their draw step. A skipped upkeep still
    # opens it: what is tested is that the turn has moved past the beginning
    # phase's untap/upkeep steps, not that an upkeep happened.
    if game.active_player_index == caster_index:
        return False
    return not (
        game.current_turn_phase == "beginning"
        and game.current_step in ("untap", "upkeep")
    )


def _during_an_opponents_upkeep(game: "Game", caster_index: int) -> bool:
    # Festival: legal only while an opponent's upkeep step is the current step.
    # Both halves are asked — the seat *and* the step — because either alone is
    # a window the card does not print: "an opponent's turn" is most of the
    # turn, and "the upkeep step" would let a player cast it in their own.
    if game.active_player_index == caster_index:
        return False
    return game.current_turn_phase == "beginning" and game.current_step == "upkeep"


CAST_RESTRICTIONS: tuple[CastRestriction, ...] = (
    CastRestriction(
        "cast this spell only during an opponent's upkeep",
        _during_an_opponents_upkeep,
        "can only be cast during an opponent's upkeep",
    ),
    CastRestriction(
        "cast this spell only during your declare attackers step",
        _during_own_declare_attackers,
        "can only be cast during your declare attackers step",
    ),
    CastRestriction(
        "cast this spell only during the declare attackers step",
        _during_declare_attackers,
        "can only be cast during the declare attackers step",
    ),
    CastRestriction(
        "cast this spell only before blockers are declared",
        _before_blockers_are_declared,
        "can only be cast before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only after combat",
        _after_combat,
        "can only be cast after combat",
    ),
    CastRestriction(
        "cast this spell only during the declare blockers step",
        _during_declare_blockers,
        "can only be cast during the declare blockers step",
    ),
    CastRestriction(
        "cast this spell only during combat before blockers are declared",
        _during_combat_before_blockers,
        "can only be cast during combat before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only during combat on your turn before blockers are declared",
        _own_combat_before_blockers,
        "can only be cast during combat on your turn before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only before the combat damage step",
        _before_combat_damage_step,
        "can only be cast before the combat damage step",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn, before attackers are declared",
        _opponents_turn_before_attackers,
        "can only be cast during an opponent's turn, before attackers are declared",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn after their upkeep step",
        _opponents_turn_after_upkeep,
        "can only be cast during an opponent's turn after their upkeep step",
    ),
)


# ---------------------------------------------------------------------------
# The board condition: "Cast this spell only if you control <noun phrase>"
# ---------------------------------------------------------------------------

#: Anchored at both ends against one printed line. The noun phrase is
#: everything after "you control", read below rather than enumerated here — the
#: whole reason this is one row and not one row per printable board.
_CONTROLS_RE = re.compile(
    r"^cast this spell only if you control (?P<board>.+)$"
)


@lru_cache(maxsize=None)
def cast_condition_line(line: str) -> "tuple[dict, str] | None":
    """"Cast this spell only if you control a snow land." (Blizzard.)

    Returns ``(filter payload, the printed noun phrase)``, or None when the
    line is not this restriction or names a board the matcher cannot test.

    The noun phrase goes through **the grammar's noun parser**, because
    ``subject_matches`` is what answers it at every cast and a second reader of
    "a snow land" would be free to disagree with it about what one is. A phrase
    carrying a key ``subject_matches`` cannot test is refused rather than
    approximated: a dropped restriction here is a spell castable on a board the
    card forbids, which is the direction this table exists to prevent.

    "**a**" and nothing else. "no snow lands" and "two or more" are different
    conditions — a negation and a threshold — and reading either as presence is
    a restriction lifted on a board the card does not name.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    match = _CONTROLS_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    board = match.group("board")
    article, _, rest = board.partition(" ")
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
    return payload, board


def _condition_holds(game: "Game", caster_index: int, payload: dict) -> bool:
    """Whether *caster_index* controls a permanent the phrase names.

    CR 109.5's observer is the casting seat, so a "you" inside the noun phrase
    means the same player the outer "you control" does.
    """
    from .subject_filters import subject_matches

    return any(
        subject_matches(game, perm, payload, observer=caster_index)
        for perm in game.controlled_by(caster_index)
    )


def check_cast_timing(game: "Game", caster_index: int, oracle_text_lower: str) -> str | None:
    """The denial message for the first violated casting restriction present in
    *oracle_text_lower*, or None if every restriction present is satisfied."""
    for restriction in CAST_RESTRICTIONS:
        if restriction.phrase in oracle_text_lower and not restriction.is_legal(game, caster_index):
            return restriction.denial_message
    # Per line rather than by substring: the board condition ends at the end of
    # its sentence, and a phrase read out of the middle of a longer one would
    # be a restriction the card does not print.
    for line in oracle_text_lower.split("\n"):
        read = cast_condition_line(line)
        if read is None:
            continue
        payload, board = read
        if not _condition_holds(game, caster_index, payload):
            return f"can only be cast if you control {board}"
    return None
