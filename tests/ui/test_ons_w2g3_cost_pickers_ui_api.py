"""Onslaught's "Tap N untapped <type> you control" costs, as a person pays
them (W2G3).

Birchlore Rangers ("Tap two untapped Elves you control: Add one mana of any
color") and Cryptic Gateway ("Tap two untapped creatures you control: …") are
battlefield abilities whose ``target_spec`` already is the set picker
(``engine/cost_pickers``: ``tap_cost``, ``count``) — the client asked, and only
its prompt said "Tap 2 Elfs". Gangrenous Goliath's is a **graveyard** ability
("Tap three untapped Clerics you control: Return this card from your graveyard
to your hand"), and its button sent a bare activation: the engine tapped the
first three Clerics it met, never the ones the player meant. The graveyard
entry now lists the charger's candidates (``tap_choices``, ``tap_count``), the
client opens the set picker over them (``openGraveyardTapCostPicker``), and
the answer rides ``cost_permanent_ids``.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from web.app import app, store

from tests.helpers import run_app_js

client = TestClient(app)
APP_JS = Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _state(sid: str, seat: int) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _goliath_table(set_pool):
    """Seat 0: four Clerics on the battlefield and Gangrenous Goliath in the
    graveyard, in its main phase with priority."""
    sid = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 51031,
    }).json()["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    ons = set_pool("ONS")
    clerics = [Permanent(card=ons[name]) for name in
               ("Daru Healer", "Daru Healer", "Doubtless One", "Battlefield Medic")]
    game.players[0].battlefield = list(clerics)
    game.players[0].graveyard = [ons["Gangrenous Goliath"]]
    game.players[0].hand = []
    game.players[1].battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    game.priority_player_index = 0
    return sid, game, clerics


def test_w2g3_the_graveyard_entry_lists_what_the_cost_may_tap(set_pool):
    sid, game, clerics = _goliath_table(set_pool)
    (entry,) = _state(sid, 0)["graveyard_abilities"]
    assert entry["name"] == "Gangrenous Goliath" and entry["tap_count"] == 3
    assert [c["permanent_id"] for c in entry["tap_choices"]] == [c.permanent_id for c in clerics]

    # A tapped Cleric cannot pay, so it is not offered.
    clerics[0].tapped = True
    (entry,) = _state(sid, 0)["graveyard_abilities"]
    assert clerics[0].permanent_id not in {c["permanent_id"] for c in entry["tap_choices"]}


def test_w2g3_the_named_clerics_are_the_ones_tapped(set_pool):
    """The set the person picked — the last three, not the first three the
    engine's default would reach — over ``cost_permanent_ids``."""
    sid, game, clerics = _goliath_table(set_pool)
    named = [c.permanent_id for c in clerics[1:]]
    sent = _act(sid, seat=0, action="activate_graveyard", card_name="Gangrenous Goliath",
                graveyard_index=0, ability_index=0, cost_permanent_ids=named)
    assert sent.status_code == 200, sent.text
    assert not clerics[0].tapped
    assert all(c.tapped for c in clerics[1:])

    # The other direction: naming a creature the cost cannot tap is refused,
    # never quietly replaced by the default (CR 601.2h).
    sid, game, clerics = _goliath_table(set_pool)
    wrong = Permanent(card=set_pool("ONS")["Glory Seeker"])
    game.players[0].battlefield.append(wrong)
    refused = _act(sid, seat=0, action="activate_graveyard", card_name="Gangrenous Goliath",
                   graveyard_index=0, ability_index=0,
                   cost_permanent_ids=[clerics[0].permanent_id, clerics[1].permanent_id,
                                       wrong.permanent_id])
    assert refused.status_code == 400, refused.text
    assert not any(c.tapped for c in clerics) and not wrong.tapped


def test_w2g3_the_client_opens_the_picker_and_sends_the_set():
    """The client's half, by name: the graveyard button opens the set picker
    for ``tap_choices`` before a target or a bare send, and its confirm sends
    the picked ids on ``cost_permanent_ids`` (a sacrifice keeps its single
    ``cost_permanent_id``)."""
    js = APP_JS.read_text(encoding="utf-8")
    opener = re.search(r"\nfunction openGraveyardTapCostPicker\(.*?\n\}\n", js, re.S).group(0)
    assert "entry?.tap_choices" in opener and "entry.tap_count" in opener
    assert "graveyardAbility: entry" in opener
    rail = re.search(r"\nfunction renderGraveyardAbilities\(.*?\n\}\n", js, re.S).group(0)
    assert rail.index("openGraveyardTapCostPicker(entry)") < rail.index("startGraveyardAbilityTargetPrompt(entry)")
    confirm = re.search(r"\nfunction confirmPermanentCost\(.*?\n\}\n", js, re.S).group(0)
    assert '{ cost_permanent_ids: picked }' in confirm


@needs_node
def test_w2g3_a_counted_noun_is_pluralised_as_the_engine_reads_it():
    out = run_app_js(
        ["costNounPlural"],
        "return ['Elf', 'creature', 'Cleric', 'Dwarf', 'Wolf', 'Sliver', 'Ally', 'Fox']"
        ".map(costNounPlural);",
        None,
    )
    assert out == ["Elves", "creatures", "Clerics", "Dwarves", "Wolves", "Slivers", "Allies", "Foxes"]
