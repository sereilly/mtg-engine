"""Quarum Trench Gnomes' record, applied at the tap event in the engine's own
AI turn (CR 106.12b).

"If target Plains is tapped for mana, it produces colorless mana instead of
white mana" is one substitution among the others over a land's production
(``land_mana_swaps.permanent_substitutions_on``), ordered against Hall of
Gemstone's colour by the tap's request (CR 616.1e). Until kg5 ``mana2`` it was
read off ``Permanent.effective_produced_mana`` ahead of every substitution, so
the summary made {C} directly and the tap event never applied it. Pinned with
Hall of Gemstone into a Legends-and-Mirage pool: the batch must see the AI aim
the Gnomes at a Plains and that Plains' white come out as {C} at the event — a
floor of one, never a count — with the honesty counts clean.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path


@pytest.mark.full
def test_the_ai_s_gnomed_plains_makes_colourless_at_the_tap_event():
    report = run_ai_simulation(
        [manifest_set_path("LEG"), manifest_set_path("MIR")], games=4, seed=5151,
        required_cards=(
            "Quarum Trench Gnomes", "Quarum Trench Gnomes", "Hall of Gemstone",
            "Plains", "Plains", "Plains",
        ),
    )
    assert report.games_completed == report.games_requested == 4
    assert report.interaction_count > 0
    lines = [line.strip() for line in report.log_lines]
    assert "Quarum Trench Gnomes: Plains now produces {C} instead of {W}" in lines
    assert "Plains produced {C} instead" in lines, [
        line for line in lines if line.startswith("Plains produced")
    ][:10]
    assert not report.issues, report.issues[:5]
    assert not report.rehearsals_raised, report.rehearsals_raised
