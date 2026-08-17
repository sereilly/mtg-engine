"""Regression: a cast naming targets on two battlefields, over HTTP.

Round 65 built the several-target machinery for permanents end to end — per-slot
filters, cross-board ids on the wire, a browser picker that stopped collapsing to
one seat — and ``web/actions.py``'s preamble resolves ``target_permanent_ids``
off the request and deliberately *keeps* them, with a comment saying why: an
index is positional on one ``target_seat``, so a pair of targets on two boards
cannot be expressed by indices at all.

``_queue_spell_from_request`` then dropped them. Every cross-board **cast** over
HTTP therefore lost its second slot and resolved it as an index on the first
slot's board, while the engine, the activation path and the browser all had it
right. Rookie Mistake — "target creature gets +0/+2 and another target creature
gets -2/-0" — has been half-castable in the browser since that round.

The activation path is asserted alongside it, because it is the path that was
already correct: if a later change breaks one of the two, this says which.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
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
            "seed": 909,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].hand = [_M21["Rookie Mistake"]]
    from engine.models import Permanent

    mine = Permanent(card=_M21["Concordia Pegasus"])      # 1/3
    theirs = Permanent(card=_M21["Concordia Pegasus"])    # 1/3
    game.players[0].battlefield = [mine]
    game.players[1].battlefield = [theirs]
    session.current_turn = 0
    game.active_player_index = 0
    return sid, game, mine, theirs


def test_a_cast_naming_one_creature_on_each_board_reaches_both():
    sid, game, mine, theirs = _make_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Rookie Mistake",
            "target_seat": 0,
            "target_permanent_ids": [mine.permanent_id, theirs.permanent_id],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (1, 5)
    assert (theirs.effective_power, theirs.effective_toughness) == (-1, 3), (
        "the second slot resolved on the opponent's board, not as an index on "
        "the caster's"
    )


def test_a_stale_id_is_a_404_rather_than_a_fallback_to_an_index():
    """The other half of the same contract: the wire never silently degrades an
    unresolvable id into a slot number."""
    sid, game, mine, theirs = _make_session()
    gone = theirs.permanent_id
    game.remove_from_battlefield(theirs)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Rookie Mistake",
            "target_seat": 0,
            "target_permanent_ids": [mine.permanent_id, gone],
        },
    )

    assert resp.status_code == 404
    assert (mine.effective_power, mine.effective_toughness) == (1, 3)
