"""A remove-a-counter cost, paid by the AI where what it buys is worth the counter.

"{1}{R}, Remove a +1/+1 counter or a charge counter from a permanent you
control: This enchantment deals 2 damage to any target." (Ion Storm.) "{T},
Remove a counter from a permanent you control: Choose one — …" (Power
Conduit.) "{2}, Remove a +1/+1 counter from a creature you control: Put a
+1/+1 counter on this creature." (Spike Rogue.) The activation chooser
declined every such cost (SET_PLAYBOOK's Known gaps, "AI leftovers"); each
permanent and kind of counter the cost may take is now rehearsed with the
whole cost paid (``ai_activation_rehearsal._counter_priced_activation``), the
choice named on ``ActivationAction.cost_permanent_ids`` / ``cost_counter_kind``,
and a counter the standing reads nothing for priced on top
(``ai_counter_costs.spent_counter_worth``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_actions import activation_announcement
from engine.ai_counter_costs import SPENT_COUNTER_WORTH, spent_counter_worth
from engine.ai_payment import tap_planned_lands
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from engine.pt import add_pt_counters
from tests.helpers import settle


def _table(set_pool, mine) -> tuple[Game, dict]:
    pool = {**set_pool("LEA"), **set_pool("MRD"), **set_pool("EXO"), **set_pool("5DN")}
    game = Game(players=[
        PlayerState(name="AI", library=[pool["Forest"]] * 8),
        PlayerState(name="Opp", library=[pool["Forest"]] * 8),
    ])
    game.interactive_seats = set()
    placed: dict = {}
    for name in mine:
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.setdefault(name, permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    game.enforce_mana_costs = True
    return game, placed


def _activate(game, action) -> None:
    action = tap_planned_lands(game, 0, action)
    result = game.activate_permanent_ability(
        0, action.permanent_name, **activation_announcement(action),
    )
    assert result.supported, result
    settle(game)


def test_ion_storm_spends_a_charge_counter_for_the_last_two_life(set_pool):
    """Pentad Prism holds two charge counters and the opponent has 2 life:
    Ion Storm is activated at the opponent, paid with one of the Prism's
    charge counters, and the game is over."""
    game, placed = _table(set_pool, ["Mountain", "Mountain", "Ion Storm", "Pentad Prism"])
    prism = placed["Pentad Prism"]
    add_counters(prism, "charge", 2)
    game.players[1].life = 2
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Ion Storm"
    assert action.cost_permanent_ids == [prism.permanent_id]
    assert action.cost_counter_kind == "charge"
    _activate(game, action)
    assert counters_on(prism, "charge") == 1
    assert game.players[1].life <= 0


def test_a_creatures_counter_is_not_spent_on_two_life(set_pool):
    """A Grizzly Bears with a +1/+1 counter is the only thing Ion Storm could
    be paid with, and the opponent is at 20: two life is worth less than the
    counter (the standing reads the smaller body). Not activated."""
    game, placed = _table(set_pool, ["Mountain", "Mountain", "Ion Storm", "Grizzly Bears"])
    add_pt_counters(placed["Grizzly Bears"], "+1/+1", 1)
    action = choose_activation_action(game, 0)
    assert action is None or action.permanent_name != "Ion Storm"


def test_power_conduit_turns_a_spare_charge_counter_into_a_bigger_creature(set_pool):
    """Power Conduit beside a Pentad Prism with one charge counter and a
    Grizzly Bears: the charge counter comes off the Prism and a +1/+1 counter
    goes on the Bears (the second mode), named by kind and permanent."""
    game, placed = _table(set_pool, ["Power Conduit", "Pentad Prism", "Grizzly Bears"])
    prism, bears = placed["Pentad Prism"], placed["Grizzly Bears"]
    add_counters(prism, "charge", 1)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Power Conduit"
    assert action.target_permanent_ids == [bears.permanent_id]
    assert (action.cost_permanent_ids, action.cost_counter_kind) == ([prism.permanent_id], "charge")
    _activate(game, action)
    assert counters_on(prism, "charge") == 0
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_spike_rogue_does_not_shuttle_a_counter_for_nothing(set_pool):
    """Spike Rogue with two +1/+1 counters beside a Grizzly Bears with one:
    moving the Bears' counter onto the Rogue for {2} is a counter moved and
    two mana spent, and the board's total is what it was. Never proposed."""
    game, placed = _table(set_pool, ["Forest", "Forest", "Spike Rogue", "Grizzly Bears"])
    add_pt_counters(placed["Spike Rogue"], "+1/+1", 2)
    add_pt_counters(placed["Grizzly Bears"], "+1/+1", 1)
    action = choose_activation_action(game, 0)
    assert action is None or action.cost_counter_kind is None


def test_what_a_counter_is_worth_beyond_the_standing(set_pool):
    """A +1/+1 counter is the standing's (the body it sizes); a charge counter
    its own permanent spends is a mana's worth; one nothing on its permanent
    reads is nothing; an age counter's loss is a relief."""
    game, placed = _table(set_pool, ["Pentad Prism", "Grizzly Bears", "Ion Storm"])
    assert spent_counter_worth(placed["Grizzly Bears"], "+1/+1") == 0.0
    assert spent_counter_worth(placed["Pentad Prism"], "charge") == SPENT_COUNTER_WORTH
    assert spent_counter_worth(placed["Ion Storm"], "charge") == 0.0
    assert spent_counter_worth(placed["Grizzly Bears"], "age") == -SPENT_COUNTER_WORTH
