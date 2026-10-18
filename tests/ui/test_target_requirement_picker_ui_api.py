"""The Flagbearer requirement in the pickers that have several slots.

"While an opponent is choosing targets as part of casting a spell they control
or activating an ability they control, that player must choose at least one
Flagbearer on the battlefield if able." (Standard Bearer, Coalition Honor
Guard, Coalition Flag — ``engine/target_requirements.py``.)

A picker with one slot arrives narrowed to the Flagbearers and needs nothing.
One with several — "up to two target creatures", a divided spell, a roles walk
— keeps its whole list, because the other slots are free, and its spec carries
what at least one pick must be (``required_targets``) and why
(``target_requirement``). The client read neither, so a person cast without a
Flagbearer, got an HTTP 400 carrying the reason and had to guess. It shows the
requirement and holds its confirm now; the server is still the authority.

Driven in a browser as a human seat for wave 2, with a Standard Bearer on the
other side: Frost Breath (the several-target picker — confirm disabled over two
other creatures, enabled once the Bearer was one of them), Fireball (the
divided picker, the same), and Lunge (the roles walk — a finished walk without
the Bearer was not sent and started again; with it, cast and resolved). The
text-level tests are the ratchet on that, not a substitute for it.

The Flagbearer here is the engine tests' invented one, because a measured
set's card is not in the web catalog; the sentence is what binds, not the name.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.app import app, store
from tests.helpers import _mk_card, app_js_function_body

client = TestClient(app)

_SENTENCE = (
    "While an opponent is choosing targets as part of casting a spell they "
    "control or activating an ability they control, that player must choose "
    "at least one Flagbearer on the battlefield if able."
)
_LABEL = "at least one Flagbearer must be chosen as a target if able (Test Bannerman)"


def _session(set_pool, hand):
    """Seat 0 to act, holding *hand*; seat 1 controls a Flagbearer, Grizzly
    Bears and a Hill Giant. Returns ``(sid, game, seat 1's permanents)``."""
    bannerman = _mk_card(
        name="Test Bannerman", type_line="Creature - Human Flagbearer",
        oracle_text=_SENTENCE, power=1, toughness=1,
    )
    assert compile_card_oracle(bannerman).supported
    lea = set_pool("LEA")
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 6012,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
        player.hand.clear()
    theirs = [
        Permanent(card=bannerman), Permanent(card=lea["Grizzly Bears"]),
        Permanent(card=lea["Hill Giant"]),
    ]
    for permanent in theirs:
        game._put_permanent_onto_battlefield(1, permanent, None)
    game.players[0].hand.extend(hand)
    session.current_turn = 0
    game.start_turn(0)
    game._settle()
    game.current_phase = "main"
    return sid, game, theirs


def _spec(sid: str, name: str) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    card = next(c for c in state["players"][0]["hand"] if c["name"] == name)
    return card["target_spec"]


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_a_several_target_spec_reaches_the_client_whole_with_the_requirement(set_pool):
    """Frost Breath: "Tap up to two target creatures." The list is not
    narrowed — the second slot is free — and the two fields say what one pick
    must be and why."""
    sid, _game, theirs = _session(set_pool, [set_pool("M21")["Frost Breath"]])
    bannerman, bears, giant = theirs

    spec = _spec(sid, "Frost Breath")

    assert spec["max_targets"] == 2
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Grizzly Bears", "Hill Giant", "Test Bannerman",
    ]
    assert [(t["id"], t["name"]) for t in spec["required_targets"]] == [
        (bannerman.permanent_id, "Test Bannerman"),
    ]
    assert spec["target_requirement"] == _LABEL

    # What the client used to send, and what it was told.
    refused = _act(
        sid, seat=0, action="cast", card_name="Frost Breath",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert refused.status_code == 400 and _LABEL in refused.text
    # Naming nobody is no way round it either.
    assert _act(sid, seat=0, action="cast", card_name="Frost Breath").status_code == 400
    accepted = _act(
        sid, seat=0, action="cast", card_name="Frost Breath",
        target_permanent_ids=[bannerman.permanent_id, bears.permanent_id],
    )
    assert accepted.status_code == 200, accepted.text


def test_a_divided_and_a_roles_spec_carry_it_too(set_pool):
    sid, _game, theirs = _session(
        set_pool, [set_pool("LEA")["Fireball"], set_pool("MMQ")["Lunge"]],
    )
    bannerman = theirs[0]

    for name, kind in (("Fireball", "divided"), ("Lunge", "roles")):
        spec = _spec(sid, name)
        assert spec["kind"] == kind, name
        assert [t["id"] for t in spec["required_targets"]] == [bannerman.permanent_id], name
        assert spec["target_requirement"] == _LABEL, name
        # Not narrowed: every creature is still on offer.
        offered = {t.get("name") for t in spec["valid_targets"] if t.get("kind") == "permanent"}
        assert {"Grizzly Bears", "Hill Giant", "Test Bannerman"} <= offered, name


def test_a_one_slot_spec_is_narrowed_and_needs_nothing_from_the_client(set_pool):
    """The neighbour: Lightning Bolt's list *is* the Flagbearer."""
    sid, _game, theirs = _session(set_pool, [set_pool("LEA")["Lightning Bolt"]])

    spec = _spec(sid, "Lightning Bolt")

    assert [t["name"] for t in spec["valid_targets"]] == ["Test Bannerman"]


def test_with_no_flagbearer_the_spec_carries_neither_field(set_pool):
    sid, game, theirs = _session(set_pool, [set_pool("M21")["Frost Breath"]])
    game.remove_from_battlefield(theirs[0])

    spec = _spec(sid, "Frost Breath")

    assert "required_targets" not in spec and "target_requirement" not in spec


def test_the_several_slot_pickers_show_the_requirement_and_hold_their_confirm():
    """The ratchet on what was driven. One reader of the two fields, asked by
    all three pickers; each confirm refuses on it; the roles walk — which ends
    by sending — asks before it sends and starts again."""
    reader = app_js_function_body("targetRequirementOf")
    assert "spec.required_targets" in reader and "spec.target_requirement" in reader
    met = app_js_function_body("targetRequirementMet")
    assert "pick.id === wanted.id" in met
    assert "wanted.seat === pick.seat && wanted.index === pick.idx" in met

    several = app_js_function_body("confirmSeveralTargets")
    assert "targetRequirementMet(p.card, p.severalTargets)" in several
    divided = app_js_function_body("confirmDividedTargets")
    assert "targetRequirementMet(p.card, p.dividedTargets)" in divided
    walk = app_js_function_body("advanceRoleWalk")
    assert "if (restartRoleWalkForRequirement()) return;" in walk
    assert walk.index("restartRoleWalkForRequirement") < walk.index("confirmRoleTargets()")
    restart = app_js_function_body("restartRoleWalkForRequirement")
    assert "rolePermanentPicks(p)" in restart and "p.roleChosen = []" in restart
    # A seat or a graveyard card answers a role and is no Flagbearer.
    assert "!t.zone" in app_js_function_body("rolePermanentPicks")

    panel = app_js_function_body("renderActivationPrompt")
    # Four readers: the divided, roles and several pickers, each beside its
    # confirm, and the one-click pickers' shared tail — which printed nothing
    # until a Lightning Bolt under a Standard Bearer was read off the screen
    # at the Apocalypse promotion (tests/ui/test_client_prompt_wording.py).
    assert panel.count("targetRequirementRowsHtml(") == 4
    assert "severalOwesRequired" in panel and "dividedOwesRequired" in panel
    # "Choosing none is legal" is not said while a requirement binds.
    assert "targetRequirementOf(p.card)" in app_js_function_body("severalTargetsHint")


def test_a_roles_walk_s_player_role_is_reachable_from_a_life_pill():
    """Found driving Lunge: ``handlePlayerTargetClick`` answers a roles walk's
    player role, and the gate in front of it (``handlePlayerPillClick``) let
    through only ``player`` / ``any`` / ``divided`` — so the pill glowed and a
    click did nothing. Donate, Lunge, Shower of Sparks and Last Stand could not
    be cast by a person at all."""
    gate = app_js_function_body("handlePlayerPillClick")
    assert 'pendingCastTarget.targetKind !== "roles"' in gate
    answer = app_js_function_body("handlePlayerTargetClick")
    assert "chooseRolePlayer(targetSeat)" in answer
