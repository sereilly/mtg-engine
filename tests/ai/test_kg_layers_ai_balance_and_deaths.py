"""A seeded AI run over Alpha and Antiquities with Balance, Living Lands,
Mishra's Factory and Soul Net pinned into both decks.

Two things the unit tests drive by hand, reached by the simulator's own turn:
Balance's rounds (each counted as it starts, through the layers — a Living
Lands Forest is one of its controller's creatures in the last round), and a
death that was a creature's only through the layers being seen by "whenever a
creature dies". A floor of one each: the paths were reached, and nothing the
run did raised or was reported.
"""

from __future__ import annotations

import re

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path

#: Seed 11 until the kg2 round, when the AI began to take mulligans and its
#: games stopped reaching a creature round with an animated Forest in it;
#: 21 is the first after it that does (12-20 cast Balance, but no Forest
#: was a creature when its round came). 36 until kg4 ``defaults``, when a
#: seat nobody asks began to give up the creatures it loses least by
#: (``ai_prompt_picks.balance_sacrifices``) and seed 36's rounds kept their
#: animated Forests; 37 is the first after it whose creature round takes one.
#: 69 since kg5 ``aicast``, when the instant-speed chooser began to announce
#: the X a target fixes: seed 37's Soul Net was countered by a Spell Blast at
#: its mana value (before, the X was the most the lands paid and the
#: rehearsal was refused), so no Soul Net saw the Forest die. Of 38-72 only
#: 69 has a creature round take a Forest with Soul Net's life gained after it
#: (50, 52, 60 and 67 take one, and no life is gained). 141 since kg5's
#: AI branches merged together (aiact, airesp, aicast, aivalue): seed 69's
#: games no longer reach a creature round; 141 passes every assertion here
#: on the merged tree (70-140 were not searched).
SEED = 141


@pytest.mark.full
def test_a_seeded_run_plays_balance_by_rounds_and_soul_net_sees_an_animated_forest_die():
    report = run_ai_simulation(
        [manifest_set_path("LEA"), manifest_set_path("ATQ")],
        games=2, seed=SEED, max_turns=14,
        required_cards=["Balance", "Mishra's Factory", "Living Lands", "Soul Net"],
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert not report.rehearsals_raised, report.rehearsals_raised

    lines = report.log_lines
    rounds = [i for i, line in enumerate(lines)
              if "Balance: each player chooses which creatures to keep" in line]
    assert rounds, "no seat cast Balance into a creature round; pick another seed"
    # The creature round took Forests: Living Lands made them creatures, and
    # the round counted them as such.
    forests_taken = [
        i for i in range(rounds[0], len(lines))
        if re.search(r"sacrificed .*Forest.* \(Balance\)", lines[i])
    ]
    assert forests_taken, lines[rounds[0]:rounds[0] + 12]
    # …and Soul Net, watching "a creature dies", saw them go.
    after = lines[forests_taken[0]:forests_taken[0] + 8]
    assert any("gained 1 life from Soul Net" in line for line in after), after
