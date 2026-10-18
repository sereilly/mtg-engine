"""A human's AI opponent casts from its graveyard (CR 601.3, CR 702.34a).

The web AI's seat goes down the same road as the simulator's:
``ai_policy.choose_cast_action`` proposes, ``zone_being_cast_from`` finds the
card, ``cast_announcement`` makes the cast. Until Odyssey's wave 2 the first
walked the hand alone and each executor in ``web/game_flow`` read "the command
zone, or else the hand" for itself — so an AI opponent never flashed a card
back, and had it been handed such a proposal it would have read the card off
its hand at the graveyard's index.

Driven through ``POST /api/sessions/{id}/action`` with mana costs enforced, so
the executor, the tap plan and the payment under test are the ones a browser
game runs.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import _mk_card
from web.app import app, store

client = TestClient(app)

HUMAN, AI = 0, 1


@pytest.fixture(scope="module")
def pool(set_pool, catalog_by_name):
    return {**catalog_by_name, **set_pool("ODY")}


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
    assert game.enforce_mana_costs, "a web game charges for its spells"
    for player in game.players:
        player.hand = []
        player.battlefield = []
        player.graveyard = []
        player.exile = []
    return created["session_id"], session


def _turn(session, seat: int) -> None:
    session.current_turn = seat
    session.game.active_player_index = seat
    session.game.priority_player_index = seat
    session.game.priority_pass_count = 0


def _give(session, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    session.game._put_permanent_onto_battlefield(seat, permanent, seat)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _act(sid: str, **body):
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_ai_step_flashes_a_card_back_for_a_human_to_answer(pool):
    """Human across the table: Firebolt goes on the stack from the AI's
    graveyard, paid for with five tapped lands at its flashback cost, and the
    human has priority over it. Resolved, it is exiled."""
    sid, session = _session("human_vs_ai", 93001)
    game = session.game
    _turn(session, AI)
    game.players[AI].graveyard = [pool["Firebolt"]]
    lands = [_give(session, AI, pool["Mountain"]) for _ in range(5)]
    human_life = game.players[HUMAN].life

    payload = _act(sid, seat=HUMAN, action="ai_step")

    assert [item["card"]["name"] for item in payload["stack"]] == ["Firebolt"]
    item = game.stack[-1]
    assert item.flashback and item.caster_index == AI
    assert all(land.tapped for land in lands)
    assert not any(game.players[AI].mana_pool.values())
    assert game.players[AI].graveyard == []
    assert payload["priority_player"] == HUMAN

    _act(sid, seat=HUMAN, action="pass_priority")

    assert game.players[HUMAN].life == human_life - 2
    assert [card.name for card in game.players[AI].exile] == ["Firebolt"]
    assert game.players[AI].graveyard == []


def test_the_ai_step_flashes_a_card_back_against_another_ai(pool):
    """No human to wait for: the other arm of the same step casts and
    resolves in one call."""
    sid, session = _session("ai_vs_ai", 93002)
    game = session.game
    _turn(session, AI)
    game.players[AI].graveyard = [pool["Firebolt"]]
    for _ in range(5):
        _give(session, AI, pool["Mountain"])
    other_life = game.players[HUMAN].life

    _act(sid, seat=HUMAN, action="ai_step")

    assert game.players[HUMAN].life == other_life - 2
    assert [card.name for card in game.players[AI].exile] == ["Firebolt"]


def test_the_ai_does_not_flash_back_what_its_lands_cannot_pay_for(pool):
    """Four lands: Firebolt's mana cost four times over, its flashback cost
    not once. Nothing is cast and nothing is tapped."""
    sid, session = _session("human_vs_ai", 93003)
    game = session.game
    _turn(session, AI)
    game.players[AI].graveyard = [pool["Firebolt"]]
    lands = [_give(session, AI, pool["Mountain"]) for _ in range(4)]

    _act(sid, seat=HUMAN, action="ai_step")

    assert game.stack == []
    assert [card.name for card in game.players[AI].graveyard] == ["Firebolt"]
    assert not any(land.tapped for land in lands)


def test_the_ai_answers_a_spell_with_an_instant_from_its_graveyard(pool):
    """The priority response reads the same list: a flashback instant in the
    AI's graveyard is cast in response as one in its hand would be —
    Fervent Denial's "Counter target spell" at a 5/5, where the policy, which
    rehearses a response before making it, holds one that would change
    nothing (a Moment's Peace in a main phase)."""
    sid, session = _session("human_vs_ai", 93004)
    game = session.game
    _turn(session, HUMAN)
    dragon = _mk_card(
        name="Human Dragon", mana_cost="", type_line="Creature - Dragon",
        power=5, toughness=5,
    )
    game.enforce_mana_costs = False  # the human's invented card has no cost
    game.players[HUMAN].hand = [dragon]
    game.players[AI].graveyard = [pool["Fervent Denial"]]
    for _ in range(7):
        _give(session, AI, pool["Island"])

    cast = _act(sid, seat=HUMAN, action="cast", card_name="Human Dragon")
    assert [item["card"]["name"] for item in cast["stack"]] == ["Human Dragon"]

    _act(sid, seat=HUMAN, action="pass_priority")

    names = [item.card.name for item in game.stack]
    assert names == ["Human Dragon", "Fervent Denial"], names
    assert game.stack[-1].flashback
    assert game.players[AI].graveyard == []
