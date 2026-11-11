"""The wire's target reaches the engine in each zone's own keyword (kg5 / ``ids``).

``web/actions.py`` turned every target id into a battlefield slot at the top
of the dispatch, and the cast and activation routes handed the engine that
slot (beside the ids where the client sent a list). Now the preamble checks a
target id (a 404 when it no longer resolves) and writes its seat, and nothing
else; ``web/action_helpers.wire_target_keywords`` hands the engine the ids, a
graveyard card by its place (``target_graveyard_indices``, the new request
field), or — the old slot fields, accepted for one more round — the slot read
in the zone the card names its target in.

Driven through the FastAPI app, the board read after each request.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine import Game
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _session(catalog_by_name, *, hand=(), mine=(), theirs=(), graveyard=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 6043,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game: Game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    game.players[0].hand.extend(catalog_by_name[name] for name in hand)
    game.players[0].graveyard.extend(catalog_by_name[name] for name in graveyard)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=catalog_by_name[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata.pop("summoning_sickness_turn", None)
            placed.append(permanent)
    game.start_priority_window(0)
    return sid, game, placed


def _act(sid, body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _resolve(sid, game):
    for _ in range(6):
        if not game.stack:
            return
        for seat in (0, 1):
            if game.stack:
                _act(sid, {"seat": seat, "action": "pass_priority"})


def test_a_graveyard_card_is_named_by_its_place_on_the_wire(catalog_by_name):
    sid, game, _ = _session(
        catalog_by_name, hand=["Raise Dead"],
        graveyard=["Grizzly Bears", "Hill Giant", "Shivan Dragon"],
    )
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Raise Dead", "target_seat": 0,
        "target_graveyard_indices": [2],
    })
    assert response.status_code == 200, response.text
    _resolve(sid, game)
    assert [c.name for c in game.players[0].hand] == ["Shivan Dragon"]


def test_the_old_slot_field_is_still_read_in_the_spells_zone(catalog_by_name):
    """A cast's ``permanent_index`` for a graveyard target (what the client's
    graveyard picker sends this round) is that pile's place, never a
    battlefield slot."""
    sid, game, _ = _session(
        catalog_by_name, hand=["Raise Dead"], mine=["Grizzly Bears", "Hill Giant"],
        graveyard=["Grizzly Bears", "Hill Giant", "Shivan Dragon"],
    )
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Raise Dead", "target_seat": 0,
        "permanent_index": 1,
    })
    assert response.status_code == 200, response.text
    _resolve(sid, game)
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears", "Hill Giant"]


def test_a_target_id_reaches_the_engine_as_the_id(catalog_by_name, monkeypatch):
    """Terror by ``target_permanent_id``: the engine is handed the id and no
    slot (the slot the gates read is the engine's own derivation)."""
    sid, game, placed = _session(
        catalog_by_name, hand=["Terror"], theirs=["Grizzly Bears", "Hill Giant"],
    )
    giant = placed[1]
    seen = {}
    original = Game.queue_from_hand

    def recording(self, *args, **kwargs):
        seen.update(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Game, "queue_from_hand", recording)
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Terror",
        "target_permanent_id": giant.permanent_id,
    })
    assert response.status_code == 200, response.text
    assert seen["target_permanent_ids"] == [giant.permanent_id]
    assert "target_permanent_index" not in seen
    _resolve(sid, game)
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]


def test_an_old_battlefield_slot_naming_nothing_is_the_404_a_stale_id_is(catalog_by_name):
    sid, game, _ = _session(catalog_by_name, hand=["Terror"], theirs=["Grizzly Bears"])
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Terror", "target_seat": 1,
        "permanent_index": 4,
    })
    assert response.status_code == 404
    assert [c.name for c in game.players[0].hand] == ["Terror"]


def test_an_activation_by_the_old_slot_field_names_the_permanent_by_id(catalog_by_name, monkeypatch):
    """Prodigal Sorcerer by ``target_seat`` + ``target_permanent_index`` (the
    activation body the client sends this round): the engine is handed the
    id of the permanent in that slot."""
    sid, game, placed = _session(
        catalog_by_name, mine=["Prodigal Sorcerer"], theirs=["Llanowar Elves", "Hill Giant"],
    )
    elves = placed[1]
    seen = {}
    original = Game.queue_permanent_ability

    def recording(self, *args, **kwargs):
        seen.update(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Game, "queue_permanent_ability", recording)
    response = _act(sid, {
        "seat": 0, "action": "activate", "permanent_name": "Prodigal Sorcerer",
        "permanent_index": 0, "target_seat": 1, "target_permanent_index": 0,
    })
    assert response.status_code == 200, response.text
    assert seen["target_permanent_ids"] == [elves.permanent_id]
    assert "target_permanent_index" not in seen
    _resolve(sid, game)
    assert [p.card.name for p in game.players[1].battlefield] == ["Hill Giant"]
