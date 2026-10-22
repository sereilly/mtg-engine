"""A roles **cast** two of whose slots are players, over HTTP.

Donate's announcement has one seat slot (``test_player_role_cast_ui_api.py``),
and the boundary used to translate it onto ``target_seat`` — one field, so a
second seat ref overwrote the first. Cultural Exchange ("…creatures **target
player** controls … creatures **another target player** controls") is the
first cast to name two players, and the refs are forwarded to the engine as
they are now: one entry per role, in role order, each ``{"seat": n}``.

This asserts the whole path a client walks: the picker it is handed, the
announcement it sends, the two prompts it is then shown (the second armed by
answering the first, with the game waiting on each), and the board afterwards.

The card is in a ``measured`` set, which the running app's catalog does not
hold, so it is put into the hand directly — the session and the wire are the
real ones.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.target_roles import ROLE_SEATS
from tests.helpers import _mk_creature_card
from web.app import app, store

client = TestClient(app)

_ODY = {c.name: c for c in load_cards(manifest_set_path("ODY", include_measured=True))}
NAME = "Cultural Exchange"


def _session(creatures=(2, 2)):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_ODY[NAME]]
    game.players[1].hand = []
    for seat, count in enumerate(creatures):
        game.players[seat].battlefield = [
            Permanent(card=_mk_creature_card(f"Seat {seat} Bear {number}", 2, 2))
            for number in range(count)
        ]
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _ids(game, seat):
    return [permanent.permanent_id for permanent in game.controlled_by(seat)]


def test_the_picker_walks_two_players_and_never_the_same_one_twice():
    sid, game = _session()

    spec = game.cast_target_spec(0, _ODY[NAME])

    assert [role["kind"] for role in spec["roles"]] == ["player", "player"]
    assert [
        (entry["seat"], [step["seat"] for step in entry["next"]])
        for entry in spec["valid_targets"]
    ] == [(0, [1]), (1, [0])]


def test_two_seat_refs_cast_the_spell_and_record_both_players():
    sid, game = _session()

    resp = _act(
        sid, seat=0, action="cast", card_name=NAME,
        target_role_refs=[{"seat": 1}, {"seat": 0}],
    )

    assert resp.status_code == 200, resp.text
    (item,) = game.stack
    assert item.choices[ROLE_SEATS] == [1, 0]
    # ...and the table is shown both of them: the hover arrows read the
    # per-role seats, where the scalar beside them is only the first.
    (shown,) = _state(sid, 1)["stack"]
    assert shown["targets"] == [
        {"kind": "player", "seat": 1}, {"kind": "player", "seat": 0},
    ]


def test_an_announcement_that_is_not_two_different_players_is_a_400():
    for refs in ([{"seat": 1}, {"seat": 1}], [{"seat": 1}], [{"seat": 0}, {"seat": 0}]):
        sid, game = _session()

        resp = _act(sid, seat=0, action="cast", card_name=NAME, target_role_refs=refs)

        assert resp.status_code == 400, (refs, resp.text)
        assert [card.name for card in game.players[0].hand] == [NAME]
        assert not game.stack

    # …and the one-seat spelling every other player-targeted cast uses.
    sid, game = _session()
    resp = _act(sid, seat=0, action="cast", card_name=NAME, target_seat=1)
    assert resp.status_code == 400, resp.text
    assert "requires 2 targets" in resp.text


def test_the_caster_answers_two_prompts_and_the_game_waits_on_each():
    sid, game = _session(creatures=(2, 3))
    assert _act(
        sid, seat=0, action="cast", card_name=NAME,
        target_role_refs=[{"seat": 1}, {"seat": 0}],
    ).status_code == 200

    # Both players pass; the spell begins to resolve and stops at its first
    # question, still on the stack (CR 608.2, CR 117.3b).
    assert _act(sid, seat=0, action="pass_priority").status_code == 200
    assert _act(sid, seat=1, action="pass_priority").status_code == 200
    state = _state(sid, 0)
    first = state["permanent_set_choice"]
    assert first["player_seat"] == 0
    assert first["card_name"] == NAME
    assert (first["up_to"], first["at_least"]) == (2, 0)
    assert "up to 2" in first["prompt"]
    assert sorted(entry["id"] for entry in first["candidates"]) == sorted(_ids(game, 1))
    assert {entry["seat"] for entry in first["candidates"]} == {1}
    assert state["waiting_on_prompt"] is True
    assert len(game.stack) == 1
    # The opponent is shown that a decision is owed, and is not asked it.
    assert _state(sid, 1)["waiting_on_prompt"] is False
    # Nothing else may happen while it is owed.
    assert _act(sid, seat=0, action="pass_priority").status_code == 400

    taken = _ids(game, 1)[:2]
    # Over the ceiling: refused, and the prompt is still there.
    assert _act(
        sid, seat=0, action="permanent_set_choice_confirm",
        target_permanent_ids=_ids(game, 1),
    ).status_code == 400
    assert _act(
        sid, seat=0, action="permanent_set_choice_confirm", target_permanent_ids=taken,
    ).status_code == 200

    # Answering the first arms the second: exactly as many, from the other board.
    second = _state(sid, 0)["permanent_set_choice"]
    assert (second["up_to"], second["at_least"]) == (2, 2)
    assert "exactly 2" in second["prompt"]
    assert {entry["seat"] for entry in second["candidates"]} == {0}
    assert len(game.stack) == 1
    given = _ids(game, 0)[:2]
    assert _act(
        sid, seat=0, action="permanent_set_choice_confirm",
        target_permanent_ids=given[:1],
    ).status_code == 400
    assert _act(
        sid, seat=0, action="permanent_set_choice_confirm", target_permanent_ids=given,
    ).status_code == 200

    state = _state(sid, 0)
    assert state.get("permanent_set_choice") is None
    assert not game.stack
    assert sorted(_ids(game, 0)) == sorted(taken)
    assert all(game.controller_index_of(game.permanent_by_id(pid)) == 1 for pid in given)
    assert [card.name for card in game.players[0].graveyard] == [NAME]
