"""Web-API tests for the cast-from-exile/graveyard permission seam.

What the client sees and sends: ``castable_from_zones`` in the state payload
(which cards the viewer may cast or play from a non-hand zone right now), a
``cast`` action carrying ``from_zone``, and the two-zone exile search prompt
(``search_exile``) with its ``search_exile_confirm`` answer. The engine is the
authority — a cast without a live grant is a 400, not a fallback to the hand.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.cast_permissions import grant_permission
from engine.models import CardDefinition
from web.app import app, store

client = TestClient(app)


def _mk_card(
    name: str,
    oracle_text: str = "Draw a card.",
    type_line: str = "Instant",
    mana_cost: str = "{R}",
    colors: tuple[str, ...] = ("R",),
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=1.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=(),
        raw={},
    )


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_a_grant_shows_up_in_castable_from_zones_and_casts_through_the_api():
    sid, session, game = _session()
    spell = _mk_card("Test Ember")
    game.players[0].graveyard.append(spell)
    game.players[0].library = [_mk_card("Test Filler")]

    assert _state(sid)["castable_from_zones"] == []
    grant_permission(
        game, player_index=0, zone="graveyard", mode="cast",
        cards=[spell], duration=None, exile_instead=True, source_name="Test Grant",
    )
    entries = _state(sid)["castable_from_zones"]
    # ``owner_seat`` is whose copy of the zone the index is into. It is the
    # viewer's own on every grant but the cross-seat one (Grinning Totem exiles
    # a card into the *searched* player's exile and hands the permission to the
    # searcher), and it is stated on every entry rather than only on that one so
    # the client has a single rule to read.
    assert entries == [
        {"zone": "graveyard", "index": 0, "name": "Test Ember", "free": False,
         "source": "Test Grant", "owner_seat": 0}
    ]
    # The opponent's view carries no permission — it is seat 0's, not a
    # property of the card.
    assert _state(sid, seat=1)["castable_from_zones"] == []

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Test Ember", "from_zone": "graveyard"},
    )
    assert resp.status_code == 200, resp.text
    # On the stack, out of the graveyard, and the stack object knows its zone.
    assert game.stack and game.stack[-1].card.name == "Test Ember"
    assert game.stack[-1].cast_from_zone == "graveyard"
    assert game.stack[-1].exile_instead_of_graveyard is True
    assert not any(c.name == "Test Ember" for c in game.players[0].graveyard)
    # Both seats pass; the spell resolves, and the grant's printed rider exiles
    # it instead of returning it to the graveyard.
    for passing_seat in (0, 1):
        passed = client.post(
            f"/api/sessions/{sid}/action",
            json={"seat": passing_seat, "action": "pass_priority"},
        )
        assert passed.status_code == 200, passed.text
    assert any(c.name == "Test Ember" for c in game.players[0].exile)
    assert not any(c.name == "Test Ember" for c in game.players[0].graveyard)
    assert _state(sid)["castable_from_zones"] == []


def test_casting_from_a_zone_without_a_grant_is_a_400():
    sid, session, game = _session()
    game.players[0].graveyard.append(_mk_card("Test Ember"))
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Test Ember", "from_zone": "graveyard"},
    )
    assert resp.status_code == 400
    assert "no effect allows" in resp.json()["detail"]


def test_the_exile_search_prompt_renders_and_confirms():
    sid, session, game = _session()
    red = _mk_card("Test Ember")
    blue = _mk_card("Test Ripple", colors=("U",), mana_cost="{U}")
    game.players[0].graveyard.extend([red, blue])
    game.players[0].library = [_mk_card("Test Cinder")]

    game.arm_pending_choice(
        "search_exile_cards", 0,
        zones=("graveyard", "library"),
        card_types=("instant", "sorcery"),
        colors=("R",),
    )

    state = _state(sid)
    prompt = state["search_exile"]
    assert prompt is not None
    assert prompt["caster_seat"] == 0
    # The blue instant fails the colour restriction, so only the red cards are
    # offered — graveyard index 0 and the lone library card.
    assert prompt["legal_graveyard_indices"] == [0]
    assert prompt["legal_indices"] == [0]

    # The owing seat cannot act around the open prompt.
    refused = client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"}
    )
    assert refused.status_code == 400

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_exile_confirm",
            "search_picks": [
                {"zone": "graveyard", "index": 0},
                {"zone": "library", "index": 0},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    exiled = [c.name for c in game.players[0].exile]
    assert sorted(exiled) == ["Test Cinder", "Test Ember"]
    assert _state(sid)["search_exile"] is None
    assert not game.effect_suspended


def test_an_illegal_pick_rejects_the_whole_answer():
    sid, session, game = _session()
    blue = _mk_card("Test Ripple", colors=("U",), mana_cost="{U}")
    game.players[0].graveyard.append(blue)
    game.arm_pending_choice(
        "search_exile_cards", 0,
        zones=("graveyard", "library"),
        card_types=("instant", "sorcery"),
        colors=("R",),
    )
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "search_exile_confirm",
            "search_picks": [{"zone": "graveyard", "index": 0}],
        },
    )
    assert resp.status_code == 400
    assert blue in game.players[0].graveyard, "nothing moved on a rejected answer"
    # Confirming with nothing picked is the legal fail-to-find and clears it.
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "search_exile_confirm", "search_picks": []},
    )
    assert resp.status_code == 200, resp.text
    assert _state(sid)["search_exile"] is None
