"""A text change aimed at a spell, over the wire.

"Change the text of target **spell** or permanent" (Sleight of Mind and its
kin) derives the ``spell_or_permanent`` picker the client already renders for
the Laces and Illusion: the hand card's ``target_spec`` lists the spell on the
stack, and the cast body the client sends for a text change —
``{"action":"cast","card_name":"Sleight of Mind","target_stack_index":N,
"old_color":"B","mana_color":"W"}`` — is accepted. The stack item it changed
is sent with ``card.text_changes`` (the printed text plus the words it now
reads differently, the shape a permanent's ``text_changes`` has), which the
card preview strikes through as it does for a permanent.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import _pass_priority
from web.app import app, store
from web.runtime import CARD_BY_NAME

client = TestClient(app)


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_colors": 2, "guest_colors": 2, "seed": 611},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.enforce_mana_costs = False
    me, you = game.players
    lions = Permanent(card=CARD_BY_NAME["savannah lions"])
    you.battlefield = [lions]
    me.battlefield = []
    me.hand = [CARD_BY_NAME["terror"], CARD_BY_NAME["sleight of mind"]]
    game._settle()
    return sid, game, lions


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()


def test_sleight_of_mind_names_a_spell_and_the_stack_shows_the_change():
    sid, game, lions = _session()
    terror = _act(
        sid, action="cast", card_name="Terror", target_permanent_id=lions.permanent_id,
    )
    assert terror.status_code == 200, terror.text

    hand = _state(sid)["players"][0]["hand"]
    (sleight,) = [card for card in hand if card["name"] == "Sleight of Mind"]
    spec = sleight["target_spec"]
    assert spec["kind"] == "spell_or_permanent"
    assert ("stack", "Terror") in [(t["kind"], t["name"]) for t in spec["valid_targets"]]

    cast = _act(
        sid, action="cast", card_name="Sleight of Mind", target_stack_index=0,
        old_color="B", mana_color="W",
    )
    assert cast.status_code == 200, cast.text

    # Both seats pass: Sleight of Mind resolves; the Terror is still waiting.
    _pass_priority(sid, 0)
    _pass_priority(sid, 1)
    state = _state(sid)
    (item,) = state["stack"]
    assert item["card"]["name"] == "Terror"
    assert {"from": "black", "to": "white"} in item["card"]["text_changes"]
    assert "Sleight of Mind changed B text to W on Terror (on the stack)" in state["log"]

    # And the Terror is countered by its changed text: the Lions are white.
    _pass_priority(sid, 0)
    _pass_priority(sid, 1)
    state = _state(sid)
    assert state["stack"] == []
    assert game.is_on_battlefield(lions)
    assert any("every target is illegal (608.2b)" in line for line in state["log"])


def test_an_unchanged_spell_is_sent_without_text_changes():
    sid, game, lions = _session()
    assert _act(
        sid, action="cast", card_name="Terror", target_permanent_id=lions.permanent_id,
    ).status_code == 200
    (item,) = _state(sid)["stack"]
    assert "text_changes" not in item["card"]
