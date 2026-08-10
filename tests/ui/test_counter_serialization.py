"""The permanent payload's ``counters`` map, which drives the canvas counter
badges and the "Counters: ..." line in the hover preview.

Counters live in permanent metadata under ``<kind>_counters``, so serialization
sweeps that suffix rather than naming each kind — a newly supported counter
(Cyclone's wind counters) renders without a web-layer change.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

ARN_PATH = manifest_set_path("ARN")
_CARDS = {c.name: c for c in load_cards(LEA_PATH)}
_CARDS.update({c.name: c for c in load_cards(ARN_PATH)})


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session.game


def _perm_payload(sid, name):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return next(p for p in state["players"][0]["battlefield"] if p["name"] == name)


def test_unnamed_counter_kind_is_serialized_generically():
    # Cyclone banks wind counters on itself; nothing in the web layer knows the
    # word "wind" — the ``_counters`` metadata suffix is what exposes it.
    sid, game = _session()
    perm = Permanent(card=_CARDS["Cyclone"])
    perm.metadata["wind_counters"] = 3
    game.players[0].battlefield = [perm]
    assert _perm_payload(sid, "Cyclone")["counters"] == {"wind": 3}


def test_multiple_counter_kinds_on_one_permanent():
    sid, game = _session()
    perm = Permanent(card=_CARDS["Grizzly Bears"])
    perm.metadata["plus_counters"] = 2
    perm.metadata["plus_1_0_counters"] = 1
    game.players[0].battlefield = [perm]
    # +1/+1 and +1/+0 counters are relabeled; a raw metadata key would read
    # "plus" / "plus_1_0" on the card face.
    assert _perm_payload(sid, "Grizzly Bears")["counters"] == {"+1/+1": 2, "+1/+0": 1}


def test_zero_and_nonnumeric_counter_values_are_omitted():
    sid, game = _session()
    perm = Permanent(card=_CARDS["Grizzly Bears"])
    perm.metadata["wind_counters"] = 0
    perm.metadata["bogus_counters"] = None
    game.players[0].battlefield = [perm]
    assert _perm_payload(sid, "Grizzly Bears")["counters"] == {}


def test_mire_counter_flag_reports_as_a_count_of_one():
    # A mire counter (put on a non-Swamp land) is stored as a boolean flag
    # rather than a tally, but it's still a counter on the card.
    sid, game = _session()
    perm = Permanent(card=_CARDS["Forest"])
    perm.metadata["mire_counter"] = True
    game.players[0].battlefield = [perm]
    assert _perm_payload(sid, "Forest")["counters"] == {"mire": 1}
