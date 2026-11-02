"""Another seat's cards reach the viewer in the colours their owner's statics
give them.

Celestial Dawn: "Nonland permanents you control are white. The same is true
for … nonland cards you own that aren't on the battlefield." kg3 ``types``
made the viewer's *own* cards seat-aware (``_serialize_card``'s colours from
``object_colors.card_colors(game, card, caster_index)``); every call with no
seat — another seat's graveyard, exile, ante, command zone, library top, a
revealed hand — and every prompt card list still went out printed. Each
caller now names the owning seat (``_serialize_card(owner_seat=)``,
``PromptContext.owned_card``), so the Dawn's owner's red cards are white to
every viewer, and a card the Dawn's controller does not own is not.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _dawn_on_seat_one():
    """Seat 0 a person, seat 1 the AI with Celestial Dawn in play."""
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 3301,
        "host_deck_cards": [{"name": "Island", "count": 40}],
        "guest_deck_cards": [{"name": "Plains", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, Permanent(card=_CARDS["Celestial Dawn"]), None)
    return sid, session, game


def _seat_one(sid, viewer=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": viewer}).json()
    return state, state["players"][1]


def test_another_seats_public_zones_are_coloured_by_their_owners_dawn():
    sid, _session, game = _dawn_on_seat_one()
    bolt, giant, mountain = (
        _CARDS["Lightning Bolt"], _CARDS["Hill Giant"], _CARDS["Mountain"],
    )
    owner = game.players[1]
    owner.graveyard[:] = [bolt, mountain]
    owner.exile[:] = [giant]
    owner.ante[:] = [bolt]
    # The viewer's own red card is not the Dawn's to recolour.
    game.players[0].graveyard[:] = [bolt]

    state, theirs = _seat_one(sid)
    assert [card["colors"] for card in theirs["graveyard"]] == [["W"], []], (
        "a land card is never recoloured; a nonland card is the owner's Dawn's white"
    )
    assert theirs["exile"][0]["colors"] == ["W"]
    assert theirs["ante"][0]["colors"] == ["W"]
    assert state["players"][0]["graveyard"][0]["colors"] == ["R"]
    # The owner sees the same thing.
    _state, own = _seat_one(sid, viewer=1)
    assert own["graveyard"][0]["colors"] == ["W"]


def test_a_revealed_hand_and_its_prompt_list_are_coloured_by_their_owner():
    sid, _session, game = _dawn_on_seat_one()
    owner = game.players[1]
    owner.hand[:] = [_CARDS["Hill Giant"], _CARDS["Grizzly Bears"]]
    glasses = Permanent(card=_CARDS["Glasses of Urza"])
    game._put_permanent_onto_battlefield(0, glasses, None)
    game.start_priority_window(0)
    looked = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": glasses.permanent_id,
        "permanent_name": "Glasses of Urza", "target_seat": 1,
    })
    assert looked.status_code == 200, looked.text
    for _ in range(4):
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        if state.get("hand_reveal"):
            break
        client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    reveal = state.get("hand_reveal")
    assert reveal, sorted(k for k, v in state.items() if v)
    assert [card["name"] for card in reveal["cards"]] == ["Hill Giant", "Grizzly Bears"]
    assert [card["colors"] for card in reveal["cards"]] == [["W"], ["W"]]
    # The opponent's hand fan, served off the same reveal, agrees.
    shown = [card for card in state["players"][1]["hand"] if card != "<hidden>"]
    assert shown and all(card["colors"] == ["W"] for card in shown), shown


def test_without_the_dawn_every_card_keeps_its_printed_colours():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 3302,
    })
    sid = response.json()["session_id"]
    game = store.get(sid).game
    game.players[1].graveyard[:] = [_CARDS["Lightning Bolt"]]
    _state, theirs = _seat_one(sid)
    assert theirs["graveyard"][0]["colors"] == ["R"]


#: The prompt renderers that still call ``ctx.serialize_card`` (printed
#: colours), each for a reason: no single owner is known, or the card is not
#: in a zone its owner's Dawn reaches.
_PRINTED_PROMPT_CARDS = {
    "trigger_card(items[index])": "a trigger's source, on the stack or battlefield",
    'choice.data.get("_cards") or ()': "found or piled cards whose owner the choice does not record",
    "ctx.serialize_card(card)}": "a pile of exiled cards claimed across seats; Phyrexian Portal's piles",
    "ctx.serialize_card(card)\n": "a reordered library pile, read through the engine's own reader",
    "hidden_card_of(permanent)": "a face-down permanent's card: on the battlefield, not off it",
    "if card is not None else None": "an item of a group the session holds",
    "owner.sideboard[index]": "outside the game is not a zone (CR 400.11)",
    "sideboard[i]": "outside the game is not a zone (CR 400.11)",
}


def test_every_prompt_card_list_names_its_owner_or_says_why_not():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "web"
    printed = []
    for name in ("prompt_cards.py", "prompt_board.py", "prompt_values.py"):
        text = (root / name).read_text(encoding="utf-8")
        start = 0
        while (at := text.find("ctx.serialize_card(", start)) != -1:
            printed.append(text[at:text.find("\n", at) + 1])
            start = at + 1
    unexplained = [
        line for line in printed
        if not any(reason in line for reason in _PRINTED_PROMPT_CARDS)
    ]
    assert not unexplained, unexplained
    assert len(printed) <= 10, printed
