"""The five "target spell or permanent" text-changers in seeded AI games.

Since kg3 they derive the ``spell_or_permanent`` picker (a permanent or a spell
on the stack) and a named spell's change is recorded on its stack object. The
AI weighs both halves of that picker and the words it names
(``ai_text_changes.choose_object_or_spell``, kg3 `aiplay`, which casts each to
effect in ``tests/ai/test_kg3_aiplay_text_changers.py``); what this holds is
that nothing the union now reaches raises — the cast, the rehearsal of it, the
resolution.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

_TEXT_CHANGERS = [
    "Sleight of Mind", "Magical Hack", "Crystal Spray", "Alter Reality",
    "Artificial Evolution",
]


@pytest.mark.full
def test_seeded_games_with_the_five_text_changers_pinned_raise_nothing():
    report = run_ai_simulation(
        [manifest_set_path(code) for code in ("LEA", "INV", "TOR", "ONS")],
        games=3, seed=612, max_turns=12, required_cards=_TEXT_CHANGERS,
    )
    assert report.games_completed == 3
    assert not report.rehearsals_raised
    assert report.interaction_count >= 1
