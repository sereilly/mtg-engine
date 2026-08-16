"""Web-API tests for paying a spell's printed additional cost (CR 601.2b).

The picker on the client is the same one that chooses a target — the caster
clicks a creature on the battlefield — but *what* is chosen is a cost payment,
and it travels on the cost field rather than the target field. The two were the
same field while the cost was folded into Sacrifice's effect; once the cost
became general (engine/cast_costs.py), sending it as a target meant paying it
twice.

These pin the server half of that contract: the field the client sends, the
identity the id resolves to, and the refusal when nothing can pay.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}


def _session(*battlefield: str):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 818,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = [Permanent(card=_CARDS[n]) for n in battlefield]
    game.players[0].hand = [_CARDS["Sacrifice"]]
    game.players[1].battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _cast(sid: str, **extra) -> dict:
    return client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Sacrifice", **extra},
    )


def test_the_chosen_creature_travels_on_the_cost_field():
    """The caster picks the Hill Giant; its mana value is what the spell buys.

    Addressed by ``cost_permanent_id`` — the stable id, resolved once at the top
    of web/actions.py — so a creature that left the battlefield since the click
    is a 404 rather than whichever permanent slid into its slot.
    """
    sid, _sess, game = _session("Grizzly Bears", "Hill Giant")
    giant = game.players[0].battlefield[1]

    resp = _cast(sid, cost_permanent_id=giant.permanent_id)
    assert resp.status_code == 200, resp.text

    # Paid *while casting* (CR 601.2b): the Giant is gone before the spell is
    # anywhere near resolving, which is the half of the rule the web path is
    # the only one that shows — `cast_from_hand` settles the stack immediately.
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [item.card.name for item in game.stack] == ["Sacrifice"]

    game._settle()
    assert game.players[0].mana_pool["B"] == 4, "the mana value of the creature picked"


def test_a_stale_cost_id_is_a_404_and_nothing_is_sacrificed():
    sid, _sess, game = _session("Grizzly Bears")

    resp = _cast(sid, cost_permanent_id=9_999_999)
    assert resp.status_code == 404

    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Sacrifice"]


def test_the_spell_is_refused_when_no_creature_can_pay():
    """CR 601.2h through the wire: the action reports the failure and the card
    stays in hand, rather than resolving for free."""
    sid, _sess, game = _session()

    resp = _cast(sid)

    assert resp.status_code >= 400 or not resp.json().get("supported", True)
    assert [c.name for c in game.players[0].hand] == ["Sacrifice"]


# ---------------------------------------------------------------------------
# The discard cost's picker — the other half, and a different picker
# ---------------------------------------------------------------------------
#
# What pays "discard a card" is a card in the caster's own hand, so it is not
# chosen on the battlefield and the permanent picker above cannot carry it.
# `derive_cast_spec` returned None for it, so the client was never told to ask
# and a human seat silently discarded whatever was first in hand.
#
# M21 is measured, not shipped, so no deck can hold Thrill of Possibility and
# the flow is exercised here at the API layer — the same place the cast-from-zone
# suite meets its measured cards.

_M21 = {
    c.name: c
    for c in load_cards(manifest_set_path("M21", include_measured=True))
}


def _discard_cost_session():
    sid, session, game = _session()
    game.players[0].hand = [
        _M21["Shock"], _M21["Thrill of Possibility"], _M21["Alpine Watchdog"]
    ]
    game.players[0].library = [_M21["Swamp"]] * 4
    return sid, session, game


def _hand_card(state: dict, name: str) -> dict:
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)


def test_the_client_is_offered_every_card_but_the_one_being_cast():
    """The spec the picker is built from. CR 601.2a has already put the spell on
    the stack by the time costs are paid, so it is not among the payments."""
    sid, _sess, _game = _discard_cost_session()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = _hand_card(state, "Thrill of Possibility")["target_spec"]

    assert spec["kind"] == "hand_card" and spec["discard_cost"] is True
    assert [(t["hand_index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, "Shock"), (2, "Alpine Watchdog")
    ]


def test_the_chosen_card_travels_on_the_cost_field():
    """`cost_hand_index` indexes the hand the client is looking at — the one
    that still holds the spell — because that is the hand the player saw when
    they clicked."""
    sid, _sess, game = _discard_cost_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Thrill of Possibility",
            "cost_hand_index": 2,
        },
    )
    assert resp.status_code == 200, resp.text

    assert [c.name for c in game.players[0].graveyard] == ["Alpine Watchdog"]
    assert [item.card.name for item in game.stack] == ["Thrill of Possibility"]


def test_naming_the_spell_itself_is_refused_over_the_wire():
    """The client should never offer it — the enumeration above withholds it —
    and the server does not trust that it didn't."""
    sid, _sess, game = _discard_cost_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Thrill of Possibility",
            "cost_hand_index": 1,
        },
    )

    assert resp.status_code >= 400 or not resp.json().get("supported", True)
    assert len(game.players[0].hand) == 3 and not game.players[0].graveyard
