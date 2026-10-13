"""Fork on a Lightning Bolt aimed at a face, over the wire.

"Copy target instant or sorcery spell, except that the copy is red. You may
choose new targets for the copy." The client offered new targets through a
second step of its own, which existed for permanent pickers and could not name
a player; so this cast — the body it sent for a face-aimed Bolt, and since the
client closer the body it sends for every Fork —

    {"action":"cast","card_name":"Fork","target_stack_index":0}

made a copy with the original's target and armed nothing. Now the copy's
controller owes the ``copy_spell_target`` prompt as Fork resolves, the same
one Double Vision's copy and Chain Lightning's use:

    state.copy_spell_target = {player_seat, card_name, candidates:[
        {kind:"player", seat, name} | {kind:"permanent", seat, index, id, name}]}
    {"action":"copy_spell_target_confirm","target_seat":N}          (a player)
    {"action":"copy_spell_target_confirm","target_permanent_id":ID}  (a permanent)

A new permanent named on the cast is still the answer by itself and arms
nothing — the wire accepts it, though the browser no longer sends it: the
client's second step stood down in favour of this prompt, one way of asking
rather than two (``test_ody_p5_closer_b_client_ui_api.py``). The rule is
``tests/rules/test_forked_copy_new_targets.py``.
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
        json={"mode": "human_vs_human", "host_colors": 2, "guest_colors": 2, "seed": 707},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    me, you = game.players
    mine = Permanent(card=CARD_BY_NAME["grizzly bears"])
    theirs = Permanent(card=CARD_BY_NAME["grizzly bears"])
    me.battlefield = [mine]
    you.battlefield = [theirs]
    me.hand = [CARD_BY_NAME["lightning bolt"], CARD_BY_NAME["fork"]]
    game._settle()
    return sid, game, me, you, mine, theirs


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()


def test_forking_a_bolt_aimed_at_a_face_asks_for_the_copys_target():
    sid, game, me, you, mine, theirs = _session()

    bolt = _act(sid, action="cast", card_name="Lightning Bolt", target_seat=1)
    assert bolt.status_code == 200, bolt.text
    fork = _act(sid, action="cast", card_name="Fork", target_stack_index=0)
    assert fork.status_code == 200, fork.text
    assert _state(sid)["copy_spell_target"] is None, "not until Fork resolves"

    # Both seats pass; Fork resolves and its controller owes the copy's target.
    _pass_priority(sid, 0)
    _pass_priority(sid, 1)

    prompt = _state(sid)["copy_spell_target"]
    assert prompt is not None, game.log[-6:]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Lightning Bolt"
    candidates = prompt["candidates"]
    assert {"kind": "player", "seat": 0, "index": None, "id": None,
            "name": me.name} in candidates
    assert {"kind": "player", "seat": 1, "index": None, "id": None,
            "name": you.name} in candidates, "the original's target is an answer"
    assert {c["id"] for c in candidates if c["kind"] == "permanent"} == {
        mine.permanent_id, theirs.permanent_id,
    }
    # The copy is on the stack above the original, still aimed where it was.
    copy = next(item for item in reversed(game.stack) if item.is_copy)
    assert (copy.target_player_index, copy.target_permanent_id) == (1, None)

    # An id that names nothing is refused where every id is (a 404, never a
    # fall back to a slot), and the prompt stands.
    assert _act(
        sid, action="copy_spell_target_confirm", target_permanent_id=987654,
    ).status_code == 404
    assert _state(sid)["copy_spell_target"] is not None

    aimed = _act(
        sid, action="copy_spell_target_confirm",
        target_permanent_id=theirs.permanent_id,
    )
    assert aimed.status_code == 200, aimed.text
    assert _state(sid)["copy_spell_target"] is None
    assert copy.target_permanent_id == theirs.permanent_id

    for _ in range(8):
        if not game.stack:
            break
        _pass_priority(sid, 0)
        _pass_priority(sid, 1)

    # The copy killed the Bears; the original went to the face it was cast at.
    assert not game.is_on_battlefield(theirs)
    assert you.life == 17


def test_a_new_permanent_named_on_the_cast_is_not_asked_again():
    """A cast that names the copy's new permanent is one answer and one ask.
    (What the client's own second step used to send; a scripted caller and a
    headless test still may.)"""
    sid, game, _me, you, _mine, theirs = _session()

    assert _act(
        sid, action="cast", card_name="Lightning Bolt", target_seat=1,
    ).status_code == 200
    assert _act(
        sid, action="cast", card_name="Fork", target_stack_index=0,
        target_seat=1, permanent_index=0,
    ).status_code == 200
    _pass_priority(sid, 0)
    _pass_priority(sid, 1)

    assert _state(sid)["copy_spell_target"] is None
    copy = next(item for item in reversed(game.stack) if item.is_copy)
    assert game.permanent_at(copy.target_player_index, copy.target_permanent_index) is theirs
