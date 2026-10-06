"""A simulated seat's ability activated from hand resolves where it was activated.

`simulate_ai_games.py --set USG` (and ULG, and UDS) exited 1 from the day the
`steps_left_owing` count existed: 3, 10 and 3 step changes in ten games "ended
with something still owed", every one a **cycling ability on the stack as the
precombat main phase ended**. `Game.activate_from_hand` is the queue form — the
web's, which leaves the ability up for the table to respond to — and the
simulator called it and moved on, where the battlefield pass beside it calls
`activate_permanent_ability`, which settles what it queues. Only the three
Urza's sets print the keyword on enough cards for a ten-game run to show it,
so every other set read clean.

Beside it, the one "activation the engine declined" the same runs reported:
the seat paid Phyrexian Reclamation's 2 life every main phase down to 1 and
then proposed it once more (CR 119.4).
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import PlayerState
from engine.ai_policy import ACTIVATION_LIFE_RESERVE, choose_activation_action
from engine.ai_simulator import (SimulationReport, _play_activations,
                                 _SimulatedGame, run_ai_simulation)
from engine.card_loader import manifest_set_path
from engine.models import Permanent


def _main_phase_table(catalog_by_name, *, hand=(), board=(), graveyard=(), life=20):
    named = catalog_by_name
    seat = PlayerState(
        name="A", life=life,
        hand=[named[name] for name in hand],
        graveyard=[named[name] for name in graveyard],
        library=[named["Forest"]] * 10,
    )
    game = _SimulatedGame(players=[seat, PlayerState(name="B", library=[named["Forest"]] * 10)])
    for name in board:
        permanent = Permanent(card=named[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.summoning_sick = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_a_cycled_card_has_resolved_before_the_pass_that_cycled_it_returns(catalog_by_name):
    game = _main_phase_table(
        catalog_by_name, hand=["Drifting Meadow"], board=["Swamp", "Swamp"],
    )
    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)

    _play_activations(game, 0, report, 1, 1)

    assert any("Drifting Meadow from hand" in line for line in report.log_lines), (
        "the seat should have cycled the land: nothing else to do with two Swamps"
    )
    assert not game.stack, "the cycling ability is still on the stack"
    seat = game.players[0]
    assert [card.name for card in seat.graveyard] == ["Drifting Meadow"]
    assert [card.name for card in seat.hand] == ["Forest"], "and its card was drawn"
    # The instrument itself: leaving the step now finds nothing owed.
    game._set_phase_and_step("combat", "beginning_of_combat")
    assert not {
        what: count for what, count in game._steps_left_owing.items()
        if what != "_examined"
    }


@pytest.mark.slow
@pytest.mark.parametrize("code", ["USG", "ULG", "UDS"])
def test_no_urzas_block_simulation_leaves_a_cycle_on_the_stack(code):
    """The run the script makes, on the three sets that exited 1 — ten games at
    the default seed, where the old tree counted 3, 10 and 3."""
    report = run_ai_simulation(
        manifest_set_path(code, include_measured=True), games=10, seed=1337,
    )

    cycled = sum("from hand" in line for line in report.log_lines)
    assert cycled >= 3, f"only {cycled} hand activation(s): the run did not exercise the keyword"
    assert report.steps_left_owing == Counter(), dict(report.steps_left_owing)


def test_the_seat_keeps_a_reserve_when_its_own_ability_costs_life(catalog_by_name):
    """Phyrexian Reclamation: "{1}{B}, Pay 2 life: Return target creature card
    from your graveyard to your hand."""
    def proposal(life):
        game = _main_phase_table(
            catalog_by_name, life=life, graveyard=["Grizzly Bears"],
            board=["Phyrexian Reclamation", "Swamp", "Swamp"],
        )
        return choose_activation_action(game, 0)

    healthy = proposal(20)
    assert healthy is not None and healthy.permanent_name == "Phyrexian Reclamation"
    assert proposal(ACTIVATION_LIFE_RESERVE + 2) is not None
    assert proposal(ACTIVATION_LIFE_RESERVE + 1) is None
    assert proposal(1) is None, "CR 119.4: a seat at 1 life cannot pay 2"
