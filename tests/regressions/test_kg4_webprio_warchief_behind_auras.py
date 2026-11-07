"""The Scourge re-check's turn 9, driven through the web API as the browser
drives it (kg4 `webprio`): the web AI attacks with Prodigal Sorcerer (six
Pemmin's Auras on it), Charging Paladin, Zealous Inquisitor and Krosan
Warchief; the person blocks the Warchief with Hill Giant; the AI holds {1}{G}.

Reproduced in the browser with every request body captured: the request
after the block was one ``ai_step``, which went from the declare blockers step
(the AI holding priority, the blocks locked) straight through combat damage —
the AI's answer to priority was asked and came back empty, because the
instant-speed chooser spent its three proposals on three of the six identical
Auras. It reproduces only with the Warchief behind the Auras on the
battlefield, as it was in the game (cast after them); every earlier rebuild
put it first. See ``tests/ai/test_kg4_webprio_identical_proposals.py``.
"""

from __future__ import annotations

import pytest

from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> None:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, (body, response.json())


# A whole web game driven over the API to the damage step (33-36 s): the
# full pass's, and every run that names this file.
@pytest.mark.full
def test_the_web_ais_blocked_warchief_regenerates_behind_six_auras():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 1)
    game = session.game
    game.enforce_mana_costs = True
    session.force_ai_attack_all = True
    for player in game.players:
        player.battlefield, player.hand, player.graveyard = [], [], []
        player.library = [_CARDS["Island"]] * 12
    (sorcerer, _paladin, _inquisitor) = _put(
        game, 1, ["Prodigal Sorcerer", "Charging Paladin", "Zealous Inquisitor"],
    )
    _put(game, 1, ["Island"] * 9 + ["Plains", "Plains", "Forest", "Mountain"])
    for aura in _put(game, 1, ["Pemmin's Aura"] * 6):
        attach_aura(aura, sorcerer)
    (warchief,) = _put(game, 1, ["Krosan Warchief"])
    placed = _put(game, 0, ["Hill Giant", "Goblin Warchief", "Edgewalker", "Mountain", "Mountain"])
    giant = placed[0]
    game._recompute_continuous_effects()

    blocked = False
    after_block = []
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            break
        combat = state.get("combat") or {}
        if blocked and state["current_step"] == "declare_blockers":
            after_block.append((state["priority_player"], [item["label"] for item in state["stack"]]))
        if (
            state["current_step"] == "declare_blockers" and not blocked
            and combat.get("attackers") and not combat.get("blockers_locked")
        ):
            _act(
                sid, action="declare_blockers", target_seat=0,
                blocker_pairs_by_id={str(giant.permanent_id): [warchief.permanent_id]},
            )
            blocked = True
        elif state["priority_player"] == 0:
            _act(sid, action="pass_priority")
        else:
            _act(sid, action="ai_step")
    assert blocked, game.log[-20:]
    assert "Krosan Warchief regenerated" in game.log, game.log[-20:]
    assert game.is_on_battlefield(warchief)
    # The regeneration went on the stack in the declare blockers step and the
    # person was asked over it (CR 117.4).
    assert any(
        holder == 0 and any("Krosan Warchief" in label for label in labels)
        for holder, labels in after_block
    ), after_block
