"""The exile search's floor on the wire and in the client (CR 701.23d).

"Search your library for seven cards, exile them in a face-down pile"
(Parallel Thoughts) must find seven. The prompt sends the engine's floor as
``min_picks`` — the key ``search_library`` sends — the route refuses an answer
under it, and the client's modal holds its one confirm button at the floor and
never offers "Take Nothing" for such a search. "Any number of <quality> cards"
(Chandra, Heart of Fire) keeps its fail-to-find.
"""

from __future__ import annotations

import shutil

import pytest

from engine.card_loader import load_cards, manifest_set_path
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from tests.helpers import client, run_app_js, seat_plays_first
from tests.rules.test_scg_w2g2c_exile_search_floor import _exile_step
from web.app import store


def _armed(set_code, name, *, library_size=10, include_measured=False):
    cards = {
        card.name: card
        for card in load_cards(manifest_set_path(set_code, include_measured=include_measured))
    }
    filler = {card.name: card for card in load_cards(manifest_set_path("LEA"))}
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "seed": 4107,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    seat_plays_first(sid)
    game = store.get(sid).game
    me, you = game.players
    me.library = [filler["Forest"], filler["Grizzly Bears"]] * (library_size // 2)
    card = cards[name]
    source = None
    if "Enchantment" in (card.type_line or ""):
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
    game._execute_oracle_instruction(_exile_step(card), OracleExecutionContext(
        caster=me, target=you, card=card, source_permanent=source, trigger_context={},
    ))
    return sid, game


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _post(sid, picks):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "search_exile_confirm", "search_picks": picks,
    })


def test_parallel_thoughts_sends_its_floor_and_the_route_refuses_less():
    sid, game = _armed("SCG", "Parallel Thoughts", include_measured=True)
    prompt = _state(sid)["search_exile"]
    assert prompt["maximum"] == 7 and prompt["min_picks"] == 7
    assert _post(sid, []).status_code == 400
    assert _post(sid, [{"zone": "library", "index": i} for i in range(6)]).status_code == 400
    assert _state(sid)["search_exile"] is not None and len(game.players[0].library) == 10
    assert _post(sid, [{"zone": "library", "index": i} for i in range(7)]).status_code == 200
    assert len(game.players[0].exile) == 7


def test_a_short_library_lowers_the_floor_to_what_it_holds():
    sid, game = _armed("SCG", "Parallel Thoughts", library_size=4, include_measured=True)
    assert _state(sid)["search_exile"]["min_picks"] == 4


def test_any_number_of_cards_with_a_quality_sends_no_floor():
    sid, game = _armed("M21", "Chandra, Heart of Fire")
    prompt = _state(sid)["search_exile"]
    assert prompt["min_picks"] == 0
    assert _post(sid, []).status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_the_modal_holds_its_confirm_at_the_floor_and_never_says_take_nothing():
    out = run_app_js(
        ["searchExileFloor", "syncSearchExileConfirm"],
        r'''
const faces = [];
const button = { textContent: "", disabled: false };
for (const [info, picked] of INPUT.cases) {
  searchExileSelected = new Set(picked);
  syncSearchExileConfirm(info, button);
  faces.push([button.textContent, button.disabled]);
}
return faces;
''',
        {"cases": [
            [{"min_picks": 7, "maximum": 7}, []],
            [{"min_picks": 7, "maximum": 7}, ["library:0", "library:1"]],
            [{"min_picks": 7, "maximum": 7}, [f"library:{i}" for i in range(7)]],
            [{"min_picks": 0}, []],
            [{"min_picks": 0}, ["graveyard:2"]],
        ]},
        prelude="let searchExileSelected = new Set();",
    )
    assert out == [
        ["Exile 0 of 7", True],
        ["Exile 2 of 7", True],
        ["Exile 7 of 7", False],
        ["Take Nothing", False],
        ["Exile 1 Card", False],
    ]
