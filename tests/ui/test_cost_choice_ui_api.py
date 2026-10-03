"""The wire for the costs a human chooses (CR 601.2h, 602.2b, 508.1h, 509.1d).

Three gaps, one shape: the engine took the payer's answer on a cost field and
had a deterministic default for a seat that named nothing — and for a human
seat nothing ever named it, so the default paid.

* **A tap cost had no picker at all.** "Tap an untapped creature you control"
  (Opposition, Earthcraft, Unerring Sling — sixteen shipped cards) derived no
  spec, so the browser never asked and the first creature on the board tapped.
* **A discard cost sent the activation the moment the card was picked**, with
  no target and no X: Kris Mage pinged its own controller, Bola Warrior made
  *itself* unable to block, Seismic Mage destroyed nothing — every one of the
  34 shipped discard-cost abilities that also target, and Deepwood Elder's X.
  The server half is that one activate body can carry the cost *and* the
  target; the client half is ``pendingActivationCost``.
* **A declaration's cost** (Leviathan's two Islands, Hollow Warrior's tap)
  was the engine's pick, never the player's. The payload now names the choice
  (``declaration_costs``) and the declaration carries the answer
  (``cost_permanent_ids``).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _session(mine, theirs=(), *, hand=()):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 2424,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = [Permanent(card=_CARDS[n]) for n in mine]
    game.players[1].battlefield = [Permanent(card=_CARDS[n]) for n in theirs]
    for perm in game.all_permanents():
        perm.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS[n] for n in hand]
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid):
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


# ---------------------------------------------------------------------------
# A tap cost's picker, and the two answers on one body
# ---------------------------------------------------------------------------


def test_opposition_ships_a_tap_cost_picker_beside_its_target():
    sid, game = _session(["Opposition", "Grizzly Bears", "Hill Giant"], ["Forest"])
    game.players[0].battlefield[1].tapped = True

    spec = _state(sid)["players"][0]["battlefield"][0]["target_spec"]
    cost = spec["cost_spec"]
    assert cost["tap_cost"] is True and cost["count"] == 1
    assert [t["name"] for t in cost["valid_targets"]] == ["Hill Giant"], (
        "a tapped creature cannot pay a tap cost"
    )


def test_the_tapped_creature_and_the_target_ride_one_activate_body():
    sid, game = _session(["Opposition", "Grizzly Bears", "Hill Giant"], ["Forest"])
    _opp, bears, giant = game.players[0].battlefield
    (forest,) = game.players[1].battlefield

    resp = _act(
        sid, action="activate", permanent_name="Opposition", permanent_index=0,
        target_permanent_id=forest.permanent_id,
        cost_permanent_ids=[giant.permanent_id],
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    assert giant.tapped and not bears.tapped
    assert forest.tapped


# ---------------------------------------------------------------------------
# A discard cost and a target: the body the client now sends
# ---------------------------------------------------------------------------


def test_kris_mage_pays_the_named_card_and_hits_the_named_target():
    """The bare body the old client sent named the discard alone, and the
    engine's fallback aimed the ping at the activator. The whole announcement
    — the card *and* the target — is one body."""
    sid, game = _session(["Kris Mage"], ["Hill Giant"], hand=["Forest", "Island"])
    (giant,) = game.players[1].battlefield

    resp = _act(
        sid, action="activate", permanent_name="Kris Mage", permanent_index=0,
        target_permanent_id=giant.permanent_id, cost_hand_index=1,
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    assert [c.name for c in game.players[0].graveyard] == ["Island"]
    assert giant.damage_marked == 1
    assert game.players[0].life == 20


def test_the_cast_side_carries_both_cards_of_a_two_card_buyback():
    """Forbid's "Buyback—Discard two cards" over the wire: the offer taken,
    the first card on ``cost_hand_index`` and the second on
    ``cost_other_hand_indices``."""
    sid, game = _session([], hand=["Forbid", "Grizzly Bears", "Forest", "Island"])
    game.players[1].hand = [_CARDS["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.start_priority_window(0)

    resp = _act(
        sid, action="cast", card_name="Forbid", target_stack_index=0,
        optional_cost_payments={"discard two cards": 1},
        cost_hand_index=2, cost_other_hand_indices=[3],
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    assert sorted(c.name for c in game.players[0].graveyard) == ["Forest", "Island"]
    assert "Forbid" in [c.name for c in game.players[0].hand], "bought back"
    assert "Grizzly Bears" in [c.name for c in game.players[0].hand]


# ---------------------------------------------------------------------------
# A declaration's cost: named in the payload, answered on the declaration
# ---------------------------------------------------------------------------


def _leviathan_session():
    sid, game = _session(["Leviathan", "Island", "Island", "Island", "Forest"])
    game.players[0].battlefield[0].tapped = False
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    game.combat_attackers_locked = False
    game.clear_priority_window()
    return sid, game


def test_the_payload_names_a_declaration_cost_while_the_declaration_is_open():
    sid, game = _leviathan_session()
    leviathan, *islands, _forest = game.players[0].battlefield

    board = _state(sid)["players"][0]["battlefield"]
    (choice,) = board[0]["declaration_costs"]["attack"]
    assert choice["verb"] == "sacrifice" and choice["count"] == 2
    assert choice["candidate_ids"] == [land.permanent_id for land in islands]
    assert all("declaration_costs" not in perm for perm in board[1:]), (
        "nothing is said about a permanent that owes nothing"
    )

    game.current_step = "declare_blockers"
    assert "declaration_costs" not in _state(sid)["players"][0]["battlefield"][0]


def test_declare_attackers_sacrifices_the_islands_named():
    sid, game = _leviathan_session()
    leviathan, i1, i2, i3, _forest = game.players[0].battlefield

    resp = _act(
        sid, action="declare_attackers", attacker_indices=[0], target_seat=1,
        cost_permanent_ids=[i2.permanent_id, i3.permanent_id],
    )
    assert resp.status_code == 200, resp.text
    assert game.is_on_battlefield(i1)
    assert not game.is_on_battlefield(i2) and not game.is_on_battlefield(i3)
    assert leviathan.attacking


# ---------------------------------------------------------------------------
# The client half, read as source (app.js is DOM-coupled; see helpers)
# ---------------------------------------------------------------------------


def test_the_discard_prompt_resumes_the_activation_rather_than_sending_it():
    """The regression itself: the discard pick used to build and send an
    activate body on the spot. It now records the cost and re-enters the
    activation, whose X and target prompts send the body."""
    body = app_js_function_body("finishDiscardCost")
    assert "resumeActivationAfterCost(" in body
    assert 'action: "activate"' not in body
    # …and on the cast side the discard is merged onto the offers already
    # announced, which used to be overwritten (Forbid lost its buyback).
    assert "...(pendingCastCost || {})" in body


def _async_function_body(name: str) -> str:
    """``app_js_function_body`` for an ``async function`` (that helper reads
    the plain spelling only)."""
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"^async function " + re.escape(name) + r"\([^)]*\)\s*\{\n(.*?)^\}$",
        source, re.S | re.M,
    )
    assert match is not None, f"{name} is gone or was renamed"
    return match.group(1)


def test_every_activate_body_carries_the_announced_cost():
    send = _async_function_body("sendAction")
    assert "pendingActivationCost" in send
    assert "activationCostAnswered(body.permanent_index, body.ability_index)" in send

    prompt = app_js_function_body("startActivationPrompt")
    assert "startActivationPermanentCostPrompt(" in prompt
    assert "activationCostAnswered(" in prompt


def test_an_x_ability_that_targets_asks_x_before_the_target():
    """CR 601.2b before 601.2c. The cascade's target branches each send the
    ability, and the ``{X}`` prompt sat below all of them — so Ballista Squad,
    Crimson Hellkite, Cinder Elemental and twelve more shipped abilities went
    out with no X and resolved for zero. X is asked first now and rides the
    stash into whichever target prompt sends."""
    prompt = app_js_function_body("startActivationPrompt")
    x_first = prompt.index("thenTargets: true")
    first_target_branch = prompt.index("cardRequiresTargetGraveyardCreature(card)")
    assert x_first < first_target_branch
    resolve = app_js_function_body("resolvePendingCastX")
    assert "pending.thenTargets" in resolve
    assert "{ x_value: selectedX }" in resolve


def test_crimson_hellkite_deals_the_announced_x_to_the_named_target():
    """The body that X-first produces: x_value and the target together."""
    sid, game = _session(["Crimson Hellkite"], ["Hill Giant"])
    (giant,) = game.players[1].battlefield

    resp = _act(
        sid, action="activate", permanent_name="Crimson Hellkite", permanent_index=0,
        target_permanent_id=giant.permanent_id, x_value=3,
    )
    assert resp.status_code == 200, resp.text
    game._settle()
    assert not game.is_on_battlefield(giant)


def test_the_tap_and_counted_sacrifice_costs_open_the_set_picker():
    picker = app_js_function_body("activationPermanentCostSpec")
    assert "tap_cost" in picker and "announces_x" in picker
    confirm = app_js_function_body("confirmPermanentCost")
    # Copper-Leaf Angel: X is the number of lands named.
    assert "fields.x_value = picked.length" in confirm


def test_the_combat_declarations_ask_for_their_costs_first():
    ok = _async_function_body("handleCombatPromptOk")
    assert ok.count("startDeclarationCostPrompt(") == 2, "attackers and blockers"
    assert "startDeclarationCostPrompt(" in _async_function_body("confirmPendingAttackTarget")
    assert "cost_permanent_ids: chosen" in app_js_function_body("continueDeclarationCost")
