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
#: counts are the fewest in which seed 1337 (or the card's ``_SEEDS``) reaches
#: the line.
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

#: A run seeded otherwise than 1337, and why. Lone Wolf ran on seed 3 from
#: the precombat-Fog round (where seed 1337's walk came under its own
#: controller's Fog) until ONS W2G5, when an activation that gives up its
#: source began to be rehearsed: seed 3's first game diverges at G1 T7, where
#: Scavenger Folk is no longer sacrificed for the opponent's Iron Star, and no
#: longer reaches the kept damage. Seed 1337 reached both answers again,
#: until the kg2 round (below).
_SEEDS = {
    # Round 4 gave both seats priority outside their own main phases, and
    # seed 1337's first two ICE games no longer reach the Bottle's card (the
    # third does, ten times over). Seed 7 reaches it in two games, nine times.
    "Elkin Bottle": 7,
    # The kg2 round's mulligans changed seed 1337's games, and its four no
    # longer walk Lone Wolf past a block; nor do 1338-1343's. Seed 1344's
    # reached both answers until Legions' closer C2 changed the AI's blocks
    # and its main-phase shields (green on the link beneath it, red on its):
    # neither 1344's four nor 1345's reach both now. Seed 1346's do.
    "Lone Wolf": 1346,
}


@pytest.mark.full
@pytest.mark.parametrize("code, pinned, games, tokens", _RUNS, ids=[run[1] for run in _RUNS])
def test_a_seeded_game_reaches_it(code, pinned, games, tokens):
    report = run_ai_simulation(
        manifest_set_path(code), games=games, seed=_SEEDS.get(pinned, 1337),
        required_cards=[pinned],
    )

    assert report.games_completed == games and report.interaction_count > 0
    for token in tokens:
        assert any(token in line for line in report.log_lines), token
    assert not report.issues, [issue.message for issue in report.issues]
    assert not report.refused_casts, dict(report.refused_casts)
    assert not report.refused_activations, dict(report.refused_activations)
    assert not report.refused_attacks and not report.refused_blocks
    assert not report.steps_left_owing, dict(report.steps_left_owing)
