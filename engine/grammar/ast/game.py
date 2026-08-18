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
    # "…for each creature you control with flying" (Aven Gagglemaster) — a
    # battlefield-count multiplier, mirroring LoseLife's graveyard one.
    per_each: object | None = None


@dataclass(frozen=True)
class LoseLife:
    player: PlayerRef
    amount: Amount
    # "…for each creature card in their graveyard" (Liliana, Death Mage) — the
    # amount is multiplied by a count of matching objects. None for the plain
    # sentence; the field is additive (this AST is append-only).
    per_each: object | None = None
    # "Each opponent who can't loses 3 life." (Liliana, Waker of the Dead) —
    # this loss applies only to opponents who could not perform the named
    # action of the preceding step ("discard"). Attached by the rider fold in
    # the sentence loop, never parsed on its own.
    who_could_not: str | None = None


@dataclass(frozen=True)
class CreateToken:
    count: Amount
    # None for a **noncreature** token (a Treasure): CR 208.1 gives P/T only to
    # creatures, and 0/0 is a different answer that would die to state-based
    # actions the moment anything animated it.
    power: int | None
    toughness: int | None
    name: str
    colors: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    # "…that are tapped and attacking" (Basri Ket) — the tokens' entry state.
    tapped: bool = False
    attacking: bool = False
    # "**Its controller** creates a 4/4 white Angel creature token." (Angelic
    # Ascension, Secure the Scene) — the token goes to the exiled permanent's
    # controller, read back from the exile step of the same resolution. None
    # means the effect's own controller, which every earlier token card is.
    recipient: str | None = None
    # "…**for each nontoken creature that died this turn**" (Gadrak). A
    # multiplier over a history, exactly as on a counter placement or a life
    # gain — the set counted is the one no battlefield still holds.
    per_death: object | None = None
    # The printed text a *predefined* token carries (CR 111.10). Transcribed
    # from `engine/tokens.py`'s table at parse time rather than left for the
    # handler to look up again, so the AST says everything the token is.
    oracle_text: str | None = None


@dataclass(frozen=True)
class CreateEmblem:
    """"You get an emblem with "<ability>"." (CR 114.2, the planeswalker
    ultimates.) The quoted ability rides as raw text: an emblem's ability is
    compiled when it fires, through the same compiler every card goes through,
    and the support gate in engine/oracle.py refuses the walker when that text
    cannot be read — so the string here is never a silent promise."""
    text: str


@dataclass(frozen=True)
class FlipCoin:
    """"Flip a coin." (CR 705.1.)

    The flip and nothing else. Its consequences are the ordinary conditional
    sentences that follow it, because how many there are is a property of the
    card and not of the flip: Tavern Swindler reads only the win, Mijae Djinn
    only the loss, Bottle of Suleiman both.
    """


@dataclass(frozen=True)
class ExtraTurn:
    player: PlayerRef
    # "Take two extra turns after this one." (Teferi, Master of Time.)
    count: int = 1


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
