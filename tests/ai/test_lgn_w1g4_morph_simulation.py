"""A seeded Legions game turns a morph with an X in its cost face up.

Legions' second half of morph: "Morph {X}{X}{R}" (Warbreak Trumpeter) and
"Morph {X}{B}{B}" (Bane of the Living) announce X as the special action is
taken (CR 107.3d), and the face-up trigger reads it (CR 702.37f). The
simulator takes the action through ``ai_special_actions`` — the chooser
rehearses sizes of X — and resolves the face-up triggers in the main phase it
took the action in, before combat (CR 116.3), rather than leaving them on the
stack as the step ends.

**A floor of one, never a count**: how often a seeded game turns a morph up
is a statement about every other card in the set.
"""

from __future__ import annotations

from engine import ai_simulator
from engine.card_loader import manifest_set_path

_PINNED = [
    "Bane of the Living", "Warbreak Trumpeter", "Dermoplasm", "Weaver of Lies",
    "Willbender", "Tribal Forcemage",
]


def test_a_simulated_legions_game_announces_x_for_a_morph():
    path = manifest_set_path("LGN", include_measured=True)

    def run():
        return ai_simulator.run_ai_simulation(
            path, games=2, seed=7, max_turns=14, required_cards=_PINNED,
        )

    report = run()
    assert report.special_actions_taken["turn_face_up"] >= 1
    assert any("with X = " in line for line in report.log_lines)
    assert report.rehearsals_raised == {}
    # The face-up trigger resolves in the main phase the action was taken in:
    # no step is left owing one of these cards' abilities.
    assert not [
        owed for owed in report.steps_left_owing
        if any(name in owed for name in _PINNED)
    ]
    assert not [
        why for why in report.refused_special_actions if "turn" in why
    ]
    assert run().log_lines == report.log_lines
