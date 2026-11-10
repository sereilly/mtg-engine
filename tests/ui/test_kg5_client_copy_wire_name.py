"""A copy is served by the name it copies (CR 707.2), and keeps the card it is
printed on for what moves between zones.

CR 707.2: "When copying an object, the copy acquires the copiable values of
the original object's characteristics … The copiable values are the values
derived from the text printed on the object (that text being name, mana cost,
…)". Sculpting Steel copying Iron Myr is *named* Iron Myr. The wire's
``name`` was ``perm.card.name`` — the printed card — so the board's name plate,
the preview, every prompt that offered the copy and the stack's ability
labels all said "Sculpting Steel", while the mana cost, P/T and text beside it
were already the copied card's (``effective_card``).

The fix serializes the effective name as ``name`` and the printed card's as
``printed_name``. The art stays the copier's (the server picks it), so the
client groups a pile by both names and matches a card *across zones* (a
bounced copy is a Sculpting Steel in hand) by ``printed_name``; the action API
answers to either name; a pasted raw state rebuilds the printed card.

Backwards: on the base every ``name`` read below said "Sculpting Steel" /
"Clone", and an activation naming the copy by the name the board showed was
refused as naming nothing.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import run_app_js, settle
from web.app import app, store

client = TestClient(app)

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 5150,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game.interactive_seats = set(range(len(game.players)))
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, session, game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _state(sid, seat=0):
    response = client.get(f"/api/sessions/{sid}/state?seat={seat}")
    assert response.status_code == 200, response.text
    return response.json()


def _act(sid, body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _steel_copying_myr(set_pool):
    """Sculpting Steel cast from hand through the action route, copying Iron
    Myr — the board the Known-gaps entry names."""
    mrd = set_pool("MRD")
    sid, session, game = _session()
    myr = _put(game, 0, mrd["Iron Myr"])
    game.players[0].hand = [mrd["Sculpting Steel"]]
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Sculpting Steel",
        "target_seat": 0, "target_permanent_id": myr.permanent_id,
    })
    assert response.status_code == 200, response.text
    settle(game)
    (steel,) = [p for p in game.players[0].battlefield if p.card.name == "Sculpting Steel"]
    assert steel.effective_card.name == "Iron Myr", game.log
    steel.metadata["summoning_sickness_turn"] = -99
    return sid, game, myr, steel


def test_a_copy_is_named_what_it_copies_for_every_viewer(set_pool):
    sid, _game, myr, steel = _steel_copying_myr(set_pool)
    for viewer in (0, 1):
        battlefield = _state(sid, viewer)["players"][0]["battlefield"]
        by_id = {entry["id"]: entry for entry in battlefield}
        copy, real = by_id[steel.permanent_id], by_id[myr.permanent_id]
        assert (copy["name"], copy["printed_name"]) == ("Iron Myr", "Sculpting Steel")
        assert copy["copied_from"] == "Iron Myr"
        # A permanent that copies nothing has one name.
        assert (real["name"], real["printed_name"]) == ("Iron Myr", "Iron Myr")
        # The art is still the physical card's — which is why the client needs
        # the printed name at all.
        assert copy["art_crop"] and copy["art_crop"] != real["art_crop"]


def test_a_face_down_permanent_names_nothing_it_hides(set_pool):
    """CR 708.2a: the printed name of a face-down permanent is the blank's, so
    the new field leaks nothing to the seat that may not look (CR 708.5)."""
    from engine.face_down import face_down_card

    sid, _session_, game = _session()
    hidden = _put(game, 0, face_down_card(set_pool("ONS")["Skirk Commando"]))
    for viewer in (0, 1):
        (entry,) = [
            e for e in _state(sid, viewer)["players"][0]["battlefield"]
            if e["id"] == hidden.permanent_id
        ]
        assert entry["face_down"] is True
        assert entry["name"] == entry["printed_name"] != "Skirk Commando"


def test_the_action_api_answers_to_either_name(set_pool):
    """The client names a permanent by what the board shows it as; a request
    written against the printed name (a test, an older client) still finds it.
    Neither carries an id here, so the name is the only check on the slot."""
    sid, game, _myr, steel = _steel_copying_myr(set_pool)
    slot = game.battlefield_index_of(steel)
    for name in ("Iron Myr", "Sculpting Steel"):
        steel.tapped = False
        response = _act(sid, {
            "seat": 0, "action": "activate", "permanent_name": name,
            "permanent_index": slot, "mana_color": "R",
        })
        assert response.status_code == 200, (name, response.text)
        assert steel.tapped, name
    refused = _act(sid, {
        "seat": 0, "action": "activate", "permanent_name": "Grizzly Bears",
        "permanent_index": slot,
    })
    assert refused.status_code >= 400, "a name the permanent has neither of"


def test_the_auto_tap_plan_names_the_copy_as_it_is_named(set_pool):
    """``web/payment_plan``'s preview names each permanent it would tap."""
    sid, game, myr, steel = _steel_copying_myr(set_pool)
    game.enforce_mana_costs = True
    myr.tapped = True
    game.players[0].hand = [set_pool("LEA")["Lightning Bolt"]]
    response = client.post(f"/api/sessions/{sid}/payment_plan", json={
        "seat": 0, "action": "cast", "card_name": "Lightning Bolt", "target_seat": 1,
    })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["payable"] is True, plan
    assert [(tap["id"], tap["name"]) for tap in plan["taps"]] == [(steel.permanent_id, "Iron Myr")]


def test_a_copys_ability_and_a_spell_aimed_at_it_name_it_as_it_is_named(set_pool):
    """The stack: a Clone copying Prodigal Sorcerer activates a *Prodigal
    Sorcerer's* ability, and a Lightning Bolt at it names Prodigal Sorcerer."""
    lea = set_pool("LEA")
    sid, _session_, game = _session()
    sorcerer = _put(game, 1, lea["Prodigal Sorcerer"])
    game.players[0].hand = [lea["Clone"], lea["Lightning Bolt"]]
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Clone",
        "target_seat": 1, "target_permanent_id": sorcerer.permanent_id,
    })
    assert response.status_code == 200, response.text
    settle(game)
    (clone,) = game.players[0].battlefield
    assert clone.effective_card.name == "Prodigal Sorcerer", game.log
    clone.metadata["summoning_sickness_turn"] = -99
    game.start_priority_window(0)

    response = _act(sid, {
        "seat": 0, "action": "activate", "permanent_id": clone.permanent_id,
        "target_seat": 1,
    })
    assert response.status_code == 200, response.text
    response = _act(sid, {
        "seat": 0, "action": "cast", "card_name": "Lightning Bolt",
        "target_seat": 0, "target_permanent_id": clone.permanent_id,
    })
    assert response.status_code == 200, response.text
    stack = _state(sid, 1)["stack"]
    labels = [item["label"] for item in stack]
    assert "Prodigal Sorcerer ability" in labels and "Clone ability" not in labels, labels
    (bolt,) = [item for item in stack if item["type"] == "spell"]
    assert bolt["target_permanent_name"] == "Prodigal Sorcerer"


def test_a_pasted_copy_is_its_printed_card(set_pool):
    """The Debug Menu's raw-state paste rebuilds a permanent from its entry: a
    copy's entry is named what it copies, and the paste puts back the card it
    is printed on — what it did before the name moved — rather than turning
    a Sculpting Steel into a real Iron Myr."""
    sid, game, _myr, steel = _steel_copying_myr(set_pool)
    state = _state(sid, 0)
    response = client.post(f"/api/sessions/{sid}/raw-state", json={"state": state, "seat": 0})
    assert response.status_code == 200, response.text
    printed = sorted(p.card.name for p in game.players[0].battlefield)
    assert printed == ["Iron Myr", "Sculpting Steel"], printed


@needs_node
def test_the_client_matches_a_copy_across_zones_by_its_printed_card():
    """A bounced copy is a Sculpting Steel in hand: the multiset diff that
    finds where a hand arrival came from reads ``printed_name``, and the
    canvas piles a copy apart from the card it copies (it wears other art)."""
    copy = {"id": 7, "name": "Iron Myr", "printed_name": "Sculpting Steel"}
    real = {"id": 8, "name": "Iron Myr", "printed_name": "Iron Myr"}
    out = run_app_js(
        ["normalizeCardName", "physicalCardName", "removedZoneEntries"],
        """
        return {
          gone: removedZoneEntries([INPUT.copy, INPUT.real], [INPUT.real]).map((e) => e.index),
          // The copy changing what it copies is not a departure.
          kept: removedZoneEntries([INPUT.copy], [{ ...INPUT.copy, name: "Ornithopter" }]).length,
          physical: [physicalCardName(INPUT.copy), physicalCardName(INPUT.real),
                     physicalCardName({ name: "Shock" }), physicalCardName("<hidden>")],
        };
        """,
        {"copy": copy, "real": real},
    )
    assert out == {
        "gone": [0], "kept": 0,
        "physical": ["Sculpting Steel", "Iron Myr", "Shock", "<hidden>"],
    }
    piles = run_app_js(
        ["_physicalName", "_pileIdentity"],
        "return [INPUT.copy, INPUT.real, { name: 'Forest' }].map(_pileIdentity);",
        {"copy": copy, "real": real},
        scripts=("battlefield-canvas.js",),
    )
    assert piles[0] != piles[1] and piles[1:] == ["Iron Myr", "Forest"]
