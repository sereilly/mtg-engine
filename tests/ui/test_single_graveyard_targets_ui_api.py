"""Web-API tests for "…target cards from **a single** graveyard".

`test_several_graveyard_targets_ui_api.py` pins several graveyard slots sent
for the caster's *own* pile. These pin the same wire shape — `target_seat`
plus `target_permanent_indices` — for the one printed phrase that leaves the
pile to the announcement: Rapid Decay's cast and Carrion Beetles' activation
(Ebony Charm's second mode, Decompose and Famished Ghoul print the same
words). Until Odyssey's second wave neither request carried anything: the
object went on the stack naming nothing and two prompts asked as it resolved.

The client already speaks this. Its several-graveyard picker collects
`{seat, idx}` picks out of every pile the spec offers and refuses to confirm
a selection spread over two (`confirmSeveralGraveyardTargets`), so one
`target_seat` is all the wire can say — which is the relation the card
prints, held by the request's own shape.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_UDS = {c.name: c for c in load_cards(manifest_set_path("UDS"))}
_USG = {c.name: c for c in load_cards(manifest_set_path("USG"))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}

_MINE = ("Grizzly Bears", "Forest")
_THEIRS = ("Swamp", "Hill Giant", "Terror", "Island")


def _make_session(*, beetles: bool = False):
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
    game.players[0].hand = [] if beetles else [_UDS["Rapid Decay"]]
    game.players[0].graveyard = [_LEA[name] for name in _MINE]
    game.players[1].graveyard = [_LEA[name] for name in _THEIRS]
    session.current_turn = 0
    game.active_player_index = 0
    if beetles:
        for player in game.players:
            player.battlefield.clear()
        permanent = Permanent(card=_USG["Carrion Beetles"])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.tapped = False
        permanent.metadata["summoning_sickness_turn"] = -99
    return sid, session, game


def _names(cards) -> list:
    return [card.name for card in cards]


def test_the_spec_offers_every_graveyard_and_says_the_cards_share_one():
    sid, _session, _game = _make_session()

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    spec = next(
        card for card in state["players"][0]["hand"] if card["name"] == "Rapid Decay"
    )["target_spec"]

    assert spec["kind"] == "graveyard_creature"
    assert spec["max_targets"] == 3
    assert spec["single_graveyard"] is True
    assert "own_graveyard_only" not in spec
    assert sorted((t["seat"], t["index"]) for t in spec["valid_targets"]) == [
        (0, 0), (0, 1), (1, 0), (1, 1), (1, 2), (1, 3),
    ]


def test_a_cast_naming_slots_in_one_graveyard_exiles_exactly_those():
    sid, _session, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Rapid Decay",
            "target_seat": 1, "target_permanent_indices": [1, 3],
        },
    )
    assert resp.status_code == 200, resp.text
    # Announced: the spell is on the stack naming its cards before anything
    # resolves, which is what the opponent gets to respond to.
    assert [stamp.card.name for stamp in game.stack[-1].target_graveyard_card] == [
        "Hill Giant", "Island",
    ]
    game.resolve_stack()

    assert _names(game.players[1].exile) == ["Hill Giant", "Island"]
    assert _names(game.players[1].graveyard) == ["Swamp", "Terror"]
    assert _names(game.players[0].graveyard) == [*_MINE, "Rapid Decay"]
    assert game.pending_choices == []


def test_a_slot_that_pile_does_not_hold_is_a_400_and_nothing_is_cast():
    sid, _session, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Rapid Decay",
            # The caster's own pile holds two cards; slot 3 is only the other's.
            "target_seat": 0, "target_permanent_indices": [0, 3],
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "no valid target for Rapid Decay"
    assert _names(game.players[0].hand) == ["Rapid Decay"]


def test_more_slots_than_the_card_prints_is_a_400():
    sid, _session, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Rapid Decay",
            "target_seat": 1, "target_permanent_indices": [0, 1, 2, 3],
        },
    )

    assert resp.status_code == 400, resp.text
    assert _names(game.players[0].hand) == ["Rapid Decay"]


def test_naming_no_cards_is_a_legal_cast_that_exiles_nothing():
    sid, _session, game = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Rapid Decay", "target_seat": 1},
    )

    assert resp.status_code == 200, resp.text
    game.resolve_stack()
    assert game.pending_choices == []
    assert _names(game.players[1].graveyard) == list(_THEIRS)
    assert game.players[1].exile == []


def test_an_activation_names_its_cards_the_same_way():
    sid, _session, game = _make_session(beetles=True)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    beetles = next(
        permanent for permanent in state["players"][0]["battlefield"]
        if permanent["name"] == "Carrion Beetles"
    )
    spec = beetles["target_spec"]
    assert (spec["kind"], spec["max_targets"], spec["single_graveyard"]) == (
        "graveyard_creature", 3, True,
    )

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "activate", "permanent_name": "Carrion Beetles",
            "permanent_index": 0, "ability_index": 0,
            "target_seat": 1, "target_permanent_indices": [0, 2],
        },
    )
    assert resp.status_code == 200, resp.text
    game.resolve_stack()

    assert _names(game.players[1].exile) == ["Swamp", "Terror"]
    assert _names(game.players[1].graveyard) == ["Hill Giant", "Island"]
    assert game.pending_choices == []
