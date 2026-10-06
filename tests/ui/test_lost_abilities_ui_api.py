"""The ability menu does not offer what an effect took away (CR 305.7).

A Mishra's Factory under Blood Moon is a Mountain: it "loses all abilities
generated from its rules text" and taps for {R}. The engine has refused its
three printed abilities for a long time. The client did not know — it builds
its ability menu from the permanent's oracle text, which no such effect
rewrites, and the server sent one target spec per printed ability beside it —
so the menu offered all three and each was a 400.

The payload says so now (``abilities_lost``, the engine's own reason from
``Game.lost_abilities_refusal``), the per-ability specs come from the
permanent's own list (``Game.usable_abilities_of``), and the client's one
reader of a permanent's ability text reads the flag first.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(*names):
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
    permanents = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanents.append(permanent)
    game._recompute_continuous_effects()
    game.start_priority_window(0)
    return sid, game, permanents


def _my_permanent(sid, permanent) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return next(
        entry for entry in state["players"][0]["battlefield"]
        if entry["id"] == permanent.permanent_id
    )


def test_the_payload_says_a_set_land_type_took_the_abilities():
    sid, _game, (factory, _moon) = _session("Mishra's Factory", "Blood Moon")

    payload = _my_permanent(sid, factory)

    assert payload["abilities_lost"] == (
        "Mishra's Factory lost its abilities when its land type was set (CR 305.7)"
    )
    # The text still prints them — which is exactly why the flag has to travel.
    assert "Assembly-Worker" in payload["oracle_text"]
    assert payload["target_spec"]["kind"] == "none"
    assert "ability_target_specs" not in payload


def test_an_untouched_factory_still_lists_all_three():
    sid, _game, (factory,) = _session("Mishra's Factory")

    payload = _my_permanent(sid, factory)

    assert payload["abilities_lost"] is None
    assert len(payload["ability_target_specs"]) == 3


def test_the_client_reads_the_flag_before_the_text():
    """``activatedAbilityText`` is the one function every ability menu, cost
    reader and prompt on the page starts from. Text-level, because ``app.js``
    is DOM-coupled and cannot be loaded here; what is checked is that the
    function consults the flag ahead of the oracle text it would otherwise
    return."""
    body = app_js_function_body("activatedAbilityText")

    assert "card.abilities_lost" in body
    assert body.index("card.abilities_lost") < body.index("card.oracle_text")


def test_a_printed_ability_of_a_set_type_land_is_a_400_and_a_plain_tap_makes_red():
    sid, game, (factory, _moon) = _session("Mishra's Factory", "Blood Moon")

    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": factory.permanent_id,
        "ability_index": 1,
    })

    assert refused.status_code == 400, refused.text
    assert "CR 305.7" in refused.json()["detail"]
    assert not factory.tapped and not factory.is_creature

    tapped = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": factory.permanent_id,
        "mana_color": "R",
    })

    assert tapped.status_code == 200, tapped.text
    assert factory.tapped and game.players[0].mana_pool.get("R") == 1
