"""Text-keyed cast-timing restrictions ("Cast this spell only during...").

These are genuinely textual (not name-keyed): the restriction is the same for
any card printed with the phrase, so a data table keyed by canonical phrase —
not a per-card hook — is the right extension point. cast_from_hand loops this
table once; a new timing-restricted card is one entry.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def _during_declare_blockers(game: "Game", caster_index: int) -> bool:
    return game.current_turn_phase == "combat" and game.current_step == "declare_blockers"


def _during_combat_before_blockers(game: "Game", caster_index: int) -> bool:
    # Blaze of Glory: legal during beginning-of-combat and declare-attackers
    # (attackers may still be declared / blockers not yet declared).
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
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


CAST_RESTRICTIONS: tuple[CastRestriction, ...] = (
    CastRestriction(
        "cast this spell only during your declare attackers step",
        _during_own_declare_attackers,
        "can only be cast during your declare attackers step",
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
        "cast this spell only before the combat damage step",
        _before_combat_damage_step,
        "can only be cast before the combat damage step",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn, before attackers are declared",
        _opponents_turn_before_attackers,
        "can only be cast during an opponent's turn, before attackers are declared",
    ),
)


def check_cast_timing(game: "Game", caster_index: int, oracle_text_lower: str) -> str | None:
    """The denial message for the first violated timing restriction present in
    *oracle_text_lower*, or None if every restriction present is satisfied."""
    for restriction in CAST_RESTRICTIONS:
        if restriction.phrase in oracle_text_lower and not restriction.is_legal(game, caster_index):
            return restriction.denial_message
    return None
