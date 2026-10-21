"""The trigger-target prompt in the browser: four things the wire already
allowed and the client did not do.

A triggered ability chooses its targets as it is put on the stack (CR 603.3d),
and for a human seat that is a prompt (``trigger_target``). The server half is
pinned by ``test_trigger_target_several_ui_api.py`` and
``test_trigger_target_graveyard_ui_api.py``; this is the client:

* **the pass that was sent under the prompt.** The client passes priority for
  its player after a cast and in phases the player set to auto-pass, and
  decided whether a prompt was in the way from a hand-kept list of the prompts
  it knew. This one was not on it: one ``pass_priority`` went out as the
  prompt appeared and came back 400. The state carries the registry's own
  answer (``waiting_on_prompt``) and the auto-pass asks it first;
* **several targets at once.** "Put a +1/+1 counter on each of up to two other
  target creatures you control" (Basri's Acolyte) was answered one id per
  click — a legal answer to "up to two", and never the second target. The
  several-targets dialog that served an opponent-chosen mode serves this
  prompt too, and its confirm sends one list: two, one or none;
* **whose graveyard.** "opponent's graveyard" names a pile only while there is
  one opponent;
* **a graveyard pick is not a permanent.** A cast at a card in a graveyard
  also sent the id of whatever permanent sat in the same numbered slot of that
  seat's battlefield.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import app_js_function_body, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _session():
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 603,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    # What the action preamble sets before every action; the triggers below
    # are put on the stack on the engine directly.
    game.interactive_seats = {0, 1}
    for player in game.players:
        player.battlefield.clear()
        player.graveyard.clear()
        player.hand.clear()
    game.stack.clear()
    game.pending_choices.clear()
    game.start_priority_window(0)
    return sid, game


def _enter(game, seat, name) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _state(sid, seat=0):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


def _acolyte_board():
    """Three creatures and a Basri's Acolyte that entered without being cast:
    its trigger asks seat 0 for up to two of them."""
    sid, game = _session()
    creatures = [
        _enter(game, 0, name) for name in ("Grizzly Bears", "Hill Giant", "Savannah Lions")
    ]
    _enter(game, 0, "Basri's Acolyte")
    return sid, game, creatures


# --- the pass that was sent under the prompt ---------------------------------

def test_the_state_says_a_prompt_holds_the_viewers_priority():
    sid, game, creatures = _acolyte_board()

    state = _state(sid)
    assert state["trigger_target"]["card_name"] == "Basri's Acolyte"
    assert state["waiting_on_prompt"] is True
    # The field is the refusal the pass would get.
    refused = _act(sid, seat=0, action="pass_priority")
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "choose the triggered ability's target before other actions"
    )

    answered = _act(
        sid, seat=0, action="trigger_target_confirm",
        target_permanent_ids=[creatures[0].permanent_id],
    )
    assert answered.status_code == 200, answered.text
    assert _state(sid)["waiting_on_prompt"] is False


def test_no_prompt_no_block_and_a_spectator_is_told_nothing():
    sid, _game = _session()

    assert _state(sid)["waiting_on_prompt"] is False
    assert client.get(f"/api/sessions/{sid}/state").json()["waiting_on_prompt"] is False


def test_the_auto_pass_asks_the_server_before_its_own_list():
    """Text-level: ``hasBlockingPromptForAutoPass`` is one line of sixty
    ``get…Info`` readers and cannot be lifted into node whole. Its first
    statement is the server's answer — and the list beside it still does not
    name this prompt, which is the census run backwards: without that first
    line the three auto-pass senders are blind to it again."""
    gate = app_js_function_body("hasBlockingPromptForAutoPass")

    first = next(line.strip() for line in gate.split("\n")
                 if line.strip() and not line.strip().startswith("//"))
    assert first == "if (state?.waiting_on_prompt) return true;"
    assert "getTriggerTargetInfo" not in gate
    for sender in (
        "maybeAutoPassUntilTurnEnd", "maybeAutoPassPriority", "maybeAutoPassDisabledPhase",
    ):
        assert "hasBlockingPromptForAutoPass(" in app_js_function_body(sender), sender


# --- several targets at once -------------------------------------------------

#: A page small enough to run the dialog: the modal's five elements, tiles
#: rebuilt from the markup the renderer writes, and the senders recorded.
_DOM = r'''
let seat = 0;
let currentState = INPUT.state;
let modalModeTargetsSelected = new Set();
let severalTargetsOpenFor = null;
let severalTargetsShares = new Map();
function escapeHtml(text) { return String(text); }
function tile(markup) {
  const el = {
    dataset: { id: /data-id="(\d+)"/.exec(markup)[1] },
    classList: {
      on: / selected"/.test(markup),
      toggle() { this.on = !this.on; },
      contains() { return this.on; },
    },
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    click() { this.listeners.click(); },
  };
  return el;
}
const nodes = {
  modalModeTargetsModal: { hidden: true, classList: { add() { nodes.modalModeTargetsModal.hidden = true; }, remove() { nodes.modalModeTargetsModal.hidden = false; } } },
  modalModeTargetsSubtitle: { textContent: "" },
  modalModeTargetsConfirmBtn: { disabled: false, dataset: {}, onclick: null },
  modalModeTargetsList: {
    tiles: [], markup: "",
    set innerHTML(html) {
      this.markup = html;
      this.tiles = (html.match(/<div class="library-card-choice[^"]*" data-id="\d+">/g) || []).map(tile);
    },
    querySelectorAll() { return this.tiles; },
  },
};
// A divided trigger's share inputs (Shambling Swarm): one per chosen target,
// rebuilt from the markup the renderer writes.
function shareInput(markup) {
  const el = {
    dataset: { triggerShare: /data-trigger-share="(\d+)"/.exec(markup)[1] },
    value: /value="(\d+)"/.exec(markup)[1],
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    set(value) { this.value = String(value); this.listeners.input(); },
  };
  return el;
}
nodes.modalModeTargetsDivision = {
  inputs: [], markup: "", dataset: {}, hidden: true,
  classList: { toggle(name, on) { nodes.modalModeTargetsDivision.hidden = on; } },
  set innerHTML(html) {
    this.markup = html;
    this.inputs = (html.match(/<input [^>]*>/g) || []).map(shareInput);
  },
  querySelectorAll() { return this.inputs; },
};
nodes.modalModeTargetsDivisionRemaining = { textContent: "" };
const document = { getElementById: (id) => nodes[id] || null };
const sent = [];
const hints = [];
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function updateActionHint(message) { hints.push(message); }
function show() { renderSeveralTargetsModal(severalTargetsPrompt(currentState)); }
function chosen() { return nodes.modalModeTargetsList.tiles.map((t) => t.classList.contains()); }
'''

_DIALOG = [
    "getTriggerTargetInfo", "getModalModeTargetsInfo", "triggerNamesSeveralTargets",
    "severalTargetsPrompt", "candidateOwnerLabel", "renderSeveralTargetsModal",
    # A divided trigger's shares (Shambling Swarm).
    "evenStartingDivision", "severalTargetsDivisionValid", "resplitSeveralTargetsShares",
    "renderSeveralTargetsDivision",
]


@needs_node
@pytest.mark.parametrize("picks", [(0, 1), (2,), ()], ids=["two", "one", "none"])
def test_up_to_two_targets_are_named_together(picks):
    """The dialog over the payload the server sent, clicked, and its one
    request posted as built: both creatures get the counter, or one does, or
    the ability names nobody."""
    sid, game, creatures = _acolyte_board()

    out = run_app_js(
        _DIALOG,
        """
        show();
        const opened = {
          hidden: nodes.modalModeTargetsModal.hidden,
          subtitle: nodes.modalModeTargetsSubtitle.textContent,
          tiles: nodes.modalModeTargetsList.tiles.length,
          confirmDisabled: nodes.modalModeTargetsConfirmBtn.disabled,
        };
        for (const index of INPUT.picks) nodes.modalModeTargetsList.tiles[index].click();
        // A third click is past the printed two and changes nothing.
        if (INPUT.picks.length === 2) nodes.modalModeTargetsList.tiles[2].click();
        const picked = chosen();
        // A state arriving while the dialog is open re-renders it; what was
        // picked stays picked.
        show();
        const afterRerender = chosen();
        await nodes.modalModeTargetsConfirmBtn.onclick();
        return { opened, picked, afterRerender, sent, hiddenAfter: nodes.modalModeTargetsModal.hidden };
        """,
        {"state": _state(sid), "picks": list(picks)},
        prelude=_DOM,
    )

    assert out["opened"] == {
        "hidden": False, "tiles": 3, "confirmDisabled": False,
        "subtitle": (
            "Basri's Acolyte: its triggered ability names up to 2 targets. "
            "Confirm with none chosen to name no target."
        ),
    }
    expected = [index in picks for index in range(3)]
    assert out["picked"] == expected and out["afterRerender"] == expected
    named = [creatures[index].permanent_id for index in picks]
    assert out["sent"] == [
        {"seat": 0, "action": "trigger_target_confirm", "target_permanent_ids": named}
    ]
    assert out["hiddenAfter"] is True

    response = client.post(f"/api/sessions/{sid}/action", json=out["sent"][0])
    assert response.status_code == 200, response.text
    resolve_stack(game)
    countered = [
        index for index, creature in enumerate(creatures)
        if counters_on(creature, "+1/+1")
    ]
    assert countered == sorted(picks)


@needs_node
def test_the_board_and_the_panel_leave_a_several_target_prompt_to_the_dialog():
    """One prompt, three places that used to answer it. The dialog owns it:
    the panel says so and offers no "Name no target" of its own, and a click
    on the board no longer sends the first creature as the whole answer."""
    sid, _game, _creatures = _acolyte_board()
    state = _state(sid)

    several = run_app_js(
        ["triggerNamesSeveralTargets"],
        "return [triggerNamesSeveralTargets(INPUT.trigger_target), "
        "triggerNamesSeveralTargets(null), "
        "triggerNamesSeveralTargets({ max_targets: 1, candidates: [] })];",
        state,
    )
    assert several == [True, False, False]

    panel = app_js_function_body("applyTriggerTargetPrompt")
    branch = panel[panel.index("if (triggerNamesSeveralTargets(info)) {"):]
    branch = branch[:branch.index("return;")]
    assert 'q("promptOkBtn").classList.add("hidden")' in branch
    assert "choose them in the dialog" in branch

    board = app_js_function_body("getPromptBoardTargeting")
    assert "if (triggerTargetInfo && !triggerNamesSeveralTargets(triggerTargetInfo)) {" in board


@needs_node
def test_a_list_of_graveyard_cards_keeps_its_buttons():
    """A several-target answer is a list of permanent ids — the one shape the
    server takes one in. A prompt whose candidates are cards in a graveyard is
    not the dialog's, whatever ``max_targets`` says."""
    prompt = {
        "player_seat": 0, "card_name": "Rysorian Badger", "max_targets": 2, "up_to": True,
        "candidates": [
            {"kind": "graveyard", "seat": 1, "graveyard_index": 0, "name": "Grizzly Bears"},
            {"kind": "graveyard", "seat": 1, "graveyard_index": 1, "name": "Hill Giant"},
        ],
    }

    out = run_app_js(
        _DIALOG,
        "return [triggerNamesSeveralTargets(INPUT.state.trigger_target), "
        "severalTargetsPrompt(INPUT.state)];",
        {"state": {"trigger_target": prompt}},
        prelude=_DOM,
    )

    assert out == [False, None]


@needs_node
def test_an_opponent_chosen_modes_targets_still_use_the_dialog():
    """The prompt the dialog was built for (Fatal Lore) reads exactly as it
    did: its own action, an empty answer allowed, the opponent's words in the
    subtitle."""
    state = {
        "modal_mode_targets": {
            "player_seat": 0, "card_name": "Fatal Lore", "mode_label": "destroy two",
            "max_targets": 2,
            "candidates": [
                {"id": 7, "seat": 1, "name": "Grizzly Bears"},
                {"id": 9, "seat": 1, "name": "Hill Giant"},
            ],
        },
        "players": [{"name": "Host"}, {"name": "Guest"}],
    }

    out = run_app_js(
        _DIALOG,
        """
        show();
        nodes.modalModeTargetsList.tiles[1].click();
        const subtitle = nodes.modalModeTargetsSubtitle.textContent;
        const owners = nodes.modalModeTargetsList.markup;
        await nodes.modalModeTargetsConfirmBtn.onclick();
        return { subtitle, sent, named: owners.includes("Guest's") };
        """,
        {"state": state}, prelude=_DOM,
    )

    assert out["subtitle"] == 'Fatal Lore: your opponent chose "destroy two". Choose up to 2.'
    assert out["sent"] == [
        {"seat": 0, "action": "modal_mode_targets_confirm", "target_permanent_ids": [9]}
    ]
    assert out["named"] is True


# --- whose graveyard ----------------------------------------------------------

@needs_node
def test_a_graveyard_is_named_by_its_owner():
    """Four seats: "opponent's graveyard" would be three different piles."""
    state = {"players": [{"name": "Ann"}, {"name": "Bo"}, {"name": "Cy"}, {}]}

    labels = run_app_js(
        ["graveyardOwnerLabel"],
        "return [0, 1, 2, 3].map((owner) => graveyardOwnerLabel(owner));",
        {"state": state},
        prelude="let seat = 0; let currentState = INPUT.state;",
    )

    assert labels == [
        "your graveyard", "Bo's graveyard", "Cy's graveyard", "Seat 4's graveyard",
    ]
    panel = app_js_function_body("applyTriggerTargetPrompt")
    assert "graveyardOwnerLabel(c.seat)" in panel
    # The string the button used to be labelled with is gone from the code
    # (a comment there still quotes it, to say why).
    assert '"opponent\'s graveyard"' not in panel.replace(
        '"opponent\'s graveyard" is one pile', ""
    )


def test_the_wire_offers_a_card_from_another_players_graveyard():
    """The prompt the label is for, from a real card: "put target Aura card
    from a graveyard onto the battlefield" (Iridescent Drake) lists both
    piles, each candidate with the seat whose pile it is."""
    sid, game = _session()
    game.players[0].graveyard.append(_CARDS["Holy Strength"])
    game.players[1].graveyard.append(_CARDS["Pacifism"])
    _enter(game, 0, "Iridescent Drake")

    prompt = _state(sid)["trigger_target"]

    assert prompt["card_name"] == "Iridescent Drake"
    assert sorted((c["kind"], c["seat"], c["name"]) for c in prompt["candidates"]) == [
        ("graveyard", 0, "Holy Strength"), ("graveyard", 1, "Pacifism"),
    ]
    assert "max_targets" not in prompt


# --- a graveyard pick is not a permanent --------------------------------------

@needs_node
def test_only_a_battlefield_slot_carries_a_permanent_id():
    answers = run_app_js(
        ["castTargetIsAPermanent"],
        "return INPUT.map((kind) => castTargetIsAPermanent(kind && { targetKind: kind }));",
        ["graveyard_creature", "creature", "permanent", "artifact", "land", None],
    )

    assert answers == [False, True, True, True, True, False]

    body = app_js_function_body("resolvePendingCastTarget")
    guard = body.index("if (castTargetIsAPermanent(pending)) {")
    stamp = body.index('paysCostWithPermanent ? "cost_permanent_id" : "target_permanent_id"')
    assert guard < stamp < body.index("}", stamp)


def test_a_graveyard_cast_with_no_permanent_id_is_the_cast_it_names():
    """The body the client now sends for a Resurrection at graveyard card 0 —
    a seat and a slot, no id — returns that card, with a permanent sitting in
    battlefield slot 0 of the same seat left alone."""
    sid, game = _session()
    bears = _enter(game, 0, "Grizzly Bears")
    game.players[0].graveyard.append(_CARDS["Hill Giant"])
    game.players[0].hand.append(_CARDS["Resurrection"])

    response = _act(
        sid, seat=0, action="cast", card_name="Resurrection",
        target_seat=0, permanent_index=0,
    )

    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears", "Hill Giant"]
    assert game.is_on_battlefield(bears)
    assert game.players[0].graveyard == [_CARDS["Resurrection"]]


# --- Torment: a division chosen with the targets, and an exact count ---------
#
# Two `trigger_target` fields wave 1 put on the wire with no client behind
# them: ``division_total`` (Shambling Swarm's "distribute three -1/-1 counters
# among one, two, or three target creatures", CR 601.2d) and
# ``exact_targets`` (Petradon's "exile two target lands", CR 601.2c). Measured
# cards, so they come from both manifest roles rather than the catalog.

_TOR: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _TOR.setdefault(_card.name, _card)


def _put(game, seat, name):
    permanent = Permanent(card=_TOR[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


@needs_node
def test_a_divided_trigger_is_answered_with_its_shares():
    """The dialog takes a share per chosen target, starts from an even split,
    holds its confirm while the shares do not total three, and sends
    ``divided_targets`` — a 1 and 2 split the id list could not say."""
    sid, game = _session()
    swarm = _put(game, 0, "Shambling Swarm")
    bears = _put(game, 1, "Grizzly Bears")
    giant = _put(game, 1, "Hill Giant")
    _put(game, 1, "Savannah Lions")
    game.place_pt_counters(swarm, "-1/-1", 3)
    game.check_state_based_actions()
    state = _state(sid)
    assert state["trigger_target"]["division_total"] == 3

    out = run_app_js(
        _DIALOG,
        """
        show();
        const subtitle = nodes.modalModeTargetsSubtitle.textContent;
        const box = nodes.modalModeTargetsDivision;
        nodes.modalModeTargetsList.tiles[0].click();
        nodes.modalModeTargetsList.tiles[1].click();
        const even = box.inputs.map((input) => input.value);
        box.inputs[0].set(1);
        const short = nodes.modalModeTargetsConfirmBtn.disabled;
        box.inputs[1].set(2);
        const whole = nodes.modalModeTargetsConfirmBtn.disabled;
        // A state arriving mid-edit keeps the inputs (and what was typed).
        show();
        const kept = box.inputs.map((input) => input.value);
        await nodes.modalModeTargetsConfirmBtn.onclick();
        return { subtitle, even, short, whole, kept, sent };
        """,
        {"state": state},
        prelude=_DOM,
    )

    assert out["subtitle"] == (
        "Shambling Swarm: its triggered ability names 1 to 3 targets. "
        "Divide 3 among the targets you choose; each gets at least 1."
    )
    assert out["even"] == ["2", "1"]
    assert (out["short"], out["whole"]) == (True, False)
    assert out["kept"] == ["1", "2"]
    assert out["sent"] == [{
        "seat": 0, "action": "trigger_target_confirm",
        "divided_targets": [
            {"seat": 1, "id": bears.permanent_id, "amount": 1},
            {"seat": 1, "id": giant.permanent_id, "amount": 2},
        ],
    }]
    response = client.post(f"/api/sessions/{sid}/action", json=out["sent"][0])
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert (counters_on(bears, "-1/-1"), counters_on(giant, "-1/-1")) == (1, 2)


@needs_node
def test_an_exact_trigger_count_holds_its_confirm_until_the_last_target():
    """"Exile two target lands": one land chosen is not an answer, so the
    confirm waits for the second — where the dialog's minimum of one offered
    a short answer the server refused."""
    sid, game = _session()
    _put(game, 0, "Swamp")
    lands = [_put(game, 1, name) for name in ("Forest", "Mountain", "Plains")]
    _put(game, 0, "Petradon")
    state = _state(sid)
    assert state["trigger_target"]["exact_targets"] is True

    out = run_app_js(
        _DIALOG,
        """
        show();
        const subtitle = nodes.modalModeTargetsSubtitle.textContent;
        const tiles = nodes.modalModeTargetsList.tiles;
        const ids = tiles.map((tile) => Number(tile.dataset.id));
        const none = nodes.modalModeTargetsConfirmBtn.disabled;
        tiles[ids.indexOf(INPUT.first)].click();
        const one = nodes.modalModeTargetsConfirmBtn.disabled;
        tiles[ids.indexOf(INPUT.second)].click();
        const two = nodes.modalModeTargetsConfirmBtn.disabled;
        await nodes.modalModeTargetsConfirmBtn.onclick();
        return { subtitle, none, one, two, sent };
        """,
        {"state": state, "first": lands[0].permanent_id, "second": lands[2].permanent_id},
        prelude=_DOM,
    )

    assert out["subtitle"] == "Petradon: its triggered ability names exactly 2 targets. Choose 2."
    assert (out["none"], out["one"], out["two"]) == (True, True, False)
    response = client.post(f"/api/sessions/{sid}/action", json=out["sent"][0])
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert sorted(card.name for card in game.players[1].exile) == ["Forest", "Plains"]
