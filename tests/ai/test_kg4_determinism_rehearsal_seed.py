"""The AI's decisions do not read the log.

``ai_rehearsal._rehearsal_seed`` was ``7919 * turn + len(game.log)``: one log
line added, removed or merged reseeded every later rehearsal's concealment
shuffle (``conceal_from``) and moved AI decisions with no AI code touched
(Scourge's engine pile merged Carbonize's two lines into one and moved 2 of
12 ``sim_fingerprint`` runs). ``ai_scoring._score_tutor_choice``'s cache was
stamped with the log's length too, so a log line decided whether a search
weighed its cards again.

The board: a seeded LEA game played twice, once as it is and once with one
extra line written into the log at the start of every turn. Every decision,
every honesty count and every other line are the same. Validated backwards in
the suite (``test_the_padded_run_can_tell_a_log_seed``): with the old seed put
back, the padded game casts Fastbond where the plain one cast Natural
Selection (turn 2).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine import ai_rehearsal, ai_scoring
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

PAD = "(kg4: one more line in the log)"
SET, SEED, GAMES, TURNS = "LEA", 7, 1, 8
REPO = Path(__file__).resolve().parents[2]


def _log_seed(game) -> int:
    """The seed as it was: the log's length."""
    return 7919 * int(getattr(game, "turn", 0) or 0) + len(game.log)


def _run(monkeypatch, *, padded: bool, seed_of=None) -> tuple[list, dict, list]:
    """One seeded run: its lines without the padding, every other field of
    its report, and the log-length seed each rehearsal would have read."""
    log_seeds: list[int] = []
    real_seed = seed_of or ai_rehearsal._rehearsal_seed

    def spy(game):
        log_seeds.append(_log_seed(game))
        return real_seed(game)

    with monkeypatch.context() as patch:
        patch.setattr(ai_rehearsal, "_rehearsal_seed", spy)
        if padded:
            start = Game.start_next_turn

            def start_padded(self, *args, **kwargs):
                self.log.append(PAD)
                return start(self, *args, **kwargs)

            patch.setattr(Game, "start_next_turn", start_padded)
        report = run_ai_simulation(
            manifest_set_path(SET), games=GAMES, seed=SEED, max_turns=TURNS,
        )
    lines = [line for line in report.log_lines if PAD not in line]
    rest = {
        key: repr(value) for key, value in dataclasses.asdict(report).items()
        if key != "log_lines"
    }
    assert report.games_completed == GAMES
    return lines, rest, log_seeds


def test_one_more_log_line_moves_no_ai_decision(monkeypatch):
    plain_lines, plain_rest, plain_seeds = _run(monkeypatch, padded=False)
    padded_lines, padded_rest, padded_seeds = _run(monkeypatch, padded=True)
    # Floors: the run rehearsed, and the padding reached the rehearsals —
    # the log-length seed would have read differently at some of them.
    assert plain_seeds, "no rehearsal was seeded; the board examined nothing"
    assert any(" cast " in line for line in plain_lines)
    assert padded_seeds != plain_seeds
    assert padded_lines == plain_lines
    assert padded_rest == plain_rest


def test_the_padded_run_can_tell_a_log_seed(monkeypatch):
    """Backwards: with the seed read off the log again, the same padding
    moves a decision — so the test above is a board on which it would."""
    plain_lines, _, _ = _run(monkeypatch, padded=False, seed_of=_log_seed)
    padded_lines, _, _ = _run(monkeypatch, padded=True, seed_of=_log_seed)
    assert padded_lines != plain_lines


def test_the_seed_is_the_same_on_a_copy_and_for_any_log():
    from engine.ai_rehearsal import scratch_copy

    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.turn = 4
    seed = ai_rehearsal._rehearsal_seed(game)
    assert ai_rehearsal._rehearsal_seed(scratch_copy(game)) == seed
    game.log.extend(["a line", "another line"])
    assert ai_rehearsal._rehearsal_seed(game) == seed
    game.players[1].life -= 3
    assert ai_rehearsal._rehearsal_seed(game) != seed


def test_a_tutor_score_is_not_weighed_again_for_a_log_line(monkeypatch, set_pool):
    lea = set_pool("LEA")
    calls: list[str] = []
    real = ai_scoring._tutor_score

    def counted(game, seat, card):
        calls.append(card.name)
        return real(game, seat, card)

    monkeypatch.setattr(ai_scoring, "_tutor_score", counted)
    monkeypatch.setattr(ai_scoring, "_TUTOR_SCORES", {})
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    first = ai_scoring._score_tutor_choice(game, 0, lea["Grizzly Bears"])
    game.log.append("a line that changes nothing")
    again = ai_scoring._score_tutor_choice(game, 0, lea["Grizzly Bears"])
    assert again == first
    assert calls == ["Grizzly Bears"]
    # …and the position still decides: a life total moved is a new position.
    game.players[0].life -= 5
    ai_scoring._score_tutor_choice(game, 0, lea["Grizzly Bears"])
    assert calls == ["Grizzly Bears", "Grizzly Bears"]


def test_no_ai_module_reads_the_log():
    """The AI writes the log and never reads it: a decision that reads it is
    a decision a reworded line moves. The simulator copies the game's lines
    into its report, which is reporting, not deciding."""
    readers = []
    modules = sorted((REPO / "engine").glob("ai_*.py"))
    assert len(modules) >= 20, modules
    for path in modules:
        if path.name == "ai_simulator.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Attribute) and node.attr == "log"):
                continue
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.attr in {"append", "extend"}:
                continue
            readers.append(f"{path.name}:{node.lineno}")
    assert not readers, readers
