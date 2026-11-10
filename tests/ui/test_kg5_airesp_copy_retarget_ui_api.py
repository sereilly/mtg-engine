"""A person re-aims a copy with several targets over the wire, one
``retarget_choice`` per target (CR 707.10c, 115.7d).

What the web asks: the prompt the browser already renders for Psychic
Battle and for a storm copy aimed at a graveyard card — ``retarget_choice``,
its ``prompt`` naming which target of how many and what it names now, its
options "Keep the original's target" first and then every other legal target,
answered by position (``retarget_choice_confirm``). One prompt per target,
each served only to the copy's controller, the next served once the last is
answered. No new prompt kind, so no client change.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


def _act(session_id: str, **body):
    return client.post(f"/api/sessions/{session_id}/action", json=body)


def _state(session_id: str, seat: int):
    return client.get(f"/api/sessions/{session_id}/state", params={"seat": seat}).json()


def _resolve_top(session_id: str):
    for seat in (0, 1):
        _act(session_id, seat=seat, action="pass_priority")


def test_each_target_of_a_forked_reckless_spite_is_its_own_prompt_over_the_wire():
    pool = _pool()
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "seed": 4002,
    }).json()
    session_id = created["session_id"]
    client.post(f"/api/sessions/{session_id}/join", json={"guest_name": "Joiner"})
    seat_plays_first(session_id)
    game = store.get(session_id).game
    game.enforce_mana_costs = False
    game.players[0].hand = [pool["Reckless Spite"], pool["Fork"]]
    theirs = []
    for name in ("Grizzly Bears", "Hill Giant", "Craw Wurm"):
        permanent = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(1, permanent, None)
        theirs.append(permanent)
    game._recompute_continuous_effects()
    assert game.queue_from_hand(
        0, "Reckless Spite", target_player_index=1,
        target_permanent_ids=[theirs[0].permanent_id, theirs[1].permanent_id],
    ).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported
    _resolve_top(session_id)  # the Fork

    first = _state(session_id, 0)["retarget_choice"]
    assert first is not None
    assert _state(session_id, 1)["retarget_choice"] is None
    assert "target 1 of 2" in first["prompt"] and "Joiner's Grizzly Bears" in first["prompt"]
    names = [option["name"] for option in first["options"]]
    assert names[0] == "Keep the original's target"
    assert "Joiner's Craw Wurm" in names
    assert _act(
        session_id, seat=0, action="retarget_choice_confirm",
        target_index=first["options"][0]["index"],
    ).status_code == 200

    second = _state(session_id, 0)["retarget_choice"]
    assert second is not None and "target 2 of 2" in second["prompt"]
    wurm = next(option for option in second["options"] if option["name"] == "Joiner's Craw Wurm")
    assert _act(
        session_id, seat=0, action="retarget_choice_confirm", target_index=wurm["index"],
    ).status_code == 200
    assert _state(session_id, 0)["retarget_choice"] is None

    _resolve_top(session_id)  # the copy: the Bears and the Wurm
    alive = sorted(p.card.name for p in game.controlled_by(1))
    assert alive == ["Hill Giant"], (alive, game.log[-8:])
