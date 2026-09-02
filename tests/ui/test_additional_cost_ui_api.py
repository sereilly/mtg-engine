"""Web-API tests for paying a spell's printed additional cost (CR 601.2b).

The picker on the client is the same one that chooses a target — the caster
clicks a creature on the battlefield — but *what* is chosen is a cost payment,
and it travels on the cost field rather than the target field. The two were the
same field while the cost was folded into Sacrifice's effect; once the cost
became general (engine/cast_costs.py), sending it as a target meant paying it
twice.

These pin the server half of that contract: the field the client sends, the
identity the id resolves to, and the refusal when nothing can pay.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import load_catalog, manifest_set_path
from engine.models import Permanent
from web.app import app, store
from tests.helpers import LEA_PATH

client = TestClient(app)

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)

# The whole shipped pool, not just Alpha: Dwarven Weaponsmith — the one card
# whose ability announces a target *and* a cost — is a Revised printing.
_CARDS = {c.name: c for c in load_catalog()}


def _session(*battlefield: str):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 818,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    game.players[0].battlefield = [Permanent(card=_CARDS[n]) for n in battlefield]
    game.players[0].hand = [_CARDS["Sacrifice"]]
    game.players[1].battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _cast(sid: str, **extra) -> dict:
    return client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Sacrifice", **extra},
    )


def test_the_chosen_creature_travels_on_the_cost_field():
    """The caster picks the Hill Giant; its mana value is what the spell buys.

    Addressed by ``cost_permanent_id`` — the stable id, resolved once at the top
    of web/actions.py — so a creature that left the battlefield since the click
    is a 404 rather than whichever permanent slid into its slot.
    """
    sid, _sess, game = _session("Grizzly Bears", "Hill Giant")
    giant = game.players[0].battlefield[1]

    resp = _cast(sid, cost_permanent_id=giant.permanent_id)
    assert resp.status_code == 200, resp.text

    # Paid *while casting* (CR 601.2b): the Giant is gone before the spell is
    # anywhere near resolving, which is the half of the rule the web path is
    # the only one that shows — `cast_from_hand` settles the stack immediately.
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [item.card.name for item in game.stack] == ["Sacrifice"]

    game._settle()
    assert game.players[0].mana_pool["B"] == 4, "the mana value of the creature picked"


def test_a_stale_cost_id_is_a_404_and_nothing_is_sacrificed():
    sid, _sess, game = _session("Grizzly Bears")

    resp = _cast(sid, cost_permanent_id=9_999_999)
    assert resp.status_code == 404

    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].hand] == ["Sacrifice"]


def test_the_spell_is_refused_when_no_creature_can_pay():
    """CR 601.2h through the wire: the action reports the failure and the card
    stays in hand, rather than resolving for free."""
    sid, _sess, game = _session()

    resp = _cast(sid)

    assert resp.status_code >= 400 or not resp.json().get("supported", True)
    assert [c.name for c in game.players[0].hand] == ["Sacrifice"]


# ---------------------------------------------------------------------------
# The discard cost's picker — the other half, and a different picker
# ---------------------------------------------------------------------------
#
# What pays "discard a card" is a card in the caster's own hand, so it is not
# chosen on the battlefield and the permanent picker above cannot carry it.
# `derive_cast_spec` returned None for it, so the client was never told to ask
# and a human seat silently discarded whatever was first in hand.
#
# M21 is measured, not shipped, so no deck can hold Thrill of Possibility and
# the flow is exercised here at the API layer — the same place the cast-from-zone
# suite meets its measured cards.

_M21 = {
    c.name: c
    for c in load_cards(manifest_set_path("M21", include_measured=True))
}


def _discard_cost_session():
    sid, session, game = _session()
    game.players[0].hand = [
        _M21["Shock"], _M21["Thrill of Possibility"], _M21["Alpine Watchdog"]
    ]
    game.players[0].library = [_M21["Swamp"]] * 4
    return sid, session, game


def _hand_card(state: dict, name: str) -> dict:
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)


def test_the_client_is_offered_every_card_but_the_one_being_cast():
    """The spec the picker is built from. CR 601.2a has already put the spell on
    the stack by the time costs are paid, so it is not among the payments."""
    sid, _sess, _game = _discard_cost_session()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = _hand_card(state, "Thrill of Possibility")["target_spec"]

    assert spec["kind"] == "hand_card" and spec["discard_cost"] is True
    assert [(t["hand_index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, "Shock"), (2, "Alpine Watchdog")
    ]


def test_the_chosen_card_travels_on_the_cost_field():
    """`cost_hand_index` indexes the hand the client is looking at — the one
    that still holds the spell — because that is the hand the player saw when
    they clicked."""
    sid, _sess, game = _discard_cost_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Thrill of Possibility",
            "cost_hand_index": 2,
        },
    )
    assert resp.status_code == 200, resp.text

    assert [c.name for c in game.players[0].graveyard] == ["Alpine Watchdog"]
    assert [item.card.name for item in game.stack] == ["Thrill of Possibility"]


def test_naming_the_spell_itself_is_refused_over_the_wire():
    """The client should never offer it — the enumeration above withholds it —
    and the server does not trust that it didn't."""
    sid, _sess, game = _discard_cost_session()

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Thrill of Possibility",
            "cost_hand_index": 1,
        },
    )

    assert resp.status_code >= 400 or not resp.json().get("supported", True)
    assert len(game.players[0].hand) == 3 and not game.players[0].graveyard


# ---------------------------------------------------------------------------
# An ability with a target *and* a cost: two announcements, two fields
# ---------------------------------------------------------------------------


def _weaponsmith_session():
    sid, session, game = _session(
        "Dwarven Weaponsmith", "Black Lotus", "Grizzly Bears"
    )
    game.players[0].hand = []
    for perm in game.players[0].battlefield:
        perm.metadata["summoning_sickness_turn"] = -99
    # "Activate only during your upkeep" is the Weaponsmith's own timing gate.
    game.current_turn_phase = "beginning"
    game.current_step = "upkeep"
    return sid, session, game


def test_the_two_pickers_are_reported_separately():
    """CR 601.2c picks the creature that gets the counter, CR 601.2b picks the
    artifact that pays. The client runs two prompts off these two lists — one
    picker collecting both would have to send one of them as the other, which is
    the mistake `cost_permanent_id` exists to prevent."""
    sid, _sess, _game = _weaponsmith_session()

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = state["players"][0]["battlefield"][0]["target_spec"]

    assert [t["name"] for t in spec["valid_targets"]] == [
        "Dwarven Weaponsmith", "Grizzly Bears"
    ]
    assert [t["name"] for t in spec["cost_spec"]["valid_targets"]] == ["Black Lotus"]


def test_the_counter_lands_on_the_named_creature_and_the_named_artifact_pays():
    """Both answers on the same action, each on its own field. The artifact
    sits *before* the target in the battlefield list, so paying the cost
    renumbers the slot the target was chosen from — which the permanent-id
    round already fixed for activation, and which is why this test exists on
    the wire rather than only in the engine."""
    sid, _sess, game = _weaponsmith_session()
    lotus = game.players[0].battlefield[1]
    bears = game.players[0].battlefield[2]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "activate",
            "permanent_name": "Dwarven Weaponsmith",
            "permanent_index": 0,
            "target_permanent_id": bears.permanent_id,
            "cost_permanent_id": lotus.permanent_id,
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert [p.card.name for p in game.players[0].battlefield] == [
        "Dwarven Weaponsmith", "Grizzly Bears"
    ]
    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


# ---------------------------------------------------------------------------
# A *spell* with a target and a cost — the same two announcements, one rule
# earlier
# ---------------------------------------------------------------------------
#
# Dwarven Weaponsmith's shape reaches the cast side through Demonic Embrace,
# Goblin Grenade and Soul Exchange, and the cast side used to answer with the
# cost *instead of* the target: `derive_cast_spec` returned the first cost
# picker and stopped. So the browser opened one prompt, sent a cast naming no
# target, and the engine refused it — "Demonic Embrace requires a target" — for
# a target it had itself declined to describe. Goblin Grenade did not even
# refuse: "any target" is not gated at announcement, so the Goblin was eaten and
# the 5 damage went wherever the fallback pointed.
#
# Demonic Embrace adds the half that is not Dwarven Weaponsmith's: its cost
# names a *zone*, so one card has two prices and the picker has to charge the
# one this cast pays.


def _embrace_session(*, in_graveyard: bool):
    sid, session, game = _session("Alpine Watchdog")
    embrace = _M21["Demonic Embrace"]
    game.players[0].hand = [_M21["Shock"], _M21["Swamp"]]
    game.players[0].graveyard = []
    if in_graveyard:
        game.players[0].graveyard = [embrace]
    else:
        game.players[0].hand.insert(0, embrace)
    game.players[0].battlefield[0].metadata["summoning_sickness_turn"] = -99
    game.start_priority_window(0)
    return sid, session, game


def test_the_hand_copy_is_offered_its_enchant_target_and_no_cost():
    """CR 601.2b charges what the *zone* prints. From the hand Demonic Embrace
    is an ordinary Aura at {1}{B}{B}, so the only announcement is its target."""
    sid, _sess, _game = _embrace_session(in_graveyard=False)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = _hand_card(state, "Demonic Embrace")["target_spec"]

    assert spec["kind"] == "creature"
    assert "cost_spec" not in spec and not spec.get("discard_cost")
    assert [t["name"] for t in spec["valid_targets"]] == ["Alpine Watchdog"]


def test_the_graveyard_copy_is_offered_both_and_keeps_them_apart():
    """From the graveyard the same card prints a second price, and the two
    announcements ride two fields: the Aura's target on the spec itself, the
    discard beside it under ``cost_spec``."""
    sid, _sess, _game = _embrace_session(in_graveyard=True)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = state["players"][0]["graveyard"][0]["target_spec"]

    assert spec["kind"] == "creature"
    assert [t["name"] for t in spec["valid_targets"]] == ["Alpine Watchdog"]
    cost = spec["cost_spec"]
    assert cost["discard_cost"] is True
    # The whole hand pays: CR 601.2a put the *graveyard* copy on the stack, so
    # nothing of the hand is withheld.
    assert [t["name"] for t in cost["valid_targets"]] == ["Shock", "Swamp"]


def test_casting_the_hand_copy_needs_only_the_target():
    sid, _sess, game = _embrace_session(in_graveyard=False)
    watchdog = game.players[0].battlefield[0]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Demonic Embrace",
            "target_seat": 0, "target_permanent_id": watchdog.permanent_id,
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert game.players[0].life == 20, "the graveyard's 3 life is not a hand price"
    assert [c.name for c in game.players[0].hand] == ["Shock", "Swamp"]
    assert (watchdog.effective_power, watchdog.effective_toughness) == (5, 3)


def test_casting_the_graveyard_copy_carries_both_answers():
    """Both fields on one action, the way the Weaponsmith's two arrive."""
    sid, _sess, game = _embrace_session(in_graveyard=True)
    watchdog = game.players[0].battlefield[0]

    resp = client.post(
        f"/api/sessions/{sid}/action",
        json={
            "seat": 0, "action": "cast", "card_name": "Demonic Embrace",
            "from_zone": "graveyard",
            "target_seat": 0, "target_permanent_id": watchdog.permanent_id,
            "cost_hand_index": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    game._settle()

    assert game.players[0].life == 17
    assert [c.name for c in game.players[0].hand] == ["Shock"]
    assert [c.name for c in game.players[0].graveyard] == ["Swamp"]
    assert (watchdog.effective_power, watchdog.effective_toughness) == (5, 3)


def test_goblin_grenade_reports_the_goblin_as_a_cost_and_the_damage_as_a_target():
    """The sacrifice-cost twin, and the one the engine could not refuse: "any
    target" is unchecked at announcement, so a spec that hid the target spent
    the Goblin and pointed the damage at the fallback."""
    sid, _sess, game = _session("Goblin Balloon Brigade", "Grizzly Bears")
    game.players[0].hand = [_CARDS["Goblin Grenade"]]
    game.start_priority_window(0)

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    spec = _hand_card(state, "Goblin Grenade")["target_spec"]

    assert spec["kind"] == "any"
    assert spec["cost_spec"]["sacrifice_cost"] is True
    # Only the Goblin can pay; the damage may go anywhere, the Goblin included.
    assert [t["name"] for t in spec["cost_spec"]["valid_targets"]] == [
        "Goblin Balloon Brigade"
    ]
    assert "Grizzly Bears" in [t.get("name") for t in spec["valid_targets"]]


def test_the_client_runs_the_second_prompt_instead_of_sending():
    """The client half of the same contract, and where the bug actually bit.

    The cost cascade used to sit above the target cascade with the note "none of
    the cards printing this one also targets", and its prompt sent the cast the
    moment the payment was picked. Three cards print both, so the payment has to
    be *held* — on ``pendingCastCost``, which rides sendAction the way the cast
    zone does — while the target prompt the spell still owes is run.
    """
    assert "function castCostSpec(" in APP_JS
    assert "function continueCastAfterCost(" in APP_JS
    assert "pendingCastCost" in APP_JS
    # The discard pick and the sacrifice/exile pick both continue rather than
    # send when a target is still owed.
    assert "thenTarget" in APP_JS
    assert "__castCostStage" in APP_JS
