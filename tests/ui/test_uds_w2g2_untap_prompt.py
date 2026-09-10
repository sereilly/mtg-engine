"""Web-API tests for Storage Matrix's untap-step type choice.

The engine's untap step is a **turn-based action** (CR 502.3) and gives nobody
priority (CR 502.4), so a decision inside it is the one shape the pending-choice
registry had never carried: every other prompt in it is armed by something
resolving. The three decisions the untap step already had (Time Vault's skip,
Winter Orb's selection, Old Man of the Sea's keep-tapped) are session fields with
a hand-written renderer, action and gate each — this one is a registered
``card_type_choice``, so the renderer, the action, the AI default and the "refuse
every other action" gate are the registry's and not this card's.

What these tests hold is the seam between the two: that the beginning phase
really stops at the untap step for a human, that the prompt reaches the seat that
owes it and nobody else, and that answering resumes the *step* rather than the
turn.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_CARDS = {
    c.name: c
    for c in load_cards(manifest_set_paths(include_measured=True))
}


def _session(seed: int = 5502):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    return sid


def _armed(seed: int = 5502):
    """Seat 1 holding a Storage Matrix and three tapped permanents, with seat
    0's turn about to end — so the next untap step is the one under test."""
    sid = _session(seed)
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    # The coin flip decides who starts, and which seat that is changes with the
    # seed — so it is pinned rather than left to the pregame: this test is about
    # the untap step that follows, and a seed whose flip went the other way would
    # have seat 0's ``end_turn`` refused and nothing under test at all.
    session.current_turn = 0
    game.active_player_index = 0
    game.players[1].battlefield = [
        Permanent(card=_CARDS["Storage Matrix"]),
        Permanent(card=_CARDS["Mountain"], tapped=True),
        Permanent(card=_CARDS["Grizzly Bears"], tapped=True),
        Permanent(card=_CARDS["Black Lotus"], tapped=True),
    ]
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "end_turn"})
    return sid, game


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _tapped(game) -> dict[str, bool]:
    return {perm.card.name: perm.tapped for perm in game.players[1].battlefield}


def test_the_beginning_phase_stops_at_the_untap_step_for_the_choice():
    """The turn does not run on with the offer unanswered.

    The failure this guards is Sanctum of All's, one step earlier in the turn:
    the step reports itself done, the phase walks to the main phase, and the
    prompt is still on screen. Here it would be worse than cosmetic — the untap
    would already have happened, so the answer could not change anything.
    """
    sid, game = _armed()
    state = _state(sid, 1)

    assert state["current_step"] == "untap", state["current_step"]
    info = state["card_type_choice"]
    assert info is not None
    assert info["card_name"] == "Storage Matrix"
    assert info["options"] == ["artifact", "creature", "land"]
    # Nothing untapped yet: the determination CR 502.3 makes has not been made.
    assert all(_tapped(game)[name] for name in ("Mountain", "Grizzly Bears", "Black Lotus"))


def test_the_prompt_carries_its_own_effect_sentence():
    """The client's fallback sentence is Teferi's Realm's and would be a lie.

    ``card_type_choice`` stopped being one card's prompt when this card started
    arming it, so what the answer *does* travels on the arming — the same reason
    the options do.
    """
    sid, _game = _armed(seed=5503)
    info = _state(sid, 1)["card_type_choice"]

    assert info["detail"] == "you can untap only permanents of the chosen type this step."
    assert "phase out" not in info["detail"]


def test_only_the_seat_that_owes_it_is_shown_the_choice():
    """"each player chooses … during **their** untap step" — the active one."""
    sid, _game = _armed(seed=5504)

    assert _state(sid, 1)["card_type_choice"] is not None
    assert _state(sid, 0)["card_type_choice"] is None


def test_every_other_action_is_refused_while_the_type_is_owed():
    """The registry's gate, not a hand-written check for this card.

    ``blocked_detail`` is what makes ``holds_priority`` true, so a kind that
    refuses nothing would be one the game carried on around — which for a
    decision inside a turn-based action means the step running past it.
    """
    sid, _game = _armed(seed=5505)

    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 1, "action": "end_turn"}
    )
    assert refused.status_code == 400, refused.text
    assert "choose a card type" in refused.json()["detail"]


def test_answering_resumes_the_untap_step_and_then_the_turn():
    """The answer is spent by the step it interrupted, and the phase carries on.

    The resume re-enters the untap step rather than the top of the turn, which
    is why the Bears untap and the turn is in a later step by the time the
    answer's response comes back.
    """
    sid, game = _armed(seed=5506)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "card_type_choice_confirm", "card_type": "creature"},
    )
    assert resp.status_code == 200, resp.text

    tapped = _tapped(game)
    assert tapped["Grizzly Bears"] is False
    assert tapped["Mountain"] is True
    assert tapped["Black Lotus"] is True

    state = _state(sid, 1)
    assert state["card_type_choice"] is None
    assert state["current_step"] != "untap", state["current_step"]


def test_an_option_the_card_never_offered_is_refused_over_the_wire():
    """The answer is bounded by the printed list all the way to the API."""
    sid, _game = _armed(seed=5507)

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 1, "action": "card_type_choice_confirm", "card_type": "enchantment"},
    )
    assert refused.status_code == 400, refused.text
    assert _state(sid, 1)["card_type_choice"] is not None
