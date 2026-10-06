"""Web-API round trip for the two answers a triggered ability's target prompt
gained: **a card in a graveyard**, and **nobody**.

"When this creature enters, you may return target creature card from your
graveyard to your hand" (Gravedigger), put onto the battlefield by something
other than a cast, so CR 603.3d chooses its target as the trigger goes on the
stack. The prompt lists the cards by pile and slot — a graveyard card has no
id — and the answer names one of them back.

"…return up to one other target creature or planeswalker to its owner's hand"
(Barrin, Tolarian Archmage): the prompt says ``up_to`` and an explicitly empty
list is the answer "nobody" (CR 115.6).

The engine halves are ``tests/engine/test_graveyard_trigger_target_census.py``
and ``tests/engine/test_up_to_names_nobody_census.py``; this pins the wire and
the three places the client reads it. The browser half was driven by hand.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 603,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    # What the action preamble sets before every action; the trigger below is
    # put on the stack on the engine directly, before any action has run.
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
        player.graveyard.clear()
        player.hand.clear()
    return sid, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_a_graveyard_card_is_offered_by_pile_and_slot_and_answered_the_same_way(
    catalog_by_name,
):
    sid, game = _session()
    game.players[0].graveyard.extend(
        catalog_by_name[name] for name in ("Lightning Bolt", "Hill Giant", "Serra Angel")
    )
    game.players[1].graveyard.append(catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(
        0, Permanent(card=catalog_by_name["Gravedigger"]), None,
    )

    prompt = _state(sid)["trigger_target"]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Gravedigger"
    # "from **your** graveyard", creature cards only: two of the four cards.
    assert prompt["candidates"] == [
        {"kind": "graveyard", "seat": 0, "graveyard_index": 1, "name": "Hill Giant"},
        {"kind": "graveyard", "seat": 0, "graveyard_index": 2, "name": "Serra Angel"},
    ]
    assert "up_to" not in prompt
    # The other seat is not asked, and while it is owed nothing else is taken.
    assert _state(sid, 1).get("trigger_target") in (None, prompt)
    assert _act(sid, seat=0, action="pass_priority").status_code == 400

    # Not a card that was offered: an instant, then the other player's pile.
    for seat, slot in ((0, 0), (1, 0)):
        refused = _act(
            sid, seat=0, action="trigger_target_confirm",
            target_seat=seat, graveyard_index=slot,
        )
        assert refused.status_code == 400, refused.text
    # The pile has to be named: a slot alone addresses nothing.
    assert _act(
        sid, seat=0, action="trigger_target_confirm", graveyard_index=2,
    ).status_code == 400
    assert _state(sid)["trigger_target"] == prompt, "a refused answer leaves it owed"

    answered = _act(
        sid, seat=0, action="trigger_target_confirm", target_seat=0, graveyard_index=2,
    )
    assert answered.status_code == 200, answered.text
    assert _state(sid).get("trigger_target") is None
    assert "Gravedigger: targets Serra Angel in" in " / ".join(_state(sid)["log"][-3:])

    # It is on the stack with its target; resolve it and the "may" behind it.
    for _ in range(6):
        if not game.stack and not game.pending_choices:
            break
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        else:
            game.resolve_top_of_stack()
    assert [card.name for card in game.players[0].hand] == ["Serra Angel"]
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt", "Hill Giant"]


def test_an_up_to_trigger_is_offered_nobody_and_takes_an_empty_list(catalog_by_name):
    sid, game = _session()
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=catalog_by_name["Barrin, Tolarian Archmage"]), None,
    )

    prompt = _state(sid)["trigger_target"]
    assert prompt["up_to"] is True
    assert [c["name"] for c in prompt["candidates"]] == ["Grizzly Bears"]

    # Naming nothing at all is still a malformed answer…
    assert _act(sid, seat=0, action="trigger_target_confirm").status_code == 400
    # …and an explicit empty list is the answer "nobody".
    answered = _act(sid, seat=0, action="trigger_target_confirm", target_permanent_ids=[])
    assert answered.status_code == 200, answered.text
    assert _state(sid).get("trigger_target") is None

    for _ in range(4):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    assert game.is_on_battlefield(bears), "the only legal target was its controller's own"
    assert game.players[0].hand == []


def test_an_ability_that_owes_its_target_cannot_be_skipped_with_an_empty_list(
    catalog_by_name,
):
    sid, game = _session()
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=catalog_by_name["Man-o'-War"]), None,
    )

    prompt = _state(sid)["trigger_target"]
    assert "up_to" not in prompt

    refused = _act(sid, seat=0, action="trigger_target_confirm", target_permanent_ids=[])
    assert refused.status_code == 400
    assert _state(sid)["trigger_target"] == prompt


def test_the_client_reads_all_three_kinds_of_candidate_and_the_decline():
    """The client's own code, read rather than run: the panel renders a button
    per graveyard card and answers by pile and slot, offers "nobody" only on
    ``up_to`` and sends it as an explicit empty list, and the board picker
    does not mistake a graveyard slot for a battlefield one."""
    panel = app_js_function_body("applyTriggerTargetPrompt")
    assert 'c.kind === "graveyard"' in panel
    assert "graveyard_index: Number(c.graveyard_index)" in panel
    assert "target_seat: Number(c.seat)" in panel
    assert "info.up_to" in panel and "target_permanent_ids: []" in panel

    dispatch = app_js_function_body("renderActivationPrompt")
    assert "applyTriggerTargetPrompt(triggerTargetPrompt)" in dispatch

    board = app_js_function_body("getPromptBoardTargeting")
    assert 'c.kind !== "graveyard"' in board
