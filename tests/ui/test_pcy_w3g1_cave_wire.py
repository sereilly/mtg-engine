"""Rhystic Cave on the wire: a click is an activation, never a tap.

"{T}: Choose a color. Add one mana of that color unless any player pays {1}.
Activate only as an instant." The engine refuses it at the tap seam — its mana
needs priority (CR 304.5) and the table's consent — so two web paths had to
learn that:

* the ``activate`` route sent a click on a land that names no ability index to
  the seam whenever the land printed any produced mana, which for the Cave is
  all five colours. The client's mana fan sends exactly that body, so the click
  failed with "failed to tap land for mana" however the player answered. A land
  the seam refuses now goes to the activation path, which gates the timing and
  offers the toll — and so does a depletion land, whose click failed the same
  way.
* the client's auto-tap planned from ``produced_mana``, which is what to offer
  when the land is activated, not whether a "tap" may be sent for it. The
  payload now carries the seam's own answer (``taps_for_mana``).

The Cave's own set is measured, so these build the board by hand rather than
through a deck.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from web.app import app, store
from web.game_flow import _auto_resolve_ai_pending
from web.serialization import _serialize_permanent

client = TestClient(app)
_W3G1_CARDS: dict = {}


def _w3g1_card(name):
    if not _W3G1_CARDS:
        _W3G1_CARDS.update(
            {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}
        )
    return _W3G1_CARDS[name]


def _w3g1_session(*, opponent_islands: int):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    game = session.game
    game.players[0].battlefield = [
        Permanent(card=_w3g1_card("Rhystic Cave")),
        Permanent(card=_w3g1_card("Island")),
    ]
    game.players[1].battlefield = [
        Permanent(card=_w3g1_card("Island")) for _ in range(opponent_islands)
    ]
    for seat in (0, 1):
        game.players[seat].mana_pool = {s: 0 for s in ("W", "U", "B", "R", "G", "C")}
    game._settle()
    game.start_priority_window(0)
    return sid, session, game  # _w3g1_session


def _w3g1_pool(game):
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def test_the_payload_says_which_lands_auto_tap_may_use():
    _sid, _session, game = _w3g1_session(opponent_islands=0)
    cave, island = game.players[0].battlefield
    cave_payload = _serialize_permanent(cave, game)
    assert cave_payload["taps_for_mana"] is False
    assert set(cave_payload["produced_mana"]) == {"W", "U", "B", "R", "G"}, (
        "the fan still offers every colour when the Cave is activated"
    )
    assert _serialize_permanent(island, game)["taps_for_mana"] is True


def test_a_click_on_the_cave_is_an_activation_that_offers_the_toll():
    """The fan's body: a colour and no ability index. The human (the active
    player) is asked first and declines; the AI opponent, with no land to pay
    from, declines in its turn; the {R} arrives."""
    sid, session, game = _w3g1_session(opponent_islands=0)
    cave = game.players[0].battlefield[0]
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_index": 0,
        "permanent_name": "Rhystic Cave", "mana_color": "R",
    })
    assert resp.status_code == 200, resp.text
    assert cave.tapped
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 0)]
    assert resp.json()["optional_pay"] is not None, "the human is shown the toll"

    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay", "accept": False,
    })
    assert resp.status_code == 200, resp.text
    assert _w3g1_pool(game) == {}, "the opponent has not answered yet"
    _auto_resolve_ai_pending(session)
    assert _w3g1_pool(game) == {"R": 1}
    assert game.pending_choices == []


def test_an_opponent_who_can_pay_denies_the_mana():
    sid, session, game = _w3g1_session(opponent_islands=1)
    client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_index": 0,
        "permanent_name": "Rhystic Cave", "mana_color": "G",
    })
    client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "resolve_optional_pay", "accept": False,
    })
    _auto_resolve_ai_pending(session)
    assert _w3g1_pool(game) == {}
    assert game.players[1].battlefield[0].tapped, "the AI paid its {1} from its Island"


def test_the_tap_action_is_refused_for_the_cave():
    """A "tap" sent for it — what the auto-tap used to send — is refused with
    nothing tapped, and the Island beside it taps as ever."""
    sid, _session, game = _w3g1_session(opponent_islands=0)
    cave, island = game.players[0].battlefield
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_index": 0, "mana_color": "R",
    })
    assert resp.status_code == 400
    assert not cave.tapped and _w3g1_pool(game) == {}
    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "tap", "permanent_index": 1, "mana_color": "U",
    })
    assert resp.status_code == 200, resp.text
    assert island.tapped and _w3g1_pool(game) == {"U": 1}


def test_a_click_on_a_depletion_land_pays_its_counter_through_the_same_route():
    """The shipped half of the route fix. Peat Bog's only mana ability is
    "{T}, Remove a depletion counter from this land: Add {B}{B}", which the tap
    seam refuses (CR 602.2b) — so a click with no ability index, the body the
    client's mana fan and single-ability click send, failed with "failed to tap
    land for mana". It is an activation now: the counter comes off and the
    {B}{B} arrives."""
    from engine.named_counters import add_counters, counters_on

    sid, _session, game = _w3g1_session(opponent_islands=0)
    bog = Permanent(card=_w3g1_card("Peat Bog"))
    game.players[0].battlefield = [bog]
    game._settle()
    game.start_priority_window(0)
    bog.tapped = False
    if counters_on(bog, "depletion") < 2:
        add_counters(bog, "depletion", 2 - counters_on(bog, "depletion"))
    assert _serialize_permanent(bog, game)["taps_for_mana"] is False

    resp = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_index": 0,
        "permanent_name": "Peat Bog",
    })
    assert resp.status_code == 200, resp.text
    assert _w3g1_pool(game) == {"B": 2}
    assert counters_on(bog, "depletion") == 1
