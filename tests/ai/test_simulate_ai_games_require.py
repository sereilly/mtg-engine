"""`simulate_ai_games.py --require` pins cards into both decks, checked against the pool.

Ten of Darksteel's twelve groups each wrote the same wrapper around
``run_ai_simulation(required_cards=[...])``, because the script and
``scripts/integration/checked_sim.py`` took no pinned cards. The flag reads
comma-separated names (a name that prints a comma is read whole), may repeat,
and refuses a name the pool the run deals from does not hold — a run that
quietly dealt without it would be a clean report about a card it never met.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import simulate_ai_games  # noqa: E402
from engine.ai_simulator import SimulationReport  # noqa: E402

POOL = ["Leonin Bola", "Heartseeker", "Akroma, Angel of Wrath", "Akroma"]


def test_names_split_on_commas_and_a_comma_name_is_read_whole():
    names, unknown = simulate_ai_games.required_names(
        ["Leonin Bola, akroma, angel of wrath,Heartseeker", "AKROMA", "Leonin Bola"], POOL,
    )
    assert names == ["Leonin Bola", "Akroma, Angel of Wrath", "Heartseeker", "Akroma"]
    assert unknown == []


def test_an_unknown_name_is_reported_as_it_was_written():
    names, unknown = simulate_ai_games.required_names(
        ["Leonin Bola, Hartseeker, Sorin, Solemn Visitor"], POOL,
    )
    assert names == ["Leonin Bola"]
    assert unknown == ["Hartseeker, Sorin, Solemn Visitor"]


def _parse(argv):
    parser = simulate_ai_games.build_parser()
    args = parser.parse_args(argv)
    return parser, args, simulate_ai_games.resolve_set(parser, args)


def test_a_name_the_pool_lacks_exits_naming_it(capsys):
    parser, args, selection = _parse(["--set", "LEA", "--require", "Shivan Dragon,Shivan Dargon"])
    with pytest.raises(SystemExit) as exited:
        simulate_ai_games.resolve_required(parser, args, selection)
    assert exited.value.code == 2
    error = capsys.readouterr().err
    assert "'Shivan Dargon'" in error and "did you mean Shivan Dragon" in error
    assert "Limited Edition Alpha (LEA)" in error


def test_more_pins_than_a_deck_holds_exits(capsys):
    parser, args, selection = _parse(["--set", "LEA"])
    args.require = [",".join(sorted({c.name for c in simulate_ai_games.load_cards(selection.paths)})[:24])]
    with pytest.raises(SystemExit):
        simulate_ai_games.resolve_required(parser, args, selection)
    assert "a deck holds 23" in capsys.readouterr().err


def test_the_pins_reach_the_simulation_and_the_report_counts_them(monkeypatch, capsys, tmp_path):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        report = SimulationReport(games_requested=1, games_completed=1, interaction_count=1)
        report.log_lines = ["AI-A casts Shivan Dragon", "Shivan Dragon attacks"]
        return report

    monkeypatch.setattr(simulate_ai_games, "run_ai_simulation", fake)
    monkeypatch.setattr(sys, "argv", [
        "simulate_ai_games.py", "--set", "LEA", "--games", "1",
        "--log-file", str(tmp_path / "sim.log"),
        "--require", "shivan dragon", "--require", "Lightning Bolt",
    ])
    assert simulate_ai_games.main() == 0
    assert seen["required_cards"] == ["Shivan Dragon", "Lightning Bolt"]
    out = capsys.readouterr().out
    assert "Pinned into both decks: Shivan Dragon (2 log lines), Lightning Bolt (0 log lines)" in out
    assert "never in the log (dealt, never met): Lightning Bolt" in out


def test_checked_sim_passes_the_pins_through(tmp_path):
    """`checked_sim.py` runs the script with every flag it was given; an
    unknown pin exits there as it does here, and the counts file says so."""
    counts = tmp_path / "counts.json"
    run = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "integration" / "checked_sim.py"), str(counts),
         "--set", "LEA", "--games", "1", "--require", "Shivan Dargon"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8",
    )
    assert run.returncode == 2, run.stderr[-2000:]
    assert "'Shivan Dargon'" in run.stderr
    written = json.loads(counts.read_text(encoding="utf-8"))
    assert written["exit"] == 2
    assert written["args"][-2:] == ["--require", "Shivan Dargon"]
