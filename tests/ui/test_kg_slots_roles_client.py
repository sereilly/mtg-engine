"""The browser's half of an optional role and of a word-narrowed role.

Primal Might's second target ("…fights **up to one** target creature you
don't control") is an optional role (``target_roles.OPTIONAL_ROLE``): the
role picker offers to stop there, and an empty walk behind the first choice
ends the announcement rather than waiting for a click nothing can answer. A
roles *cast* with an X asks the X after the walk (the walk used to end by
sending, at X = 0).

Phyrexian Splicer's first target is "creature with the chosen ability": the
server ships one walk per printed word (``valid_targets_by_keyword``), the
client walks the one for the word clicked, a word with an empty walk is not
offered, and a word chosen for a cancelled activation is not the next one's.

Driven in a browser (port 8032) both ways for each card; these pin the wire
and the client functions that walk did.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(mine=(), theirs=(), hand=()):
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host",
        "host_colors": 2, "guest_colors": 2, "seed": 4104,
        "host_deck_cards": [{"name": "Forest", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    game.enforce_mana_costs = False
    rows = []
    for seat, names in enumerate((mine, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            row.append(permanent)
        rows.append(row)
    game.players[0].hand[:] = [_CARDS[name] for name in hand]
    game.start_priority_window(0)
    return sid, game, rows[0], rows[1]


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _drain(sid, game):
    for _ in range(6):
        if not game.stack:
            return
        _act(sid, action="pass_priority")


def _hand_spec(sid, name):
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)["target_spec"]


def test_the_wire_hands_primal_might_two_roles_the_second_optional():
    sid, _game, (bears,), (ogre,) = _session(
        ["Grizzly Bears"], ["Gray Ogre"], hand=["Primal Might"],
    )
    spec = _hand_spec(sid, "Primal Might")

    assert spec["kind"] == "roles"
    assert [bool(role.get("optional_role")) for role in spec["roles"]] == [False, True]
    (first,) = spec["valid_targets"]
    assert (first["seat"], first["name"]) == (0, "Grizzly Bears")
    assert [(n["seat"], n["name"]) for n in first["next"]] == [(1, "Gray Ogre")]


def test_a_wrong_side_cast_is_refused_and_one_target_is_accepted_over_the_wire():
    sid, game, (bears,), (ogre,) = _session(
        ["Grizzly Bears"], ["Gray Ogre"], hand=["Primal Might"],
    )

    refused = _act(
        sid, action="cast", card_name="Primal Might", x_value=1,
        target_permanent_ids=[ogre.permanent_id, bears.permanent_id],
    )
    assert refused.status_code == 400, refused.text
    assert [card.name for card in game.players[0].hand] == ["Primal Might"]

    accepted = _act(
        sid, action="cast", card_name="Primal Might", x_value=2,
        target_permanent_ids=[bears.permanent_id],
    )
    assert accepted.status_code == 200, accepted.text
    _drain(sid, game)
    assert (bears.effective_power, ogre.damage_marked) == (4, 0)


def test_the_wire_hands_splicer_one_walk_per_word_and_refuses_the_wrong_word():
    sid, game, (splicer, bears), (angel,) = _session(
        ["Phyrexian Splicer", "Grizzly Bears"], ["Serra Angel"],
    )
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = next(
        c for c in state["players"][0]["battlefield"] if c["name"] == "Phyrexian Splicer"
    )["target_spec"]
    walks = spec["valid_targets_by_keyword"]
    assert [entry["name"] for entry in walks["flying"]] == ["Serra Angel"]
    assert walks["trample"] == [] and walks["shadow"] == []

    refused = _act(
        sid, action="activate", permanent_id=splicer.permanent_id,
        chosen_keyword="trample",
        target_permanent_ids=[angel.permanent_id, bears.permanent_id],
    )
    assert refused.status_code == 400, refused.text
    assert not splicer.tapped

    accepted = _act(
        sid, action="activate", permanent_id=splicer.permanent_id,
        chosen_keyword="flying",
        target_permanent_ids=[angel.permanent_id, bears.permanent_id],
    )
    assert accepted.status_code == 200, accepted.text
    _drain(sid, game)
    assert game._has_keyword(bears, "flying") and not game._has_keyword(angel, "flying")


_ROLES = [
    {"kind": "creature", "own_only": True, "role": "slot_0"},
    {"kind": "creature", "opponent_only": True, "role": "slot_1", "optional_role": True},
]


def test_the_client_may_end_a_walk_only_before_optional_roles():
    answers = run_app_js(
        ["rolesMayEndAt"],
        "return [0, 1, 2].map((n) => rolesMayEndAt(INPUT, n));",
        _ROLES,
    )
    assert answers == [False, True, True]


def test_the_client_walks_the_tree_for_the_word_it_was_given():
    spec = {
        "kind": "roles",
        "valid_targets": [{"name": "default"}],
        "valid_targets_by_keyword": {"flying": [{"name": "flier"}], "shadow": []},
    }
    prelude = (
        "let pendingChosenAbilityWord = null;\n"
        "function targetSpecOf(card) { return card.target_spec; }\n"
    )
    answers = run_app_js(
        ["roleWalkOf"],
        "const card = { target_spec: INPUT };\n"
        "const out = [roleWalkOf(card, 'activate')];\n"
        "pendingChosenAbilityWord = 'flying';\n"
        "out.push(roleWalkOf(card, 'activate'), roleWalkOf(card, 'cast'));\n"
        "pendingChosenAbilityWord = 'shadow';\n"
        "out.push(roleWalkOf(card, 'activate'));\n"
        "return out;",
        spec, prelude=prelude,
    )
    assert answers == [
        [{"name": "default"}], [{"name": "flier"}], [{"name": "default"}], [],
    ]


def test_the_client_wiring_for_both_halves():
    """What the browser drive exercised, held in the source: the skip button,
    the auto-finish on an empty optional role, the X after a roles cast, the
    disabled word, and the word cleared on cancel."""
    advance = app_js_function_body("advanceRoleWalk")
    assert "rolesMayEndAt(p.roles, p.roleChosen.length)" in advance
    assert "finishRoleWalkEarly()" in advance
    confirm = app_js_function_body("confirmRoleTargets")
    assert "hasXCost(p.card)" in confirm and "rolesBody" in confirm
    assert "pending.rolesBody" in app_js_function_body("resolvePendingCastX")
    assert "valid_targets_by_keyword" in app_js_function_body("renderAbilityWordPrompt")
    assert "roleWalkOf(card, castAction)" in app_js_function_body("startCastRolesTargetPrompt")
