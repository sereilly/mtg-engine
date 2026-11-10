"""A trick the seat holds for after the blocks is part of the fight it is
weighed through, and of the attack it declares.

Two halves of one defect (the Known-gaps "AI leftovers" entry, kg4):

* **A rehearsal's fight had no priority driver.** The copy a precombat
  decision is read on fights its combat by the policies that would declare
  it (``ai_rehearsal._fight_the_combat``), and every seat's priority on it
  was passed — so the copy "with nothing bought" read a Zealous Inquisitor
  blocked by a Grizzly Bears as a trade, and the redirect ("{1}{W}: The next
  1 damage that would be dealt to this creature this turn is dealt to target
  creature instead") was bought in the main phase, where it only deters the
  block, rather than raised after it, where it wins it. The copy's fight now
  lets the rehearsal's own seat answer priority in the declare-blockers step
  (``_fight_priority_driver``, its choosers one level down), and the copy
  with nothing bought holds the mana the purchase would spend.
* **The attack policy counted printed bodies** (``_score_block_pair``), so
  a creature whose best blocker beats it stayed home whatever its seat held
  behind it. ``ai_declarations._attacks_its_held_trick_wins`` rehearses each
  such creature's attack through the fight, the trick held, and adds the
  ones that leave the seat ahead.

Driven through the simulator's own seams: the main-phase activation door
(``ai_simulator._play_activations``), then the combat
(``ai_combat.run_ai_combat_phase``) with the simulator's priority driver
installed, and the board read after it.
"""

from __future__ import annotations

import pytest

from engine.ai_abilities import choose_activation_action
from engine.ai_combat import run_ai_combat_phase
from engine.ai_declarations import _attacks_its_held_trick_wins
from engine.ai_simulator import _play_activations, run_ai_simulation
from engine.card_loader import manifest_set_path
from tests.ai.test_kg4_aiact_moves_nothing import _table


def _creatures(game, seat) -> list:
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


def _raised_after_the_blocks(report) -> list:
    return [
        line for line in report.log_lines
        if "activate Zealous Inquisitor" in line and "[in the declare blockers step]" in line
    ]


def test_the_redirect_is_held_and_raised_once_the_bears_has_blocked():
    game, report = _table(("Zealous Inquisitor", "Plains", "Plains"), step="precombat_main")
    assert choose_activation_action(game, 0) is None
    _play_activations(game, 0, report, 1, 1)
    assert not report.log_lines, report.log_lines  # nothing bought before the attack
    run_ai_combat_phase(game, 0)
    assert _raised_after_the_blocks(report), report.log_lines
    assert "AI-B declared 1 blocker(s)" in game.log
    assert _creatures(game, 0) == ["Zealous Inquisitor"]
    assert _creatures(game, 1) == []


def test_the_creature_a_held_trick_makes_worth_sending_attacks():
    """Against a Hill Giant the Inquisitor's printed body loses the block
    (``_score_block_pair``) and it stayed home. With the redirect held it
    attacks; the Giant blocks, the redirect is raised, and the two trade —
    a 2/2 for a 3/3."""
    game, report = _table(
        ("Zealous Inquisitor", "Plains", "Plains"), other=("Hill Giant", "Mountain"),
        step="precombat_main",
    )
    run_ai_combat_phase(game, 0)
    assert "AI-A declared 1 attacker(s)" in game.log, game.log[-8:]
    assert _raised_after_the_blocks(report), report.log_lines
    assert _creatures(game, 0) == [] and _creatures(game, 1) == []


def test_without_the_mana_for_the_trick_it_stays_home():
    """The negative: the same board with the Plains tapped holds no trick,
    and the printed bodies decide — the Inquisitor does not attack into the
    Giant."""
    game, report = _table(
        ("Zealous Inquisitor", "Plains", "Plains"), other=("Hill Giant", "Mountain"),
        step="precombat_main",
    )
    for permanent in game.controlled_by(0):
        if permanent.card.name == "Plains":
            permanent.tapped = True
    run_ai_combat_phase(game, 0)
    assert "AI-A declared 0 attacker(s)" in game.log or not any(
        "declared 1 attacker" in line for line in game.log
    ), game.log[-8:]
    assert _creatures(game, 0) == ["Zealous Inquisitor"]


def test_the_trick_counting_is_not_asked_outside_the_declare_attackers_step():
    """The rehearsal of an attack is asked only where an attack is being
    declared: from a main phase, the chosen set comes back as it was."""
    game, _report = _table(
        ("Zealous Inquisitor", "Plains", "Plains"), other=("Hill Giant", "Mountain"),
        step="precombat_main",
    )
    assert _attacks_its_held_trick_wins(game, 0, [], [0], 1) == []


@pytest.mark.full
def test_a_seeded_scourge_run_raises_the_redirect_after_the_blocks():
    """Zealous Inquisitor pinned into seeded Scourge decks: the redirect is
    raised in a declare-blockers step at least once, and no rehearsal
    raised. A floor of one, never a count."""
    report = run_ai_simulation(
        manifest_set_path("SCG"), games=4, seed=5, max_turns=16,
        required_cards=["Zealous Inquisitor"],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    assert _raised_after_the_blocks(report), [
        line for line in report.log_lines if "Zealous Inquisitor" in line
    ]
