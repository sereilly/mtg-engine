"""A landcycle for a land the seat does not need is not proposed (kg4 aivalue).

SCG's wave 2 saw a seat return Eternal Dragon from its graveyard in its
upkeep for {3}{W}{W} and plainscycle it for {2} with what was left, three
turns running (seed 11, game 1, turns 9-11), with ten lands on the table.
Re-measured on 313bd09d the loop is the **cycle**, not the return: the
hand chooser (``ai_hand_activations``) proposes what its rehearsal does not
read as harmful, and a standing prices every card in hand alike
(``ai_rehearsal.CARD_WORTH``), so plainscycling a seven-drop the seat could
cast next turn for its eleventh land read as a card out and a card in —
nothing — at a flat 2.5. A graveyard-recursion value (the brief's guess)
would have made that cycle read *better*: the Dragon in the yard would be
worth something and the Plains still a card.

The standing prices a land on the battlefield beyond the six a seat is
counted as needing at ``SPARE_LAND_WORTH``; a search that can only find a
land, made when the seat's lands are already more than that, now pays the
difference (``ai_rehearsal.spare_land_find_price``, read off the seat's own
library through ``search_matches``).

Validated backwards: with the price answering 0 (the base), the census finds
every landcycler proposed for a spare land, and the seeded drive finds the
return-and-cycle turn.
"""

from __future__ import annotations

from unittest import mock

import pytest

from engine import ai_hand_activations, ai_rehearsal
from engine.ai_hand_activations import choose_hand_activation_action
from engine.ai_simulator import run_ai_simulation
from engine.ai_weighed_cast import _effect_steps
from engine.activation_zones import HAND
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


@pytest.fixture(scope="module")
def pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _no_price(game, seat, searches) -> float:
    return 0.0


def _land_cyclers(pool) -> list:
    """``(card, basic it finds)`` for every supported card of both manifest
    roles whose first ability from a hand is a cycle that searches for a
    basic land type and does nothing else (plainscycling, swampcycling …)."""
    rows = []
    for name, card in sorted(pool.items()):
        if card.primary_type == "land":
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand or from_hand[0].instruction is None:
            continue
        steps = _effect_steps(from_hand[0].instruction)
        searches = [step for step in steps if step.kind == "search_library"]
        if len(searches) != 1 or len(steps) != 1:
            continue
        text = repr(searches[0].payload).lower()
        found = [basic for basic in _BASICS if basic.lower() in text]
        if len(found) != 1:
            continue
        rows.append((card, found[0]))
    return rows


def _table(pool, card, basic: str, lands: int) -> Game:
    """*card* in seat 0's hand, *lands* of *basic* on its battlefield with
    exactly two untapped — the cycle's {2} — and a library holding more."""
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for index in range(lands):
        land = _nosick(Permanent(card=pool[basic]))
        land.tapped = index >= 2
        game.players[0].battlefield.append(land)
    game.players[0].hand = [card]
    game.players[0].library = [pool[basic]] * 5 + [pool["Grizzly Bears"]] * 5
    game.players[1].library = [pool["Island"]] * 10
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "postcombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def _census(pool) -> dict:
    found = {"examined": [], "cycled_for_a_spare": [], "cycled_for_a_need": []}
    for card, basic in _land_cyclers(pool):
        found["examined"].append(card.name)
        spare = choose_hand_activation_action(_table(pool, card, basic, 8), 0)
        if spare is not None and spare.card_name == card.name:
            found["cycled_for_a_spare"].append(card.name)
        needed = choose_hand_activation_action(_table(pool, card, basic, 3), 0)
        if needed is not None and needed.card_name == card.name:
            found["cycled_for_a_need"].append(card.name)
    return found


def test_no_card_is_landcycled_for_a_land_the_seat_does_not_need(pool):
    found = _census(pool)
    assert found["cycled_for_a_spare"] == [], found
    # Floors: how much the census read, and that landcycling still happens
    # where the land is one the seat needs.
    assert len(found["examined"]) >= 6, found
    assert "Eternal Dragon" in found["examined"], found
    assert set(found["cycled_for_a_need"]) == set(found["examined"]), found


def test_without_the_price_the_census_finds_every_cycle(pool):
    """Backwards: the find unpriced, as on 313bd09d."""
    with mock.patch.object(ai_hand_activations, "spare_land_find_price", _no_price):
        found = _census(pool)
    assert set(found["cycled_for_a_spare"]) == set(found["examined"]), found


def test_the_price_is_the_finds_and_the_seats(pool):
    """Priced only where every card the search can find is a land and the
    seat's lands, the find among them, are more than it needs: a Plains at
    six lands out, nothing at three, nothing for a search that could find a
    creature."""
    from engine.ai_valuation import land_searches

    dragon = pool["Eternal Dragon"]
    cycle = usable_activated_abilities(compile_card_oracle(dragon), zone=HAND)[0]
    searches = land_searches(cycle.instruction)
    assert searches
    spare = ai_rehearsal.CARD_WORTH - ai_rehearsal.SPARE_LAND_WORTH
    assert ai_rehearsal.spare_land_find_price(
        _table(pool, dragon, "Plains", 6), 0, searches,
    ) == pytest.approx(spare)
    assert ai_rehearsal.spare_land_find_price(_table(pool, dragon, "Plains", 3), 0, searches) == 0
    assert ai_rehearsal.spare_land_find_price(_table(pool, dragon, "Plains", 6), 0, ()) == 0


# --- the board the entry names ------------------------------------------------


def _returned_then_cycled(report) -> list:
    """``(game, turn, seat)`` for each turn in which a seat both returned
    Eternal Dragon from its graveyard and cycled it."""
    returned, cycled = set(), set()
    for line in report.log_lines:
        if not line.startswith("G") or " T" not in line[:8]:
            continue
        game_turn, _, rest = line.partition(" ")
        turn, _, rest = rest.partition(" ")
        seat = rest.split(" ", 1)[0]
        key = (game_turn, turn, seat)
        if "activate Eternal Dragon from graveyard" in rest:
            returned.add(key)
        elif "activate Eternal Dragon from hand" in rest:
            cycled.add(key)
    return sorted(returned & cycled)


def _drive():
    returns, loops = 0, []
    for seed in (11, 13):
        report = run_ai_simulation(
            manifest_set_path("SCG"), games=1, seed=seed, max_turns=14,
            required_cards=("Eternal Dragon",),
        )
        returns += report.activations_from_graveyard.get("Eternal Dragon", 0)
        loops.extend(_returned_then_cycled(report))
    return returns, loops


@pytest.mark.full
def test_eternal_dragon_is_not_returned_and_cycled_in_one_turn():
    returns, loops = _drive()
    assert loops == [], loops
    assert returns >= 1  # the road back was taken: the subject was exercised


@pytest.mark.full
def test_without_the_price_the_seeded_games_loop():
    with mock.patch.object(ai_hand_activations, "spare_land_find_price", _no_price):
        _returns, loops = _drive()
    assert loops, "the base's return-and-cycle turn did not reappear"
