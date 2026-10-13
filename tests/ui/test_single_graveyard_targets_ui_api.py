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


def test_the_body_the_client_sends_for_an_activation_names_its_permanent():
    """`confirmSeveralGraveyardTargets` built ONE body for casts and
    activations — ``card_name``, ``target_seat`` and the slots — so an
    activation arrived with no ``permanent_index`` and no ``ability_index``,
    and the route read ``card_name`` as the permanent's name for want of
    anything better (a stopgap, deleted with its cause: two permanents of one
    name were told apart by nothing).

    The confirm now builds an activate body the way every other one is built,
    with the source by slot **and by id**. Replayed here against the SECOND of
    two Carrion Beetles, which is the board the old body could not address."""
    sid, _session, game = _make_session(beetles=True)
    second = Permanent(card=_USG["Carrion Beetles"])
    game._put_permanent_onto_battlefield(0, second, None)
    second.metadata["summoning_sickness_turn"] = -99
    first = next(p for p in game.controlled_by(0) if p is not second)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "activate", "permanent_name": "Carrion Beetles",
            "permanent_index": 1, "permanent_id": second.permanent_id,
            "ability_index": 0,
            "target_seat": 1, "target_permanent_indices": [1, 3],
        },
    )
    assert resp.status_code == 200, resp.text
    assert (first.tapped, second.tapped) == (False, True)
    game.resolve_stack()

    assert _names(game.players[1].exile) == ["Hill Giant", "Island"]
    assert game.pending_choices == []


def test_an_activation_named_only_by_a_cast_s_card_name_is_refused():
    """The body the stopgap existed for. It names no permanent, so it is not
    an activation of anything; the route says so instead of guessing."""
    sid, _session, game = _make_session(beetles=True)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "activate", "card_name": "Carrion Beetles",
            "target_seat": 1, "target_permanent_indices": [1, 3],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "permanent_name or permanent_index is required"
    assert game.players[1].exile == [] and not game.stack


def test_the_several_graveyard_confirm_builds_an_activate_body():
    """The client half, read as text (``app.js`` is DOM-coupled): the confirm
    that sends several graveyard slots builds the activation's own body — the
    permanent's slot, its id and the ability — and never an ``activate``
    carrying a cast's ``card_name``."""
    from tests.helpers import app_js_function_body

    body = app_js_function_body("confirmSeveralGraveyardTargets")
    assert 'action: "activate"' in body
    assert "permanent_index: p.sourcePermanentIndex" in body
    assert '"permanent_id", seat, p.sourcePermanentIndex' in body
    assert "body.ability_index = p.abilityIndex" in body
    # The cast body is the only one that carries `card_name`.
    activate_half = body.split('action: "activate"', 1)[1].split("card_name", 1)[0]
    assert "permanent_name: cardName" in activate_half


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
