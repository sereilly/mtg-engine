"""Champions of Kamigawa's Phase 5 closer: the two cards the browser agent
recorded failing, each a server half and a client half.

* **Commune with Nature's pick had no way out.** "Look at the top five cards
  of your library. You may reveal a creature card from among them and put it
  into your hand." The ``look_top_pick`` payload carried neither which cards
  the pick may take nor whether it may take none, though the engine knows both
  (``live_look_top_candidates``; the ``optional`` decline in
  ``_resolve_look_top_pick``). The dialog offered every card with no "take
  nothing", hid itself before the answer was checked, and the handler refused
  a decline ("hand_index … is required") — so a land clicked stranded the
  prompt with nothing on screen, and five noncreature cards on top had no
  answer at all. The payload now says ``legal_indices`` and ``optional``, the
  handler passes a decline to the resolver, and the dialog marks the cards it
  cannot take, offers the decline where the card prints "you may", and stays
  up until an answer is accepted. The family: Peer Through Depths, Ancestral
  Knowledge, Garruk's Harbinger; Impulse, which must take a card, still must.
* **Hankyu's aim ability asked for a creature.** "{T}: Put an aim counter on
  Hankyu" on the equipped creature names the Equipment, by the id
  ``bind_granter`` wrote (``on_granter_id``), and targets nothing — but the
  spec fell through to ``add_named_counter_to_target``'s kind row, a creature
  picker. The browser asked "Choose target", and the creature clicked was
  announced as targeted: Horobi, Death's Wail destroyed it. The spec now says
  ``none``, and an activated ability that targets nothing is never announced
  as targeting a stray permanent sent beside it. The neighbour, Hankyu's shot
  ("any target"), still targets — and Horobi still sees that.

Each payload is the server's own, read from a web session's state after the
engine armed it; each client function is the real source, lifted out of
``app.js`` by ``run_app_js``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.named_counters import counters_on
from web.app import app

from tests.helpers import (declare_attack, drive_combat, run_app_js,
                           seat_plays_first, settle)

client = TestClient(app)


def _card(set_pool, name: str):
    for code in ("CHK", "WTH", "M21", "VIS", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _session(seed: int = 7):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": seed,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    game = seat_plays_first(sid).game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.exile = []
    game.enforce_mana_costs = False
    game._sync_control()
    return sid, game


def _place(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _state(sid: str) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": 0})
    assert response.status_code == 200, response.text
    return response.json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})


def _names(cards) -> list[str]:
    return [card.name for card in cards]


# ---------------------------------------------------------------------------
# Commune with Nature and its shape — the wire
# ---------------------------------------------------------------------------

_NO_CREATURE = ["Forest", "Island", "Lightning Bolt", "Swamp", "Mountain", "Grizzly Bears"]


def _commune(set_pool, library):
    sid, game = _session()
    game.players[0].library = [_card(set_pool, name) for name in library]
    game.players[0].hand = [_card(set_pool, "Commune with Nature")]
    assert game.cast_from_hand(0, "Commune with Nature").supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "look_top_pick", owed
    return sid, game


def test_closer_commune_with_no_creature_on_top_can_take_nothing(set_pool):
    """Five noncreature cards on top: nothing may be taken, the payload says
    so, and taking nothing is an answer the server accepts — all five go to
    the bottom, and the sixth card is on top."""
    sid, game = _commune(set_pool, _NO_CREATURE)
    info = _state(sid)["look_top_pick"]
    assert info["optional"] is True
    assert info["legal_indices"] == []
    assert [card["name"] for card in info["cards"]] == _NO_CREATURE[:5]

    answered = _act(sid, action="look_top_pick_confirm")
    assert answered.status_code == 200, answered.text
    state = answered.json()
    assert state["look_top_pick"] is None
    assert any("took nothing" in line for line in state["log"]), state["log"][-5:]
    settle(game)
    assert game.players[0].hand == []
    library = _names(game.players[0].library)
    assert library[0] == "Grizzly Bears" and sorted(library[1:]) == sorted(_NO_CREATURE[:5])


def test_closer_commune_refuses_a_land_and_keeps_the_pick_open(set_pool):
    """One creature among the five: only it is offered. A land is refused
    with the prompt still owed (the dialog's answer is re-asked, never lost),
    and the creature is then taken."""
    library = ["Forest", "Grizzly Bears", "Island", "Lightning Bolt", "Swamp"]
    sid, game = _commune(set_pool, library)
    info = _state(sid)["look_top_pick"]
    assert info["legal_indices"] == [1] and info["optional"] is True

    refused = _act(sid, action="look_top_pick_confirm", hand_index=0)
    assert refused.status_code == 400
    assert "can't be taken" in refused.json()["detail"]
    assert _state(sid)["look_top_pick"] is not None

    taken = _act(sid, action="look_top_pick_confirm", hand_index=1)
    assert taken.status_code == 200, taken.text
    settle(game)
    assert _names(game.players[0].hand) == ["Grizzly Bears"]


def test_closer_impulse_must_still_take_a_card(set_pool):
    """The neighbour: Impulse prints no "may", so its payload is not optional,
    every card is offered, and a decline is refused with the prompt kept."""
    sid, game = _session()
    game.players[0].library = [
        _card(set_pool, name) for name in ("Forest", "Island", "Swamp", "Mountain", "Plains")
    ]
    game.players[0].hand = [_card(set_pool, "Impulse")]
    assert game.cast_from_hand(0, "Impulse").supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "look_top_pick", owed
    info = _state(sid)["look_top_pick"]
    assert info["optional"] is False
    assert info["legal_indices"] == [0, 1, 2, 3]

    refused = _act(sid, action="look_top_pick_confirm")
    assert refused.status_code == 400
    assert "not optional" in refused.json()["detail"]
    assert _state(sid)["look_top_pick"] is not None
    assert _act(sid, action="look_top_pick_confirm", hand_index=2).status_code == 200
    settle(game)
    assert _names(game.players[0].hand) == ["Swamp"]


def _arm_peer(set_pool):
    sid, game = _session()
    game.players[0].library = [
        _card(set_pool, name)
        for name in ("Forest", "Lightning Bolt", "Grizzly Bears", "Island", "Swamp")
    ]
    game.players[0].hand = [_card(set_pool, "Peer Through Depths")]
    assert game.cast_from_hand(0, "Peer Through Depths").supported
    return sid, game, [1], "hand"


def _arm_ancestral_knowledge(set_pool):
    sid, game = _session()
    game.players[0].library = [_card(set_pool, "Island")] * 4 + [
        _card(set_pool, "Grizzly Bears"),
    ] * 8
    game.players[0].hand = [_card(set_pool, "Ancestral Knowledge")]
    assert game.cast_from_hand(0, "Ancestral Knowledge").supported
    return sid, game, list(range(10)), "exile"


def _arm_harbinger(set_pool):
    sid, game = _session()
    game.players[0].library = [
        _card(set_pool, name) for name in ("Forest", "Grizzly Bears", "Island", "Swamp")
    ]
    _place(game, 0, _card(set_pool, "Garruk's Harbinger"))
    declare_attack(game, 0)
    return sid, game, [1], "hand"


@pytest.mark.parametrize("arm", [_arm_peer, _arm_ancestral_knowledge, _arm_harbinger],
                         ids=["peer_through_depths", "ancestral_knowledge", "garruks_harbinger"])
def test_closer_the_optional_look_and_pick_family_can_take_nothing(set_pool, arm):
    """Each optional look-and-pick sends its eligible cards and ``optional``,
    and its decline over the wire is accepted: nothing taken."""
    sid, game, legal, destination = arm(set_pool)
    if arm is _arm_harbinger:
        owed = drive_combat(game, through="combat_damage", defaults=False)
    else:
        owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "look_top_pick", owed
    info = _state(sid)["look_top_pick"]
    assert info["optional"] is True
    assert info["legal_indices"] == legal
    assert info["pick_destination"] == destination
    hand_before = len(game.players[0].hand)
    answered = _act(sid, action="look_top_pick_confirm")
    assert answered.status_code == 200, answered.text
    assert answered.json()["look_top_pick"] is None
    assert len(game.players[0].hand) == hand_before
    assert game.players[0].exile == []


# ---------------------------------------------------------------------------
# Commune with Nature — the dialog
# ---------------------------------------------------------------------------

_MODAL_PRELUDE = r"""
var seat = 0;
var SENT = [];
var REFUSE = null;
var HINTS = [];
var lookTopPickInFlight = false;
var lookTopPickRefusal = null;
var currentState = {players: [{name: "Host"}, {name: "AI"}]};
function makeEl(id) {
  const classes = new Set(id === "lookTopPickFooter" || id === "lookTopPickNote" ? ["hidden"] : []);
  const el = {
    id, textContent: "", disabled: false, _html: "", dataset: {}, onclick: null,
    _tiles: [],
    classList: {
      add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
      toggle(c, on) { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
      contains(c) { return classes.has(c); },
    },
    set innerHTML(v) {
      this._html = v;
      // The tiles the markup draws, each with its class and position, so a
      // click can be sent the way a person sends one.
      this._tiles = [...String(v).matchAll(/<div class="([^"]*)" data-idx="(\d+)">/g)].map((m) => ({
        cls: m[1], dataset: { idx: m[2] }, handlers: [],
        addEventListener(kind, fn) { if (kind === "click") this.handlers.push(fn); },
      }));
    },
    get innerHTML() { return this._html; },
    addEventListener() {}, querySelector() { return null; },
    querySelectorAll(sel) { return sel === ".library-card-choice" ? this._tiles : []; },
  };
  return el;
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
function updateActionHint(message) { HINTS.push(message); }
async function sendAction(body) {
  SENT.push(body);
  if (REFUSE) throw new Error(REFUSE);
}
function getLookTopPickInfo() { return INPUT.info; }
"""

_MODAL_FUNCTIONS = [
    "renderLookTopPickModal", "lookTopPickKey", "lookTopPickLegal",
    "lookTopPickDeclineLabel", "setLookTopPickNote", "answerLookTopPick",
]

_MODAL_DRIVE = """
const view = () => ({
  hidden: q("lookTopPickModal").classList.contains("hidden"),
  footerHidden: q("lookTopPickFooter").classList.contains("hidden"),
  decline: q("lookTopPickDecline").textContent,
  subtitle: q("lookTopPickSubtitle").textContent,
  note: q("lookTopPickNote").textContent,
  noteHidden: q("lookTopPickNote").classList.contains("hidden"),
  tiles: q("lookTopPickGrid")._tiles.map((t) => t.cls),
});
renderLookTopPickModal(INPUT.info);
const opened = view();
// A refused answer: the dialog stays, and says why.
REFUSE = INPUT.refusal;
const tiles = q("lookTopPickGrid")._tiles;
const illegal = tiles.findIndex((t) => t.cls.includes("illegal"));
if (illegal >= 0) await tiles[illegal].handlers[0]();
const afterIllegal = {...view(), sent: SENT.length};
const legal = tiles.findIndex((t) => !t.cls.includes("illegal"));
if (legal >= 0) await tiles[legal].handlers[0]();
const afterRefused = view();
// A re-render while the pick is still open keeps the refusal said.
renderLookTopPickModal(INPUT.info);
const rerendered = view();
REFUSE = null;
if (q("lookTopPickDecline").onclick) await q("lookTopPickDecline").onclick();
return {opened, afterIllegal, afterRefused, rerendered, sent: SENT, hints: HINTS};
"""


def test_closer_the_dialog_marks_what_the_pick_cannot_take_and_offers_nothing(set_pool):
    """Commune with Nature's dialog, on the server's payload: the noncreature
    cards are marked and a click on one sends nothing; a refused answer keeps
    the dialog up with the refusal in it, through a re-render; and "Take
    nothing" sends the decline — a body with no ``hand_index``."""
    library = ["Forest", "Grizzly Bears", "Island", "Lightning Bolt", "Swamp"]
    sid, _game = _commune(set_pool, library)
    info = _state(sid)["look_top_pick"]
    shown = run_app_js(_MODAL_FUNCTIONS, _MODAL_DRIVE,
                       {"info": info, "refusal": "that card can't be taken"},
                       prelude=_MODAL_PRELUDE)
    opened = shown["opened"]
    assert opened["hidden"] is False
    assert opened["tiles"] == [
        "library-card-choice illegal", "library-card-choice",
        "library-card-choice illegal", "library-card-choice illegal",
        "library-card-choice illegal",
    ]
    assert opened["footerHidden"] is False and opened["decline"] == "Take nothing"
    assert "a highlighted card" in opened["subtitle"]
    assert 'or choose "Take nothing"' in opened["subtitle"]
    # The marked card: refused here, nothing sent, the dialog still up.
    assert shown["afterIllegal"]["sent"] == 0
    assert shown["afterIllegal"]["hidden"] is False
    assert "can't take that card" in shown["afterIllegal"]["note"]
    # The server refusing an answer: the dialog stays, saying so.
    assert shown["afterRefused"]["hidden"] is False
    assert shown["afterRefused"]["note"] == "that card can't be taken"
    assert shown["afterRefused"]["noteHidden"] is False
    assert shown["rerendered"]["note"] == "that card can't be taken"
    assert shown["sent"] == [
        {"seat": 0, "action": "look_top_pick_confirm", "hand_index": 1},
        {"seat": 0, "action": "look_top_pick_confirm"},
    ]


def test_closer_the_dialog_with_nothing_takeable_still_has_an_answer(set_pool):
    """Five noncreature cards: every card marked, the sentence says none can be
    taken, and the decline is the one answer offered."""
    sid, _game = _commune(set_pool, _NO_CREATURE)
    info = _state(sid)["look_top_pick"]
    shown = run_app_js(_MODAL_FUNCTIONS, _MODAL_DRIVE, {"info": info, "refusal": None},
                       prelude=_MODAL_PRELUDE)
    assert all("illegal" in cls for cls in shown["opened"]["tiles"])
    assert "None of them can be taken" in shown["opened"]["subtitle"]
    assert shown["sent"] == [{"seat": 0, "action": "look_top_pick_confirm"}]


def test_closer_the_dialog_for_a_pick_that_must_take_a_card_is_unchanged(set_pool):
    """Impulse: every card offered, no footer, no decline."""
    sid, game = _session()
    game.players[0].library = [
        _card(set_pool, name) for name in ("Forest", "Island", "Swamp", "Mountain")
    ]
    game.players[0].hand = [_card(set_pool, "Impulse")]
    assert game.cast_from_hand(0, "Impulse").supported
    assert settle(game, defaults=False).kind == "look_top_pick"
    info = _state(sid)["look_top_pick"]
    shown = run_app_js(_MODAL_FUNCTIONS, _MODAL_DRIVE, {"info": info, "refusal": None},
                       prelude=_MODAL_PRELUDE)
    assert shown["opened"]["tiles"] == ["library-card-choice"] * 4
    assert shown["opened"]["footerHidden"] is True
    assert "take nothing" not in shown["opened"]["subtitle"].lower()
    assert shown["sent"] == [{"seat": 0, "action": "look_top_pick_confirm", "hand_index": 0}]


# ---------------------------------------------------------------------------
# Hankyu's aim ability
# ---------------------------------------------------------------------------


def _hankyu_board(set_pool):
    """Hankyu on seat 0's Grizzly Bears; Horobi and a Craw Wurm across the
    table, Horobi put there after the equip (whose target it would destroy)."""
    sid, game = _session()
    hankyu = _place(game, 0, _card(set_pool, "Hankyu"))
    bears = _place(game, 0, _card(set_pool, "Grizzly Bears"))
    wurm = _place(game, 1, _card(set_pool, "Craw Wurm"))
    slot = game.players[0].battlefield.index(hankyu)
    assert game.activate_permanent_ability(
        0, "Hankyu", permanent_index=slot, target_permanent_ids=[bears.permanent_id],
    ).supported
    settle(game)
    assert hankyu.metadata.get("attached_to") is bears
    horobi = _place(game, 1, _card(set_pool, "Horobi, Death's Wail"))
    return sid, game, hankyu, bears, wurm, horobi


def _bears_payload(state: dict) -> dict:
    return next(
        perm for perm in state["players"][0]["battlefield"] if perm["name"] == "Grizzly Bears"
    )


def test_closer_hankyu_aim_ability_asks_for_no_target(set_pool):
    """The aim ability's spec is "none", so the browser opens no picker; the
    shot beside it still asks for any target."""
    sid, _game, _hankyu, _bears, _wurm, _horobi = _hankyu_board(set_pool)
    specs = _bears_payload(_state(sid))["ability_target_specs"]
    assert specs[0]["kind"] == "none"
    assert not specs[0].get("valid_targets")
    assert specs[1]["kind"] == "any" and specs[1].get("requires_target", True)


def test_closer_hankyu_aim_destroys_nothing_under_horobi(set_pool):
    """Activated as the browser now sends it (no target), and with a stray
    creature sent beside it as the old picker did, the counter goes on Hankyu
    and Horobi destroys nobody: the aim ability targets nothing (CR 115.1c)."""
    sid, game, hankyu, bears, wurm, horobi = _hankyu_board(set_pool)

    def aim(**extra):
        bears.tapped = False
        game.priority_player_index = 0
        slot = game.players[0].battlefield.index(bears)
        response = _act(sid, action="activate", permanent_index=slot, ability_index=0, **extra)
        assert response.status_code == 200, response.text
        settle(game)

    aim()
    assert counters_on(hankyu, "aim") == 1
    aim(target_permanent_id=wurm.permanent_id, target_seat=1)
    assert counters_on(hankyu, "aim") == 2
    assert game.is_on_battlefield(wurm) and game.is_on_battlefield(bears)
    assert not any("Horobi, Death's Wail destroyed" in line for line in game.log)


def test_closer_hankyu_shot_still_targets_and_horobi_sees_it(set_pool):
    """The neighbour: the shot names "any target", so the Wurm it is aimed at
    becomes a target — Horobi destroys it before the shot resolves."""
    sid, game, hankyu, bears, wurm, horobi = _hankyu_board(set_pool)
    bears.tapped = False
    game.priority_player_index = 0
    slot = game.players[0].battlefield.index(bears)
    assert _act(sid, action="activate", permanent_index=slot, ability_index=0).status_code == 200
    settle(game)
    bears.tapped = False
    game.priority_player_index = 0
    shot = _act(sid, action="activate", permanent_index=slot, ability_index=1,
                target_permanent_id=wurm.permanent_id, target_seat=1)
    assert shot.status_code == 200, shot.text
    settle(game)
    assert counters_on(hankyu, "aim") == 0
    assert not game.is_on_battlefield(wurm)
    assert any("Horobi, Death's Wail destroyed Craw Wurm" in line for line in game.log)
