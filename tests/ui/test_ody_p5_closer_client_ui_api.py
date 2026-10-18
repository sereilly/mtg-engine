"""What Odyssey's Phase 5 found by clicking, and the closing round fixed.

Each of these was a defect a person met in the running app that no engine
instrument can see — the engine was right every time. So the ratchets are of
two kinds: what the **wire** carries (asked of a live session), and, as text,
that the client still **reads** it (``app.js`` and ``deck-editor.js`` are
DOM-coupled and bare ``node`` cannot load them; see
``tests.helpers.app_js_function_body``).

* **End Turn stalled its own turn in Declare Blockers.** Two automatic senders
  both owed the empty attack declaration while End Turn was passing, one of
  them after an animation wait, and a state rendered while a sender's
  in-flight flag was up was skipped and never asked again.
* **A filter land asked which colour it adds.** The permanent's
  ``produced_mana`` is a summary of everything it can make, and a filter land's
  reads like a dual land's; ``ability_mana`` says what each ability adds and
  whether activating it is a choice.
* **A modal's Confirm fired once per prompt ever shown.**
* **Automatic requests the server will refuse**: an ``ai_step`` into the
  human's open prompt, and anything at all once the game is over.
* **A saved personal deck read "60 unsupported".**
* Three small ones: no Auto-Tap after a several-target activation was refused
  for mana, an ability menu left open for a permanent that had gone, and
  "Cast Mountain targeting seat 1." for a land play.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store

client = TestClient(app)

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"

#: The four senders that act for the viewer on a rendered state, each behind
#: its own in-flight flag. (`maybeAutoStepAi` is the fifth and has always
#: asked again in its ``finally``.)
SENDERS = {
    "maybeAutoPassUntilTurnEnd": "autoPassTurnEndInFlight",
    "maybeAutoPassPriority": "autoPassPriorityInFlight",
    "maybeAutoPassDisabledPhase": "autoPassDisabledPhaseInFlight",
    "maybeAutoAdvanceCombatDeclaration": "autoCombatDeclareInFlight",
}


def _app_js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _sender_body(name: str) -> str:
    """The body of one of the automatic senders. They are ``async function``s,
    which ``app_js_function_body`` does not read; the same shape otherwise —
    the closing brace is the first one in column 0."""
    match = re.search(
        r"^async function " + re.escape(name) + r"\([^)]*\)\s*\{\n(.*?)^\}$",
        _app_js(), re.S | re.M,
    )
    assert match is not None, f"{name} is gone, renamed, or no longer async"
    return match.group(1)


def _deck_editor_function(name: str) -> str:
    """One function of ``deck-editor.js``, which lives inside an IIFE: from its
    two-space-indented header to the first two-space-indented closing brace."""
    source = (STATIC / "deck-editor.js").read_text(encoding="utf-8")
    match = re.search(
        rf"^  (?:async )?function {re.escape(name)}\(.*?^  \}}", source, re.S | re.M
    )
    assert match, f"deck-editor.js has no function {name}"
    return match.group(0)


@pytest.fixture(scope="module")
def cards() -> dict:
    catalog = load_catalog()
    pool = catalog.values() if isinstance(catalog, dict) else catalog
    return {card.name: card for card in pool}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 3131,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    return sid, game


def _put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = False
    return permanent


def _mine(sid: str, name: str, seat: int = 0) -> dict:
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(
        permanent for permanent in state["players"][seat]["battlefield"]
        if permanent["name"] == name
    )


# --- End Turn and the empty attack ------------------------------------------


def test_the_empty_attack_has_one_submitter_while_end_turn_is_passing():
    """End Turn (`maybeAutoPassUntilTurnEnd`, `owesOwnAttack`) declares no
    attackers for its own seat at once. The combat nudge used to send the same
    declaration after waiting for animations — twice in the log on every End
    Turn, and its wait could outlast the two states that followed."""
    nudge = _sender_body("maybeAutoAdvanceCombatDeclaration")
    attack_branch = nudge.split("} else if (", 1)[0]
    assert 'isCombatStep(state, "declare_attackers")' in attack_branch
    assert "!shouldAutoPassUntilTurnEnd(state)" in attack_branch
    assert "owesOwnAttack" in _sender_body("maybeAutoPassUntilTurnEnd")


@pytest.mark.parametrize("sender, flag", sorted(SENDERS.items()))
def test_a_state_skipped_for_an_in_flight_flag_is_asked_again(sender, flag):
    """A sender's own response is rendered inside its `await sendAction`, with
    its flag still up, so that render is skipped. The stall was a skipped state
    that was also the last one the server sent: Declare Blockers on the
    viewer's own turn, nobody holding priority, and nothing left to nudge it."""
    body = _sender_body(sender)
    assert re.search(rf"if \(.*{flag}.*\)\s*(?:\{{\s*)?return;", body), (
        f"{sender} no longer skips on {flag}; the retry below may be unnecessary"
    )
    tail = body.rsplit("finally", 1)[1]
    assert re.search(
        rf"{flag} = false;\s*(?://[^\n]*\s*)*retryAutoAdvanceAfterFlight\(\);", tail
    ), f"{sender} clears {flag} without asking again"


def test_the_retry_asks_the_server_not_the_state_the_sender_was_handed():
    """A sender's own response can be mid-transition at a turn boundary (the
    old turn's step and priority beside a log the new turn has written to).
    Skipping it is what kept a sender off it; re-running the senders on
    `currentState` sent passes the server refused. The retry fetches."""
    retry = app_js_function_body("retryAutoAdvanceAfterFlight")
    assert "getState()" in retry
    assert "currentState" not in retry


def test_a_pass_that_crossed_another_request_does_not_switch_end_turn_off():
    body = _sender_body("maybeAutoPassUntilTurnEnd")
    assert "does not have priority|no active priority window" in body
    # …and the other two passers stand down once End Turn has the passing.
    for sender in ("maybeAutoPassPriority", "maybeAutoPassDisabledPhase"):
        revalidation = _sender_body(sender).split("const latest = currentState;", 1)[1]
        assert "autoPassTurnEndEnabled ||" in revalidation.split("return;", 1)[0]


# --- Requests the server will refuse ----------------------------------------


@pytest.mark.parametrize("sender", sorted(SENDERS))
def test_no_automatic_sender_acts_on_a_finished_game(sender):
    """`pass_priority` went out after "AI lost the game" and came back 400
    "game already finished"."""
    first_line = _sender_body(sender).lstrip().splitlines()[0]
    assert first_line.strip() == "if (gameIsOver(state)) return;"


def test_the_ai_is_not_stepped_into_a_decision_the_viewer_owes():
    """`waiting_on_prompt` is the server's answer to "would this viewer's next
    action be refused because a decision is owed". An `ai_step` is such an
    action: sent into an open discard it was a 400 painted over the prompt in
    red, on every AI turn that armed one."""
    should = app_js_function_body("shouldAutoStepAi")
    assert "if (gameIsOver(state)) return false;" in should
    assert "if (state.waiting_on_prompt) return false;" in should


def test_the_prompt_panel_stands_down_for_the_game_over_overlay():
    panel = app_js_function_body("renderActivationPrompt")
    guard = re.search(r"if \(gameIsOver\(currentState\)\) \{\s*panel\.classList\.add\(\"hidden\"\);\s*return;", panel)
    assert guard, "the step's prompt is live under the Victory overlay again"
    assert guard.start() < panel.index("getCleanupDiscardInfo()")
    over = app_js_function_body("gameIsOver")
    assert 'state.status === "finished"' in over and "state.winner" in over


# --- What an ability adds ----------------------------------------------------

FILTER_LANDS = (
    "Darkwater Catacombs", "Mossfire Valley", "Shadowblood Ridge",
    "Skycloud Expanse", "Sungrass Prairie",
)


@pytest.mark.parametrize("name", FILTER_LANDS)
def test_a_filter_land_s_output_is_fixed(cards, name):
    """"{1}, {T}: Add {R}{G}." makes both symbols whichever is asked for. Its
    `produced_mana` reads like a dual land's, and that was all the client had."""
    sid, game = _session()
    _put(game, 0, cards[name])
    payload = _mine(sid, name)
    assert len(payload["produced_mana"]) == 2
    (entry,) = payload["ability_mana"]
    assert entry["choice"] is False
    assert sorted(entry["symbols"]) == sorted(payload["produced_mana"])


def test_each_ability_says_what_it_adds_by_the_index_the_action_takes(cards):
    sid, game = _session()
    for name in ("Karplusan Forest", "City of Brass", "Sol Ring", "Cabal Pit", "Land Cap", "Forest"):
        _put(game, 0, cards[name])
    # A painland: the colourless line is fixed, the coloured line is a choice
    # of its own two symbols — not of the land's three.
    colourless, coloured = _mine(sid, "Karplusan Forest")["ability_mana"]
    assert colourless == {"symbols": ["C"], "choice": False}
    assert coloured["choice"] is True and sorted(coloured["symbols"]) == ["G", "R"]
    assert _mine(sid, "City of Brass")["ability_mana"] == [
        {"symbols": ["W", "U", "B", "R", "G"], "choice": True}
    ]
    assert _mine(sid, "Sol Ring")["ability_mana"] == [{"symbols": ["C"], "choice": False}]
    # The mana line and a line that makes no mana.
    assert _mine(sid, "Cabal Pit")["ability_mana"] == [{"symbols": ["B"], "choice": False}, None]
    # A rider beside the mana (a depletion counter) changes nothing asked here.
    (land_cap,) = _mine(sid, "Land Cap")["ability_mana"]
    assert land_cap["choice"] is True and sorted(land_cap["symbols"]) == ["U", "W"]
    # A basic land has no activated ability in its program, and says nothing.
    assert "ability_mana" not in _mine(sid, "Forest")


def test_only_the_viewer_s_own_permanents_say_it(cards):
    sid, game = _session()
    _put(game, 0, cards["Mossfire Valley"])
    assert "ability_mana" in _mine(sid, "Mossfire Valley", seat=0)
    other = client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()
    theirs = next(p for p in other["players"][0]["battlefield"] if p["name"] == "Mossfire Valley")
    assert "ability_mana" not in theirs


def test_the_client_asks_no_colour_of_a_fixed_output_and_offers_the_ability_s_own():
    """The colour prompts in `startActivationPrompt` are decided by the
    ability's entry where there is one; the card's text and the permanent's
    summary are what is left for a permanent the server said nothing about."""
    start = app_js_function_body("startActivationPrompt")
    assert "const ownMana = chosenAbilityMana(card);" in start
    assert start.index("chosenAbilityMana(card)") < start.index("cardRequiresManaColorChoice(card)")
    assert re.search(
        r"const asksAnyColor = ownMana\s*\?\s*ownMana\.choice && ownMana\.symbols\.length >= 5\s*:\s*cardRequiresManaColorChoice\(card\);",
        start,
    )
    fan = app_js_function_body("abilityManaColors")
    stated = fan.index("chosenAbilityMana(card)")
    assert stated < fan.index("getDualLandColors(card)")
    assert re.search(r"return stated\.choice && stated\.symbols\.length >= 2 \? stated\.symbols : null;", fan)
    chosen = app_js_function_body("chosenAbilityMana")
    assert "card.ability_mana" in chosen and "card.__abilityIndex" in chosen
    assert "oracle_text" not in chosen


def test_a_filter_land_whose_cost_is_floating_is_sent_as_it_is_clicked():
    """With the fan gone a filter land takes the ordinary costed-ability path,
    whose first step is "press OK to start paying". With the {1} already in the
    pool that step decides nothing, so a fixed-output mana ability the pool
    covers goes out on the click; with an empty pool the step is what lets the
    player tap for it."""
    start = app_js_function_body("startActivationPrompt")
    assert re.search(
        r"const fixedManaPaidFromPool =\s*!!ownMana && !ownMana\.choice\s*&& manaPoolCanPayCost\(",
        start,
    )
    assert "if (!shouldPromptForActivationCost(activationCost) || fixedManaPaidFromPool) {" in start


# --- One listener per Confirm ------------------------------------------------


def test_no_modal_confirm_unbinds_itself():
    """`delete confirmBtn.dataset.bound` removed the marker and not the
    listener, so each prompt bound another: Cultural Exchange's second Confirm
    sent `[126]` and then `[]`."""
    assert "delete confirmBtn.dataset.bound" not in _app_js()
    assert "delete shuffleBtn.dataset.bound" not in _app_js()


@pytest.mark.parametrize("renderer", [
    "renderUntapUpToModal", "renderPermanentSetChoiceModal", "renderKeepPermanentsModal",
])
def test_a_set_choice_confirm_is_bound_under_its_marker(renderer):
    body = app_js_function_body(renderer)
    assert body.count('confirmBtn.addEventListener("click"') == 1
    assert re.search(
        r"if \(confirmBtn && !confirmBtn\.dataset\.bound\) \{\s*confirmBtn\.dataset\.bound = \"1\";\s*confirmBtn\.addEventListener",
        body,
    )


# --- A personal deck's status ------------------------------------------------


def test_a_deck_entry_with_no_status_is_given_the_catalog_s():
    """A personal deck is stored as `{name, count}`; the stats line counts
    `status !== "ok"`. Every deck enters the editor through `resetDeck`."""
    reset = _deck_editor_function("resetDeck")
    for board in ("entries", "sideboard", "commander"):
        assert f"{board} = withEntryStatus({board});" in reset
    derive = _deck_editor_function("withEntryStatus")
    assert "!entry.status" in derive and "cardStatus(entry.name)" in derive
    # …and a name the catalog does not know still reads as unknown.
    status = _deck_editor_function("cardStatus")
    assert 'if (!card) return "unknown";' in status


def test_a_shared_deck_arrives_with_the_server_s_status():
    deck = client.get("/api/decks").json()["decks"][0]
    assert deck["cards"] and all(entry["status"] == "ok" for entry in deck["cards"])


# --- Three small ones --------------------------------------------------------


def test_a_several_target_send_refused_for_mana_offers_the_auto_tap():
    confirm = app_js_function_body("confirmSeveralTargets")
    assert 'startsWith("insufficient mana")' in confirm
    assert "cost: getActivatedAbilityCost(card, p.abilityIndex), actionBody: body" in confirm
    # …and the prompt is not swept away behind the offer.
    assert "if (!pendingAutoTap) clearPendingHandCast();" in confirm


def test_an_ability_menu_does_not_outlive_its_permanent():
    assert "dropAbilityChoiceIfStale(state);" in app_js_function_body("renderBoard")
    drop = app_js_function_body("dropAbilityChoiceIfStale")
    assert "permanent.id === id" in drop and "pendingAbilityChoice = null;" in drop


def test_a_land_is_played_and_nothing_targets_a_seat_by_default():
    assert "targeting seat ${" not in _app_js()
    hint = app_js_function_body("playedCardHint")
    assert "Played ${cardName}." in hint and "Cast ${cardName}." in hint
