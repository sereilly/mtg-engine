"""The census behind round 4's priority windows: instants a simulated seat
casts outside its own main phase, read at the engine's own cast seam.

**The defect.** No instant had ever been cast in a simulated game in response
to anything, during combat, or on the opponent's turn. The engine's headless
priority window was "both players pass in succession", so the stack drained
and nobody was asked; a simulated seat cast in its own main phases and nowhere
else.

**Measured on the base tree (main at 393ce8f4) before the change**, over the
seven seeded runs (`simulate_ai_games.py --games 10 --seed 1337` for LEA, MIR,
USG, INV, PLS, 7ED and M21), by an instrument that gives every seat priority
where CR 117.3-117.4 would — before each resolution, and at each step's end
for the seat whose turn it is not — and asks whether it then held an instant
it could pay for:

* 24,248 times a seat would have received priority with an object on the
  stack that was not its own, or in a step of the opponent's turn; in 9,967
  of them it held an instant whose mana its lands could pay. 2,663 / 1,073 of
  those were another seat's object on the stack, 1,970 / 816 the declare
  blockers step, 1,925 / 789 the opponent's end step.
* **273 instants were cast across the seven runs, and 0 of them outside
  their caster's own main phase.** This spy reads 0 on that tree, which is
  the backwards validation: the same count over the same seam.

Each test below reads one seeded run with every real (non-rehearsal) cast
recorded as it goes on the stack, independently of the report, and holds the
report's honesty counts to what the spy saw. The floors are what keep a later
change that quietly closes the windows from passing: a run in which the
windows exist and nothing is cast in one reads exactly as a run with none.
"""
from collections import Counter

import pytest

from engine.ai_simulator import run_ai_simulation
from engine.ai_valuation import rehearsing
from engine.card_loader import manifest_set_path
from engine.game import Game

#: The run: small enough to keep the suite's cost down (two games, about
#: twenty seconds), and one in which a cast lands in each of the three views
#: on the tree this was written against — a Seedling Charm and a Power Sink
#: in response, a Fog in the declare-blockers step, all on the opponent's
#: turn. The end-step window is held by its own board in
#: ``test_ai_instant_speed_windows.py``.
_RUN = dict(code="MIR", games=2, seed=1337, max_turns=10)


@pytest.fixture(scope="module")
def _census():
    seen: Counter = Counter()
    original = Game.queue_from_hand

    def queue_from_hand(self, caster_index, card_name, *args, **kwargs):
        if rehearsing():
            return original(self, caster_index, card_name, *args, **kwargs)
        stack_before = len(self.stack)
        own_main = (
            caster_index == self.active_player_index
            and self.current_step in ("precombat_main", "postcombat_main")
            and not self.stack
        )
        phase = self.current_turn_phase
        off_turn = caster_index != self.active_player_index
        result = original(self, caster_index, card_name, *args, **kwargs)
        if not result.supported:
            return result
        spell = next(
            (item.card for item in reversed(self.stack)
             if not item.is_ability and item.card.name == card_name),
            None,
        )
        if spell is None or spell.primary_type != "instant":
            return result
        seen["instants"] += 1
        if own_main:
            return result
        seen["outside_own_main"] += 1
        seen["in_response"] += stack_before > 0
        seen["in_combat"] += phase == "combat"
        seen["on_opponents_turn"] += off_turn
        return result

    Game.queue_from_hand = queue_from_hand
    try:
        report = run_ai_simulation(
            manifest_set_path(_RUN["code"]), games=_RUN["games"],
            seed=_RUN["seed"], max_turns=_RUN["max_turns"],
        )
    finally:
        Game.queue_from_hand = original
    return report, seen


def test_instants_are_cast_outside_their_casters_main_phase(_census):
    """The defect's own number, 0 of 273 on the base tree: here, instants
    cast in response, in combat and on the opponent's turn, each at least
    once in a short run."""
    report, seen = _census
    assert seen["outside_own_main"] >= 3, dict(seen)
    assert seen["in_response"] >= 1, dict(seen)
    assert seen["in_combat"] >= 1, dict(seen)
    assert seen["on_opponents_turn"] >= 3, dict(seen)
    assert not report.issues, [issue.message for issue in report.issues]
    assert not report.steps_left_owing, dict(report.steps_left_owing)


def test_the_report_counts_what_the_cast_seam_saw(_census):
    """``SimulationReport``'s three views of those casts are the spy's,
    exactly — the honesty count reports what happened, not what the driver
    believes it did."""
    report, seen = _census
    assert report.casts_in_response == seen["in_response"]
    assert report.casts_in_combat == seen["in_combat"]
    assert report.casts_on_opponents_turn == seen["on_opponents_turn"]
    assert not report.refused_instant_casts, dict(report.refused_instant_casts)


def test_the_windows_were_offered_and_weighed(_census):
    """The floor on what was examined: priority offered in the simulator's
    windows, and the chooser asked where the seat held an instant it could
    pay for. A zero here would make every number above a statement about
    nothing."""
    report, _seen = _census
    assert report.priority_offers >= 80, report.priority_offers
    assert report.priority_offers_weighed >= 10, report.priority_offers_weighed
    assert report.priority_offers_weighed <= report.priority_offers
