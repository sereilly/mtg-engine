"""The game and its players: tokens, life, turns, and outcomes.

Token creation, life gain and loss, extra turns, and the three CR 104 outcomes.

Grouped as "the game" rather than "the board", the same way the lowering side
groups it: none of these changes what a permanent is, and all of them change the
state a player or the game is in. `DrawGame` carries no player because CR 104.4
is a third outcome, not a win with an asterisk.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import (
    Amount,
    PlayerRef,
)


@dataclass(frozen=True)
class GainLife:
    player: PlayerRef
    amount: Amount


@dataclass(frozen=True)
class LoseLife:
    player: PlayerRef
    amount: Amount


@dataclass(frozen=True)
class CreateToken:
    count: Amount
    power: int
    toughness: int
    name: str
    colors: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtraTurn:
    player: PlayerRef


@dataclass(frozen=True)
class WinGame:
    """"You win the game." (CR 104.2b.)"""
    player: PlayerRef


@dataclass(frozen=True)
class LoseGame:
    """"Target player loses the game." / "You lose the game." (CR 104.3e.)"""
    player: PlayerRef


@dataclass(frozen=True)
class DrawGame:
    """"The game is a draw." (CR 104.4c.)

    No player field: the sentence has no subject, and the effect ends the game
    for everyone. Its own node rather than a ``WinGame`` with a flag, because
    104.4 is a third outcome and not a win with an asterisk.
    """
