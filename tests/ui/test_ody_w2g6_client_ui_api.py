"""What Odyssey's client round put on the wire, and what the client does with it.

Wave 1 was kept out of ``web/static/`` and reported what a person could not do
with its cards in a browser; W2G6 was the round with a browser. Every change
here was **clicked** in the running app (the report says what and what the
state API showed) — these tests are the half that can be held without one: the
payload a control reads, and, as text, that ``app.js`` still reads it
(``app.js`` is DOM-coupled and bare ``node`` cannot load it).

* ``ability_denials`` — CR 602.5 per ability on the permanent payload. For
  Barbarian Ring the state was identical at six and at seven cards in the
  graveyard, and the refusal reached a person as the action's error after a
  target had been chosen.
* ``color_changed`` — a colour the layers give has no ``color_override``.
* An action-priced ``optional_pay`` carries the printed sentence and, for
  "X unless Y", which half each answer is. ``number_choice`` carries the card's
  text.

The cards are put into the session by hand: a measured set's cards are not in
the catalog a session deals from.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import app_js_function_body
from web.app import app, store
from web.prompts import offer_wording

client = TestClient(app)

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"


def _app_js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


def _cards() -> dict:
    found: dict = {}
    for code in ("ODY", "LEA"):
        for card in load_cards(manifest_set_path(code, include_measured=True)):
            found.setdefault(card.name, card)
    return found


@pytest.fixture(scope="module")
def cards() -> dict:
    return _cards()


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 2626,
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


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _mine(sid: str, name: str, seat: int = 0) -> dict:
    return next(
        permanent for permanent in _state(sid, seat)["players"][seat]["battlefield"]
        if permanent["name"] == name
    )


# --- CR 602.5 on the payload -------------------------------------------------


def test_a_threshold_ability_says_it_is_denied_and_stops_saying_so(cards):
    sid, game = _session()
    _put(game, 0, cards["Barbarian Ring"])
    _put(game, 0, cards["Grizzly Bears"])
    game.players[0].graveyard.extend([cards["Forest"]] * 6)

    ring = _mine(sid, "Barbarian Ring")
    # One entry per usable ability, by the index the activate action takes:
    # the mana ability may be activated, the threshold ability may not.
    assert ring["ability_denials"] == [
        None, "only if there are seven or more cards in your graveyard",
    ]
    # A permanent with nothing denied carries no key at all.
    assert "ability_denials" not in _mine(sid, "Grizzly Bears")

    game.players[0].graveyard.append(cards["Forest"])
    assert "ability_denials" not in _mine(sid, "Barbarian Ring")


def test_the_denial_is_the_engine_s_own_refusal(cards):
    """The string a button shows is the one the activation is refused with —
    read off ``activation_denial``, so the two cannot disagree."""
    sid, game = _session()
    _put(game, 0, cards["Barbarian Ring"])
    _put(game, 0, cards["Mountain"])
    game.players[0].graveyard.extend([cards["Forest"]] * 6)
    denial = _mine(sid, "Barbarian Ring")["ability_denials"][1]

    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Barbarian Ring",
              "permanent_index": 0, "ability_index": 1, "target_seat": 1},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == f"Barbarian Ring: {denial}"


def test_only_the_viewer_s_own_permanents_carry_denials(cards):
    sid, game = _session()
    _put(game, 0, cards["Barbarian Ring"])
    theirs = next(
        permanent for permanent in _state(sid, seat=1)["players"][0]["battlefield"]
        if permanent["name"] == "Barbarian Ring"
    )
    assert "ability_denials" not in theirs


def test_the_client_reads_the_denial_before_it_opens_a_picker():
    menu = app_js_function_body("abilityOptionDisabledReason")
    assert "serverAbilityDenial(card, opt.index)" in menu
    start = app_js_function_body("startActivationPrompt")
    gate = start.index("serverAbilityDenial(card, abilityIndex)")
    # Before every cost prompt and every target picker of the cascade.
    assert gate < start.index("startActivationDiscardCostPrompt(")
    assert gate < start.index("startCastGraveyardCreatureTargetPrompt(")


# --- a colour the layers give ------------------------------------------------


def test_a_derived_colour_is_flagged_and_a_printed_one_is_not(cards):
    sid, game = _session()
    _put(game, 0, cards["Repentant Vampire"])
    _put(game, 0, cards["Grizzly Bears"])
    game.players[0].graveyard.extend([cards["Forest"]] * 6)
    vampire = _mine(sid, "Repentant Vampire")
    assert (vampire["colors"], vampire["color_changed"], vampire["color_override"]) == (["B"], False, None)

    game.players[0].graveyard.append(cards["Forest"])
    vampire = _mine(sid, "Repentant Vampire")
    # Threshold: "is white". ``color_override`` is one effect's slot and stays
    # empty, which is why a client reading it alone signalled nothing.
    assert (vampire["colors"], vampire["color_changed"], vampire["color_override"]) == (["W"], True, None)
    assert _mine(sid, "Grizzly Bears")["color_changed"] is False

    canvas = (STATIC / "battlefield-canvas.js").read_text(encoding="utf-8")
    assert "colorCard.color_changed === true" in canvas


# --- offers and numbers that said nothing ------------------------------------


class _Card:
    def __init__(self, text: str):
        self.oracle_text = text


class _Context:
    def __init__(self, text: str):
        self.card = _Card(text)


def test_an_unless_offer_says_which_half_each_answer_is():
    wording = offer_wording({"_context": _Context(
        "Blazing Salvo deals 3 damage to target creature unless that creature's "
        "controller has Blazing Salvo deal 5 damage to them."
    )})
    assert wording == {
        "card_text": "Blazing Salvo deals 3 damage to target creature unless that "
                     "creature's controller has Blazing Salvo deal 5 damage to them.",
        "decline_text": "Blazing Salvo deals 3 damage to target creature",
        "accept_text": "that creature's controller has Blazing Salvo deal 5 damage to them",
    }


def test_a_trigger_s_opening_is_not_part_of_either_answer():
    wording = offer_wording({"_context": _Context(
        "This creature enters with three +1/+1 counters on it.\n"
        "At the beginning of your upkeep, sacrifice this creature unless you "
        "remove a +1/+1 counter from it.\n"
        "{1}, Discard a card: Put a +1/+1 counter on this creature."
    )})
    assert wording["decline_text"] == "sacrifice this creature"
    assert wording["accept_text"] == "you remove a +1/+1 counter from it"


def test_a_may_offer_is_its_sentence_and_two_offers_are_the_whole_text():
    one = offer_wording({"_context": _Context(
        "Create a 2/2 Weird. Then you may return an instant or sorcery card "
        "from your graveyard to your hand. Exile this spell."
    )})
    assert one == {
        "card_text": "Then you may return an instant or sorcery card from your graveyard to your hand.",
    }
    # Nothing is guessed between two offers on one card.
    both = "You may draw a card.\nYou may gain 1 life."
    assert offer_wording({"_context": _Context(both)}) == {"card_text": both}
    assert offer_wording({}) == {}


def test_a_punisher_s_offer_reaches_its_seat_with_words(cards):
    """Blazing Salvo over the wire: the offer goes to the *creature's
    controller*, and its payload was a card name and four zeroes."""
    sid, game = _session()
    game.enforce_mana_costs = False
    _put(game, 1, cards["Grizzly Bears"])
    game.players[0].hand.append(cards["Blazing Salvo"])
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Blazing Salvo",
              "target_seat": 1, "permanent_index": 0},
    )
    assert cast.status_code == 200, cast.text
    for seat in (0, 1):
        client.post(f"/api/sessions/{sid}/action", json={"seat": seat, "action": "pass_priority"})

    offer, = _state(sid, seat=1)["optional_pay"]["pending"]
    assert offer["player_index"] == 1 and "prompt" not in offer
    assert offer["accept_text"] == "that creature's controller has Blazing Salvo deal 5 damage to them"
    assert offer["decline_text"] == "Blazing Salvo deals 3 damage to target creature"

    prompt = app_js_function_body("applyOptionalPayPrompt")
    assert "current?.accept_text" in prompt and "current?.decline_text" in prompt
    assert "current.card_text" in prompt


def test_a_number_choice_carries_the_card_that_asked(cards):
    sid, game = _session()
    game.enforce_mana_costs = False
    game.players[0].hand.extend([cards["Rites of Initiation"], cards["Forest"], cards["Forest"]])
    cast = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "cast", "card_name": "Rites of Initiation"},
    )
    assert cast.status_code == 200, cast.text
    for seat in (0, 1):
        client.post(f"/api/sessions/{sid}/action", json={"seat": seat, "action": "pass_priority"})
    choice = _state(sid)["number_choice"]
    assert (choice["minimum"], choice["maximum"]) == (0, 2)
    assert choice["card_text"].startswith("Discard any number of cards at random.")
    assert "info.card_text" in app_js_function_body("applyNumberChoicePrompt")


# --- the client, as text ------------------------------------------------------


def test_a_ceiling_discard_is_finished_by_a_confirm_not_by_its_count():
    """"Discard any number of cards" submitted itself when the selection
    reached ``count`` — the whole hand. The toggle returns for a ceiling and
    the panel's button sends the batch, an empty one included."""
    toggle = re.search(
        r"^async function toggleDiscardSelection\([^)]*\)\s*\{\n(.*?)^\}$",
        _app_js(), re.S | re.M,
    ).group(1)
    ceiling = toggle.index("if (info.up_to) {\r\n    renderBoard") if "\r\n" in toggle else toggle.index("if (info.up_to) {\n    renderBoard")
    assert ceiling < toggle.index("await submitDiscardSelection(info)")
    panel = app_js_function_body("applyDiscardSelectPrompt")
    assert 'id="discardUpToConfirmBtn"' in panel and "Discard nothing" in panel
    submit = re.search(
        r"^async function submitDiscardSelection\([^)]*\)\s*\{\n(.*?)^\}$",
        _app_js(), re.S | re.M,
    ).group(1)
    assert 'action: "discard_confirm", discard_indices: indices' in submit


def test_a_graveyard_cost_has_a_picker_and_its_answer_is_a_cost():
    """A graveyard exile cost fell to the graveyard *target* prompt, so the
    click went out as a target and the engine's default paid. It is asked by
    the cost cascade, before any target, and answered on the cost field."""
    start = app_js_function_body("startActivationPrompt")
    assert start.index("startActivationGraveyardCostPrompt(") < start.index(
        "startCastGraveyardCreatureTargetPrompt("
    )
    assert "cost_graveyard_indices: picked" in app_js_function_body("confirmPermanentCost")
    picker = app_js_function_body("startActivationGraveyardCostPrompt")
    assert 'zone: "graveyard"' in picker and "anyNumber" in picker


def test_a_chosen_cost_survives_the_lands_clicked_to_pay_for_it():
    """Each land clicked to pay an ability's mana re-enters
    ``startActivationPrompt`` as another activation, which dropped the cost
    the player had just chosen (Goblin Warrens sacrificed the engine's first
    two Goblins). The stash of the activation being paid for is kept."""
    start = app_js_function_body("startActivationPrompt")
    assert "const stashIsBeingPaidFor = !!pendingActivation" in start
    assert "pendingActivationCost && !stashIsBeingPaidFor" in start


def test_an_exact_graveyard_exile_holds_its_confirm():
    """Bloodcurdler's "exile two cards" is a floor as well as a ceiling. A
    short answer was sent, refused, and left the modal closed over a prompt
    the game was still waiting on."""
    modal = app_js_function_body("renderGraveyardExileModal")
    assert "const need = info.up_to ? 0 : Math.min(cap, legal.size);" in modal
    assert "confirmBtn.disabled = chosen < need;" in modal
    assert "renderGraveyardExileModal(info);" in modal  # reopened on a refusal


def test_each_of_up_to_n_targets_divides_nothing_and_may_name_nobody():
    confirm = app_js_function_body("confirmDividedTargets")
    assert "if (n === 0 && !eachUpTo) {" in confirm
    assert "(Number.isInteger(printedTargets) || eachUpTo) && !hasXCost(card)" in confirm
    each = app_js_function_body("dividedEachUpTo")
    assert 'spec.division === "each"' in each and "spec.max_targets" in each


def test_a_graveyard_spec_s_count_is_read_as_its_ceiling_unless_it_is_a_cost():
    ceiling = app_js_function_body("severalTargetMaximum")
    assert 'spec.kind === "graveyard_creature" && !specIsACost(spec)' in ceiling


def test_an_alternative_cost_named_in_part_holds_the_confirm_and_says_what_is_owed():
    js = _app_js()
    assert "shortAlternative = { chosen: chosenIds.length, wanted, verb: verb.toLowerCase() };" in js
    assert '${pending.refreshing || shortAlternative ? " disabled" : ""}' in js
    assert "offer.mana_owed" in js
    owed = app_js_function_body("pendingAutoTapCost")
    assert "pendingCastAlternativeOwed !== null" in owed
    assert "leaves the rest to the engine's default pick, exactly as the counted" not in js


def test_a_cast_with_no_graveyard_card_to_click_is_the_engine_s_to_refuse():
    prompt = app_js_function_body("startCastGraveyardCreatureTargetPrompt")
    empty = prompt.split("(spec.valid_targets || []).length === 0", 1)[1]
    assert 'if (castAction === "activate") {' in empty
    assert 'const body = { seat, action: castAction || "cast", card_name: cardName };' in empty


def test_the_prompts_say_where_the_cards_are_going():
    scry = app_js_function_body("renderScryModal")
    assert 'info.destination === "graveyard"' in scry and "Surveil ${count}" in scry
    look = app_js_function_body("renderLookTopPickModal")
    for key in ("info.pick_destination", "info.rest_destination", "info.remaining", "info.pile_seat"):
        assert key in look


def test_the_retired_kudzu_prompt_is_gone_from_the_client():
    js = _app_js()
    assert "kudzu_reattach" not in js and "KudzuReattach" not in js
