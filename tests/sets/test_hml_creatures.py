"""Per-card tests for Homelands' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G5: upkeep, counters and forced sacrifice ---

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on


def _w1g5_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _w1g5_caravan(set_pool, *, active_seat: int, counters: int = 3):
    """Trade Caravan and a tapped Plains, on the seat whose upkeep is not
    running unless *active_seat* says so."""
    caravan = Permanent(card=set_pool("HML")["Trade Caravan"])
    caravan.metadata["summoning_sickness_turn"] = -99
    land = Permanent(card=_w1g5_lea()["Plains"])
    p1 = PlayerState(name="P1", battlefield=[caravan, land])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(active_seat)
    game._settle()
    game.current_step = "upkeep"
    add_counters(caravan, "currency", counters - counters_on(caravan, "currency"))
    land.tapped = True
    return game, caravan, land


def test_trade_caravan_banks_a_currency_counter_each_upkeep(set_pool):
    """"At the beginning of your upkeep, put a currency counter on this
    creature." The counters are what the untap is bought with, so a Caravan that
    banked none can never use its ability."""
    caravan = Permanent(card=set_pool("HML")["Trade Caravan"])
    game = Game(players=[PlayerState(name="P1", battlefield=[caravan]),
                         PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()

    assert counters_on(caravan, "currency") == 1


def test_trade_caravan_untaps_a_basic_land_on_an_opponents_upkeep(set_pool):
    """"Remove two currency counters from this creature: Untap target basic
    land. Activate only during an opponent's upkeep." """
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=1)

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert not land.tapped
    assert counters_on(caravan, "currency") == 1


def test_trade_caravan_is_refused_on_its_own_controllers_upkeep(set_pool):
    """The printed window is an **opponent's** upkeep, and an unenforced timing
    clause is an ability that works more often than the card allows.

    The counters are the other half of the assertion: CR 602.5 forbids the
    activation from *beginning*, so nothing in CR 601.2's steps happens and the
    cost is not paid. This engine charged a counter-removal cost above the
    timing gate, so a Caravan refused here used to lose two counters for it.
    """
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=0)
    held = counters_on(caravan, "currency")

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert not result.supported
    assert land.tapped
    assert counters_on(caravan, "currency") == held


def test_trade_caravan_is_refused_outside_an_upkeep_step(set_pool):
    """An opponent's *turn* is not an opponent's *upkeep*: the clause names a
    step, and a window widened to the whole turn is the same silent gift."""
    game, caravan, land = _w1g5_caravan(set_pool, active_seat=1)
    game.current_step = None
    game.current_turn_phase = "precombat_main"

    result = game.activate_permanent_ability(
        0, "Trade Caravan", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert not result.supported
    assert land.tapped
