"""The Debug Menu's raw-state paste keeps the hidden objects it does not name.

The paste (``POST /api/sessions/{id}/raw-state``, ``web/debug_actions``) takes
the state payload a seat was served, edited, and rebuilds the visible zones
from it. Two kinds of object reach that payload with no card named:

* a card **face down in exile** (CR 406.3) is the ``"<hidden>"`` card back
  every viewer is shown — and the paste skipped placeholders, so pasting any
  board with a Knowledge Vault's pile on it deleted the pile (Scourge's
  Phase 5: a face-down exile had to be set up through play after the last
  paste);
* a **face-down permanent** (CR 708.2) is named "Face-down creature", which is
  no card, so a paste of any board holding a morph was refused whole as
  "unknown card".

Each is driven through play — the Vault's ``{2}, {T}`` resolving, a creature
put onto the battlefield face down — then pasted back through the route as
the seat's own payload, and read back from every seat's payload and the
board.
"""
from __future__ import annotations

from engine.card_loader import load_catalog
from engine.face_down import face_down_card, hidden_card_of, is_face_down
from engine.models import Permanent
from tests.helpers import client
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4404,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.battlefield = []
        player.exile = []
    game.players[0].library = [_CARDS["Forest"]] * 5 + game.players[0].library
    return sid, game


def _state(sid, seat):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _exile_shown(sid, viewer, seat=0):
    return [
        entry["name"] if isinstance(entry, dict) else entry
        for entry in _state(sid, viewer)["players"][seat]["exile"]
    ]


def _paste(sid, state, seat):
    return client.post(f"/api/sessions/{sid}/raw-state", json={"state": state, "seat": seat})


def _vault_exiles_one(sid, game):
    """Knowledge Vault's "{2}, {T}: Exile the top card of your library face
    down", activated through the route and resolved."""
    vault = Permanent(card=_CARDS["Knowledge Vault"])
    game._put_permanent_onto_battlefield(0, vault, None)
    game.stack.clear()
    game.start_priority_window(0)
    acted = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_name": "Knowledge Vault",
        "permanent_id": vault.permanent_id, "ability_index": 0,
    })
    assert acted.status_code == 200, acted.text
    game._settle()
    assert not game.stack
    (exiled,) = game.players[0].exile
    assert exiled.name == "Forest"
    assert _exile_shown(sid, 0) == ["<hidden>"] and _exile_shown(sid, 1) == ["<hidden>"]
    return exiled


def test_a_pasted_face_down_exile_is_kept_face_down():
    sid, game = _session()
    exiled = _vault_exiles_one(sid, game)

    for seat in (0, 1):
        pasted = _paste(sid, _state(sid, seat), seat)
        assert pasted.status_code == 200, pasted.text
        # The same object, still hidden from both seats — and from the seat
        # that pasted, in the payload the paste route answers with.
        assert [id(card) for card in game.players[0].exile] == [id(exiled)]
        assert _exile_shown(sid, 0) == ["<hidden>"]
        assert _exile_shown(sid, 1) == ["<hidden>"]
        assert pasted.json()["players"][0]["exile"] == ["<hidden>"]
    # The Vault the paste rebuilt is a new object (CR 400.7) and the card is
    # no longer linked to it, but CR 406.3 has no ending: nobody turned it up.
    assert "Forest" not in "\n".join(game.log[-3:])


def test_a_paste_places_the_kept_card_where_its_placeholder_stands():
    """A named card beside the card back, including one that is the same
    deck object as the face-down card (a deck repeats one object per copy):
    each lands at its own position, and the face-down one stays the hidden
    one."""
    sid, game = _session()
    exiled = _vault_exiles_one(sid, game)

    state = _state(sid, 0)
    state["players"][0]["exile"] = [{"name": "Forest"}, "<hidden>", {"name": "Mountain"}]
    pasted = _paste(sid, state, 0)
    assert pasted.status_code == 200, pasted.text

    pile = game.players[0].exile
    assert [card.name for card in pile] == ["Forest", "Forest", "Mountain"]
    assert pile[1] is exiled and pile[0] is not exiled
    assert _exile_shown(sid, 0) == ["Forest", "<hidden>", "Mountain"]
    assert _exile_shown(sid, 1) == ["Forest", "<hidden>", "Mountain"]


def test_a_paste_that_drops_the_placeholder_drops_the_card():
    """The paste still says what the pile holds: a card back left out of it is
    a card taken out of exile, and a placeholder with no hidden card behind it
    names nothing."""
    sid, game = _session()
    _vault_exiles_one(sid, game)

    state = _state(sid, 0)
    state["players"][0]["exile"] = []
    state["players"][1]["exile"] = ["<hidden>"]
    assert _paste(sid, state, 0).status_code == 200
    assert game.players[0].exile == [] and game.players[1].exile == []
    assert _exile_shown(sid, 0) == [] and _exile_shown(sid, 1, seat=1) == []


def test_a_pasted_face_down_permanent_keeps_its_card():
    sid, game = _session()
    real = _CARDS["Exalted Angel"]
    morph = Permanent(card=face_down_card(real))
    game._put_permanent_onto_battlefield(0, morph, None)
    game._recompute_continuous_effects()

    for seat in (0, 1):
        # Seat 0's payload names the hidden card (CR 708.5); seat 1's does not,
        # and the paste finds it by the permanent's id.
        shown = _state(sid, seat)["players"][0]["battlefield"]
        assert [entry["face_down"] for entry in shown] == [True]
        assert ("hidden_card" in shown[0]) is (seat == 0)
        pasted = _paste(sid, _state(sid, seat), seat)
        assert pasted.status_code == 200, pasted.text
        (rebuilt,) = game.players[0].battlefield
        assert is_face_down(rebuilt) and hidden_card_of(rebuilt) is real
        assert rebuilt.effective_power == 2
        assert _state(sid, 1)["players"][0]["battlefield"][0]["name"] == "Face-down creature"
        assert _state(sid, 0)["players"][0]["battlefield"][0]["hidden_card"]["name"] == "Exalted Angel"


def test_a_face_down_permanent_nothing_names_is_refused_whole():
    """From another table — no ``hidden_card``, no permanent with that id — the
    paste cannot know what the creature is, and says how to name it, with
    nothing changed."""
    sid, game = _session()
    morph = Permanent(card=face_down_card(_CARDS["Exalted Angel"]))
    game._put_permanent_onto_battlefield(0, morph, None)
    state = _state(sid, 1)
    state["players"][0]["battlefield"][0]["id"] = 987654
    state["players"][0]["life"] = 3

    refused = _paste(sid, state, 1)
    assert refused.status_code == 400
    assert "hidden_card" in refused.json()["detail"]
    assert game.players[0].battlefield == [morph] and game.players[0].life != 3


def test_a_pasted_aura_is_attached_as_play_attaches_it():
    """The paste's ``attached_to_seat`` / ``attached_to_index`` reconnect an
    Aura through ``attach_aura`` — both directions — so its grant applies: a
    pasted Rancor on a Grizzly Bears is +2/+0 and trample at once. It wrote the
    Aura's own ``attached_to`` alone, and the Bears stayed a vanilla 2/2."""
    sid, game = _session()
    state = _state(sid, 0)
    state["players"][0]["battlefield"] = [
        {"name": "Grizzly Bears"},
        {"name": "Rancor", "attached_to_seat": 0, "attached_to_index": 0},
    ]
    pasted = _paste(sid, state, 0)
    assert pasted.status_code == 200, pasted.text
    bears = pasted.json()["players"][0]["battlefield"][0]
    assert (bears["name"], bears["power"], bears["toughness"]) == ("Grizzly Bears", 4, 2)
    assert "Trample" in bears["keywords"]
    rancor = pasted.json()["players"][0]["battlefield"][1]
    assert rancor["attached_to_id"] == bears["id"]
