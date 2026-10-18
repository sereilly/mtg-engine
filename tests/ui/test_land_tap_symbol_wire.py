"""The wire for a land tapped for a symbol the client names.

A land click is sent as ``activate`` with ``mana_color`` and, for a land the
client may simply tap, no ability named. Three things went wrong on the way
to ``Game.tap_land_for_mana``:

* the colour chose nothing: a Karplusan Forest clicked for {R} ran its first
  ability and made {C};
* ``mana_color: "C"`` — a value the schema allows, because the same field
  names a *symbol* here and {C} is one of the six — reached the colour
  normalizer from "{T}: Add {B} or {R}." and came back a 500;
* a land's ``produced_mana`` listed what its *priced* abilities make, so the
  client offered five colours for a School of the Unseen whose tap makes {C}.

The engine half is ``tests/rules/test_land_tap_asks_for_a_symbol.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(*names):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4107,
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
    permanents = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
        permanents.append(permanent)
    game.auto_resolve_pending_choices()
    game._recompute_continuous_effects()
    for permanent in permanents:
        permanent.tapped = False
    game.start_priority_window(0)
    return sid, game, permanents


def _payload(sid, permanent) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    for entry in state["players"][0]["battlefield"]:
        if entry["id"] == permanent.permanent_id:
            return entry
    raise AssertionError(f"{permanent.card.name} is not on the payload")


def _click(sid, permanent, **named):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": permanent.card.name,
        "permanent_id": permanent.permanent_id, **named,
    })


def _pool(game) -> dict:
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def test_a_painland_clicked_for_a_colour_makes_that_colour():
    sid, game, (forest,) = _session("Karplusan Forest")
    assert sorted(_payload(sid, forest)["produced_mana"]) == ["C", "G", "R"]

    response = _click(sid, forest, mana_color="R")
    assert response.status_code == 200, response.text
    assert _pool(game) == {"R": 1}
    assert game.players[0].life == 19

    # Clicked for {C}, or with no colour at all: its first ability, no damage.
    for named in ({"mana_color": "C"}, {}):
        sid, game, (forest,) = _session("Karplusan Forest")
        response = _click(sid, forest, **named)
        assert response.status_code == 200, (named, response.text)
        assert _pool(game) == {"C": 1}, named
        assert game.players[0].life == 20, named


def test_colourless_named_to_a_land_that_offers_two_colours_is_not_a_500():
    sid, game, (caves,) = _session("Bloodfell Caves")
    (index,) = [
        i for i, ability in enumerate(game.usable_abilities_of(caves))
        if is_tap_alone_mana_ability(ability)
    ]
    for named in ({"mana_color": "C"}, {"mana_color": "C", "ability_index": index}):
        sid, game, (caves,) = _session("Bloodfell Caves")
        response = _click(sid, caves, **named)
        assert response.status_code == 200, (named, response.text)
        assert _pool(game) == {"B": 1}, named
        assert caves.tapped

    # …and by the plain tap action, which carries the same field.
    sid, game, (caves,) = _session("Bloodfell Caves")
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_name": "Bloodfell Caves",
        "permanent_id": caves.permanent_id, "mana_color": "C",
    })
    assert response.status_code == 200, response.text
    assert _pool(game) == {"B": 1}


def test_a_land_is_offered_as_what_a_tap_alone_makes_of_it():
    sid, game, (school,) = _session("School of the Unseen")
    payload = _payload(sid, school)
    assert payload["taps_for_mana"] is True
    assert payload["produced_mana"] == ["C"]
    # The click that names a colour only the priced ability makes is the tap.
    response = _click(sid, school, mana_color="R")
    assert response.status_code == 200, response.text
    assert _pool(game) == {"C": 1}

    sid, _game, (farm,) = _session("Tinder Farm")
    assert _payload(sid, farm)["produced_mana"] == ["G"]

    # A land every one of whose mana abilities is the tap alone is as it was.
    sid, _game, (island, city) = _session("Tropical Island", "City of Brass")
    assert sorted(_payload(sid, island)["produced_mana"]) == ["G", "U"]
    assert sorted(_payload(sid, city)["produced_mana"]) == ["B", "G", "R", "U", "W"]
