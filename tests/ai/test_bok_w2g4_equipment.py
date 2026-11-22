"""The AI equips an Equipment whose equip is not its first ability, and spends
what it charges.

Umezawa's Jitte prints three modes before its "Equip {2}", so its equip is
the fourth ability the engine lists. The main-phase chooser
(``ai_abilities._activation_candidate``) proposed a later ability only where a
rehearsal measured a lasting gain (``_land_ability_worth``), and an attachment
with no static bonus is none — the Jitte's worth is the counters its combat
trigger puts on it — so it was cast three times in six games and never once
equipped (BOK W1G9). An equip's creature is chosen by ``_choose_equip_target``
wherever the equip is printed, which declines when the Equipment is already on
the best creature; it is now asked the question an equip printed first is.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_policy import activate_chosen_ability
from engine.equipment import attach_equipment, equipped_creature
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from tests.helpers import _nosick, settle


def _table(set_pool, *, theirs=(), charge: int = 0, attached: bool = False):
    """Umezawa's Jitte and a Grizzly Bears under P1, two Plains to pay with,
    *theirs* (LEA cards) under P2; the Jitte holding *charge* counters, and on
    the Bears if *attached*. P1's first main phase, costs enforced."""
    lea, bok = set_pool("LEA"), set_pool("BOK")
    jitte = Permanent(card=bok["Umezawa's Jitte"])
    bears = _nosick(Permanent(card=lea["Grizzly Bears"]))
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[_nosick(Permanent(card=lea["Plains"])) for _ in range(2)] + [jitte, bears],
            library=[lea["Plains"]] * 5,
        ),
        PlayerState(
            name="P2",
            battlefield=[_nosick(Permanent(card=lea[name])) for name in theirs],
            library=[lea["Forest"]] * 5,
        ),
    ])
    game.enforce_mana_costs = True
    game._settle()
    if charge:
        add_counters(jitte, "charge", charge)
    if attached:
        assert attach_equipment(game, jitte, bears)
    game.start_turn(0)
    game._settle()
    return game, jitte, bears


def test_the_jitte_is_equipped_though_its_equip_is_printed_last(set_pool):
    """Unattached, with a creature to carry it: the seat pays {2} to equip
    the Bears — the fourth ability, aimed at its own creature."""
    game, jitte, bears = _table(set_pool)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Umezawa's Jitte"
    assert action.ability_index == 3
    result = activate_chosen_ability(game, 0, action)
    assert result.supported, result.details
    settle(game)
    assert equipped_creature(jitte) is bears


def test_an_equipped_jitte_is_not_moved_onto_the_creature_it_is_on(set_pool):
    """Already on the only creature: nothing to move it to, so the {2} is not
    spent every main phase re-equipping the same Bears."""
    game, jitte, bears = _table(set_pool, attached=True)
    action = choose_activation_action(game, 0)
    assert action is None or action.ability_index != 3
    assert equipped_creature(jitte) is bears


def test_a_charged_jitte_shrinks_an_opposing_creature_to_death(set_pool):
    """Equipped and holding two charge counters, with a Llanowar Elves across
    the table: the "-1/-1" mode is aimed at the Elves, a counter is removed
    and the Elves die (CR 704.5f)."""
    game, jitte, _bears = _table(set_pool, theirs=["Llanowar Elves"], charge=2, attached=True)
    (elves,) = list(game.controlled_by(1))
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Umezawa's Jitte"
    assert list(action.target_permanent_ids or ()) == [elves.permanent_id]
    result = activate_chosen_ability(game, 0, action)
    assert result.supported, result.details
    settle(game)
    assert counters_on(jitte, "charge") == 1
    assert not list(game.controlled_by(1))
    assert [card.name for card in game.players[1].graveyard] == ["Llanowar Elves"]


@pytest.mark.full
def test_a_seeded_game_equips_the_jitte_charges_it_and_spends_a_counter():
    """The simulator plays the engine's turn: with the Jitte pinned into both
    decks (seed 1, ten turns, measured), it is equipped, its combat trigger
    charges it and a mode spends a counter. A floor of one each — the subject
    was exercised — and nothing refused."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        manifest_set_path("BOK", include_measured=True), games=1, seed=1,
        max_turns=10, required_cards=["Umezawa's Jitte"],
    )
    lines = report.log_lines
    assert any("Umezawa's Jitte is now attached to" in line for line in lines)
    assert any("Umezawa's Jitte gets 2 charge counters" in line for line in lines)
    assert any(
        "from Umezawa's Jitte" in line or "Umezawa's Jitte gives" in line
        or "Umezawa's Jitte grants" in line
        for line in lines
    )
    assert not report.refused_activations, report.refused_activations
    assert not report.refused_instant_activations, report.refused_instant_activations
    assert not report.rehearsals_raised, report.rehearsals_raised
