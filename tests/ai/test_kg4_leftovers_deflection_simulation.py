"""The AI re-aims a counterspell with Deflection (CR 115.7a), in a seeded
batch through the engine's own turn.

Until kg4 a spell whose one target was a spell was no "spell with a single
target" (``targeting.single_spell_target`` refused it), so a Deflection with
a Counterspell on the stack was refused with "no valid target" and the AI's
picker never offered one. Deflection and Counterspell are pinned into both
Seventh Edition decks; the batch must play a Deflection that moves a
Counterspell onto another spell — the floor of one, never a count — with the
honesty counts clean: nothing refused, no rehearsal raised, no issue.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path


@pytest.mark.full
def test_the_ai_deflects_a_counterspell_onto_another_spell():
    report = run_ai_simulation(
        manifest_set_path("7ED"), games=6, seed=4401,
        required_cards=("Deflection", "Counterspell", "Shock", "Deflection", "Counterspell"),
    )
    assert report.games_completed == report.games_requested == 6
    assert report.interaction_count > 0
    re_aimed = [
        line for line in report.log_lines
        if line.startswith("Deflection: Counterspell now targets")
    ]
    assert re_aimed, [line for line in report.log_lines if line.startswith("Deflection")][:10]
    assert not report.issues, report.issues[:5]
    assert not report.refused_casts, report.refused_casts
    assert not report.rehearsals_raised, report.rehearsals_raised
