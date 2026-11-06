"""Dimensional Breach's upkeep return, over the wire and in the client.

"…at the beginning of each player's upkeep, that player returns one of the
exiled cards they own to the battlefield." W2G1 built the prompt
(``exiled_card_return``: ``web/prompt_cards._exiled_card_return``); this is its
client half (SCG W2G2b, ``applyExiledCardReturnPrompt``). Scourge is still
under ``measured``, so the board is placed on the session's game directly and
the Breach cast through the engine, as the Debug Menu does; every answer goes
through the real action route in the body the client builds.
"""

from __future__ import annotations

import shutil

import pytest

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import client, resolve_stack, run_app_js, seat_plays_first
from tests.ui.test_lgn_w2g1_client_ui_api import _DOM
from web.app import store


def _pool():
    names = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    names.update({
        card.name: card
        for card in load_cards(manifest_set_path("SCG", include_measured=True))
    })
    return names


def _breached(mine, theirs):
    """A human-vs-human table where seat 0 has cast Dimensional Breach over
    *mine* / *theirs*, stopped in seat 0's next upkeep with the return owed."""
    pool = _pool()
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "seed": 4106,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    seat_plays_first(sid)
    game = store.get(sid).game
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=pool[name])
            permanent.metadata["summoning_sickness_turn"] = -99
            game._put_permanent_onto_battlefield(seat, permanent, None)
    game.players[0].hand.append(pool["Dimensional Breach"])
    game._recompute_continuous_effects()
    assert game.cast_from_hand(0, "Dimensional Breach").supported
    resolve_stack(game)
    assert list(game.all_permanents()) == []
    game.turn += 1
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.resolve_upkeep(0, defer_priority=True)
    resolve_stack(game)
    return sid, game


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_return_is_offered_face_up_to_its_seat_and_the_route_takes_the_pick():
    sid, game = _breached(["Grizzly Bears", "Hill Giant", "Craw Wurm"], ["Plains"])
    prompt = _state(sid, 0)["exiled_card_return"]
    assert prompt["player_seat"] == 0 and prompt["zone"] == "battlefield"
    names = [choice["name"] for choice in prompt["choices"]]
    assert sorted(names) == ["Craw Wurm", "Grizzly Bears", "Hill Giant"]
    # Face up: each choice carries the card as the client draws it.
    for choice in prompt["choices"]:
        assert choice["card"]["name"] == choice["name"] and choice["card"]["type"]
    # The other seat is not asked (it is not their card to choose).
    assert _state(sid, 1)["exiled_card_return"] is None
    pick = next(c for c in prompt["choices"] if c["name"] == "Grizzly Bears")
    response = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "exiled_card_return_confirm",
        "exile_entry_index": pick["entry_index"],
    })
    assert response.status_code == 200, response.text
    assert _state(sid, 0)["exiled_card_return"] is None
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
    assert sorted(card.name for card in game.players[0].exile) == ["Craw Wurm", "Hill Giant"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_the_client_draws_a_button_per_card_and_sends_the_one_clicked():
    """The renderer, run in node over the payload the server sent: one button
    per card with its name and type (no Decline, no Cancel), and the click on
    the second sends that card's ``entry_index`` — which the route honours."""
    sid, game = _breached(["Grizzly Bears", "Hill Giant"], ["Plains"])
    state = _state(sid, 0)
    out = run_app_js(
        ["getExiledCardReturnInfo", "applyExiledCardReturnPrompt"],
        r'''
const info = getExiledCardReturnInfo(currentState);
applyExiledCardReturnPrompt(info);
const buttons = q("promptSteps").querySelectorAll("[data-ecr-entry]");
const labels = q("promptSteps").innerHTML;
await buttons[1].click();
return {
  title: q("promptTitle").textContent,
  entries: buttons.map((b) => Number(b.dataset.ecrEntry)),
  labels,
  cancelHidden: q("promptCancelBtn").classList.contains("hidden"),
  sent: SENT,
  other: getExiledCardReturnInfo({ ...currentState, exiled_card_return: { ...currentState.exiled_card_return, player_seat: 1 } }),
};
''',
        {"state": state},
        prelude=_DOM + "function showCardPreview() {}",
    )
    choices = state["exiled_card_return"]["choices"]
    assert out["title"] == "Dimensional Breach — return an exiled card"
    assert out["entries"] == [c["entry_index"] for c in choices]
    for choice in choices:
        assert choice["name"] in out["labels"] and choice["card"]["type"] in out["labels"]
    assert out["cancelHidden"] is True and "Decline" not in out["labels"]
    assert out["other"] is None  # another seat's prompt is not drawn here
    (body,) = out["sent"]
    assert body == {
        "seat": 0, "action": "exiled_card_return_confirm",
        "exile_entry_index": choices[1]["entry_index"],
    }
    response = client.post(f"/api/sessions/{sid}/action", json=body)
    assert response.status_code == 200, response.text
    assert [p.card.name for p in game.controlled_by(0)] == [choices[1]["name"]]
