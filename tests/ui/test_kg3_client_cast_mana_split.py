"""A spell's "any combination" mana is split by its caster, on the cast.

Burnt Offering: "As an additional cost to cast this spell, sacrifice a
creature. Add an amount of {B} and/or {R} equal to the sacrificed creature's
mana value." The cast path has taken ``mana_combination`` since W2G3, and
Goblin Clearcutter's *activation* had a chooser (``ability_mana``'s
``combination``), but nothing told the client a spell makes a split, so a
person always got the engine's default (the "Three wire leftovers from
Legions' client group" Known-gaps entry). The hand card now carries
``mana_combination`` — the count each permanent paying the cost would make
it, by id — and the client asks the activation's chooser before the cast is
sent (``castManaSplitFor`` / ``askCastManaSplit`` in ``sendAction``).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _burnt_offering_beside(*creatures):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 5151,
        "host_deck_cards": [{"name": "Swamp", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game.players[1].hand.clear()
    placed = []
    for name in creatures:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        placed.append(permanent)
    game.players[0].hand[:] = [_CARDS["Burnt Offering"]]
    game.start_priority_window(0)
    return sid, game, placed


def _hand_card(sid):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return state, state["players"][0]["hand"][0]


def test_the_hand_card_says_the_split_and_its_count_per_sacrifice():
    sid, _game, (giant, bears) = _burnt_offering_beside("Hill Giant", "Grizzly Bears")
    _state, card = _hand_card(sid)
    assert card["mana_combination"]["symbols"] == ["B", "R"]
    by_cost = card["mana_combination"]["count_by_cost"]
    assert by_cost[str(giant.permanent_id)] == 4
    assert by_cost[str(bears.permanent_id)] == 2
    # Every other card in hand says nothing.
    other = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert all(
        "mana_combination" not in c
        for c in other["players"][1]["hand"] if isinstance(c, dict)
    )


def test_the_split_the_caster_names_is_the_mana_they_get():
    sid, game, (giant,) = _burnt_offering_beside("Hill Giant")
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Burnt Offering", "hand_index": 0,
        "cost_permanent_id": giant.permanent_id,
        "mana_combination": {"B": 1, "R": 3},
    })
    assert cast.status_code == 200, cast.text
    resolve_stack(game)
    pool = game.players[0].mana_pool
    assert (pool.get("B", 0), pool.get("R", 0)) == (1, 3), pool
    assert any("Burnt Offering produced {B}{R}{R}{R}" in line for line in game.log), game.log[-6:]


def test_the_client_asks_the_split_for_the_creature_it_sacrifices():
    sid, _game, (giant, bears) = _burnt_offering_beside("Hill Giant", "Grizzly Bears")
    state, _card = _hand_card(sid)
    asked = run_app_js(
        ["castManaSplitFor"],
        "seat = 0; return INPUT.bodies.map((b) => castManaSplitFor(b, INPUT.state));",
        {
            "state": state,
            "bodies": [
                {"action": "cast", "card_name": "Burnt Offering", "hand_index": 0,
                 "cost_permanent_id": bears.permanent_id},
                {"action": "cast", "card_name": "Burnt Offering", "hand_index": 0,
                 "cost_permanent_id": giant.permanent_id, "mana_combination": {"B": 4}},
                {"action": "cast", "card_name": "Burnt Offering", "hand_index": 0},
            ],
        },
        prelude="let seat = null;",
    )
    assert asked[0]["combination"] == {"symbols": ["B", "R"], "count": 2}
    assert asked[1] is None, "a body that already names its split is not asked again"
    assert asked[2] is None, "no cost named, no count to split"
