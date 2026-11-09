"""Printed prohibitions on losing and on winning the game (CR 104.3, CR 104.2b).

"You can't lose the game and your opponents can't win the game." (Platinum
Angel.) A continuous effect from a static ability (CR 611.3) that takes an
outcome away rather than replacing it: the player at 0 life, with ten poison
counters, who drew from an empty library or whom an effect says loses the game,
simply keeps playing (the 2009-10-01 ruling lists all of them), and an
opponent's "you win the game" does nothing.

What it does **not** reach, and why each is outside the one funnel this module
answers for:

- a concession (CR 104.3a; the Angel's 2004-12-01 ruling: "A concession causes
  you to leave the game, which then causes you to lose the game") —
  ``Game.concede`` never asks;
- a draw (CR 104.4; the same ruling: "Effects that say the game is a draw …
  are not affected by Platinum Angel");
- CR 104.2a, a player whose opponents have all left, which "happens
  immediately and overrides all effects that would preclude that player from
  winning the game" — ``Game.get_winner`` never asks.

**Every loss the engine performs goes through ``Game.lose_the_game``**, which
asks :func:`player_cant_lose`, and every "wins the game" effect asks
:func:`player_cant_win` before anybody loses to it. The ban is derived from the
board on every ask rather than stamped on a seat, which is what makes it lift
the instant the Angel leaves (CR 611.3b): a player still at 0 life loses at the
very next state-based check, with no sweep to remember.

The two halves are here together for the reason every text-keyed table in this
engine gives — **what the grammar may admit and what the engine carries out are
one list**: the seam that enforces a ban, the support gate that decides whether
the card is implemented (``derived_static_claims``), the grammar's registry and
the parse-coverage report all ask :func:`game_result_ban_line`. The sentence is
anchored whole, so a line that says more than this is a rule nothing here
carries out and stays unclaimed.
"""

from __future__ import annotations

import re

#: Which seats a printed subject names, relative to the permanent's controller
#: (CR 109.5's "you"). Scope names, not seat numbers: who "you" is depends on
#: who controls the permanent, which is the board scan's question.
_SCOPES: dict[str, str] = {
    "you": "you",
    "your opponents": "opponents",
    "players": "each_player",
    "each player": "each_player",
}

#: The two outcomes a ban takes away.
LOSE = "lose"
WIN = "win"

_CLAUSE = re.compile(
    rf"^(?P<subject>{'|'.join(_SCOPES)}) can't (?P<outcome>lose|win) the game$"
)


def game_result_ban_line(line: str) -> tuple[tuple[str, str], ...] | None:
    """The ``(outcome, scope)`` pairs *line* bans, or None when it is not
    wholly a ban.

    "You can't lose the game and your opponents can't win the game." is two
    clauses joined by "and", each of which must read as a ban — so a line
    joining a ban to anything else returns None rather than half of itself.
    """
    text = " ".join((line or "").strip().lower().rstrip(".").split())
    text = text.replace("’", "'")
    if not text:
        return None
    bans: list[tuple[str, str]] = []
    for clause in text.split(" and "):
        match = _CLAUSE.match(clause.strip())
        if match is None:
            return None
        bans.append((match.group("outcome"), _SCOPES[match.group("subject")]))
    return tuple(bans)


def _banning_sources(game, seat: int, outcome: str) -> list:
    """Every permanent whose printed ban takes *outcome* away from *seat*.

    The **effective** card (CR 707.2, CR 612.1), so a copy of the Angel bans
    too and a text change that rewrote the sentence stops being read; the
    control seam, so a stolen Angel protects the thief.
    """
    found = []
    for controller, permanent in game.permanents_with_controller():
        text = permanent.effective_card.oracle_text or ""
        if "the game" not in text:
            continue
        for line in text.splitlines():
            for banned, scope in game_result_ban_line(line) or ():
                if banned != outcome:
                    continue
                if (
                    scope == "each_player"
                    or (scope == "you" and controller == seat)
                    or (scope == "opponents" and controller != seat)
                ):
                    found.append(permanent)
    return found


def player_cant_lose(game, seat: int) -> list:
    """The permanents saying *seat* can't lose the game (empty if none)."""
    return _banning_sources(game, seat, LOSE)


def player_cant_win(game, seat: int) -> list:
    """The permanents saying *seat* can't win the game (empty if none)."""
    return _banning_sources(game, seat, WIN)


__all__ = [
    "LOSE",
    "WIN",
    "game_result_ban_line",
    "player_cant_lose",
    "player_cant_win",
]
