"""Fifth Dawn's Phase 5: a land under Fist of Suns is played, not priced.

Clicked first: with Fist of Suns on the battlefield, clicking a Plains in hand
opened "Pay for Plains?" — the cast-offer prompt, with "Pay its mana cost"
and Fist's "Pay {W}{U}{B}{R}{G}" — before the land was played. Fist grants
its price to "spells you cast", and a land is played, never cast (CR 305.1;
CR 118.9's alternative costs are a spell's), but the hand card's
``target_spec.cost_offers`` carries Fist's offer, and ``castCostOffers`` read
it for whatever card it was handed. Either answer then played the land
(the server ignores ``alternative_cost`` on a land play), so the prompt was a
detour, never a charge.

The payload is the server's own, read from a web session; the client
function is the real source, lifted out of ``app.js``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app

from tests.helpers import run_app_js, seat_plays_first

client = TestClient(app)


def _p5_card(set_pool, name: str):
    for code in ("5DN", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def test_p5_a_land_in_hand_under_fist_of_suns_offers_no_price(set_pool):
    """``castCostOffers`` returns nothing for a land (the Plains plays at
    the click) and still returns Fist's offer for a spell beside it (Eon
    Hub's "Pay {W}{U}{B}{R}{G}" prompt, the neighbour that must keep
    working)."""
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 7,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    game = seat_plays_first(sid).game
    for player in game.players:
        player.battlefield = []
        player.hand = []
    for name in ("Fist of Suns", "Plains", "Island", "Swamp", "Mountain", "Forest"):
        permanent = Permanent(card=_p5_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, permanent, None)
    game.players[0].hand = [_p5_card(set_pool, "Plains"), _p5_card(set_pool, "Eon Hub")]
    game._sync_control()

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    land, spell = state["players"][0]["hand"]
    assert (land["name"], spell["name"]) == ("Plains", "Eon Hub")
    assert any(offer.get("granted_by") == "Fist of Suns"
               for offer in spell["target_spec"]["cost_offers"])

    offered = run_app_js(
        ["targetSpecOf", "castCostOffers"],
        "return [castCostOffers(INPUT.land), castCostOffers(INPUT.spell)];",
        {"land": land, "spell": spell},
        prelude="const EMPTY_TARGET_SPEC = {};",
    )
    assert offered[0] is None
    assert [offer["label"] for offer in offered[1]] == ["pay {W}{U}{B}{R}{G}"]
