"""A seeded game does the things no simulated game had done.

Each is a line the simulator's log had never held, with the card that makes it
pinned into every deck (``required_cards``): a permanent sacrificed for mana,
a card cast from outside the hand, a permission an *activation* bought being
spent in the main phase that bought it, and a blocked attacker keeping its
damage on its blocker when it could have walked past. The unit tests beside
this file hold each decision; this holds that a whole game reaches it — the
run completes, the count is non-zero and nothing is refused, owed or lost.
"""
from __future__ import annotations

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

#: ``(set, pinned card, games, log tokens that must each appear)``. The game
#: counts are the fewest in which seed 1337 reaches the line.
_RUNS = [
    # "{T}, Sacrifice this artifact: Add three mana of any one color."
    ("LEA", "Black Lotus", 1, ("sacrificed Black Lotus to activate its ability",)),
    # "{3}, {T}: Exile the top card of your library. Until the beginning of
    # your next upkeep, you may play that card." — granted by an activation,
    # after the cast pass has run and gone before the next turn's.
    ("ICE", "Elkin Bottle", 2, ("[from exile]",)),
    # "You may have this creature assign its combat damage as though it
    # weren't blocked." — both answers, in one run.
    ("7ED", "Lone Wolf", 4, (
        "Lone Wolf keeps its combat damage on the creatures blocking it",
        "Lone Wolf assigns its combat damage as though it weren't blocked",
    )),
]


@pytest.mark.slow
@pytest.mark.parametrize("code, pinned, games, tokens", _RUNS, ids=[run[1] for run in _RUNS])
def test_a_seeded_game_reaches_it(code, pinned, games, tokens):
    report = run_ai_simulation(
        manifest_set_path(code), games=games, seed=1337, required_cards=[pinned],
    )

    assert report.games_completed == games and report.interaction_count > 0
    for token in tokens:
        assert any(token in line for line in report.log_lines), token
    assert not report.issues, [issue.message for issue in report.issues]
    assert not report.refused_casts, dict(report.refused_casts)
    assert not report.refused_activations, dict(report.refused_activations)
    assert not report.refused_attacks and not report.refused_blocks
    assert not report.steps_left_owing, dict(report.steps_left_owing)
