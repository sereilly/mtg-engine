"""The copy's re-aiming prompt, over the real HTTP action endpoint.

Chain Lightning is the pool's one card that offers a spell copy to a seat other
than the caster, and that is the whole reason this goes through the API rather
than through the engine alone: the prompt is owed by the **opponent**, so every
half of the web layer that asks "whose choice is this?" is exercised — the
renderer that only shows it to its seat, the gate that refuses that seat's other
actions, and the action handler that checks an answer back against the list the
prompt offered.

The set is still under ``measured``, so the card is not in ``CARD_CATALOG`` and
no deck can hold one; the board is placed directly on the session's game, which
is what the Debug Menu does for a shipped card.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import client
from web.app import store


def _r36_session():
    leg = {card.name: card for card in load_cards(manifest_set_path("LEG", include_measured=True))}
    lea = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 3, "seed": 3601,
    }).json()
    session_id = created["session_id"]
    client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    game = store.get(session_id).game
    game.enforce_mana_costs = False
    game.players[0].hand = [leg["Chain Lightning"]]
    game.players[0].battlefield = [Permanent(card=lea["Serra Angel"])]
    game.players[1].battlefield = [
        Permanent(card=lea["Grizzly Bears"]),
        Permanent(card=lea["Mountain"]),
        Permanent(card=lea["Mountain"]),
    ]
    game._recompute_continuous_effects()
    return session_id, game


def _act(session_id: str, **body):
    return client.post(f"/api/sessions/{session_id}/action", json=body)


def _state(session_id: str, seat: int):
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


def _resolve_top(session_id: str):
    for seat in (0, 1):
        _act(session_id, seat=seat, action="pass_priority")


def _cast_at_the_bears(session_id: str, game):
    bears = game.players[1].battlefield[0]
    assert _act(
        session_id, seat=0, action="cast", card_name="Chain Lightning",
        target_seat=1, target_permanent_id=bears.permanent_id,
    ).status_code == 200
    _resolve_top(session_id)


def test_the_payer_is_the_damaged_seat_and_the_payment_taps_their_lands():
    """The offer is rendered for seat 1, refused for seat 0, and paying it taps
    the payer's own Mountains — a mid-resolution "you may pay" gives its player
    no priority window to make the mana first."""
    session_id, game = _r36_session()
    _cast_at_the_bears(session_id, game)

    offer = _state(session_id, 1)["optional_pay"]["pending"][0]
    assert offer["player_index"] == 1 and offer["cost"] == {"R": 2}
    assert _act(session_id, seat=0, action="resolve_optional_pay", accept=True).status_code == 400

    assert _act(session_id, seat=1, action="resolve_optional_pay", accept=True).status_code == 200

    mountains = [p for p in game.players[1].battlefield if p.card.name == "Mountain"]
    assert [p.tapped for p in mountains] == [True, True]


def test_the_copys_prompt_offers_players_and_permanents_and_gates_other_actions():
    """"Any target" is both (CR 115.4), so both are in the candidate list — and
    while the choice is owed, that seat's other actions are refused with the
    registry's own message rather than silently allowed."""
    session_id, game = _r36_session()
    _cast_at_the_bears(session_id, game)
    _act(session_id, seat=1, action="resolve_optional_pay", accept=True)
    _act(session_id, seat=1, action="resolve_optional_pay", accept=True)

    prompt = _state(session_id, 1)["copy_spell_target"]
    assert prompt["player_seat"] == 1
    assert {c["kind"] for c in prompt["candidates"]} == {"player", "permanent"}
    assert {c["name"] for c in prompt["candidates"]} >= {"Host", "Joiner", "Serra Angel"}
    assert _state(session_id, 0)["copy_spell_target"] is None, "not the caster's choice"

    blocked = _act(session_id, seat=1, action="pass_priority")
    assert blocked.status_code == 400
    assert "copy's target" in blocked.json()["detail"]


def test_the_copy_is_the_payers_and_resolves_at_the_target_they_chose():
    """**The test this round exists for**, over the wire: the copy is controlled
    by the seat that paid and is sent back at the caster's face."""
    session_id, game = _r36_session()
    _cast_at_the_bears(session_id, game)
    _act(session_id, seat=1, action="resolve_optional_pay", accept=True)
    _act(session_id, seat=1, action="resolve_optional_pay", accept=True)

    assert _act(
        session_id, seat=1, action="copy_spell_target_confirm", target_seat=0
    ).status_code == 200

    copy = game.stack[-1]
    assert copy.is_copy and copy.caster_index == 1 and copy.target_player_index == 0
    _resolve_top(session_id)
    assert game.players[0].life == 17, game.log
    assert game.players[1].life == 20, game.log
