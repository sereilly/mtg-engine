"""Mindslaver in the AI simulator (CR 723): an AI controlling an AI.

A seeded MRD run with the card pinned has to activate it, take a turn under
the control it makes (``SimulationReport.controlled_turns``), and leave
nothing refused, owing or raised — the simulator plays the engine's turn, so
a controlled turn that stalled or a rehearsal that crashed on the record would
read here. A floor of one, never a count (tests/README's rule for a seeded
simulation test).
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path


@pytest.mark.full
def test_a_pinned_mindslaver_is_activated_and_its_turn_played_cleanly():
    report = run_ai_simulation(
        manifest_set_path("MRD", include_measured=True),
        games=4, seed=7, required_cards=["Mindslaver"],
    )
    activations = [
        line for line in report.log_lines
        if " activate Mindslaver -> resolved" in line
    ]
    assert activations, "no seat activated Mindslaver"
    assert report.controlled_turns >= 1
    assert not report.steps_left_owing
    assert not report.rehearsals_raised
    assert not [
        key for key in report.refused_instant_activations if "Mindslaver" in key
    ]
    assert not [key for key in report.refused_casts if "Mindslaver" in key]
