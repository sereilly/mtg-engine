"""CR 616.1e for an entry, through the web layer.

Since round kg5 `asks` an entry two "would enter" replacements contend for is
put to the player who will control the permanent
(``tests/regressions/test_kg5_asks_contended_entry.py`` is the engine's
census). This is the check that a person playing Lake of the Dead with no
Swamp, under an opponent's Land Equilibrium, is shown the question — and
nobody can act around it — and that the answer is what happens.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_SHIPPED = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4246,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _put(game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_SHIPPED[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.pending_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _names(cards) -> list[str]:
    return [card.name for card in cards]


@pytest.mark.parametrize("option, lands_left", [
    (0, 2),   # the Lake's own toll first: it goes to the graveyard, nothing else
    (1, 1),   # Land Equilibrium first: the toll then takes the entry, not the land owed
])
def test_a_contended_land_play_asks_its_player_and_the_answer_is_what_happens(
    option, lands_left,
):
    sid, game = _session()
    _put(game, 0, "Forest")
    _put(game, 0, "Forest")
    _put(game, 1, "Land Equilibrium")
    _put(game, 1, "Forest")
    game.players[0].hand = [_SHIPPED["Lake of the Dead"]]

    played = _act(sid, seat=0, action="cast", card_name="Lake of the Dead")
    assert played.status_code == 200, played.text

    state = _state(sid)
    prompt = state["effect_order"]
    assert prompt is not None, "armed and never rendered"
    assert prompt["player_seat"] == 0
    assert prompt["event_kind"] == "would_enter_battlefield"
    assert len(prompt["options"]) == 2
    assert "Lake of the Dead" in prompt["options"][0]
    assert "Land Equilibrium" in prompt["options"][1]
    assert state["waiting_on_prompt"] is True
    # The land is on its way, in no zone, while its player chooses.
    assert _names(game.players[0].hand) == [] and _names(game.players[0].graveyard) == []
    assert not any(p.card.name == "Lake of the Dead" for p in game.all_permanents())
    assert _state(sid, seat=1)["effect_order"] is None
    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 400

    answered = _act(sid, seat=0, action="effect_order_confirm", option_index=option)
    assert answered.status_code == 200, answered.text
    owed = _state(sid)["sacrifice_select"]
    if option == 1:
        # Land Equilibrium's rider: the seat picks which land goes.
        assert owed is not None and owed["player_seat"] == 0, owed
        land = next(p for p in game.controlled_by(0) if p.has_type("land"))
        picked = _act(
            sid, seat=0, action="sacrifice_confirm",
            sacrifice_permanent_ids=[land.permanent_id],
        )
        assert picked.status_code == 200, picked.text
    else:
        assert owed is None, owed
    assert "Lake of the Dead" in _names(game.players[0].graveyard)
    assert sum(
        1 for p in game.controlled_by(0) if p.has_type("land")
    ) == lands_left
    assert not game.effect_order_answers
