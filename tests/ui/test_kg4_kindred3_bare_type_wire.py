"""A bare creature type names a permanent of it on the wire too (CR 109.2,
205.3m).

"{R}: Tap target Wall." (Ali Baba) and "Sacrifice a Goblin" (Arms Dealer) used
to send the creature picker; a bare creature type now records no card type, so
the target spec the client is sent is the general one narrowed by the subtype
(``wall_only`` for a Wall, the carried ``filter`` otherwise) — shapes the
client already answers (a Swamp sacrifice, a type union). What the spec offers
is the engine's list, so an invented Kindred permanent of the type is offered
beside the creatures of it, the creature that is not of it is not, and the id
the client sends is the permanent the ability reaches.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _kindred(name: str, type_line: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


WALL = _kindred("Test Wall Idol", "Kindred Artifact — Wall")
GOBLIN = _kindred("Test Goblin Idol", "Kindred Artifact — Goblin")


def _session(mine=(), theirs=()):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
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
    rows = []
    for seat, cards in enumerate((mine, theirs)):
        row = []
        for card in cards:
            permanent = Permanent(card=_CARDS[card] if isinstance(card, str) else card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            row.append(permanent)
        rows.append(row)
    game.start_priority_window(0)
    return sid, game, rows[0], rows[1]


def _entry(sid, permanent):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0})
    assert state.status_code == 200, state.text
    for seat in state.json()["players"]:
        for entry in seat.get("battlefield") or ():
            if entry.get("id") == permanent.permanent_id:
                return entry
    raise AssertionError("permanent not in the state payload")


def _drain(sid, game):
    for _ in range(6):
        if not game.stack:
            return
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )


def test_ali_baba_is_sent_the_walls_and_taps_the_kindred_one():
    sid, game, (ali,), (idol, wall, bears) = _session(
        ["Ali Baba"], [WALL, "Wall of Stone", "Grizzly Bears"],
    )
    spec = _entry(sid, ali)["target_spec"]
    assert spec["kind"] == "permanent" and spec.get("wall_only") is True, spec
    offered = {entry["name"] for entry in spec["valid_targets"]}
    assert offered == {"Test Wall Idol", "Wall of Stone"}, spec["valid_targets"]

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": ali.permanent_id,
        "target_permanent_id": idol.permanent_id,
    })
    _drain(sid, game)
    assert response.status_code == 200, response.text
    assert idol.tapped and not wall.tapped and not bears.tapped


def test_arms_dealer_is_sent_the_kindred_goblin_as_a_sacrifice():
    sid, game, (dealer, idol), (giant,) = _session(
        ["Arms Dealer", GOBLIN], ["Hill Giant"],
    )
    spec = _entry(sid, dealer)["target_spec"]
    cost = spec["cost_spec"]
    assert cost["kind"] == "permanent" and cost.get("sacrifice_cost") is True, cost
    assert cost["filter"] == {"subtype_filter": "goblin"}, cost
    assert {entry["name"] for entry in cost["valid_targets"]} == {
        "Arms Dealer", "Test Goblin Idol",
    }

    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": dealer.permanent_id,
        "target_permanent_id": giant.permanent_id,
        "cost_permanent_id": idol.permanent_id,
    })
    _drain(sid, game)
    assert response.status_code == 200, response.text
    assert not game.is_on_battlefield(idol) and game.is_on_battlefield(dealer)
    assert not game.is_on_battlefield(giant), game.log[-4:]
