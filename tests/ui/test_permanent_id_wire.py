"""The permanent's stable ``id`` on the wire, and the action fields that take it.

The client polls a state payload and then, some hundreds of milliseconds later,
posts an action written against it. Until now the only address it had for a
battlefield card was its *slot*, and a slot is only true for as long as nothing
leaves the battlefield: a creature dying between the poll and the click shifts
every later card down one, so the index the click carries names a different
permanent than the one under the cursor.

``id`` is the stable address. It goes out **alongside** ``index`` and comes back
in ``*_permanent_id`` fields that resolve to indices at one point in
``web.actions.do_action`` — additively, so the canvas can migrate on its own
schedule instead of in the same commit as the server.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.models import Permanent
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

_CARDS = {c.name: c for c in load_cards(LEA_PATH)}


def _session(seed: int = 5):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_ai", "host_name": "H",
            "host_colors": 2, "guest_colors": 2, "seed": seed,
        },
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    return sid, session.game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _battlefield(sid, seat=0):
    return _state(sid, seat)["players"][seat]["battlefield"]


def _put(game, seat, name):
    perm = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


# --------------------------------------------------------------------------
# Emitting it
# --------------------------------------------------------------------------

def test_every_battlefield_permanent_carries_an_id():
    sid, game = _session()
    bears = _put(game, 0, "Grizzly Bears")
    giant = _put(game, 0, "Hill Giant")

    payload = _battlefield(sid)
    assert [p["id"] for p in payload] == [bears.permanent_id, giant.permanent_id]


def test_the_id_is_emitted_alongside_the_index_not_instead_of_it():
    """Additive on purpose: the canvas addresses cards by array position today,
    and swapping the contract in the same change as the renderer would put the
    widest blast radius in the repo behind a single revert."""
    sid, game = _session()
    _put(game, 0, "Grizzly Bears")
    card = _battlefield(sid)[0]
    # Position in the array is still the index the client has always used.
    assert card["id"] and "name" in card and "tapped" in card


def test_an_id_is_stable_across_polls_while_an_index_is_not():
    """The failure the id removes, in one test: two polls with a death in
    between. The survivor keeps its id and changes its slot."""
    sid, game = _session()
    doomed = _put(game, 0, "Grizzly Bears")
    survivor = _put(game, 0, "Hill Giant")

    before = _battlefield(sid)
    assert [p["name"] for p in before] == ["Grizzly Bears", "Hill Giant"]
    survivor_slot_before = 1

    game.players[0].battlefield = [survivor]

    after = _battlefield(sid)
    assert [p["name"] for p in after] == ["Hill Giant"]
    # Same permanent, new slot, same id.
    assert after[0]["id"] == before[survivor_slot_before]["id"] == survivor.permanent_id
    assert doomed.permanent_id not in [p["id"] for p in after]


def test_ids_do_not_collide_between_seats():
    """One counter for the whole game, not one per player — otherwise "slot 0"
    is merely renamed "id 0" and still means two different permanents."""
    sid, game = _session()
    mine = _put(game, 0, "Grizzly Bears")
    theirs = _put(game, 1, "Grizzly Bears")
    state = _state(sid)
    ids = [p["id"] for seat in (0, 1) for p in state["players"][seat]["battlefield"]]
    assert ids == [mine.permanent_id, theirs.permanent_id]
    assert len(set(ids)) == 2


def test_an_aura_reports_its_host_by_id_as_well_as_by_index():
    sid, game = _session()
    host = _put(game, 0, "Grizzly Bears")
    aura = _put(game, 0, "Holy Strength")
    aura.metadata["attached_to"] = host

    payload = next(p for p in _battlefield(sid) if p["name"] == "Holy Strength")
    assert payload["attached_to_id"] == host.permanent_id
    assert payload["attached_to_index"] == 0
    assert payload["attached_to_seat"] == 0


def test_a_returning_permanent_reports_a_new_id():
    """CR 400.7 reaching the client: a card that leaves and comes back is a new
    object, so a canvas still holding the old id draws nothing rather than
    silently re-attaching its selection to the new permanent."""
    sid, game = _session()
    perm = _put(game, 0, "Grizzly Bears")
    first = _battlefield(sid)[0]["id"]

    game.players[0].battlefield = []
    game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS["Grizzly Bears"]), None)

    assert _battlefield(sid)[0]["id"] != first


# --------------------------------------------------------------------------
# Accepting it
# --------------------------------------------------------------------------

def _act(sid, **payload):
    return client.post(f"/api/sessions/{sid}/action", json=payload)


def test_an_action_may_address_a_permanent_by_id():
    sid, game = _session()
    _put(game, 0, "Forest")
    target = _put(game, 0, "Forest")

    response = _act(sid, seat=0, action="tap", permanent_id=target.permanent_id)
    assert response.status_code == 200
    assert target.tapped
    assert not game.players[0].battlefield[0].tapped


def test_an_id_beats_a_stale_index_sent_beside_it():
    """The precedence that makes the field worth having. A client mid-migration
    may send both; the id is the one that still means what it said."""
    sid, game = _session()
    first = _put(game, 0, "Forest")
    second = _put(game, 0, "Forest")

    response = _act(
        sid, seat=0, action="tap",
        permanent_id=second.permanent_id, permanent_index=0,
    )
    assert response.status_code == 200
    assert second.tapped and not first.tapped


def test_an_id_that_no_longer_resolves_is_refused_rather_than_falling_back():
    """The point of the whole exercise. Falling back to the index beside it
    would tap whichever permanent had slid into that slot — which is exactly the
    bug the id exists to prevent, now with a stable-looking field name on it."""
    sid, game = _session()
    doomed = _put(game, 0, "Forest")
    survivor = _put(game, 0, "Forest")
    game.players[0].battlefield = [survivor]

    response = _act(
        sid, seat=0, action="tap",
        permanent_id=doomed.permanent_id, permanent_index=0,
    )
    assert response.status_code == 404
    assert not survivor.tapped


def test_a_target_id_supplies_the_seat_it_is_on():
    """An id knows which battlefield it sits on, so a request cannot name a
    permanent and the wrong player at the same time."""
    sid, game = _session()
    game.players[0].hand = [_CARDS["Giant Growth"]]
    game.enforce_mana_costs = False
    theirs = _put(game, 1, "Grizzly Bears")

    response = _act(
        sid, seat=0, action="cast", card_name="Giant Growth",
        target_permanent_id=theirs.permanent_id,
    )
    assert response.status_code == 200
    item = game.stack[-1] if game.stack else None
    if item is not None:
        assert item.target_player_index == 1
        assert item.target_permanent_id == theirs.permanent_id
    else:
        assert theirs.power_bonus == 3


def test_index_only_requests_still_work():
    """Additive means additive: nothing that spoke indices yesterday has to
    change today."""
    sid, game = _session()
    _put(game, 0, "Forest")
    target = _put(game, 0, "Forest")
    assert _act(sid, seat=0, action="tap", permanent_index=1).status_code == 200
    assert target.tapped
