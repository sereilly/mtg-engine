"""The client halves of kg3 `client`, run on payloads the server really sent.

* CR 508.1d told to a person (``attackRequirementLines``), and End Turn's
  auto-pass standing down where the empty declaration obeys too few
  (``emptyAttackDeclarationRefused``) instead of looping on the refusal —
  Juggernaut on a person's battlefield.
* Two same-named permanents on the retarget prompt read apart
  (``retargetOptionLabels``).
* Magical Hack aimed at a spell offers the land words that spell's text
  reads now — since kg4 the server's reading (``text_change.stack_words``,
  ``web/offers.text_change_offer``; driven in
  ``test_kg4_client2_text_change_words.py``), read by ``textChangeWordOptions``.
* The re-ask back-off (``retryAutoAdvanceAfterFlight``): one scheduled
  re-ask serves every sender, and its delay grows only while nothing changes.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import run_app_js
from web.app import app, store
from tests.helpers import combat_ids

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _juggernaut_at_declare_attackers():
    response = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": 6262,
        "host_deck_cards": [{"name": "Plains", "count": 40}],
        "guest_deck_cards": [{"name": "Forest", "count": 40}],
    })
    assert response.status_code == 200, response.text
    sid = response.json()["session_id"]
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    session.current_turn = 0
    game.active_player_index = 0
    juggernaut = Permanent(card=_CARDS["Juggernaut"])
    game._put_permanent_onto_battlefield(0, juggernaut, None)
    juggernaut.metadata.pop("summoning_sickness_turn", None)
    game.start_priority_window(0)
    for _ in range(4):
        state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
        if state["current_step"] == "declare_attackers":
            return sid, game, state
        moved = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "next_phase"})
        assert moved.status_code == 200, moved.text
    raise AssertionError(state["current_step"])


_ATTACK_FUNCTIONS = [
    "attackRequirementLines", "attackRequirementEntry", "emptyAttackDeclarationRefused",
    "getCombatState",
]


def test_juggernaut_is_told_and_end_turn_does_not_send_the_refused_empty_attack():
    sid, _game, state = _juggernaut_at_declare_attackers()
    entry = state["combat"]["attack_requirements"][0]
    assert entry["attacking_player_index"] == 0 and entry["most_obeyable"] == 1
    refused = client.post(f"/api/sessions/{sid}/action", json=combat_ids(store.get(sid).game, {
        "seat": 0, "action": "declare_attackers", "attacker_indices": [], "target_seat": 1,
    }))
    assert refused.status_code == 400 and "Juggernaut must attack if able" in refused.text

    seen = run_app_js(
        _ATTACK_FUNCTIONS,
        "seat = 0; return { lines: attackRequirementLines(INPUT.combat, 0),"
        " refused: emptyAttackDeclarationRefused(INPUT), other: attackRequirementLines(INPUT.combat, 1) };",
        state,
        prelude="let seat = null; let currentState = null;",
    )
    assert seen["lines"] == ["Required: Juggernaut must attack if able."]
    assert seen["refused"] is True
    assert seen["other"] == []

    # End Turn's sender itself, with the network stubbed: it stands down and
    # says why rather than posting the declaration the server just refused.
    sent = run_app_js(
        _ATTACK_FUNCTIONS + [
            "maybeAutoPassUntilTurnEnd", "shouldAutoPassUntilTurnEnd", "isCombatStep",
        ],
        "seat = 0; await maybeAutoPassUntilTurnEnd(INPUT);"
        " return { sent, hints, enabled: autoPassTurnEndEnabled };",
        state,
        prelude=(
            "let seat = null; let currentState = null; const sent = []; const hints = [];"
            " let autoPassTurnEndEnabled = true; let autoPassMode = 'self';"
            " let autoPassTurnEndInFlight = false; let autoPassTurnEndRequestedStateKey = '';"
            " function gameIsOver() { return false; }"
            " function hasBlockingPromptForAutoPass() { return false; }"
            " function getAutoPassStateKey() { return 'k'; }"
            " function getStepKeyForAutoPass() { return 'k'; }"
            " async function sendAction(body) { sent.push(body); }"
            " function updateActionHint(text) { hints.push(text); }"
            " function renderBoard() {} function retryAutoAdvanceAfterFlight() {}"
            " function firstLivingOpponentSeat() { return 1; }"
            " function iDeclareBlocks() { return false; }"
        ),
    )
    assert sent["sent"] == [], sent
    assert sent["enabled"] is False
    assert any("must declare attackers" in hint and "Juggernaut" in hint for hint in sent["hints"])


def test_a_conditional_requirement_alone_leaves_the_empty_attack_legal():
    combat = {"attack_requirements": [{
        "attacking_player_index": 0, "most_obeyable": 1,
        "requirements": [{"attacker_index": 0, "reason": "Ekundu Cyclops must attack if able",
                          "conditional": True}],
    }]}
    seen = run_app_js(
        _ATTACK_FUNCTIONS,
        "seat = 0; return [emptyAttackDeclarationRefused({combat: INPUT}),"
        " attackRequirementLines(INPUT, 0)];",
        combat,
        prelude="let seat = null; let currentState = null;",
    )
    assert seen[0] is False
    assert seen[1] == ["Required: Ekundu Cyclops must attack if able, if its condition is met."]


def test_two_willbenders_one_seat_controls_read_apart():
    state = {"players": [
        {"battlefield": [
            {"id": 11, "name": "Willbender", "tapped": False, "power": 1, "toughness": 2},
            {"id": 12, "name": "Island"},
            {"id": 13, "name": "Willbender", "tapped": False, "power": 1, "toughness": 2},
        ]},
        {"name": "AI", "battlefield": [{"id": 21, "name": "Willbender", "tapped": True}]},
    ]}
    options = [
        {"index": 0, "kind": "permanent", "name": "Willbender", "id": 11, "seat": 0},
        {"index": 1, "kind": "permanent", "name": "Willbender", "id": 13, "seat": 0},
        {"index": 2, "kind": "permanent", "name": "Willbender", "id": 21, "seat": 1},
        {"index": 3, "kind": "player", "name": "AI"},
    ]
    functions = ["retargetOptionLabels", "retargetOptionLabel", "candidatePermanentName",
                 "candidateOwnerLabel"]
    labels = run_app_js(
        functions,
        "seat = 0; currentState = INPUT.state;"
        " return Object.fromEntries(retargetOptionLabels(INPUT.options, INPUT.state));",
        {"options": options, "state": state},
        prelude="let seat = null; let currentState = null;",
    )
    assert labels == {
        "0": "Willbender — yours (back of the pile)",
        "1": "Willbender — yours (front of the pile)",
        "2": "Willbender — AI's",
        "3": "AI (player)",
    }
    # Where the board shows a difference, the difference is the label.
    state["players"][0]["battlefield"][2]["tapped"] = True
    labels = run_app_js(
        functions,
        "seat = 0; currentState = INPUT.state;"
        " return Object.fromEntries(retargetOptionLabels(INPUT.options, INPUT.state));",
        {"options": options, "state": state},
        prelude="let seat = null; let currentState = null;",
    )
    assert labels["0"] == "Willbender — yours (untapped)"
    assert labels["1"] == "Willbender — yours (tapped)"


def test_magical_hack_offers_the_land_words_a_spell_reads_now():
    """The words come from the server, per top-first stack index; the client
    offers exactly those, in colour order."""
    hack = {"text_change": {"mode": "land_type", "words": {}, "stack_words": {
        "0": ["U", "G"], "1": ["B"],
    }}}
    words = run_app_js(
        ["textChangeWordOptions", "castTextChange"],
        "return [0, 1, 2].map((i) => textChangeWordOptions(INPUT, { stackIndex: i }).map((o) => o.symbol));",
        hack,
        prelude=(
            "const MANA_COLOR_OPTIONS = [{symbol:'W'},{symbol:'U'},{symbol:'B'},{symbol:'R'},{symbol:'G'}];"
        ),
    )
    assert words == [["U", "G"], ["B"], []]


def test_one_reask_serves_every_sender_and_backs_off_while_nothing_changes():
    seen = run_app_js(
        ["retryAutoAdvanceAfterFlight", "stateRefetchDelayMs", "noteStateForRefetchBackoff",
         "snapStateRefetchBackoff"],
        """
        const delays = [];
        globalThis.setTimeout = (fn, ms) => { delays.push(ms); timers.push(fn); return 1; };
        // Four senders' finally blocks on one state: one fetch.
        for (let i = 0; i < 4; i += 1) retryAutoAdvanceAfterFlight();
        const first = { scheduled: timers.length, delay: delays[0] };
        timers.shift()();
        // The same state rendered again and again: the delay grows, capped.
        const grown = [];
        for (let i = 0; i < 8; i += 1) {
          noteStateForRefetchBackoff({ key: "same" });
          retryAutoAdvanceAfterFlight();
          grown.push(delays[delays.length - 1]);
          timers.shift()();
        }
        // A change snaps it back.
        noteStateForRefetchBackoff({ key: "moved" });
        retryAutoAdvanceAfterFlight();
        const afterChange = delays[delays.length - 1];
        timers.shift()();
        noteStateForRefetchBackoff({ key: "moved" });
        noteStateForRefetchBackoff({ key: "moved" });
        snapStateRefetchBackoff();
        retryAutoAdvanceAfterFlight();
        return { first, grown, afterChange, afterAction: delays[delays.length - 1], fetches };
        """,
        None,
        prelude=(
            "let sessionId = 's'; let fetches = 0; const timers = [];"
            " async function getState() { fetches += 1; }"
            " function getAutoPassStateKey(state) { return state.key; }"
            " let stateRefetchScheduled = false; let stateRefetchQuietRenders = 0;"
            " let stateRefetchLastKey = ''; const STATE_REFETCH_BACKOFF_BASE_MS = 250;"
            " const STATE_REFETCH_BACKOFF_MAX_MS = 4000;"
        ),
    )
    assert seen["first"] == {"scheduled": 1, "delay": 0}
    assert seen["grown"] == [0, 0, 250, 500, 1000, 2000, 4000, 4000]
    assert seen["afterChange"] == 0
    assert seen["afterAction"] == 0
    assert seen["fetches"] == 10
