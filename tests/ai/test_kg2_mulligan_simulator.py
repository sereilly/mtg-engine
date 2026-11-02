"""The simulator asks the AI's keep decision (``ai_mulligan``) for every seat,
and counts what it took (``SimulationReport.mulligans_taken``).

Until the ``kg2`` round ``run_ai_simulation`` called ``keep_hand`` for each
seat: no simulated seat ever mulliganed, and a one-land seven was played out
with nothing in the report to say so.

**The census** runs the simulator's own deal — ``run_ai_simulation`` with no
turns, so each game is its decks, its coin flip, its shuffles and its
mulligans and nothing else — over several shipped sets, and reads every
decision the call site asks through a spy on the decision. Validated
backwards: with the simulator's call put back to ``keep_hand`` for each seat,
the spy sees no decision at all and the floors below fail.
"""
from __future__ import annotations

from collections import Counter
from unittest import mock

from engine import ai_mulligan
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.search_filters import card_has_type

#: Sets across the pool's eras. ARN prints no basic land, so its decks take
#: the manifest's (``limited_deck._basic_land_pool``).
CENSUS_SETS = ("LEA", "ARN", "ICE", "TMP", "INV", "ONS", "M21")
GAMES = 30
SEED = 4


def _lands(cards) -> int:
    return sum(1 for card in cards if card_has_type(card, "land"))


def test_every_seat_s_opening_seven_is_judged_and_the_bad_ones_mulliganed():
    decisions: list[dict] = []
    real = ai_mulligan.keeps_opening_hand

    def spy(game, seat):
        answer = real(game, seat)
        hand = list(game.players[seat].hand)
        owed = game.mulligan_effective_count(seat)
        going = set(ai_mulligan.opening_hand_bottom(game, seat))
        kept = [card for index, card in enumerate(hand) if index not in going]
        decisions.append({
            "lands": _lands(hand), "owed": owed, "keep": answer,
            "kept_size": len(kept), "kept_lands": _lands(kept),
            "share": ai_mulligan.deck_land_share(game, seat),
        })
        return answer

    taken = 0
    with mock.patch.object(ai_mulligan, "keeps_opening_hand", spy):
        for code in CENSUS_SETS:
            report = run_ai_simulation(
                manifest_set_path(code), games=GAMES, seed=SEED, max_turns=0
            )
            assert report.games_completed == GAMES
            assert not report.issues, [issue.message for issue in report.issues]
            taken += report.mulligans_taken

    sevens = [d for d in decisions if d["owed"] == 0]
    # The floor: every seat of every game was asked about its seven, and the
    # deals reached the hands this exists for.
    assert len(sevens) >= 2 * GAMES * len(CENSUS_SETS)
    by_lands = Counter(d["lands"] for d in sevens)
    assert by_lands[0] + by_lands[1] >= 1 and by_lands[2] >= 1

    for d in sevens:
        if d["lands"] <= 1 or d["lands"] >= 6:
            assert d["keep"] is False, d
    for d in decisions:
        if d["keep"] and d["kept_size"] > ai_mulligan.ALWAYS_KEEP_AT:
            low, high = ai_mulligan.keep_window(d["kept_size"], d["share"])
            assert low <= d["kept_lands"] <= high, d
    # Each "no" is a mulligan taken, and the report counts every one.
    assert taken == sum(1 for d in decisions if not d["keep"]) >= 1


def test_a_one_land_seven_is_mulliganed_in_a_played_game():
    """LEA, seed 1: the first game deals AI-A-1 a one-land seven (found by the
    kg2 round's deal census). The seat mulligans before its first turn, keeps
    a shorter hand, and the game is played out from there."""
    report = run_ai_simulation(manifest_set_path("LEA"), games=1, seed=1, max_turns=1)
    assert report.mulligans_taken >= 1
    assert not report.issues, [issue.message for issue in report.issues]
    lines = report.log_lines
    took = next(i for i, line in enumerate(lines) if "AI-A-1 took mulligan #1" in line)
    kept = next(i for i, line in enumerate(lines) if "AI-A-1 keeps opening hand of" in line)
    assert took < kept
    assert "keeps opening hand of 7" not in lines[kept]
    assert report.interaction_count > 0 or report.lands_played > 0
