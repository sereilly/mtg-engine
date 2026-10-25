"""Balance's three rounds, answered through the browser's own code.

kg/layers made Balance three successive ``balance`` prompts — lands, then cards
in hand, then creatures, each counted on the board the last one left, seats
asked one at a time from the active player — with ``balance_select.stage`` and
an ``id`` per entry, and left the client untouched. Each round here is the
served payload handed to the client's functions in node (the board half,
``balanceBoardTargeting``; the hand half, ``toggleBalanceHandSelection``; the
panel and its Confirm, ``applyBalanceSelectPrompt``), and the body the Confirm
sends is the body posted for the next round.

The board is the one each round owes something on, and on which the first and
the last round differ: the caster's animated Mishra's Factory is offered with
the lands in the first round and, kept, is a creature in the last — so the
opponent's three creatures are cut to two, not one.

What the client got wrong, now fixed: the panel said "Choose Sacrifices" and
"click your lands and creatures" in the hand round; a pick made in one round
was not dropped by a new one unless the Confirm had cleared it; and a refused
Confirm lost the picks into an unhandled rejection with no reason shown.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack, run_app_js
from web.app import app, store

client = TestClient(app)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _session(by_name, mode: str):
    """Seat 0 (active): Mishra's Factory, animated, and four Plains; a
    Grizzly Bears; Balance and two more cards in hand. Seat 1: two Islands;
    Hill Giant, Grizzly Bears, Wall of Wood; four cards in hand."""
    created = client.post("/api/sessions", json={
        "mode": mode, "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 5151,
    }).json()
    sid = created["session_id"]
    if mode == "human_vs_human":
        client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False

    def put(name, seat):
        perm = _nosick(Permanent(card=by_name[name]))
        game._put_permanent_onto_battlefield(seat, perm, None)
        _nosick(perm)
        return perm

    game.players[0].battlefield = []
    game.players[1].battlefield = []
    factory = put("Mishra's Factory", 0)
    plains = [put("Plains", 0) for _ in range(4)]
    put("Grizzly Bears", 0)
    put("Island", 1)
    put("Island", 1)
    put("Hill Giant", 1)
    put("Grizzly Bears", 1)
    wall = put("Wall of Wood", 1)
    game._recompute_continuous_effects()
    game.players[0].hand = [by_name["Balance"], by_name["Forest"], by_name["Swamp"]]
    game.players[1].hand = [by_name[n] for n in ("Island", "Mountain", "Hill Giant", "Shock")]
    session.current_turn = 0
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    result = game.activate_permanent_ability(
        0, "Mishra's Factory", permanent_index=game.battlefield_index_of(factory), ability_index=1,
    )
    assert result.supported, result
    resolve_stack(game)
    game._recompute_continuous_effects()
    assert factory.is_creature and factory.has_type("land")
    game.cast_from_hand(0, "Balance")
    return sid, game, factory, plains, wall


_PRELUDE = r'''
let seat = INPUT.seat;
let currentState = INPUT.state;
let balanceSelection = { lands: [], creatures: [], hand: [] };
const sent = [];
const hints = [];
const elements = {};
function fakeElement(id) {
  return {
    id, textContent: "", innerHTML: "", disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener(_type, fn) { this.listener = fn; },
  };
}
function q(id) { return elements[id] || (elements[id] = fakeElement(id)); }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
function sendAction(body) {
  sent.push(body);
  return INPUT.refuse ? Promise.reject(new Error("invalid balance selection")) : Promise.resolve();
}
function updateActionHint(text) { hints.push(text); }
function refreshPromptSelection() {}
'''

_FUNCTIONS = [
    "getBalanceSelectInfo", "balanceBoardTargeting", "promptTargeting",
    "toggleBalanceHandSelection", "balanceRoundText", "applyBalanceSelectPrompt",
]

_BODY = r'''
const info = getBalanceSelectInfo(INPUT.state);
if (!info) return { info: null };
const targeting = balanceBoardTargeting(INPUT.state, info);
for (const [s, idx] of INPUT.permanents) targeting.onPermanent(s, idx);
for (const h of INPUT.hand) toggleBalanceHandSelection(h);
applyBalanceSelectPrompt(info);
const shown = {
  title: q("promptTitle").textContent,
  body: q("promptBody").textContent,
  ready: !q("promptSteps").innerHTML.includes(" disabled"),
};
await q("balanceConfirmBtn").listener();
return {
  stage: info.stage, keys: [...targeting.permanentKeys].sort(), shown, sent, hints,
  kept: balanceSelection,
};
'''


def _answer(sid, seat, *, permanents=(), hand=(), refuse=False):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    out = run_app_js(
        _FUNCTIONS, _BODY,
        {"state": state, "seat": seat, "permanents": list(permanents),
         "hand": list(hand), "refuse": refuse},
        prelude=_PRELUDE,
    )
    return state["balance_select"], out


def _post(sid, out):
    (body,) = out["sent"]
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_three_rounds_two_seats_each_answered_by_the_client(by_name):
    sid, game, factory, plains, wall = _session(by_name, "human_vs_human")

    # Round 1, lands: the caster keeps the Factory and one Plains.
    info, out = _answer(sid, 0, permanents=[
        (0, game.battlefield_index_of(p)) for p in plains[1:]
    ])
    assert out["stage"] == "lands" and info["lands_to_sacrifice"] == 3
    assert out["shown"]["title"] == "Balance — Lands (1 of 3)" and out["shown"]["ready"]
    assert out["keys"] == sorted(f"0-{e['index']}" for e in info["lands"])
    assert f"0-{game.battlefield_index_of(factory)}" in out["keys"], "the Factory is a land here"
    assert sorted(out["sent"][0]["land_indices"]) == sorted(
        game.battlefield_index_of(p) for p in plains[1:]
    )
    assert _post(sid, out).status_code == 200
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Mishra's Factory", "Plains",
    ]

    # The caster owes nothing in the hand round; its client shows no prompt.
    assert _answer(sid, 0)[1] == {"info": None}

    # Round 2, cards in hand: four against two, the guest discards two.
    info, out = _answer(sid, 1, hand=[0, 3])
    assert out["stage"] == "hand" and info["cards_to_discard"] == 2
    assert out["shown"]["title"] == "Balance — Cards in Hand (2 of 3)" and out["keys"] == []
    assert "discard" in out["shown"]["body"] and "sacrifice" not in out["shown"]["body"]
    assert out["sent"][0]["discard_indices"] == [0, 3]
    assert _post(sid, out).status_code == 200
    assert sorted(c.name for c in game.players[1].graveyard) == ["Island", "Shock"]

    # Round 3, creatures: the kept Factory is a creature now, so the guest's
    # three are cut to two — one sacrifice, not two.
    info, out = _answer(sid, 1, permanents=[(1, game.battlefield_index_of(wall))])
    assert out["stage"] == "creatures" and info["creatures_to_sacrifice"] == 1
    assert out["shown"]["title"] == "Balance — Creatures (3 of 3)"
    assert out["sent"][0]["creature_indices"] == [game.battlefield_index_of(wall)]
    assert _post(sid, out).status_code == 200
    assert client.get(f"/api/sessions/{sid}/state", params={"seat": 1}).json()["balance_select"] is None
    assert sorted(p.card.name for p in game.controlled_by(1)) == [
        "Grizzly Bears", "Hill Giant", "Island", "Island",
    ]
    assert game.is_on_battlefield(factory)


def test_against_the_ai_the_human_answers_its_round_and_the_ai_the_rest(by_name):
    sid, game, factory, plains, wall = _session(by_name, "human_vs_ai")
    _info, out = _answer(sid, 0, permanents=[
        (0, game.battlefield_index_of(p)) for p in plains[1:]
    ])
    assert out["stage"] == "lands"
    assert _post(sid, out).status_code == 200
    # The AI's hand and creature rounds are answered by its defaults on the
    # way out of the same request; the spell is done.
    assert client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["balance_select"] is None
    assert not game.stack
    assert len(game.players[1].hand) == 2
    assert len([p for p in game.controlled_by(1) if p.is_creature]) == 2


def test_a_refused_confirm_keeps_the_picks_and_says_why(by_name):
    sid, game, _factory, plains, _wall = _session(by_name, "human_vs_human")
    picks = [(0, game.battlefield_index_of(p)) for p in plains[1:]]
    _info, out = _answer(sid, 0, permanents=picks, refuse=True)
    assert out["hints"] == ["invalid balance selection"]
    assert sorted(out["kept"]["lands"]) == sorted(idx for _seat, idx in picks)
