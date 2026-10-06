"""The web layer's AI seat pays, and reaches, the way the simulator's does.

``web/game_flow._ai_step`` is the second executor of an AI seat's choice (the
simulator's is held by ``tests/ai``). Two things it could not do, and a third
it did wrong, each for want of a line the two executors now share
(``engine.ai_policy.tap_planned_lands`` / ``cast_zone_of``):

* pay with a source that is **sacrificed** — and still announce the target it
  chose, which the sacrifice has moved to another slot;
* cast a card an effect lets it cast from **outside its hand**;
* cast a spell an effect made **free** without tapping lands for it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.ai_policy import choose_cast_action
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store
from web.game_flow import _ai_step

from tests.helpers import resolve_stack

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths()):
    _POOL.setdefault(_card.name, _card)


def _ai_main_phase(battlefield, *, hand=(), graveyard=()):
    """An all-AI session in seat 1's precombat main phase, costs enforced,
    seat 1 holding exactly what the test names."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "guest_name": "AI",
        "host_colors": 2, "guest_colors": 2, "seed": 90210,
    }).json()
    session = store.get(created["session_id"])
    session.seat_types = {0: "ai", 1: "ai"}  # no human: a cast resolves at once
    game = session.game
    game.enforce_mana_costs = True
    session.current_turn = 1
    game.active_player_index = 1
    seat = game.players[1]
    seat.battlefield = []
    game.players[0].battlefield = []
    for name in battlefield:
        permanent = Permanent(card=_POOL[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    seat.hand = [_POOL[name] for name in hand]
    seat.graveyard = [_POOL[name] for name in graveyard]
    game.players[0].hand = []
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.start_priority_window(1)
    return session, game


def test_the_web_ai_pays_with_a_lotus_and_the_aura_lands_where_it_was_aimed():
    session, game = _ai_main_phase(
        ["Black Lotus", "Grizzly Bears", "Hill Giant"], hand=["Holy Strength"],
    )
    # What the policy will name, asked the way `_ai_step` is about to ask it:
    # a host by its slot **behind** the Lotus that pays.
    action = choose_cast_action(game, 1)
    assert action.card_name == "Holy Strength" and action.target_permanent_index > 0
    host = game.permanent_at(1, action.target_permanent_index)
    other = next(p for p in game.controlled_by(1) if p.is_creature and p is not host)
    before = (host.effective_power, other.effective_power)

    _ai_step(session)
    resolve_stack(game)

    assert [c.name for c in game.players[1].graveyard] == ["Black Lotus"], game.log[-6:]
    assert host.effective_power == before[0] + 1, game.log[-6:]
    assert other.effective_power == before[1]


def test_the_web_ai_casts_out_of_its_graveyard_under_yawgmoths_agenda():
    session, game = _ai_main_phase(
        ["Yawgmoth's Agenda", "Forest", "Forest"], graveyard=["Grizzly Bears"],
    )

    _ai_step(session)
    resolve_stack(game)

    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1)), game.log[-6:]
    assert game.players[1].graveyard == []
    assert sum(1 for p in game.controlled_by(1) if p.tapped) == 2


def test_the_web_ai_taps_nothing_for_a_spell_aluren_made_free():
    session, game = _ai_main_phase(["Aluren", "Forest", "Forest"], hand=["Grizzly Bears"])

    _ai_step(session)
    resolve_stack(game)

    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1)), game.log[-6:]
    assert not any(p.tapped for p in game.controlled_by(1))
