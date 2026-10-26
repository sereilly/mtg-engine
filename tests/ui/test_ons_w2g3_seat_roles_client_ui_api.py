"""Onslaught's roles announcements, as a person walks them (W2G3).

* **Zero is an answer.** Wheel and Deal ("Any number of target opponents …")
  and Kaboom! ("Choose any number of target players or planeswalkers") are
  chains of optional roles; the walk may stop at any depth, zero included. The
  client ended a zero-depth walk by sending ``target_permanent_ids: []``,
  which the cast route read as a bare cast and aimed at a default seat — a
  Kaboom! naming nobody went on the stack targeting the opponent. A cast walk
  that names no role now says ``target_role_refs: []``, and the route reads
  an empty role list as "no target" (``web/action_helpers.py``); a walk whose
  first role is owed (Blatant Thievery) is still refused by the engine.
* **The walk says how deep this table goes.** "1 of 7" for a chain the server
  built two levels deep at a three-seat table is now "1 of up to 2 —
  opponent 1; you may stop", and the stop button says how many are chosen.
* **Blatant Thievery** names whose permanent each role wants ("a permanent
  Bob controls"), and its stack arrows land on both boards: the serializer
  drew every slot on the first target's board.
* **Aphetto Dredging**: after the type is chosen the client re-asks
  ``card_target_spec`` for that word (``castTargetsFollowChosenType``,
  ``refetchCastSpecForChosenType``) and walks that list, never the hand
  card's default-type one.
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


def _table(set_pool, hand, *, seats=3, boards=None):
    created = client.post("/api/sessions", json={
        "mode": "free_for_all", "seed": 7,
        "seats": [{"name": n, "is_ai": False, "colors": 2} for n in ("Alice", "Bob", "Cara")[:seats]],
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.priority_player_index = 0
    ons = set_pool("ONS")
    for seat, player in enumerate(game.players):
        player.battlefield[:] = [
            Permanent(card=ons[name]) for name in ((boards or {}).get(seat) or ())
        ]
    game.players[0].hand[:] = [ons[name] for name in hand]
    game._sync_control()
    return sid, game


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _hand_spec(sid, name):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    (card,) = [c for c in state["players"][0]["hand"] if c["name"] == name]
    return card["target_spec"]


def test_w2g3_an_empty_role_list_casts_naming_nobody(set_pool):
    sid, game = _table(set_pool, ["Kaboom!", "Wheel and Deal"])
    hands_before = [len(p.hand) for p in game.players]
    sent = _act(sid, seat=0, action="cast", card_name="Kaboom!", target_role_refs=[])
    assert sent.status_code == 200, sent.text
    (item,) = game.stack
    assert item.target_player_index is None, "no default seat rode the cast"
    game.resolve_stack()
    assert [p.life for p in game.players] == [20, 20, 20]

    sent = _act(sid, seat=0, action="cast", card_name="Wheel and Deal", target_role_refs=[])
    assert sent.status_code == 200, sent.text
    assert game.stack[-1].target_player_index is None
    game.resolve_stack()
    assert [len(p.hand) for p in game.players][1:] == hands_before[1:], "nobody wheeled"


def test_w2g3_an_empty_role_list_is_still_refused_where_a_role_is_owed(set_pool):
    sid, game = _table(
        set_pool, ["Blatant Thievery"], boards={1: ["Glory Seeker"], 2: ["Wellwisher"]},
    )
    refused = _act(sid, seat=0, action="cast", card_name="Blatant Thievery", target_role_refs=[])
    assert refused.status_code == 400, refused.text
    assert not game.stack and len(game.players[0].hand) == 1


def test_w2g3_blatant_thievery_draws_its_arrows_on_both_boards(set_pool):
    sid, game = _table(
        set_pool, ["Blatant Thievery"],
        boards={1: ["Goblin Sledder", "Glory Seeker"], 2: ["Daru Lancer", "Wellwisher"]},
    )
    seeker = game.players[1].battlefield[1]
    wellwisher = game.players[2].battlefield[1]
    sent = _act(sid, seat=0, action="cast", card_name="Blatant Thievery", target_role_refs=[
        {"permanent_id": seeker.permanent_id}, {"permanent_id": wellwisher.permanent_id},
    ])
    assert sent.status_code == 200, sent.text
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    (item,) = state["stack"]
    assert item["targets"] == [
        {"kind": "permanent", "seat": 1, "index": 1},
        {"kind": "permanent", "seat": 2, "index": 1},
    ]


_ROLE_FUNCTIONS = [
    "roleTreeDepth", "roleWalkStepLabel", "rolesMayEndAt", "roleChoosesAPlayer",
    "roleSkipLabel", "currentRole", "roleTargetNoun", "roleReadsAGraveyard",
    "roleChoosesASpell", "costNounPlural", "perOpponentRoleNoun",
]
_ROLE_PRELUDE = 'const SEAT_ROLE_KINDS = ["player", "player_or_planeswalker"];'


@needs_node
def test_w2g3_the_walk_says_how_deep_this_table_goes(set_pool):
    sid, _game = _table(set_pool, ["Wheel and Deal", "Blatant Thievery"],
                        boards={1: ["Glory Seeker"], 2: ["Wellwisher"]})
    wheel = _hand_spec(sid, "Wheel and Deal")
    thievery = _hand_spec(sid, "Blatant Thievery")
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    out = run_app_js(
        _ROLE_FUNCTIONS,
        """
        const walk = (spec, chosen) => {
          let options = spec.valid_targets;
          for (let i = 0; i < chosen; i += 1) options = options[0].next;
          return { targetKind: "roles", roles: spec.roles,
                   roleChosen: Array(chosen).fill({ seat: 1, zone: "player" }), roleOptions: options };
        };
        currentState = INPUT.state;
        return {
          first: roleWalkStepLabel(walk(INPUT.wheel, 0)),
          firstSkip: roleSkipLabel(walk(INPUT.wheel, 0)),
          secondSkip: roleSkipLabel(walk(INPUT.wheel, 1)),
          thievery: roleWalkStepLabel(walk(INPUT.thievery, 0)),
          whose: perOpponentRoleNoun(walk(INPUT.thievery, 0), INPUT.thievery.roles[0]),
          whose2: perOpponentRoleNoun(walk(INPUT.thievery, 1), INPUT.thievery.roles[1]),
        };
        """,
        {"wheel": wheel, "thievery": thievery, "state": state},
        prelude=_ROLE_PRELUDE + " let currentState = null;",
    )
    assert len(wheel["roles"]) == 7
    assert out["first"] == "1 of up to 2 — opponent 1; you may stop"
    assert out["firstSkip"] == "No players — cast it naming none"
    assert out["secondSkip"] == "Stop here — 1 player chosen"
    assert out["thievery"] == "1 of 2", "an owed walk keeps its count and has no stop"
    assert (out["whose"], out["whose2"]) == ("a permanent Bob controls", "a permanent Cara controls")


def test_w2g3_a_cast_walk_naming_nothing_sends_an_empty_role_list():
    js = APP_JS.read_text(encoding="utf-8")
    confirm = re.search(r"\nfunction confirmRoleTargets\(.*?\n\}\n", js, re.S).group(0)
    assert "(!activating && roleChosen.length === 0) ||" in confirm
    assert "target_role_refs: roleRefs" in confirm


@needs_node
def test_w2g3_aphetto_dredging_walks_the_list_for_the_word_chosen(set_pool, monkeypatch):
    sid, game = _table(set_pool, ["Aphetto Dredging"])
    ons = set_pool("ONS")
    game.players[0].graveyard[:] = [ons["Elvish Warrior"], ons["Goblin Sledder"], ons["Wirewood Elf"]]
    spec = _hand_spec(sid, "Aphetto Dredging")
    assert spec["chosen_creature_type"] == "elf"
    follows = run_app_js(
        ["targetSpecOf", "castTargetsFollowChosenType"],
        "const card = { name: 'Aphetto Dredging', target_spec: INPUT.spec };"
        " return [castTargetsFollowChosenType(card, 'goblin'), castTargetsFollowChosenType(card, 'elf'),"
        " castTargetsFollowChosenType({ target_spec: { announces_creature_type: true, kind: 'none' } }, 'elf')];",
        {"spec": spec},
    )
    assert follows == [True, False, False]
    # What the refetch asks for, and that it narrows to the word. The route's
    # own lookup is the shipped catalog, which a measured set is not in: the
    # card is registered there for this test, as the promotion will register
    # it (W2G1's wire test does the same).
    import web.runtime as runtime

    monkeypatch.setitem(runtime.CARD_BY_NAME, "aphetto dredging", ons["Aphetto Dredging"])
    refetched = client.get(f"/api/sessions/{sid}/card_target_spec", params={
        "card_name": "Aphetto Dredging", "seat": 0, "hand_index": 0,
        "chosen_creature_type": "goblin",
    }).json()["target_spec"]
    assert [t["name"] for t in refetched["valid_targets"]] == ["Goblin Sledder"]
    sent = _act(sid, seat=0, action="cast", card_name="Aphetto Dredging",
                chosen_creature_type="goblin", target_seat=0, target_permanent_indices=[1])
    assert sent.status_code == 200, sent.text
    game.resolve_stack()
    assert [c.name for c in game.players[0].hand] == ["Goblin Sledder"]
    js = APP_JS.read_text(encoding="utf-8")
    refetch = re.search(r"\nasync function refetchCastSpecForChosenType\(.*?\n\}\n", js, re.S).group(0)
    assert "chosen_creature_type: word" in refetch and "card.target_spec = payload.target_spec" in refetch
