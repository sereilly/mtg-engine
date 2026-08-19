"""A "Choose one or more" cast, over HTTP.

The engine can take several modes and give each its own targets (CR 601.2b /
601.2c), and that is asserted in ``tests/rules/test_casting_spells.py``. This
file asks the other half of the same question: does the wire carry it?

The wire is where the last multi-target feature was lost — round 65 built
cross-board targeting end to end and ``_queue_spell_from_request`` dropped the
ids, so every such cast over HTTP resolved on one board. A mode's target is the
same shape of thing: a second target field that a request model without it would
silently discard while still returning 200.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_M21 = {c.name: c for c in load_cards(manifest_set_path("M21", include_measured=True))}


def _make_session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 424,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_M21["Sublime Epiphany"]]
    mine = Permanent(card=_M21["Alpine Watchdog"])
    theirs = Permanent(card=_M21["Garruk's Gorehorn"])
    game.players[0].battlefield = [mine]
    game.players[1].battlefield = [theirs]
    game.players[1].hand = []
    game.players[1].library = [_M21["Shock"]]
    session.current_turn = 0
    game.active_player_index = 0
    game._sync_control()
    return sid, game, mine, theirs


def test_a_hand_card_reports_that_several_of_its_modes_may_be_taken():
    """The client cannot read the bound off the mode list, and reading it off
    the labels would be the substring match the compiler stopped making. So it
    is sent."""
    sid, _game, _mine, _theirs = _make_session()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    card = next(c for c in state["players"][0]["hand"] if c["name"] == "Sublime Epiphany")

    assert card["modes_at_least"] is True
    assert len(card["modes"]) == 5


def test_a_cast_naming_three_modes_performs_all_three_over_http():
    """One request, three modes, three different targets: a permanent on the
    opponent's board, one on the caster's, and a seat."""
    sid, game, mine, theirs = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Sublime Epiphany",
            "mode_choices": [
                {"index": 2, "target_seat": 1, "permanent_id": theirs.permanent_id},
                {"index": 3, "target_seat": 0, "permanent_id": mine.permanent_id},
                {"index": 4, "target_seat": 1},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert [c.name for c in game.players[1].hand] == ["Garruk's Gorehorn", "Shock"]
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Alpine Watchdog", "Alpine Watchdog",
    ]
    assert list(game.controlled_by(1)) == []


def test_a_modes_stale_id_is_not_repointed_at_whatever_took_the_slot():
    """The same contract every other target on this wire holds to (CR 400.7): an
    id that no longer names a permanent is a mode that does nothing, never a
    fall back to the index beside it — which by then addresses the permanent
    that slid into the slot."""
    sid, game, mine, theirs = _make_session()
    gone = theirs.permanent_id
    game.remove_from_battlefield(theirs)
    survivor = Permanent(card=_M21["Concordia Pegasus"])
    game.players[1].battlefield = [survivor]
    game._sync_control()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Sublime Epiphany",
            "mode_choices": [
                {"index": 2, "target_seat": 1, "permanent_id": gone, "permanent_index": 0},
            ],
        },
    )

    assert resp.status_code == 404, resp.text
    assert [p.card.name for p in game.controlled_by(1)] == ["Concordia Pegasus"], (
        "the stale id bounced the permanent that took the vacated slot"
    )
    assert game.players[1].hand == []
    assert [c.name for c in game.players[0].hand] == ["Sublime Epiphany"], (
        "refused before the spell left the hand"
    )
