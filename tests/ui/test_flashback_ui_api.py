"""Web-API tests for flashback (CR 702.34): what a browser is told about a
flashback card in its viewer's graveyard, and what it has to send to cast it.

Nothing new is on the wire. Flashback is a cast permission that requires an
alternative cost (``engine/flashback.py``), so the card arrives through the
seam every zone cast already uses — ``castable_from_zones`` says the pile is
open, and the ``cast`` action carries ``from_zone`` — and the three things a
client reads the price off are the price of *this* cast:

* the ``castable_from_zones`` entry names the cost and the keyword;
* the graveyard copy's ``mana_cost`` is the flashback cost (its
  ``printed_mana_cost`` is unchanged), because that field is "the cost the UI
  shows and auto-taps for" and the insufficient-mana prompt taps lands for it;
* the engine's refusal for too little mana still opens on "insufficient mana",
  which is the phrase that prompt is keyed on.

The cards are put into the session by hand: a measured set's cards are not in
the catalog a session deals from.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)


def _cards() -> dict:
    found: dict = {}
    # INV and EXO for the two shipped cards the W2G6 tests put beside a
    # flashback card: Yawgmoth's Agenda and Sphere of Resistance.
    for code in ("ODY", "LEA", "INV", "EXO"):
        for card in load_cards(manifest_set_path(code, include_measured=True)):
            found.setdefault(card.name, card)
    return found


def _session(*, mountains: int = 0):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 3434,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    cards = _cards()
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    for _ in range(mountains):
        game._put_permanent_onto_battlefield(0, Permanent(card=cards["Mountain"]), None)
    return sid, game, cards


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _engine_keys(entry: dict) -> dict:
    """A ``castable_from_zones`` entry without the two keys the web layer adds
    (``ways``, ``castable_now``): what the engine's permission seam said."""
    return {key: value for key, value in entry.items() if key not in ("ways", "castable_now")}


def _zone_entries(sid: str, seat: int = 0) -> dict:
    return {entry["name"]: entry for entry in _state(sid, seat)["castable_from_zones"]}


def test_a_flashback_card_in_the_viewer_s_graveyard_is_offered_with_its_price():
    sid, game, cards = _session()
    game.players[0].graveyard.extend([cards["Firebolt"], cards["Grizzly Bears"], cards["Morgue Theft"]])

    state = _state(sid)
    # The engine's entry (``playable_from_zones``), exactly as it was…
    assert [_engine_keys(entry) for entry in state["castable_from_zones"]] == [
        {"zone": "graveyard", "index": 0, "name": "Firebolt", "free": False,
         "source": "flashback", "owner_seat": 0, "cost": "pay {4}{R}",
         "cost_mana": "{4}{R}", "cost_keyword": "flashback"},
        {"zone": "graveyard", "index": 2, "name": "Morgue Theft", "free": False,
         "source": "flashback", "owner_seat": 0, "cost": "pay {4}{B}",
         "cost_mana": "{4}{B}", "cost_keyword": "flashback"},
    ]
    # …and what the web layer adds for a person (``_zone_cast_options``): the
    # one way each may be cast, its price, and that this empty board cannot
    # pay for either.
    assert [entry["ways"] for entry in state["castable_from_zones"]] == [
        [{"alternative_cost": True, "source": "flashback", "keyword": "flashback",
          "free": False, "land": False, "price": "{4}{R}", "cost": "pay {4}{R}",
          "castable_now": False}],
        [{"alternative_cost": True, "source": "flashback", "keyword": "flashback",
          "free": False, "land": False, "price": "{4}{B}", "cost": "pay {4}{B}",
          "castable_now": False}],
    ]
    assert [entry["castable_now"] for entry in state["castable_from_zones"]] == [False, False]
    mine = {card["name"]: card for card in state["players"][0]["graveyard"]}
    # What this cast is charged, and what the card prints.
    assert (mine["Firebolt"]["mana_cost"], mine["Firebolt"]["printed_mana_cost"]) == ("{4}{R}", "{R}")
    assert (mine["Morgue Theft"]["mana_cost"], mine["Morgue Theft"]["printed_mana_cost"]) == ("{4}{B}", "{1}{B}")
    assert mine["Grizzly Bears"]["mana_cost"] == mine["Grizzly Bears"]["printed_mana_cost"]
    # The picker for the graveyard copy is the cast's own: Morgue Theft is
    # leaving that pile, so the creature card is offered and the spell is not.
    assert mine["Morgue Theft"]["target_spec"]["valid_targets"] == [
        {"kind": "graveyard", "seat": 0, "index": 1, "name": "Grizzly Bears"}
    ]
    # Nobody else is offered it, and nobody else sees a price on it.
    theirs = _state(sid, seat=1)
    assert theirs["castable_from_zones"] == []
    seen = {card["name"]: card for card in theirs["players"][0]["graveyard"]}
    assert seen["Firebolt"]["mana_cost"] == "{R}"


def test_a_flashback_cast_goes_through_the_ordinary_cast_action():
    sid, game, cards = _session(mountains=5)
    firebolt = cards["Firebolt"]
    game.players[0].graveyard.append(firebolt)
    body = dict(seat=0, action="cast", card_name="Firebolt", from_zone="graveyard", target_seat=1)

    # No mana floating: refused, in the words the client's auto-tap prompt
    # is keyed on, with the card still where it was.
    refused = _act(sid, **body)
    assert refused.status_code == 400
    assert refused.json()["detail"].startswith("insufficient mana")
    assert "flashback cost ({4}{R})" in refused.json()["detail"]
    assert firebolt in game.players[0].graveyard and not game.stack

    for index in range(5):
        assert _act(sid, seat=0, action="tap", permanent_index=index).status_code == 200
    cast = _act(sid, **body)
    assert cast.status_code == 200, cast.text
    item = game.stack[-1]
    assert (item.card.name, item.cast_from_zone, item.flashback) == ("Firebolt", "graveyard", True)
    assert firebolt not in game.players[0].graveyard
    assert not any(game.players[0].mana_pool.values())
    # While it is on the stack it is not offered from anywhere.
    assert _state(sid)["castable_from_zones"] == []

    for seat in (0, 1):
        assert _act(sid, seat=seat, action="pass_priority").status_code == 200
    assert game.players[1].life == 18
    assert [c.name for c in game.players[0].exile] == ["Firebolt"]
    assert _state(sid)["castable_from_zones"] == []


def test_flashback_keeps_the_card_s_timing_and_its_owner():
    """A sorcery is flashed back when a sorcery could be cast (the card's own
    ruling: "you must still follow any timing restrictions and permissions,
    including those based on the card's type"), and only by its owner."""
    sid, game, cards = _session()
    game.enforce_mana_costs = False
    game.players[0].graveyard.append(cards["Firebolt"])
    session = store.get(sid)
    session.current_turn = 1
    game.active_player_index = 1
    off_turn = _act(sid, seat=0, action="cast", card_name="Firebolt", from_zone="graveyard", target_seat=1)
    assert off_turn.status_code == 400
    assert "your turn" in off_turn.json()["detail"]
    # Seat 1, with priority on its own turn, has no permission over seat 0's pile.
    game.priority_player_index = 1
    stolen = _act(sid, seat=1, action="cast", card_name="Firebolt", from_zone="graveyard", target_seat=0)
    assert stolen.status_code == 400
    assert "no effect allows playing that card" in stolen.json()["detail"]
    assert [c.name for c in game.players[0].graveyard] == ["Firebolt"]


def test_the_price_shown_is_the_price_a_cost_modifier_leaves():
    """Catalyst Stone ("Flashback costs you pay cost {2} less") changes what
    the cast is charged, so it changes what the auto-tap prompt is told."""
    sid, game, cards = _session(mountains=3)
    game._put_permanent_onto_battlefield(0, Permanent(card=cards["Catalyst Stone"]), None)
    game.players[0].graveyard.append(cards["Firebolt"])
    game.players[1].graveyard.append(cards["Firebolt"])
    mine, = _state(sid)["players"][0]["graveyard"]
    assert (mine["mana_cost"], mine["printed_mana_cost"]) == ("{2}{R}", "{R}")
    theirs, = _state(sid, seat=1)["players"][1]["graveyard"]
    assert theirs["mana_cost"] == "{6}{R}"

    for index in range(3):
        assert _act(sid, seat=0, action="tap", permanent_index=index).status_code == 200
    cast = _act(sid, seat=0, action="cast", card_name="Firebolt", from_zone="graveyard", target_seat=1)
    assert cast.status_code == 200, cast.text
    assert not any(game.players[0].mana_pool.values())


# --- W2G6: what a person is shown about a cast out of a graveyard -----------


def test_castable_now_is_the_board_paying_this_cast_s_price():
    """A permission is not a payment. ``castable_from_zones`` said only that
    the pile was open, so the browser's emerald glow sat on a Morgue Theft
    over five Mountains. ``castable_now`` is the hand highlight's question
    asked of the flashback cost: timing, targets, and the mana on the board."""
    sid, game, cards = _session(mountains=5)
    game._put_permanent_onto_battlefield(1, Permanent(card=cards["Grizzly Bears"]), None)
    game.players[0].graveyard.extend([cards["Firebolt"], cards["Morgue Theft"], cards["Grizzly Bears"]])
    entries = _zone_entries(sid)
    assert entries["Firebolt"]["castable_now"] is True          # {4}{R} over five Mountains
    assert entries["Morgue Theft"]["castable_now"] is False     # {4}{B}: no black source

    # One land short.
    mountain = next(p for p in game.controlled_by(0) if p.card.name == "Mountain")
    game.remove_from_battlefield(mountain)
    assert _zone_entries(sid)["Firebolt"]["castable_now"] is False
    game._put_permanent_onto_battlefield(0, Permanent(card=cards["Mountain"]), None)
    assert _zone_entries(sid)["Firebolt"]["castable_now"] is True

    # A sorcery, on another player's turn.
    session = store.get(sid)
    session.current_turn = 1
    game.active_player_index = 1
    game.priority_player_index = 0
    entry = _zone_entries(sid)["Firebolt"]
    assert entry["castable_now"] is False and entry["ways"][0]["castable_now"] is False


def test_the_price_of_a_way_is_what_the_cast_is_charged():
    """Read off the engine's own pricing (``alternative_cost_mana``, CR
    118.9d): Catalyst Stone takes {2} off, Sphere of Resistance puts {1} on,
    and the number the card shows is the number the payment takes."""
    sid, game, cards = _session(mountains=5)
    game.players[0].graveyard.append(cards["Firebolt"])
    assert _zone_entries(sid)["Firebolt"]["ways"][0]["price"] == "{4}{R}"
    game._put_permanent_onto_battlefield(1, Permanent(card=cards["Sphere of Resistance"]), None)
    assert _zone_entries(sid)["Firebolt"]["ways"][0]["price"] == "{5}{R}"
    game._put_permanent_onto_battlefield(0, Permanent(card=cards["Catalyst Stone"]), None)
    assert _zone_entries(sid)["Firebolt"]["ways"][0]["price"] == "{3}{R}"

    for index in range(4):
        assert _act(sid, seat=0, action="tap", permanent_index=index).status_code == 200
    cast = _act(
        sid, seat=0, action="cast", card_name="Firebolt", from_zone="graveyard",
        target_seat=1, alternative_cost=True,
    )
    assert cast.status_code == 200, cast.text
    assert not any(game.players[0].mana_pool.values())


def test_two_permissions_are_two_ways_and_the_cast_says_which():
    """A flashback card under Yawgmoth's Agenda may be cast for its mana cost
    under the Agenda or for its flashback cost under its own keyword (CR
    601.2b). The entry named one permission, so the browser could not flash
    Roar of the Wurm back for {3}{G} at all. Both ways are listed, each with
    the ``alternative_cost`` flag the cast action takes to pick it."""
    sid, game, cards = _session()
    for _ in range(4):
        game._put_permanent_onto_battlefield(0, Permanent(card=cards["Forest"]), None)
    game._put_permanent_onto_battlefield(0, Permanent(card=cards["Yawgmoth's Agenda"]), None)
    roar = cards["Roar of the Wurm"]
    game.players[0].graveyard.extend([roar, cards["Forest"]])

    entries = _zone_entries(sid)
    assert [
        (way["alternative_cost"], way["source"], way["keyword"], way["price"], way["castable_now"])
        for way in entries["Roar of the Wurm"]["ways"]
    ] == [
        (False, "Yawgmoth's Agenda", None, "{6}{G}", False),   # four Forests cannot
        (True, "flashback", "flashback", "{3}{G}", True),      # …and can
    ]
    assert entries["Roar of the Wurm"]["castable_now"] is True
    # A land is played, and its one way says so.
    assert [(way["land"], way["price"]) for way in entries["Forest"]["ways"]] == [(True, "")]

    for index in range(4):
        assert _act(sid, seat=0, action="tap", permanent_index=index).status_code == 200
    # A bare cast is the Agenda's, at the mana cost: four mana do not pay it.
    bare = _act(sid, seat=0, action="cast", card_name="Roar of the Wurm", from_zone="graveyard")
    assert bare.status_code == 400 and bare.json()["detail"].startswith("insufficient mana")
    # The flag picks the permission that requires an alternative cost.
    flashed = _act(
        sid, seat=0, action="cast", card_name="Roar of the Wurm", from_zone="graveyard",
        alternative_cost=True,
    )
    assert flashed.status_code == 200, flashed.text
    item = game.stack[-1]
    assert (item.card.name, item.flashback) == ("Roar of the Wurm", True)
    assert not any(game.players[0].mana_pool.values())


def test_the_client_sends_the_way_it_offered():
    """The client half, read as text (``app.js`` is DOM-coupled). A zone cast
    asks which way when the server lists two, hands the cast chain the price
    of the way chosen, and ``sendAction`` carries ``alternative_cost`` for a
    way that requires one. The canvas lights a pile by ``castable_now``."""
    from pathlib import Path

    import re

    from tests.helpers import app_js_function_body

    static = Path(__file__).resolve().parents[2] / "web" / "static"
    app_js = (static / "app.js").read_text(encoding="utf-8")
    # `beginZoneCast` is async, which `app_js_function_body` does not match.
    begin = re.search(
        r"^async function beginZoneCast\([^)]*\)\s*\{\n(.*?)^\}$", app_js, re.S | re.M,
    ).group(1)
    assert "startZoneWayChoicePrompt(card, zone, entry)" in begin
    assert "card = zoneCastCard(card, chosenWay)" in begin
    assert "pendingCastZoneWay = chosenWay" in begin
    priced = app_js_function_body("zoneCastCard")
    assert "mana_cost: way.price" in priced

    assert "pendingCastZoneWay?.alternative_cost === true && body.alternative_cost == null" in app_js
    assert "entry.castable_now === true" in (static / "battlefield-canvas.js").read_text(encoding="utf-8")
    # Nothing about a price is computed in the browser: the zone panel reads
    # the server's `ways`.
    zone_cards = app_js_function_body("renderZoneCards")
    assert "zoneEntry.ways" in zone_cards and "zoneEntry.castable_now" in zone_cards
