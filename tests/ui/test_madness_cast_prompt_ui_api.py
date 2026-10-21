"""The madness offer over the wire (CR 702.35a, CR 608.2g).

The server half of what wave 2's client group builds: a person who discards a
card with madness is shown the ``madness_cast`` prompt, may tap lands while it
is open (it is paid in mana, so ``tap`` and ``activate`` answer it as they
answer every payment prompt), and answers it with ``madness_cast_confirm`` —
``accept: false`` to put the card into the graveyard, or ``accept: true`` with
the ordinary cast fields (targets, X, division) to cast it out of exile for
its madness cost. Nothing here drives a browser; ``web/static/`` has no branch
for this prompt yet, and that is the client group's list.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


def _w1g1_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 702,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.interactive_seats = {0, 1}
    game.players[0].battlefield = [
        Permanent(card=_POOL["Aquamoeba"]), Permanent(card=_POOL["Mountain"]),
    ]
    game.players[1].battlefield = [Permanent(card=_POOL["Grizzly Bears"])]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [_POOL["Fiery Temper"]]
    game.players[0].graveyard = []
    game.players[0].exile = []
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **fields})


def test_w1g1_the_offer_is_rendered_and_holds_the_game():
    sid, game = _w1g1_session()
    prompt = _state(sid)["madness_cast"]
    assert prompt["card_name"] == "Fiery Temper"
    assert prompt["cost"] == "{R}"
    assert prompt["exile_index"] == 0
    # The question is its owner's: the other seat is not asked it.
    assert _state(sid, 1)["madness_cast"] is None
    assert _act(sid, action="pass_priority").status_code == 400


def test_w1g1_declining_puts_the_card_into_the_graveyard():
    sid, game = _w1g1_session()
    answered = _act(sid, action="madness_cast_confirm", accept=False)
    assert answered.status_code == 200, answered.text
    assert [c.name for c in game.players[0].graveyard] == ["Fiery Temper"]
    assert _state(sid)["madness_cast"] is None


def test_w1g1_the_cast_is_paid_by_tapping_and_sent_with_the_cast_fields():
    sid, game = _w1g1_session()
    bears = game.players[1].battlefield[0]
    cast = {
        "action": "madness_cast_confirm", "accept": True,
        "card_name": "Fiery Temper",
        "target_seat": 1, "target_permanent_id": bears.permanent_id,
    }
    # Unpaid: refused with the engine's reason, and the offer stays open.
    refused = _act(sid, **cast)
    assert refused.status_code == 400
    assert "insufficient mana" in refused.json()["detail"]
    assert _state(sid)["madness_cast"] is not None

    mountain = game.players[0].battlefield[1]
    tapped = _act(sid, action="tap", permanent_id=mountain.permanent_id)
    assert tapped.status_code == 200, tapped.text

    answered = _act(sid, **cast)
    assert answered.status_code == 200, answered.text
    assert _state(sid)["madness_cast"] is None
    assert game.stack and game.stack[-1].card.name == "Fiery Temper"
    assert not game.stack[-1].ability_effect_kind  # the spell, not the trigger
