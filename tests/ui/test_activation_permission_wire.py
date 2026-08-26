"""The "who may activate" permission on the wire (CR 602.1b).

The client has to decide, on a click, whether a permanent on *someone else's*
battlefield is reachable at all. It used to decide by searching the served
oracle text for one of the two spellings it had been told about, which is the
copy `engine/activation_permissions.py` retired: a permission added to the
engine's table was enforced by the engine and refused by the UI, and the click
simply said "You don't control this permanent."

So the answer is served. This pins the field the canvas reads and the API path
behind it, because a boolean the client stops receiving fails silently — the
click is refused and nothing logs an error.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store
from web.serialization import _serialize_permanent
from engine.card_loader import manifest_set_path
from tests.helpers import LEA_PATH

client = TestClient(app)

_ARN = {c.name: c for c in load_cards(manifest_set_path("ARN"))}
_LEA = {c.name: c for c in load_cards(LEA_PATH)}


def _r29_session(seed: int = 11):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai", "host_name": "H",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session.game


def test_a_widened_permanent_says_so_on_the_wire():
    _sid, game = _r29_session()
    efreet = Permanent(card=_ARN["Ifh-Bíff Efreet"])
    game._put_permanent_onto_battlefield(0, efreet, None)
    game._settle()

    payload = _serialize_permanent(efreet, game)

    assert payload["activatable_by_other_seats"] is True


def test_an_ordinary_permanent_does_not():
    _sid, game = _r29_session()
    tome = Permanent(card=_LEA["Jayemdae Tome"])
    game._put_permanent_onto_battlefield(0, tome, None)
    game._settle()

    payload = _serialize_permanent(tome, game)

    assert payload["activatable_by_other_seats"] is False
