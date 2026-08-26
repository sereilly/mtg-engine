"""Web-API tests for a triggered ability that picks its own target.

Floral Spuzzem is the first card in the pool whose *trigger* targets something
the event does not name — "target artifact defending player controls" is a
choice, and CR 603.3d puts it at the moment the ability goes on the stack. That
is a prompt the client had no reason to render before, so this pins the round
trip end to end: the state payload offers the defending player's artifacts and
only those, the confirm lands, and the "if you do" rider is then visible in the
one place it can be checked honestly — the defending player's life total after
combat damage.

The set is measured rather than shipped, which is the point of a measured set:
a card's focused test is written while the work is being done.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)

_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG", include_measured=True))}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _r32_session():
    """A human-vs-human duel with Floral Spuzzem attacking, unblocked.

    Both an artifact of the attacker's own and two of the defender's, because
    the narrowing has to be visible in the payload: an offer that included the
    attacker's Mox would be the fire site's old behaviour, which stamped the
    attacking creature's own battlefield slot as the ability's target.
    """
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 3232,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    spuzzem = Permanent(card=_LEG["Floral Spuzzem"])
    spuzzem.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield = [spuzzem, Permanent(card=_LEA["Mox Pearl"])]
    game.players[1].battlefield = [
        Permanent(card=_LEA["Mox Ruby"]), Permanent(card=_LEA["Black Lotus"]),
    ]
    game.players[1].life = 20
    session.current_turn = 0
    game.active_player_index = 0
    # What `web/actions.py` stamps on every request: both seats are human, so
    # both queue their prompts rather than taking a default at once. Set here
    # because the combat below is driven on the engine directly — the round
    # trip these tests are about is the prompt payload and the answer.
    game.interactive_seats = {0, 1}
    game._sync_control()
    return sid, session, game


def _r32_attack(sid, game):
    """Declare the attack and run the rail to the moment blocks lock."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    game._settle()
    game.advance_combat_phase()


def _r32_state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def test_the_prompt_offers_the_defending_players_artifacts_and_no_others():
    sid, session, game = _r32_session()

    _r32_attack(sid, game)
    prompt = _r32_state(sid)["trigger_target"]

    assert prompt["player_seat"] == 0
    assert prompt["card_name"] == "Floral Spuzzem"
    assert sorted(c["name"] for c in prompt["candidates"]) == [
        "Black Lotus", "Mox Ruby",
    ]
    assert {c["seat"] for c in prompt["candidates"]} == {1}


def test_confirming_the_target_destroys_it_and_the_rider_stops_the_damage():
    sid, session, game = _r32_session()

    _r32_attack(sid, game)
    prompt = _r32_state(sid)["trigger_target"]
    chosen = next(c for c in prompt["candidates"] if c["name"] == "Black Lotus")

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "trigger_target_confirm",
            "target_permanent_id": chosen["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    assert game.confirm_optional_pay(0, "Floral Spuzzem", accept=True)
    game._settle()
    while game.current_turn_phase == "combat":
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break

    assert [p.card.name for p in game.players[1].battlefield] == ["Mox Ruby"]
    # The rider, read where it has to be read: no combat damage was assigned.
    assert game.players[1].life == 20, game.log


def test_an_id_the_prompt_never_offered_is_refused():
    """The picker and the engine read one list. The attacker's own Mox is on
    the battlefield and is an artifact, and naming it must not work."""
    sid, session, game = _r32_session()
    ours = game.players[0].battlefield[1]

    _r32_attack(sid, game)
    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0,
            "action": "trigger_target_confirm",
            "target_permanent_id": ours.permanent_id,
        },
    )

    assert resp.status_code == 400, resp.text
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Floral Spuzzem", "Mox Pearl",
    ]
