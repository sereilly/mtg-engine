"""A stack object's permanent target on the wire is the permanent it chose,
read by id — never whatever has since moved into the slot it held.

Found in Onslaught's post-promotion pass: Chain of Vapor cast at the human's
own Daru Lancer returned it, then waited on the stack for "that permanent's
controller may sacrifice a land … copy this spell". While it waited, the
spell's ``target_permanent_name`` read "Wirewood Elf" and its arrow pointed at
the Elf — the permanent that now sat in the Lancer's old battlefield slot —
and the copy's prompt said "click the copy's current target to leave it where
it is" over the wrong creature. The engine resolves targets by id
(``StackItem.target_permanent_id``); the serializer read the announced slot
(``target_permanent_index``), which nothing renumbers. The same held for any
target that left in response (a Shock's creature sacrificed or bounced) and
for a target whose board lost a permanent ahead of it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session_with_shock_on_the_stack(theirs, target_name):
    """Seat 0 has cast Shock at the AI's *target_name*; the stack holds it."""
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Mountain", "count": 40}],
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
    permanents = {}
    for name in theirs:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        permanents[name] = permanent
    game.players[0].hand.append(_CARDS["Shock"])
    game.start_priority_window(0)
    target = permanents[target_name]
    cast = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Shock",
        "hand_index": len(game.players[0].hand) - 1,
        "target_permanent_id": target.permanent_id,
    })
    assert cast.status_code == 200, cast.text
    assert [item.card.name for item in game.stack] == ["Shock"]
    return sid, game, permanents


def _shock(sid, seat=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(item for item in state["stack"] if item["label"] == "Shock")


def test_a_target_that_left_names_nothing_rather_than_its_old_slots_new_tenant():
    sid, game, permanents = _session_with_shock_on_the_stack(
        ["Grizzly Bears", "Hill Giant"], "Grizzly Bears",
    )
    bears, giant = permanents["Grizzly Bears"], permanents["Hill Giant"]
    item = _shock(sid)
    assert item["target_permanent_name"] == "Grizzly Bears"
    bears_slot = game.battlefield_index_of(bears)

    # The Bears leave in response; the Giant slides into their slot.
    game.remove_from_battlefield(bears)
    game.players[1].hand.append(bears.card)
    assert game.battlefield_index_of(giant) == bears_slot

    for seat in (0, 1):
        item = _shock(sid, seat)
        assert item["target_permanent_name"] is None, item
        assert item["target_permanent_index"] is None, item
        assert item["targets"] == [], item


def test_a_target_whose_board_shifted_is_still_named_where_it_now_is():
    sid, game, permanents = _session_with_shock_on_the_stack(
        ["Grizzly Bears", "Hill Giant"], "Hill Giant",
    )
    bears, giant = permanents["Grizzly Bears"], permanents["Hill Giant"]
    game.remove_from_battlefield(bears)
    game.players[1].hand.append(bears.card)

    item = _shock(sid)
    index = game.battlefield_index_of(giant)
    assert item["target_permanent_name"] == "Hill Giant"
    assert item["target_permanent_index"] == index
    assert item["target_permanent_seat"] == 1
    assert item["targets"] == [{"kind": "permanent", "seat": 1, "index": index}]
