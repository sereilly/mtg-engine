"""A returning Aura's host is asked of a person over the wire (CR 303.4f).

Replenish returns every enchantment card from its caster's graveyard at once,
and each Aura among them enters attached to something "that player chooses".
The engine asks an interactive seat through the general ``permanent_choice``
prompt — the one Enchantment Alteration and Takklemaggot already arm — so the
renderer, the action (``permanent_choice_confirm``) and the client's branch
for it (``getPermanentChoiceInfo`` in ``web/static/app.js``: the candidates
highlighted on the canvas, answered by stable id) are all existing ones. This
holds the wire end to end: the question reaches the seat that owes it and
nobody else, names the Aura in its prompt, offers exactly the legal hosts by
id, refuses an illegal one with the prompt kept, and an answer completes the
resolution with every card entering together.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_POOL = {card.name: card for card in load_catalog()}


def _session_with_replenish():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "H", "guest_name": "G",
            "host_colors": 2, "guest_colors": 2, "seed": 303,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "G"})
    session = store.get(sid)
    session.current_turn = 0
    session.pregame_phase = None
    game = session.game
    # Both seats are people — what the action route writes before every action.
    game.interactive_seats = {0, 1}
    game.enforce_mana_costs = False
    game.active_player_index = 0
    for player in game.players:
        player.hand, player.graveyard = [], []
        for permanent in list(game.controlled_by(game.players.index(player))):
            game.remove_from_battlefield(permanent)
    game.stack.clear()
    game.pending_choices.clear()
    game.players[0].hand = [_POOL["Replenish"]]
    game.players[0].graveyard = [_POOL["Holy Strength"], _POOL["Castle"]]
    bears = Permanent(card=_POOL["Grizzly Bears"])
    giant = Permanent(card=_POOL["Hill Giant"])
    knight = Permanent(card=_POOL["Black Knight"])
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    game._put_permanent_onto_battlefield(1, knight, None)
    assert game.cast_from_hand(0, "Replenish").supported
    game.resolve_top_of_stack(pause_for_choices=True)
    return sid, game, bears, giant, knight


def test_the_seat_returning_the_aura_is_asked_and_answers_by_id():
    sid, game, bears, giant, knight = _session_with_replenish()

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    info = state["permanent_choice"]
    assert info is not None, "the question reaches the seat that owes it"
    assert info["player_seat"] == 0 and info["card_name"] == "Replenish"
    assert "Holy Strength" in info["prompt"]
    assert info["optional"] is False
    # Black Knight has protection from white (CR 702.16c), so it is not offered.
    assert sorted((c["name"], c["id"]) for c in info["candidates"]) == sorted([
        ("Grizzly Bears", bears.permanent_id), ("Hill Giant", giant.permanent_id),
    ])
    assert state["waiting_on_prompt"] is True
    other = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    assert other["permanent_choice"] is None

    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "permanent_choice_confirm",
        "target_permanent_id": knight.permanent_id,
    })
    assert refused.status_code == 400
    assert game.pending_choices_of("permanent_choice")
    assert [card.name for card in game.players[0].graveyard] == ["Holy Strength", "Castle"]

    answered = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "permanent_choice_confirm",
        "target_permanent_id": giant.permanent_id,
    })
    assert answered.status_code == 200, answered.text
    strength = next(
        perm for perm in game.all_permanents() if perm.card.name == "Holy Strength"
    )
    assert strength.metadata.get("attached_to") is giant
    assert any(perm.card.name == "Castle" for perm in game.controlled_by(0))
    assert [card.name for card in game.players[0].graveyard] == ["Replenish"]
    assert not game.stack
