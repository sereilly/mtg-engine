"""Web-API tests for the two announcements this round holds to the picker's
list: a named *player*, and the target a permanent spell names for its entry
trigger.

The browser never sent either of the illegal announcements below — its picker
did not offer the caster for "target opponent", and it now does not offer a
protected creature for an entry trigger. But the wire is not the browser:
``web/actions.py`` forwards ``target_seat`` and ``target_permanent_id``
unchecked, so a hand-written request reached the engine, and the engine is what
has to refuse (a spell) or set aside (a permanent's entry trigger).

The second half is the path the change **opens**: a cast whose announcement is
set aside becomes a ``trigger_target`` prompt for the human who cast it, on a
road — a cast — that never raised that prompt before. So the round trip is
pinned end to end: the payload offers the trigger's own list, an id outside it
is refused, and the confirm is what resolves.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {card.name: card for card in load_catalog()}


def _session(hand, opp_battlefield=(), opp_hand=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 6031,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = []
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[1].battlefield = [Permanent(card=_CARDS[name]) for name in opp_battlefield]
    game.players[1].hand = [_CARDS[name] for name in opp_hand]
    game._sync_control()
    session.current_turn = 0
    game.active_player_index = 0
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid, seat, action, **fields):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": seat, "action": action, **fields},
    )


def _hand_card(state, name):
    return next(card for card in state["players"][0]["hand"] if card["name"] == name)


def _resolve_the_spell(sid, game, name):
    """Both seats pass until the permanent spell *name* has resolved."""
    for _ in range(4):
        if not any(item.card.name == name and item.ability_instruction is None
                   for item in game.stack):
            return
        for seat in (0, 1):
            _act(sid, seat, "pass_priority")


def test_a_spell_aimed_at_its_own_caster_as_target_opponent_is_a_400():
    """Duress over the wire with ``target_seat`` set to the caster's own."""
    sid, game = _session(["Duress", "Giant Growth"], opp_hand=["Giant Growth"])

    spec = _hand_card(_state(sid), "Duress")["target_spec"]
    assert [entry["seat"] for entry in spec["valid_targets"]] == [1]

    refused = _act(sid, 0, "cast", card_name="Duress", target_seat=0)

    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "no valid target for Duress"
    assert [card.name for card in game.players[0].hand] == ["Duress", "Giant Growth"]
    assert game.stack == []

    accepted = _act(sid, 0, "cast", card_name="Duress", target_seat=1)
    assert accepted.status_code == 200, accepted.text


def test_the_cast_picker_for_an_entry_trigger_leaves_out_a_protected_creature():
    sid, _game = _session(["Nekrataal"], opp_battlefield=["White Knight", "Grizzly Bears"])

    spec = _hand_card(_state(sid), "Nekrataal")["target_spec"]

    assert sorted(entry["name"] for entry in spec["valid_targets"]) == ["Grizzly Bears"]


def test_naming_the_protected_creature_anyway_becomes_the_triggers_own_prompt():
    sid, game = _session(
        ["Nekrataal"], opp_battlefield=["White Knight", "Grizzly Bears", "Hill Giant"],
    )
    knight, _bears, giant = game.players[1].battlefield

    cast = _act(sid, 0, "cast", card_name="Nekrataal", target_permanent_id=knight.permanent_id)
    assert cast.status_code == 200, cast.text  # a permanent spell does not target
    _resolve_the_spell(sid, game, "Nekrataal")

    prompt = _state(sid)["trigger_target"]
    assert prompt is not None, game.log[-6:]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Nekrataal"
    assert sorted(entry["name"] for entry in prompt["candidates"]) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert game.is_on_battlefield(knight)

    wrong = _act(sid, 0, "trigger_target_confirm", target_permanent_id=knight.permanent_id)
    assert wrong.status_code == 400, wrong.text

    right = _act(sid, 0, "trigger_target_confirm", target_permanent_id=giant.permanent_id)
    assert right.status_code == 200, right.text
    for _ in range(4):
        if not game.stack:
            break
        for seat in (0, 1):
            _act(sid, seat, "pass_priority")

    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(knight)
    assert [perm.card.name for perm in game.players[1].battlefield] == [
        "White Knight", "Grizzly Bears",
    ]
