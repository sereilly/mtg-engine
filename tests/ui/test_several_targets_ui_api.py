"""Web-API tests for a spell that names "up to N target" permanents.

The client picks several permanents and confirms once, so the request carries a
*list* where every other target prompt carries one. These pin the round trip:
the spec the client reads to know it must collect several, the ids it sends
back, and the refusal when one of them is stale.

Basri's Acolyte because it is the card the multi-target round bought. The set is
measured rather than shipped, which is exactly the point of a measured set — a
card's focused test is written while the work is being done.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _session():
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
    mine = [Permanent(card=_M21["Concordia Pegasus"]) for _ in range(3)]
    # A copy, so `mine` stays the three creatures that were there before the
    # cast — the Acolyte joins the battlefield list, and an alias would make it
    # look like a fourth target.
    game.players[0].battlefield = list(mine)
    game.players[0].hand = [_M21["Basri's Acolyte"]]
    game.players[1].battlefield = [Permanent(card=_M21["Concordia Pegasus"])]
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game, mine


def _spec(sid: str, card_name: str) -> dict:
    """The target spec as the client reads it — off the serialized hand card.

    Not the ``card_target_spec`` endpoint: that resolves the name against the
    *shipped* catalog, which a measured set is deliberately absent from. A card
    in hand carries its own spec, which is the path a real cast takes."""
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    hand = state["players"][0]["hand"]
    return next(c for c in hand if c["name"] == card_name)["target_spec"]


def _cast(sid: str, session, **body) -> object:
    """Cast and let the spell resolve. A human-vs-human cast queues onto the
    stack and waits for priority; these tests are about the targeting round
    trip, not the priority window."""
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Basri's Acolyte", **body},
    )
    if resp.status_code == 200:
        session.game.resolve_stack()
    return resp


def test_the_spec_tells_the_client_how_many_targets_to_collect():
    sid, session, game, mine = _session()

    spec = _spec(sid, "Basri's Acolyte")

    assert spec["max_targets"] == 2
    assert spec["own_only"] is True
    # Only the caster's creatures: "you control" narrows the enumeration, so the
    # client never offers a target the effect would decline.
    assert {t["seat"] for t in spec["valid_targets"]} == {0}
    assert len(spec["valid_targets"]) == 3


def test_a_cast_naming_two_permanents_by_id_counters_exactly_those_two():
    sid, session, game, mine = _session()

    resp = _cast(
        sid, session,
        target_seat=0,
        target_permanent_ids=[mine[0].permanent_id, mine[2].permanent_id],
    )
    assert resp.status_code == 200, resp.text

    assert [p.effective_power for p in mine] == [2, 1, 2]
    assert game.players[1].battlefield[0].effective_power == 1


def test_a_stale_id_in_the_list_is_refused_rather_than_followed():
    """The whole reason the client sends ids. A permanent that left the
    battlefield between the click and the send must 404, never resolve to
    whichever permanent slid into its slot."""
    sid, session, game, mine = _session()
    gone_id = mine[1].permanent_id
    game.remove_from_battlefield(mine[1])

    resp = _cast(
        sid, session,
        target_seat=0,
        target_permanent_ids=[mine[0].permanent_id, gone_id],
    )

    assert resp.status_code == 404, resp.text
    assert any(c.name == "Basri's Acolyte" for c in game.players[0].hand), (
        "the spell was not cast"
    )


def test_choosing_no_targets_is_a_legal_cast():
    """"Up to two" may name none (CR 601.2c), so the confirm button has to be
    reachable with nothing selected and the cast has to go through."""
    sid, session, game, mine = _session()

    resp = _cast(sid, session, target_seat=0)
    assert resp.status_code == 200, resp.text

    assert [p.effective_power for p in mine] == [1, 1, 1]
    assert any(p.card.name == "Basri's Acolyte" for p in game.players[0].battlefield)
