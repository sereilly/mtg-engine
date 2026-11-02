"""Two alternative costs on one cast: the wire names each, the cast takes one.

Dream Halls beside a morph card is two CR 118.9 alternative costs — "cast it
face down as a 2/2 creature for {3}" and Dream Halls' "discard a card that
shares a color with that spell" — and CR 118.9a lets the caster apply one of
them. The wire's ``alternative_cost`` was a bool and ``cast_cost_offers``
offered only the first alternative, while the cast refused any bare
announcement where two applied: a person could take neither (the "Face-down
leftovers on the wire" Known-gaps entry). Each offer now carries its
``alternative_index`` (and ``granted_by`` / ``keyword``), and the cast takes
``alternative_cost_index``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _dream_halls_and_a_morph():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 7171,
        "host_deck_cards": [{"name": "Plains", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.players[1].hand.clear()
    game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS["Dream Halls"]), None)
    for _ in range(3):
        game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS["Plains"]), None)
    game.players[0].hand[:] = [_CARDS["Daru Lancer"], _CARDS["Savannah Lions"]]
    game.start_priority_window(0)
    return sid, session, game


def _lancer_offers(sid):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    lancer = next(c for c in state["players"][0]["hand"] if c["name"] == "Daru Lancer")
    return [o for o in lancer["target_spec"].get("cost_offers", []) if o["kind"] == "alternative"]


def _cast(sid, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "cast", "card_name": "Daru Lancer", "hand_index": 0,
        "alternative_cost": True, "auto_tap": True, **fields,
    })


def test_both_alternatives_are_offered_each_with_its_position():
    sid, _session, _game = _dream_halls_and_a_morph()
    offers = _lancer_offers(sid)
    assert [o["alternative_index"] for o in offers] == [0, 1], offers
    morph, halls = offers
    assert morph["keyword"] == "morph"
    assert morph["label"] == "cast it face down as a 2/2 creature for {3}"
    assert "granted_by" not in morph
    assert halls["granted_by"] == "Dream Halls"
    assert halls["hand_verb"] == "discard"
    assert [c["name"] for c in halls["hand_choices"]] == ["Savannah Lions"]
    assert morph["payable"] and halls["payable"]


def test_a_bare_announcement_where_two_apply_is_refused_and_says_why():
    sid, _session, game = _dream_halls_and_a_morph()
    refused = _cast(sid)
    assert refused.status_code == 400, refused.text
    assert "name which (CR 118.9a)" in refused.text
    assert [c.name for c in game.players[0].hand] == ["Daru Lancer", "Savannah Lions"]


def test_the_morph_is_cast_face_down_for_three():
    sid, _session, game = _dream_halls_and_a_morph()
    cast = _cast(sid, alternative_cost_index=0)
    assert cast.status_code == 200, cast.text
    assert [c.name for c in game.players[0].hand] == ["Savannah Lions"]
    assert sum(1 for p in game.controlled_by(0) if p.tapped) == 3
    resolve_stack(game)
    face_down = [p for p in game.controlled_by(0) if p.card.face_down_of is not None]
    assert len(face_down) == 1
    assert face_down[0].card.face_down_of.name == "Daru Lancer"
    assert game.players[0].graveyard == []


def test_dream_halls_is_cast_face_up_for_a_discard():
    sid, _session, game = _dream_halls_and_a_morph()
    cast = _cast(sid, alternative_cost_index=1, alternative_cost_hand_index=1)
    assert cast.status_code == 200, cast.text
    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].graveyard] == ["Savannah Lions"]
    assert not any(p.tapped for p in game.controlled_by(0))
    resolve_stack(game)
    lancer = [p for p in game.controlled_by(0) if p.card.name == "Daru Lancer"]
    assert len(lancer) == 1 and lancer[0].card.face_down_of is None


def test_a_position_past_the_offers_is_refused():
    sid, _session, _game = _dream_halls_and_a_morph()
    refused = _cast(sid, alternative_cost_index=2)
    assert refused.status_code == 400, refused.text
    assert "no alternative cost at position 2" in refused.text


def test_the_client_offers_mana_once_and_sends_the_chosen_position():
    """The prompt's own functions, run on the offers the server sent: the
    morph's button says what it does, a granted offer names its source, and
    the announcement carries the position the person clicked."""
    sid, _session, _game = _dream_halls_and_a_morph()
    offers = _lancer_offers(sid)
    seen = run_app_js(
        ["alternativeOfferIndex", "alternativeOfferHead", "alternativeOfferButtonText",
         "escapeHtml"],
        "return INPUT.offers.map((o) => ({"
        " index: alternativeOfferIndex(o),"
        " head: alternativeOfferHead(o),"
        " button: alternativeOfferButtonText(o) }));",
        {"offers": offers},
    )
    assert seen[0] == {
        "index": 0, "head": "Instead of its mana cost: ",
        "button": "Cast face down for {3}",
    }
    assert seen[1]["index"] == 1
    assert seen[1]["head"] == "Instead of its mana cost, by Dream Halls: "
