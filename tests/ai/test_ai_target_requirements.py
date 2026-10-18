"""An AI seat across the table from a Flagbearer, over whole simulated games.

"While an opponent is choosing targets …, that player must choose at least one
Flagbearer on the battlefield if able." A cast the engine refuses costs nothing
and breaks no rule, so an AI that proposes one fails no assertion — it
re-proposes the same card every turn and does nothing for as long as the
Flagbearer lives. That is what ``SimulationReport.refused_casts`` counts, and
what this file holds at zero for the requirement's own refusal.

The single-decision half — which permanent the policy names, and what it
declines to cast at all — is ``tests/engine/test_target_requirements.py``.
"""

from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path


_REFUSAL = "must be chosen as a target if able"


@pytest.mark.slow
def test_no_cast_is_refused_for_ignoring_a_flagbearer_in_simulation():
    """Alpha's burn, removal, pump and Auras against decks that each carry
    Standard Bearer and Coalition Honor Guard. ``required_cards`` pins the two
    into both decks, so a seed that dealt neither cannot pass this having
    regressed nothing — and the test says they were cast."""
    report = run_ai_simulation(
        cards_path=[
            manifest_set_path("LEA"),
            manifest_set_path("APC", include_measured=True),
        ],
        games=4,
        seed=2001,
        max_turns=16,
        required_cards=("Standard Bearer", "Coalition Honor Guard"),
    )
    assert report.games_completed == 4 and report.interaction_count > 0

    entered = [
        line for line in report.log_lines
        if "put Standard Bearer onto battlefield" in line
        or "put Coalition Honor Guard onto battlefield" in line
    ]
    assert entered, "no Flagbearer ever reached the battlefield"

    refused = {reason: count for reason, count in report.refused_casts.items() if _REFUSAL in reason}
    assert not refused, refused
    assert not [line for line in report.log_lines if _REFUSAL in line]
