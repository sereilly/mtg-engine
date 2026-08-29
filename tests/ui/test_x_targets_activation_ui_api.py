"""Web-API tests for an **activated ability** that names X targets.

Candelabra of Tawnos — "{X}, {T}: Untap X target lands" — is the card, and it is
one of the two shipped cards recorded *failing* in ``CARD_VERIFICATION.md``
("It should ask me how many lands to untap"). The engine half was always right:
given an X and a list of ids it untaps exactly those lands, and
``tests/sets/test_antiquities_artifacts.py`` proves it. What was missing was the
whole client path, and the engine tests could not see it because they pass the
X and the targets themselves.

Three things had to line up and none of them did:

* the activation cascade asked "does this ability target a land?" before it
  asked "does it name several?", so the single-land picker claimed the card,
  sent one target and never asked for X;
* the X prompt for an ability existed but ran *after* that cascade, and sent
  the ability the moment a number was chosen — with no targets at all;
* ``resolvePendingCastX`` explicitly excluded ``castAction === "activate"``
  from continuing into the several-targets picker.

So these pin the round trip rather than the JS: the spec the client reads to
know it must ask for X, and the request the fixed cascade sends.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store
from web.runtime import CARD_CATALOG

client = TestClient(app)

_CARDS = {card.name: card for card in CARD_CATALOG}


def _session(land_count=3, mana=5):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai",
            "host_name": "Host",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 99,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    game = session.game
    candelabra = Permanent(card=_CARDS["Candelabra of Tawnos"])
    candelabra.summoning_sick = False
    lands = [Permanent(card=_CARDS["Forest"]) for _ in range(land_count)]
    for land in lands:
        land.tapped = True
    game.players[0].battlefield = [candelabra, *lands]
    game.players[0].mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": mana}
    return sid, game, candelabra, lands


def _activation_spec(sid):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return state["players"][0]["battlefield"][0].get("target_spec")


def test_the_spec_tells_the_client_the_ability_names_x_targets():
    """`x_targets` is what makes the client ask for X *before* picking, and it
    has to arrive beside the ordinary land `kind` — the client used to read the
    kind, match its single-land picker and never look at this flag."""
    sid, _game, _candelabra, _lands = _session()

    spec = _activation_spec(sid)

    assert spec is not None
    assert spec["x_targets"] is True
    assert spec["kind"] == "land"
    assert {t["index"] for t in spec["valid_targets"]} == {1, 2, 3}


def test_activating_with_an_announced_x_untaps_exactly_those_lands():
    sid, game, candelabra, lands = _session()
    chosen = [lands[0].permanent_id, lands[1].permanent_id]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Candelabra of Tawnos",
            "permanent_index": 0,
            "x_value": 2,
            "target_permanent_ids": chosen,
            "target_seat": 0,
        },
    )
    assert resp.status_code == 200, resp.json()
    game._settle()

    assert [land.tapped for land in lands] == [False, False, True]
    assert candelabra.tapped, "{T} is part of the cost"
    assert game.players[0].mana_pool["C"] == 3, "and {X} charged 2"


def test_an_x_the_player_cannot_pay_is_refused_with_nothing_spent():
    """CR 601.2b: the announced X has to be paid. The refusal matters more than
    usual here because the picker is sized by X — an unaffordable announcement
    that went through would untap lands nobody paid for."""
    sid, game, candelabra, lands = _session(mana=1)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Candelabra of Tawnos",
            "permanent_index": 0,
            "x_value": 2,
            "target_permanent_ids": [lands[0].permanent_id, lands[1].permanent_id],
            "target_seat": 0,
        },
    )

    assert resp.status_code == 400
    assert all(land.tapped for land in lands)
    assert not candelabra.tapped, "nothing was paid"
    assert game.players[0].mana_pool["C"] == 1
