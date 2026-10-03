"""The wire half of CR 605: a land's chosen mana ability reaches the tap seam.

``ActionRequest.ability_index`` already existed and the client already sent it
for a multi-ability card — except through its two colour prompts (the
any-colour prompt and the dual-land mana fan), which built their body without
it. The route then saw a land with no chosen ability and tapped its *first*
mana ability: a Karplusan Forest whose menu said "{T}: Add {R} or {G}. This land
deals 1 damage to you." and whose fan said {R} produced {C} and no damage. With
the index, the route sent a painland's coloured ability down the activation
path (a three-kind set decided it), which announces nothing a tap-for-mana
announces. Both ends now carry the choice to ``tap_land_for_mana``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store
from tests.helpers import app_js_function_body

client = TestClient(app)
_W2G3_CARDS: dict = {}


def _w2g3_card(name):
    if not _W2G3_CARDS:
        _W2G3_CARDS.update({c.name: c for c in load_catalog()})
    return _W2G3_CARDS[name]


def _w2g3_session(*permanents):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 5},
    ).json()
    sid = created["session_id"]
    session = store.get(sid)
    session.current_turn = 0
    game = session.game
    game.players[0].battlefield = list(permanents)
    game.players[0].mana_pool = {s: 0 for s in ("W", "U", "B", "R", "G", "C")}
    game.players[0].tapped_land_for_mana_this_turn = False
    game._settle()
    return sid, game


def _w2g3_activate(sid, index, **extra):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_index": index, **extra,
    })


def _w2g3_pool(game):
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def test_a_painlands_coloured_ability_chosen_on_the_wire_goes_through_the_tap_seam():
    sid, game = _w2g3_session(Permanent(card=_w2g3_card("Karplusan Forest")))

    resp = _w2g3_activate(sid, 0, permanent_name="Karplusan Forest", ability_index=1, mana_color="R")

    assert resp.status_code == 200, resp.json()
    assert _w2g3_pool(game) == {"R": 1}
    assert game.players[0].life == 19
    # The seam's own record, which the activation path never wrote.
    assert game.players[0].tapped_land_for_mana_this_turn


def test_a_swap_reaches_the_painlands_coloured_ability_on_the_wire():
    sid, game = _w2g3_session(
        Permanent(card=_w2g3_card("Karplusan Forest")),
        Permanent(card=_w2g3_card("Infernal Darkness")),
    )

    resp = _w2g3_activate(sid, 0, permanent_name="Karplusan Forest", ability_index=1, mana_color="G")

    assert resp.status_code == 200, resp.json()
    assert _w2g3_pool(game) == {"B": 1}


def test_a_granted_mana_ability_chosen_on_the_wire_beats_the_lands_own(set_pool):
    terrain = Permanent(card=set_pool("NEM")["Overlaid Terrain"])
    sid, game = _w2g3_session(terrain)
    forest = Permanent(card=_w2g3_card("Karplusan Forest"))
    game._put_permanent_onto_battlefield(0, forest, None)
    game._settle()
    index = next(
        i for i, p in enumerate(game.players[0].battlefield) if p is forest
    )

    resp = _w2g3_activate(sid, index, permanent_name="Karplusan Forest", ability_index=2, mana_color="U")

    assert resp.status_code == 200, resp.json()
    assert _w2g3_pool(game) == {"U": 2}


def test_the_clients_colour_prompts_send_the_chosen_ability():
    """Both colour prompts record the ability the menu chose, and the one body
    they end in sends it."""
    prompt = app_js_function_body("startActivationPrompt")
    assert prompt.count("abilityIndex,\n") >= 2 or prompt.count("abilityIndex,\r\n") >= 2, (
        "pendingManaColor must carry abilityIndex in both colour prompts"
    )
    resolve = app_js_function_body("resolvePendingManaColor")
    assert "ability_index = pending.abilityIndex" in resolve
