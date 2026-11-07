"""A seeded run is the run a fresh process plays, whatever ran before it.

The playbook's entry: a seeded AI test failed differently after other files in
one process than alone — "some module-level state survives between runs and
reaches the simulator". Measured at kg4 on the tree with the rehearsal seed
off the log: the twelve ``sim_fingerprint`` runs played in one process, one
after another, match the twelve fresh processes line for line; two seeded
scenarios (LEA, and ``test_kg_layers_ai_balance_and_deaths``'s board) after the
whole of ``tests/ai``'s quick pass, and four (those, ODY and TMP) after the
quick pass of ``tests/engine``, ``tests/regressions``, ``tests/rules``,
``tests/sets`` and ``tests/ui``, match their first play in that process.

What the census found is the state that *could* carry a run over:
``ai_scoring._TUTOR_SCORES``, a process-long memo of a search's card scores,
validated by ``id(game)``. CPython hands a freed object's address to the next
allocation, so a game put where a freed one stood, with the same counts on it,
was answered from the freed one's scores. It holds its game by a weak
reference now, and ``tests/regressions/test_derived_card_memo_identity.py``'s
guard, which looked only at a memo's *key*, also fails a memo whose validity
stamp is an address.

The board here: a seeded LEA game played by a fresh interpreter, and played
in this process after each deliberate polluter — the process-wide id and
timestamp counters far on, the module RNG disturbed, another set's run, the
compile caches emptied and refilled — each the same, line for line. Validated
backwards in the suite: with the simulator's own reseeding switched off, the
disturbed RNG moves the game (``test_the_comparison_can_tell_a_run_that_reads_the_process``).
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import types
from pathlib import Path

import pytest

from engine import Game, PlayerState
from engine import ai_scoring
from engine import ai_simulator
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition

REPO = Path(__file__).resolve().parents[2]
SET, SEED, GAMES, TURNS = "LEA", 7, 1, 8

#: The same game, played by an interpreter that has run nothing else.
_FRESH = """
import json, sys
sys.path.insert(0, {repo!r})
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
report = run_ai_simulation(manifest_set_path({set!r}), games={games}, seed={seed}, max_turns={turns})
sys.stdout.write(json.dumps(report.log_lines))
"""


def _fresh_lines() -> list[str]:
    script = _FRESH.format(repo=str(REPO), set=SET, games=GAMES, seed=SEED, turns=TURNS)
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True,
    )
    return json.loads(completed.stdout)


def _lines() -> list[str]:
    report = run_ai_simulation(
        manifest_set_path(SET), games=GAMES, seed=SEED, max_turns=TURNS,
    )
    assert report.games_completed == GAMES
    return report.log_lines


def _counters_far_on():
    from engine import continuous, models

    for _ in range(100_003):
        models.next_permanent_id()
    for _ in range(77_777):
        continuous.next_timestamp()


def _rng_disturbed():
    random.seed(424242)
    random.random()


def _another_run():
    run_ai_simulation(manifest_set_path("MIR"), games=1, seed=3, max_turns=6)


def _compile_caches_emptied():
    from engine.oracle_types import clear_compilation_caches
    from tests.passes import rewarm_compile_cache

    clear_compilation_caches()
    rewarm_compile_cache()


POLLUTERS = (
    ("the process-wide counters far on", _counters_far_on),
    ("the module RNG disturbed", _rng_disturbed),
    ("another set's seeded run", _another_run),
    ("the compile caches emptied and refilled", _compile_caches_emptied),
)


@pytest.mark.full
def test_a_seeded_run_is_the_run_a_fresh_process_plays():
    fresh = _fresh_lines()
    # A floor: the game was played, and decided things.
    assert sum(" cast " in line for line in fresh) >= 1, fresh[:20]
    # Whatever this process ran before this test is the first polluter.
    assert _lines() == fresh, "a seeded run read what ran before it in this process"
    for label, pollute in POLLUTERS:
        pollute()
        assert _lines() == fresh, f"a seeded run moved after {label}"


@pytest.mark.full
def test_the_comparison_can_tell_a_run_that_reads_the_process(monkeypatch):
    """Backwards: a simulator that did not reseed the module RNG would play
    on whatever sequence the process left it — and the same comparison
    sees it."""
    fresh = _fresh_lines()
    unseeded = types.SimpleNamespace(
        **{name: getattr(random, name) for name in dir(random) if not name.startswith("__")},
    )
    unseeded.seed = lambda *args, **kwargs: None
    monkeypatch.setattr(ai_simulator, "random", unseeded)
    _rng_disturbed()
    assert _lines() != fresh


def _probe_card() -> CardDefinition:
    return CardDefinition(
        name="Probe Bears", mana_cost="{1}{G}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(), raw={"name": "Probe Bears", "power": "2", "toughness": "2"},
    )


def test_a_tutor_score_is_never_another_games(monkeypatch):
    """Two games, equal in every count, and the scorer's memo between them.
    The second is weighed on itself — even where it stands at the first
    one's address, which is what an address-stamped memo cannot tell apart
    (every game at one address: ``id`` answers alike in the scorer's module;
    on the tree before, the second game was handed the first one's score)."""
    weighed_on: list[str] = []

    def score(game, seat, card):
        weighed_on.append(game.players[0].name)
        return float(len(weighed_on))

    monkeypatch.setattr(ai_scoring, "_tutor_score", score)
    monkeypatch.setattr(ai_scoring, "_TUTOR_SCORES", {})
    monkeypatch.setattr(ai_scoring, "id", lambda obj: 1, raising=False)
    card = _probe_card()
    first = Game(players=[PlayerState(name="first"), PlayerState(name="P1")])
    assert ai_scoring._score_tutor_choice(first, 0, card) == 1.0
    # Asked again of the same game at the same position: the memo answers.
    assert ai_scoring._score_tutor_choice(first, 0, card) == 1.0
    del first
    second = Game(players=[PlayerState(name="second"), PlayerState(name="P1")])
    assert ai_scoring._score_tutor_choice(second, 0, card) == 2.0
    assert weighed_on == ["first", "second"]
