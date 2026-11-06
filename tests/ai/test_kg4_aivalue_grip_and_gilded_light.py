"""Grip of Chaos and Gilded Light's spell half are cast (kg4 aivalue).

The playbook's entry, from SCG's W1G8: "Grip of Chaos and Gilded Light's
spell half are never cast (the rehearsal reads no gain)". Re-measured on
313bd09d, neither half holds:

* Grip of Chaos is a permanent, and a permanent's cast is not rehearsed
  (``ai_scoring._score_cast`` scores it by what it is), so the cast chooser
  proposes it whenever it can be paid for — and with nothing better to cast,
  casts it.
* Gilded Light ("You gain shroud until end of turn") is fleeting in its
  caster's own main phase with nothing aimed at it, and is held there — the
  right answer. In response to a spell aimed at its caster the rehearsal
  resolves the stack and reads the spell countered on resolution (CR 608.2b:
  its only target is illegal), and the instant-speed chooser casts it.

These hold the corrected reading, the response driven through the engine's
priority seam (``Game.priority_driver`` answered by
``ai_priority.act_at_priority``, as the simulator answers it).
"""

from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.ai_priority import act_at_priority
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick


@pytest.fixture(scope="module")
def pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _table(pool, own, other, hand, *, active: int) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=pool[name])))
    for player in game.players:
        player.library = [pool["Island"]] * 10
    game.players[0].hand = [pool[name] for name in hand]
    game.active_player_index = active
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(active)
    return game


def test_grip_of_chaos_is_cast_when_it_is_what_the_seat_can_cast(pool):
    game = _table(pool, ["Mountain"] * 6, ["Grizzly Bears"], ["Grip of Chaos"], active=0)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Grip of Chaos"


def test_gilded_light_is_held_with_nothing_aimed_at_its_caster(pool):
    game = _table(pool, ["Plains", "Plains"], ["Grizzly Bears"], ["Gilded Light"], active=0)
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Gilded Light"


def test_gilded_light_answers_a_lava_axe_aimed_at_its_caster(pool):
    """The opponent casts Lava Axe at the AI seat; before it resolves the
    engine gives priority (CR 117.3b), the AI's answer casts Gilded Light,
    and the Axe is countered on resolution for want of a legal target."""
    game = _table(pool, ["Plains", "Plains"], ["Mountain"] * 5, ["Gilded Light"], active=1)
    game.players[1].hand = [pool["Lava Axe"]]
    answered = []

    def driver(table, seat):
        if seat != 0:
            return False
        act = act_at_priority(table, seat)
        if act is not None:
            answered.append(act.kind)
        return act is not None

    game.priority_driver = driver
    game.players[1].mana_pool["R"] = 5
    result = game.cast_from_hand(1, "Lava Axe", target_player_index=0)
    assert result.supported, result.details
    assert answered == ["cast"], game.log[-8:]
    assert game.players[0].life == 20, game.log[-8:]
    assert "Gilded Light" in [card.name for card in game.players[0].graveyard]
    assert not game.stack, game.log[-8:]
