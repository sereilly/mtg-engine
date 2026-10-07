"""The ability menu and the hand-ability buttons read the server's CR 602.5
prohibitions.

The engine refuses an activation the board forbids through one table
(``engine/activation_prohibitions.py``), and the wire has carried that table's
answer since it was written: ``ability_prohibitions`` on each of the viewer's
permanents, one entry per usable ability, and ``prohibited`` on a
``hand_abilities`` entry. The browser read neither. A Prodigal Sorcerer under
a Cursed Totem was offered its target prompt and the answer was a 400; a
cycling card under a City of Solitude on another player's turn was a button
that looked unaffordable.

Three things are held, in the order a click meets them:

* **the wire and the action agree** — over five boards, every ability the
  payload calls prohibited is refused by ``activate`` with that same sentence,
  and none it leaves clear is refused for a prohibition. The reader the client
  had (the ability's own line) is run over the same abilities and finds
  nothing, which is the census run backwards;
* **the client's readers, run in node over those payloads** —
  ``abilityProhibitionOf`` per ability, ``abilityProhibitionLines`` for the
  hover preview, ``handAbilityProhibition`` and the button
  ``renderHandAbilities`` builds;
* **where they are asked** — text-level, because the menu and the click are
  branches of DOM-bound functions: the menu's disabled reason asks the server
  first, and a single-ability permanent's click asks before any target or
  cost prompt.
"""
from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import app_js_function_body, run_app_js
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)

#: label -> (seat 0's battlefield, whose turn it is). Seat 0 has priority.
_BOARDS = {
    "a Cursed Totem": (
        ["Cursed Totem", "Prodigal Sorcerer", "Morphling", "Llanowar Elves", "Rod of Ruin"], 0,
    ),
    "a Null Rod": (["Null Rod", "Sol Ring", "Rod of Ruin", "Prodigal Sorcerer"], 0),
    "a City of Solitude on another player's turn": (
        ["City of Solitude", "Prodigal Sorcerer", "Rod of Ruin", "Morphling"], 1,
    ),
    "a City of Solitude on the player's own turn": (
        ["City of Solitude", "Prodigal Sorcerer", "Rod of Ruin", "Morphling"], 0,
    ),
    "nothing forbidding anything": (["Prodigal Sorcerer", "Rod of Ruin", "Morphling"], 0),
}


def _session(board, *, turn=0, hand=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4245,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.pregame_phase = None
    game.enforce_mana_costs = False
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    for name in board:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        permanent.tapped = False
    bears = Permanent(card=_CARDS["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].library = [_CARDS["Forest"]] * 5
    game.stack.clear()
    session.current_turn = turn
    game.active_player_index = turn
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _state(sid):
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


@pytest.fixture(scope="module")
def census():
    """Every usable ability on every board: what the wire says of it and what
    the action then does."""
    rows = []
    for label, (board, turn) in _BOARDS.items():
        sid, game = _session(board, turn=turn)
        payload = _state(sid)["players"][0]["battlefield"]
        for slot, permanent in enumerate(game.controlled_by(0)):
            entry = payload[slot]
            usable = game.usable_abilities_of(permanent, card=permanent.effective_card)
            listed = entry.get("ability_prohibitions") or [None] * len(usable)
            assert len(listed) == len(usable), (label, entry["name"])
            for index, ability in enumerate(usable):
                response = client.post(f"/api/sessions/{sid}/action", json={
                    "seat": 0, "action": "activate", "permanent_name": entry["name"],
                    "permanent_id": entry["id"], "ability_index": index,
                    "target_seat": 1,
                })
                refusal = (
                    response.json().get("detail") if response.status_code != 200 else None
                )
                rows.append({
                    "board": label, "name": entry["name"], "index": index,
                    "said": listed[index], "refusal": refusal,
                    "line": ability.source_line or "", "card": entry,
                })
                # Whatever was activated is taken back off the stack, so the
                # next ability meets the same board.
                game.stack.clear()
                for other in game.controlled_by(0):
                    other.tapped = False
                game.start_priority_window(0)
    return rows


def test_what_the_wire_calls_prohibited_the_action_refuses_in_the_same_words(census):
    prohibited = [row for row in census if row["said"]]

    assert len(prohibited) >= 15, len(prohibited)
    for row in prohibited:
        assert row["refusal"] == row["said"], row
    # …and the sentences are the engine's, naming what forbids the ability.
    assert {row["said"] for row in prohibited} >= {
        "Prodigal Sorcerer's activated abilities can't be activated (Cursed Totem)",
        "Sol Ring's activated abilities can't be activated (Null Rod)",
        "Prodigal Sorcerer's abilities can't be activated on another player's "
        "turn (City of Solitude)",
    }


def test_what_the_wire_leaves_clear_is_not_refused_for_a_prohibition(census):
    clear = [row for row in census if not row["said"]]

    assert len(clear) >= 15, len(clear)
    for row in clear:
        assert "can't be activated" not in str(row["refusal"] or ""), row
    # A Cursed Totem names creatures, a Null Rod artifacts: the other kind on
    # each board is clear, and so is everything on a board with neither.
    spared = {(row["board"], row["name"]) for row in clear}
    assert ("a Cursed Totem", "Rod of Ruin") in spared
    assert ("a Null Rod", "Prodigal Sorcerer") in spared
    assert ("a City of Solitude on the player's own turn", "Morphling") in spared


@needs_node
def test_the_client_reads_each_prohibition_off_the_payload(census):
    """``abilityProhibitionOf(card, index)`` for every ability of every board,
    over the payloads the server sent. A single-ability permanent is clicked
    with no index, which is its ability 0."""
    asked = [
        {"card": row["card"], "index": row["index"], "said": row["said"]}
        for row in census
    ]

    answers = run_app_js(
        ["abilityProhibitionOf", "abilityProhibitionLines"],
        """
        return INPUT.map((q) => ({
          byIndex: abilityProhibitionOf(q.card, q.index),
          bare: abilityProhibitionOf(q.card),
          lines: abilityProhibitionLines(q.card),
        }));
        """,
        asked,
    )

    for row, answer in zip(census, answers):
        assert answer["byIndex"] == row["said"], row
        first = (row["card"].get("ability_prohibitions") or [None])[0]
        assert answer["bare"] == first, row
        listed = [s for s in row["card"].get("ability_prohibitions") or [] if s]
        assert answer["lines"] == list(dict.fromkeys(listed)), row


@needs_node
def test_the_reader_the_menu_had_saw_none_of_them(census):
    """The census, backwards. The menu's disabled reason was a reading of the
    ability's own printed line (its timing clause, its hand-size rider). No
    line on these boards says "Cursed Totem": that reader is blind to every
    prohibited ability here, which is the defect — and why the server's answer
    is asked first."""
    prohibited = [row for row in census if row["said"]]

    blind = run_app_js(
        ["abilityLineDisabledReason"],
        "return INPUT.map((line) => abilityLineDisabledReason(line));",
        [row["line"] for row in prohibited],
        prelude=(
            "function getCurrentPlayerState() { return { hand: [], hand_count: 0 }; }\n"
            "function activationTimingDisabledReason() { return null; }\n"
        ),
    )

    assert blind == [None] * len(prohibited)


def test_the_menu_and_the_click_ask_the_server_first():
    reason = app_js_function_body("abilityOptionDisabledReason")
    assert reason.index("abilityProhibitionOf(card, opt?.index)") < reason.index(
        "abilityLineDisabledReason"
    )
    # The click that sends an option re-asks that one function, so a keyboard
    # route into a greyed-out button is refused too.
    assert "abilityOptionDisabledReason(opt, pending.card)" in app_js_function_body(
        "resolveAbilityChoice"
    )

    cascade = app_js_function_body("startActivationPrompt")
    asked = cascade.index("abilityProhibitionOf(card, abilityIndex)")
    for later in (
        "abilityHasNothingToChoose(card)", "cardRequiresHandCost(card)",
        "cardRequiresSeveralTargets(card)", "activatedAbilityRequiresTargetCreature(card)",
        "shouldPromptForActivationCost(activationCost)",
    ):
        assert asked < cascade.index(later), later

    # …and the reason is on the menu's face and in the hover preview, not only
    # in a tooltip a disabled button may never show.
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "ability-prohibition-note" in source
    assert "abilityProhibitionLines(card)" in app_js_function_body("showCardPreview")


# --- a hand ability ----------------------------------------------------------

_DOM = r'''
function element() {
  return {
    children: [], className: "", dataset: {}, disabled: false, title: "", textContent: "",
    classList: {
      list: new Set(),
      add(name) { this.list.add(name); },
      toggle(name, on) { if (on) this.list.add(name); else this.list.delete(name); },
    },
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    appendChild(child) { this.children.push(child); },
    set innerHTML(_value) { this.children = []; },
  };
}
const host = element();
const document = { createElement: () => element() };
function q(id) { return id === "handAbilities" ? host : null; }
let seat = 0;
let pendingAutoTap = null;
const sent = [];
function sendAction(body) { sent.push(body); return Promise.resolve(); }
function renderActivationPrompt() {}
function updateActionHint() {}
'''


@needs_node
def test_a_prohibited_hand_ability_is_a_dead_button_that_says_why():
    """A City of Solitude on another player's turn: the cycling button is
    disabled, marked, and carries the server's sentence — on the player's own
    turn it is an ordinary button whose click sends the activation."""
    buttons = {}
    for label, turn in (("theirs", 1), ("mine", 0)):
        sid, game = _session(
            ["City of Solitude", "Forest", "Forest"], turn=turn, hand=["Drifting Meadow"],
        )
        game.enforce_mana_costs = True
        state = _state(sid)
        (entry,) = state["hand_abilities"]
        buttons[label] = (sid, entry, run_app_js(
            ["handAbilityProhibition", "renderHandAbilities", "isManaRefusal"],
            """
            renderHandAbilities(INPUT, true);
            const button = host.children[0];
            const view = {
              text: button.textContent, title: button.title, disabled: button.disabled,
              marked: button.classList.list.has("is-prohibited"),
              said: handAbilityProhibition(INPUT.hand_abilities[0]),
            };
            if (!button.disabled) button.listeners.click();
            return { ...view, sent };
            """,
            state, prelude=_DOM,
        ))

    sid, entry, theirs = buttons["theirs"]
    sentence = (
        "Drifting Meadow's abilities can't be activated on another player's "
        "turn (City of Solitude)"
    )
    assert entry["prohibited"] == sentence and entry["payable"] is False
    assert theirs["disabled"] is True and theirs["marked"] is True
    assert theirs["title"] == sentence and theirs["said"] == sentence
    assert theirs["text"].endswith("Cycling {2}: Drifting Meadow")
    assert theirs["text"] != "Cycling {2}: Drifting Meadow"
    assert theirs["sent"] == []
    # The server agrees with the button it sent.
    refused = client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate_hand", "card_name": "Drifting Meadow",
        "hand_index": 0, "ability_index": 0,
    })
    assert refused.status_code == 400 and refused.json()["detail"] == sentence

    sid, entry, mine = buttons["mine"]
    assert entry["prohibited"] is None and entry["payable"] is True
    assert mine["disabled"] is False and mine["marked"] is False
    assert mine["said"] is None
    assert mine["text"] == "Cycling {2}: Drifting Meadow"
    assert mine["sent"] == [{
        "seat": 0, "action": "activate_hand", "card_name": "Drifting Meadow",
        "hand_index": 0, "ability_index": 0,
    }]
