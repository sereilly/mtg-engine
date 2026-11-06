"""The combat damage dialog reads a creature's keywords off the server.

``cardHasKeyword`` decided first strike, double strike, deathtouch and trample
for the combat damage dialog (``getAttackerAssignGroups``, the offers beside
it) and for the damage effects — by reading the card's printed text, while the
payload has carried each permanent's effective keywords all along
(``keywords``, ``web/serialization._effective_keywords``: an Aura's grant in,
a layer-6 removal out). A Grizzly Bears under Rancor had no trample in the
dialog. A client copy of an engine answer the payload already carries — the
census kg4's activation-denial work asked for.
"""
from __future__ import annotations

import shutil

import pytest

from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, run_app_js, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _bears_under(aura_name):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 4408,
    }).json()
    sid = created["session_id"]
    game = seat_plays_first(sid).game
    game.players[0].battlefield = []
    bears = Permanent(card=_CARDS["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    if aura_name:
        aura = Permanent(card=_CARDS[aura_name])
        game._put_permanent_onto_battlefield(0, aura, None)
        attach_aura(aura, bears)
    game.stack.clear()
    game._recompute_continuous_effects()
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return next(p for p in state["players"][0]["battlefield"] if p["name"] == "Grizzly Bears")


def _reads(card, words):
    return run_app_js(
        ["cardHasKeyword"],
        "return INPUT.words.map((w) => cardHasKeyword(INPUT.card, w));",
        {"card": card, "words": words},
    )


@needs_node
def test_a_granted_trample_is_trample_in_the_dialog():
    bears = _bears_under("Rancor")
    assert "trample" not in bears["oracle_text"].lower()
    assert "Trample" in bears["keywords"]
    assert _reads(bears, ["trample", "deathtouch", "first strike"]) == [True, False, False]
    # Without the Aura, no trample.
    assert _reads(_bears_under(None), ["trample"]) == [False]


@needs_node
def test_a_keyword_the_layers_took_away_is_gone():
    lost = {"name": "An invented Wurm", "oracle_text": "Trample", "keywords": []}
    assert _reads(lost, ["trample"]) == [False]
    # A bare card the server sent no keyword list with is read off its text.
    assert _reads({"name": "Bare", "oracle_text": "Trample"}, ["trample"]) == [True]
