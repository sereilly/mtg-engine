"""The AI turns a morph face up for a cost that is not mana (CR 702.37e).

Zombie Cutthroat ("Morph—Pay 5 life") and Putrid Raptor ("Morph—Discard a
Zombie card") pinned into seeded Scourge decks: the special-action chooser
(``ai_special_actions``) rehearses the turn-up through the seam the web
shares, the life or the discard included in the standing it reads, and takes
it when the body is worth the price. A floor of one, never a count; and no
rehearsal raised, no turn-up refused.
"""

from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_paths


@pytest.mark.full
def test_the_ai_pays_a_non_mana_morph_cost():
    (path,) = [p for p in manifest_set_paths(include_measured=True) if p.stem.startswith("SCG")]
    report = run_ai_simulation(
        path, games=4, seed=5, max_turns=16,
        required_cards=["Zombie Cutthroat", "Putrid Raptor"],
    )
    assert report.games_completed == 4
    assert report.special_actions_taken["turn_face_up"] >= 1
    assert not report.refused_special_actions
    assert not report.rehearsals_raised
    paid = [
        line for line in report.log_lines
        if "for its morph cost Pay 5 life" in line
        or "for its morph cost Discard a Zombie card" in line
    ]
    assert paid, "no non-mana morph cost was paid"
