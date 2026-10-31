"""A seeded Onslaught game reaches morph: cast face down, turned face up.

The two honesty counts the subsystem arrived with (``SimulationReport.
face_down_casts`` and ``special_actions_taken["turn_face_up"]``) read zero in
every run before it — nothing could be cast face down — so a pool printing
morph that reads zero is either that coming back or the policy never finding
the {3} worth it. **A floor of one, never a count**: how often a seeded game
casts a morph is a statement about every other card in the set.
"""

from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.card_loader import manifest_set_path

#: Morph cards across the five colours, so either seat's two-colour deck holds
#: some, with costs a limited deck reaches.
_PINNED = [
    "Krosan Colossus", "Exalted Angel", "Whipcorder", "Battering Craghorn",
    "Grinning Demon", "Hystrodon",
]


@pytest.mark.full
def test_a_simulated_onslaught_game_casts_a_morph_face_down_and_turns_one_up():
    path = manifest_set_path("ONS", include_measured=True)

    def run():
        return ai_simulator.run_ai_simulation(
            path, games=2, seed=7, max_turns=14, required_cards=_PINNED,
        )

    report = run()
    assert sum(report.face_down_casts.values()) >= 1
    assert report.special_actions_taken["turn_face_up"] >= 1
    assert any(
        "turned a face-down creature face up" in line for line in report.log_lines
    )
    assert report.rehearsals_raised == {}
    # The census the simulator keeps over every card in the game: a face-down
    # permanent counted as the card it hides, never as a card appearing.
    assert not [
        issue for issue in report.issues if "Zone conservation" in issue.message
    ]
    assert not [
        why for why in report.refused_special_actions if "turn" in why
    ]
    assert [
        why for why in report.refused_casts if why.split(":")[0] in _PINNED
    ] == []
    assert run().log_lines == report.log_lines
