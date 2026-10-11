"""A spell on the stack as a target *beside*, or *instead of*, a permanent —
over HTTP, and in the client's own code.

Two announcements the wire could not make:

* **A roles cast one of whose slots is a spell.** "Counter target spell and
  Suffocating Blast deals 3 damage to target creature." ``TargetRoleRef`` had
  three alternatives (a permanent id, a graveyard slot, a seat); a stack object
  is a fourth, by its top-first ``stack_index`` — the number the picker's own
  entry carries. ``_queue_spell_from_request`` translates it into the channel
  a cast has always named a spell on.
* **An activation whose one target is a spell or a permanent.** Blind Seer's
  "{1}{U}: Target spell or permanent becomes the color of your choice until
  end of turn" derived a permanent picker, so there was nothing to send; with
  the union read, the cast side's existing ``spell_or_permanent`` prompt has to
  be reachable from the activation cascade too.

The engine and API halves are driven here. The client half is read as text
(``app.js`` is DOM-coupled) *and was driven in a real browser* — this file is
not that drive; it holds the wire and the code paths the drive went through.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)

_APC = {c.name: c for c in load_cards(manifest_set_path("APC", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_INV = {c.name: c for c in load_cards(manifest_set_path("INV"))}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 2121,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    for player in game.players:
        player.hand = []
        player.battlefield = []
    session.current_turn = 1
    game.active_player_index = 1
    return sid, game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _opposing_bolt(game):
    game.players[1].hand = [_LEA["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game.stack[-1]


# --- Suffocating Blast: a stack role beside a permanent role ----------------


def test_the_picker_offers_a_spell_and_then_a_creature():
    """What the browser is handed: role 0's list is stack entries, each
    carrying under ``next`` the creatures role 1 would then allow."""
    sid, game = _session()
    _put(game, 1, _LEA["Grizzly Bears"])
    _opposing_bolt(game)

    spec = game.cast_target_spec(0, _APC["Suffocating Blast"])

    assert [role["kind"] for role in spec["roles"]] == ["stack", "creature"]
    (entry,) = spec["valid_targets"]
    assert (entry["kind"], entry["stack_index"], entry["name"]) == (
        "stack", 0, "Lightning Bolt",
    )
    assert [step["name"] for step in entry["next"]] == ["Grizzly Bears"]


def test_a_stack_role_ref_counters_the_spell_and_burns_the_creature():
    """The announcement the walk sends: one ref per role, in role order, the
    first naming the spell by its top-first stack index."""
    sid, game = _session()
    bears = _put(game, 1, _LEA["Grizzly Bears"])
    _opposing_bolt(game)
    game.players[0].hand = [_APC["Suffocating Blast"]]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Suffocating Blast",
            "target_role_refs": [
                {"stack_index": 0},
                {"permanent_id": bears.permanent_id},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    blast = game.stack[-1]
    assert blast.card.name == "Suffocating Blast"
    assert blast.target_stack_item.card.name == "Lightning Bolt"
    assert blast.target_permanent_id == [None, bears.permanent_id]

    game._settle()
    assert game.players[0].life == 20
    assert "Lightning Bolt" in [card.name for card in game.players[1].graveyard]
    assert any("dealt 3 damage to Grizzly Bears" in line for line in game.log)


def test_a_roles_cast_with_its_spell_slot_empty_is_refused():
    """Sent as a bare id list the spell slot is a hole, and CR 601.2c declines
    the whole announcement with nothing spent."""
    sid, game = _session()
    bears = _put(game, 1, _LEA["Grizzly Bears"])
    _opposing_bolt(game)
    game.players[0].hand = [_APC["Suffocating Blast"]]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "cast",
            "card_name": "Suffocating Blast",
            "target_permanent_ids": [bears.permanent_id],
        },
    )

    assert resp.status_code == 400, resp.text
    assert [card.name for card in game.players[0].hand] == ["Suffocating Blast"]


def test_the_role_walk_takes_a_stack_click_and_sends_a_stack_ref():
    """The client's half, read as text: a roles walk standing on a spell role
    is a prompt that targets the stack, a click there answers that role, and
    the announcement carries the spell as a ``stack_index`` ref."""
    targets_stack = app_js_function_body("pendingPromptTargetsTheStack")
    assert "roleChoosesASpell(currentRole(p))" in targets_stack

    select = app_js_function_body("selectStackSpellTarget")
    assert "pendingPromptTargetsTheStack()" in select
    assert "chooseRoleSpell(arrayIndex)" in select
    # …and the roles branch returns before the one-target send below it.
    assert select.index("chooseRoleSpell(arrayIndex)") < select.index("sendAction(")

    choose = app_js_function_body("chooseRoleSpell")
    assert 'o.kind === "stack" && o.stack_index === arrayIndex' in choose
    assert "advanceRoleWalk(option)" in choose

    confirm = app_js_function_body("confirmRoleTargets")
    assert 't.zone === "stack"' in confirm
    assert "stack_index: t.stackIndex" in confirm

    assert 'return "spell"' in app_js_function_body("roleTargetNoun")


# --- Blind Seer: a spell *or* a permanent, by activation --------------------


def test_blind_seers_payload_carries_the_spell_or_permanent_picker():
    """The state the browser polls: the permanent's activation spec is the
    Laces' kind, with the spell on the stack among its legal targets."""
    sid, game = _session()
    _put(game, 0, _INV["Blind Seer"])
    _put(game, 1, _LEA["Grizzly Bears"])
    _opposing_bolt(game)

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    seer = state["players"][0]["battlefield"][0]

    assert seer["name"] == "Blind Seer"
    spec = seer["target_spec"]
    assert spec["kind"] == "spell_or_permanent"
    assert sorted((t["kind"], t.get("name")) for t in spec["valid_targets"]) == [
        ("permanent", "Blind Seer"), ("permanent", "Grizzly Bears"),
        ("stack", "Lightning Bolt"),
    ]


def test_blind_seer_activated_at_a_spell_over_http():
    sid, game = _session()
    seer = _put(game, 0, _INV["Blind Seer"])
    _put(game, 1, _LEA["Grizzly Bears"])
    bolt = _opposing_bolt(game)

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "activate",
            "permanent_name": "Blind Seer",
            "permanent_id": seer.permanent_id,
            "target_stack_index": 0,
        },
    )

    assert resp.status_code == 200, resp.text
    ability = game.stack[-1]
    assert ability.card.name == "Blind Seer" and ability.target_stack_item is bolt


def test_the_activation_cascade_reaches_the_spell_or_permanent_prompt():
    """The client's half: the activation branch that opens a permanent prompt
    answers this kind too, with the stack half switched on."""
    assert 'k === "spell_or_permanent"' in app_js_function_body(
        "activatedAbilityRequiresTargetPermanent"
    )
    cascade = app_js_function_body("startActivationPrompt")
    assert "cardRequiresTargetSpellOrPermanent(card)" in cascade
    assert "const alsoStack = spellOrPermanent ||" in cascade
