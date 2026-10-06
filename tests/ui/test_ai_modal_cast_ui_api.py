"""The web AI casts a modal spell in the mode its policy chose (CR 601.2b).

``engine.ai_policy.cast_announcement`` is the one function that turns a
``CastAction`` into a cast, and ``web/game_flow`` has four sites that make one:
the AI step's two arms (a human across the table — the spell waits on the
stack; no human — it resolves), the priority response, and the
declare-blockers instant. Each spelled its keywords out, so the mode would
have reached whichever ones somebody remembered; a mode dropped by an executor
is not refused, it is cast as the first bullet at the target chosen for
another.

Driven through ``POST /api/sessions/{id}/action`` so the executor under test is
the one a browser game runs.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import _mk_card
from web.app import app, store

client = TestClient(app)

RELIC = _mk_card(name="Human Relic", type_line="Artifact")


def _session(mode: str, seed: int):
    created = client.post(
        "/api/sessions",
        json={
            "mode": mode, "host_name": "Host", "guest_name": "AI",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        },
    ).json()
    session = store.get(created["session_id"])
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand = []
        player.battlefield = []
        player.graveyard = []
    return created["session_id"], session


def _ai_turn(session, seat: int = 1) -> None:
    session.current_turn = seat
    session.game.active_player_index = seat
    session.game.priority_player_index = seat
    session.game.priority_pass_count = 0


def _give(session, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    session.game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_the_ai_step_puts_the_chosen_mode_on_the_stack_for_a_human(catalog_by_name):
    """Human opponent: the spell is queued and the human gets priority over
    it — with Crosis's Charm's *third* bullet chosen, because the only thing
    across the table is an artifact."""
    sid, session = _session("human_vs_ai", 91001)
    _ai_turn(session)
    session.game.players[1].hand = [catalog_by_name["Crosis's Charm"]]
    relic = _give(session, 0, RELIC)

    response = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [item["card"]["name"] for item in payload["stack"]] == ["Crosis's Charm"]
    item = session.game.stack[-1]
    assert item.chosen_mode_index == 2
    assert item.target_permanent_id == [relic.permanent_id]
    assert payload["priority_player"] == 0

    passed = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
    )
    assert passed.status_code == 200, passed.text
    human = session.game.players[0]
    assert [card.name for card in human.graveyard] == ["Human Relic"], (
        "destroyed (mode 2), not returned to hand (mode 0)"
    )
    assert human.hand == [] and human.battlefield == []


def test_the_ai_step_resolves_the_chosen_mode_against_another_ai(catalog_by_name):
    """No human to wait for: the other arm of the same step, which casts and
    resolves in one call."""
    sid, session = _session("ai_vs_ai", 91002)
    _ai_turn(session)
    session.game.players[1].hand = [catalog_by_name["Hull Breach"]]
    _give(session, 0, RELIC)
    _give(session, 0, _mk_card(name="Human Shrine", type_line="Enchantment"))

    response = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "ai_step"},
    )

    assert response.status_code == 200, response.text
    other = session.game.players[0]
    assert sorted(card.name for card in other.graveyard) == [
        "Human Relic", "Human Shrine",
    ], "the third bullet: both, where mode 0 takes the artifact alone"


def test_the_ai_answers_a_spell_with_the_mode_that_counters_it(catalog_by_name):
    """The priority response: "Counter target spell" is Dromar's Charm's
    second bullet, and this window is the only moment it can be announced."""
    sid, session = _session("human_vs_ai", 91003)
    _ai_turn(session, seat=0)
    game = session.game
    dragon = _mk_card(
        name="Human Dragon", mana_cost="", type_line="Creature - Dragon",
        power=5, toughness=5,
    )
    game.players[0].hand = [dragon]
    game.players[1].hand = [catalog_by_name["Dromar's Charm"]]

    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Human Dragon"},
    )
    assert cast.status_code == 200, cast.text
    assert [item["card"]["name"] for item in cast.json()["stack"]] == ["Human Dragon"]

    passed = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
    )
    assert passed.status_code == 200, passed.text
    names = [item.card.name for item in game.stack]
    assert names == ["Human Dragon", "Dromar's Charm"], names
    assert game.stack[-1].chosen_mode_index == 1

    # The human lets the Charm resolve; the Dragon never arrives.
    for _ in range(4):
        if not game.stack:
            break
        again = client.post(
            f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"},
        )
        assert again.status_code == 200, again.text
    assert game.stack == []
    assert [card.name for card in game.players[0].graveyard] == ["Human Dragon"]
    assert game.players[0].battlefield == []
    assert game.players[1].life == 20, "countered — not the first bullet's five life"
