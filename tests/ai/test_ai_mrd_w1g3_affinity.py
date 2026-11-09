"""The AI casts affinity spells at the price affinity makes — Mirrodin's W1G3.

The cast path, the castable highlight and the AI's affordability read all
price a spell through ``cost_modifiers.cost_reduction_for_cast``; the per-card
tests in ``tests/sets/test_mrd_*.py`` hold each reader. This is the whole turn:
seeded AI-vs-AI games over Mirrodin with the affinity cards and Hum of the
Radix pinned into both decks. Floors, never counts.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

_AFFINITY = (
    "Frogmite", "Myr Enforcer", "Thoughtcast", "Somber Hoverguard", "Broodstar",
    "Assert Authority", "Scale of Chiss-Goria",
)


@pytest.mark.full
def test_a_seeded_mirrodin_game_casts_affinity_spells_cheaper():
    """The run completes; at least one affinity spell is cast with its
    reduction logged ("… costs less to cast"), at least one artifact spell is
    taxed by a Hum of the Radix, none of the pinned cards is ever refused for
    its price, and no rehearsal raised — so the AI's plan and the cast agree
    on what each spell costs."""
    report = run_ai_simulation(
        manifest_set_path("MRD", include_measured=True), games=4, seed=4103,
        required_cards=[*_AFFINITY, "Hum of the Radix"],
    )
    assert report.games_completed == 4
    lines = [line.strip() for line in report.log_lines]
    assert any(
        line.startswith(f"{name} costs less to cast") for name in _AFFINITY for line in lines
    )
    assert any("is taxed by Hum of the Radix" in line for line in lines)
    refused = {
        reason: count for reason, count in report.refused_casts.items()
        if any(name in reason for name in (*_AFFINITY, "Hum of the Radix"))
    }
    assert not refused
    assert not report.rehearsals_raised
