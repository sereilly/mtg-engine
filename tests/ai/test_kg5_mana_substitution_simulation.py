"""The AI taps a land under two substitutions for the symbol its plan counted,
in a seeded batch through the engine's own turn (CR 616.1e).

Naked Singularity ("If tapped for mana, Plains produce {R}, Islands produce
{G}, …") over a dual land is two effects on one tap, and "the player tapping
the land for mana can choose to produce mana of either color" (its ruling,
2013-04-15). The choice is the symbol the tap is asked for
(``land_mana_swaps.ordered_substitutions``), and the AI's planner asks for the
one it counted (``payment_colors`` offers both). Until kg5 the first clause in
printed order answered every tap, so a Tundra the plan counted as {G} made
{R}. Pinned into both decks of an Alpha-and-Ice-Age pool; the batch must see
a Tundra make each of its two colours — a floor of one each, never a count —
with the honesty counts clean.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path


@pytest.mark.full
def test_the_ai_taps_a_dual_under_naked_singularity_for_either_colour():
    # Seed 5151 made both colours until kg5's AI merges (aiact's sacrifice
    # weighing onward) moved its games: its Tundras were then asked only for
    # {R}. 5155-5157 each make both on the merged tree; 5155 is the row.
    report = run_ai_simulation(
        [manifest_set_path("LEA"), manifest_set_path("ICE")], games=4, seed=5155,
        required_cards=("Naked Singularity", "Tundra", "Tundra", "Taiga", "Savannah"),
    )
    assert report.games_completed == report.games_requested == 4
    assert report.interaction_count > 0
    lines = [line.strip() for line in report.log_lines]
    for made in ("{R}", "{G}"):
        assert f"Tundra produced {made} instead" in lines, [
            line for line in lines if line.startswith("Tundra produced")
        ][:10]
    assert not report.issues, report.issues[:5]
    assert not report.rehearsals_raised, report.rehearsals_raised
