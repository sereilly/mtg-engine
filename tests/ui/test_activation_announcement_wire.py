"""The wire does not accept an activation a browser cannot send (CR 602.2b).

``POST /api/sessions/{id}/action`` with ``action: "activate"`` is the route a
person's click arrives on. The client runs a picker for every target an
ability owes (it is handed the legal ones on ``target_spec``) and a picker for
every cost the payer chooses, and sends the answers with the action — CR 601.2c
and CR 601.2b through CR 602.2b. Two requests no client makes used to be
accepted, each resolving on something nobody chose:

* an activation naming **no target** for an ability that owes one. The engine's
  own API allows that for a headless caller and lets the handler pick; over the
  wire Samite Pilgrim's "prevent the next X damage that would be dealt to
  **target creature**" returned 200 and shielded the *opponent*;
* a **cost** permanent that cannot pay. Ertai, the Corrupted told to sacrifice a
  Sol Ring sacrificed Ertai — and because the route turned ``cost_permanent_id``
  into a bare slot on the payer's battlefield, an id naming an *opponent's*
  creature paid with whatever the payer held in that slot.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.shields import shields_on
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(mine=(), theirs=()):
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
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            row.append(permanent)
        rows.append(row)
    game.start_priority_window(0)
    return sid, game, rows[0], rows[1]


def _activate(sid, permanent, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": permanent.permanent_id,
        **fields,
    })


def _drain(sid, game):
    """Pass priority until the stack is empty; the AI seat passes in turn."""
    for _ in range(6):
        if not game.stack:
            return
        client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": 0, "action": "pass_priority"},
        )


def test_a_bare_activate_of_a_creature_only_shield_is_refused():
    sid, game, (pilgrim, bears, _plains), (theirs,) = _session(
        ["Samite Pilgrim", "Grizzly Bears", "Plains"], ["Grizzly Bears"],
    )

    refused = _activate(sid, pilgrim)

    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == (
        "Samite Pilgrim: this ability needs a target (CR 602.2b)"
    )
    assert not pilgrim.tapped and game.stack == []

    named = _activate(sid, pilgrim, target_permanent_id=bears.permanent_id)
    _drain(sid, game)

    assert named.status_code == 200, named.text
    assert pilgrim.tapped and shields_on(bears)
    assert not shields_on(theirs)
    assert not shields_on(game.players[0]) and not shields_on(game.players[1])


def test_the_only_legal_target_still_has_to_be_clicked():
    """The engine names a sole legal target for a *headless* caller. A client
    is asked for it like any other: the announcement is the player's."""
    sid, game, (tahngarth,), _ = _session(["Tahngarth, Talruum Hero"])

    refused = _activate(sid, tahngarth)

    assert refused.status_code == 400, refused.text
    assert not tahngarth.tapped and game.stack == []


def test_any_target_needs_the_seat_or_the_object_it_was_aimed_at():
    """"{T}: This creature deals 1 damage to any target." A seat alone is an
    announcement for an ability whose target may be a player — when the client
    sent one. The route's own default seat is not a choice anybody made."""
    sid, game, (tim,), _ = _session(["Prodigal Sorcerer"])

    refused = _activate(sid, tim)

    assert refused.status_code == 400, refused.text
    assert not tim.tapped and game.players[1].life == 20

    accepted = _activate(sid, tim, target_seat=1)
    _drain(sid, game)

    assert accepted.status_code == 200, accepted.text
    assert tim.tapped and game.players[1].life == 19


def test_an_ability_that_targets_nothing_is_still_sent_bare():
    """The refusal is the obligation's, not a rule about bare requests: "{T}:
    Add {G}" and a self-pump name nothing and are activated exactly as before."""
    sid, game, (shade,), _ = _session(["Frozen Shade"])

    accepted = _activate(sid, shade)
    _drain(sid, game)

    assert accepted.status_code == 200, accepted.text
    assert shade.effective_power == 1


def test_a_cost_permanent_that_cannot_pay_is_a_400_and_nothing_is_sacrificed():
    sid, game, (ertai, ring), _ = _session(["Ertai, the Corrupted", "Sol Ring"])
    game.players[1].hand.append(_CARDS["Grizzly Bears"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    game.start_priority_window(0)

    refused = _activate(
        sid, ertai, target_stack_index=0, cost_permanent_id=ring.permanent_id,
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == (
        "Ertai, the Corrupted: Sol Ring cannot pay its cost"
    )
    assert game.is_on_battlefield(ertai) and not ertai.tapped
    assert game.is_on_battlefield(ring) and len(game.stack) == 1


def test_an_opponents_permanent_named_as_a_sacrifice_is_not_read_as_a_slot():
    """The id names the opponent's Bears, which sit in the opponent's slot 0.
    Read as a bare slot it meant the payer's slot 0 — and the payer's own
    creature there went to the graveyard for a payment nobody announced."""
    sid, game, (mine, bombardment), (theirs,) = _session(
        ["Grizzly Bears", "Goblin Bombardment"], ["Grizzly Bears"],
    )

    refused = _activate(
        sid, bombardment, target_seat=1, cost_permanent_id=theirs.permanent_id,
    )

    assert refused.status_code == 400, refused.text
    assert "cannot pay its cost" in refused.json()["detail"]
    assert game.is_on_battlefield(mine) and game.is_on_battlefield(theirs)
    assert game.players[1].life == 20

    paid = _activate(
        sid, bombardment, target_seat=1, cost_permanent_id=mine.permanent_id,
    )
    _drain(sid, game)

    assert paid.status_code == 200, paid.text
    assert not game.is_on_battlefield(mine) and game.players[1].life == 19
