"""The simulator's first turn is the starting player's (CR 103.1, 103.8).

``run_ai_simulation`` flips for the starting player
(``Game.select_starting_player``: the flip's winner "chooses to go first", the
AI's choice), deals from that seat and takes the mulligan declarations in turn
order from it (CR 103.5) — and until the kg3 round then gave seat 0 the first
turn in every game, so in each game the flip went to seat 1 the log said one
seat chose to go first and the other did.

**The census** reads every game of a seeded run over two sets: who won the
flip, and who skipped the first turn's draw step — which CR 103.8a gives the
player who plays first in a two-player game, and which the engine logs as that
turn's draw step begins. Validated backwards: with the simulator's first turn
put back to seat 0, every game the flip went to seat 1 names the other seat
and the census fails; the floors say both seats won flips, so the run could
not pass by never examining a seat-1 game.
"""
from __future__ import annotations

import re

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

_FLIP = re.compile(r"Coin flip: (\S+) wins and chooses to go first")
_SKIP = re.compile(r"(\S+) skips the first turn's draw step \(CR 103\.8a\)")


def _games(report) -> list[list[str]]:
    games: list[list[str]] = []
    for line in report.log_lines:
        if line.startswith("=== Game "):
            games.append([])
        elif games:
            games[-1].append(line.strip())
    return games


@pytest.mark.cr("103.1", "103.8", "103.8a")
@pytest.mark.parametrize("code", ["LEA", "ONS"])
def test_the_flip_s_winner_takes_the_first_turn(code):
    report = run_ai_simulation(manifest_set_path(code), games=8, seed=103, max_turns=1)
    assert report.games_completed == 8
    winners = []
    for index, lines in enumerate(_games(report), start=1):
        flips = [m.group(1) for line in lines if (m := _FLIP.search(line))]
        skips = [m.group(1) for line in lines if (m := _SKIP.search(line))]
        assert len(flips) == 1, (index, flips)
        # Exactly one first-turn draw step is skipped, and it is the seat
        # that chose to go first.
        assert skips == flips, (index, flips, skips)
        winners.append(flips[0])
    # The floor: both seats won a flip, so a seat-1 starter was examined.
    assert any(name.startswith("AI-A-") for name in winners), winners
    assert any(name.startswith("AI-B-") for name in winners), winners
