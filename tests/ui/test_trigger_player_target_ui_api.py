"""Web-API tests for a triggered ability that picks a *player* as its target.

Floral Spuzzem's round taught ``_choose_trigger_targets`` to announce an
object; this is the other half of CR 601.2c, and until now it did not happen at
all. "Whenever you draw a card, target opponent mills two cards" (Teferi's
Tutelage) chose nobody, and the resolution fell back to the first living
opponent — right in a duel by coincidence, because there is only one of those.

So the table here is a three-seat free-for-all: two opponents is the smallest
board on which "the seat nobody chose" and "the seat the card names" can
differ, and it is the board the whole round is about.

The wire has two shapes in one list — a permanent by its stable id, a player by
their seat — so the payload says which each candidate is, and the answer sends
one field or the other.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store

client = TestClient(app)

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _table():
    """A three-seat free-for-all with Teferi's Tutelage under the human seat."""
    created = client.post(
        "/api/sessions",
        json={
            "mode": "free_for_all",
            "seats": [
                {"name": "Human", "is_ai": False, "colors": 2},
                {"name": "Second", "is_ai": True, "colors": 2},
                {"name": "Third", "is_ai": True, "colors": 2},
            ],
            "seed": 4343,
        },
    ).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.enforce_mana_costs = False
    # do_action refreshes this from the session's seat types on every
    # request; these tests fire the trigger straight at the engine, which no
    # request precedes, so the human seat is named here. Without it the prompt
    # takes its default at once and the round trip under test never exists.
    game.interactive_seats = {0}
    tutelage = Permanent(card=_M21["Teferi's Tutelage"])
    game.players[0].battlefield = [tutelage]
    for seat in (1, 2):
        game.players[seat].library = [_LEA["Mountain"]] * 6
        game.players[seat].graveyard = []
    game._sync_control()
    return sid, game, tutelage


def _fire_the_mill(game, tutelage):
    """Put the "whenever you draw a card" ability on the stack, unbound."""
    ability = next(
        a for a in compile_card_oracle(tutelage.card).triggered_abilities
        if a.instruction is not None and a.condition.kind == "draws_card"
    )
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=tutelage, card=tutelage.card,
        instruction=ability.instruction, effect_kind=ability.effect_kind,
    )


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_prompt_offers_the_opponents_faces_and_says_they_are_faces():
    sid, game, tutelage = _table()

    _fire_the_mill(game, tutelage)

    prompt = _state(sid)["trigger_target"]
    assert prompt["card_name"] == "Teferi's Tutelage"
    assert prompt["player_seat"] == 0
    assert [(c["kind"], c["seat"]) for c in prompt["candidates"]] == [
        ("player", 1), ("player", 2),
    ]
    # A face has no permanent to name, and the payload says so rather than
    # sending a null the client would have to guess about.
    assert all(c["id"] is None for c in prompt["candidates"])


def test_confirming_a_seat_mills_that_player_and_only_that_player():
    sid, game, tutelage = _table()

    _fire_the_mill(game, tutelage)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "trigger_target_confirm", "target_seat": 2},
    )

    assert resp.status_code == 200, resp.text
    game.resolve_stack(pause_for_choices=True)
    assert len(game.players[2].graveyard) == 2, game.log
    assert game.players[1].graveyard == [], "the opponent the card did not name"


def test_a_seat_the_prompt_never_offered_is_refused():
    """The engine and the picker read one list, so the ability's own controller
    is not an answer to "target **opponent**" (CR 115.4)."""
    sid, game, tutelage = _table()

    _fire_the_mill(game, tutelage)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "trigger_target_confirm", "target_seat": 0},
    )

    assert resp.status_code == 400, resp.text
    assert _state(sid)["trigger_target"] is not None, "the prompt is still owed"


def test_an_answer_naming_nothing_at_all_is_refused():
    sid, game, tutelage = _table()

    _fire_the_mill(game, tutelage)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "trigger_target_confirm"},
    )

    assert resp.status_code == 400, resp.text
    assert "target_seat" in resp.json()["detail"]
