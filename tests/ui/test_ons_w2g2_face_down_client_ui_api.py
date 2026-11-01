"""Onslaught's client round, part A (W2G2): morph, face-down cards, and a
library's revealed top card — the halves that can be held without a browser.

Every branch here was **clicked** in the running app on a human-vs-human
table, both seats in their own tab, with each seat's state read after each
click (the round's report names the screenshots). These tests hold the rest:
the real client functions, lifted by name out of ``web/static`` and run in
node (``tests.helpers.run_app_js``) against the payload the server really sent
each seat, and the body a click builds posted back to the one action route.

* **Turning a morph face up** (CR 702.37e, a CR 116.2b special action):
  ``SPECIAL_ACTION_LABELS.turn_face_up`` names the hidden card and the server's
  ``morph_cost``; the button's body turns it up and the server pays.
* **A face-down permanent and spell, for both seats** (CR 708.5): drawn from
  what arrived — the controller's ``hidden_card`` shows the real card marked
  face down, anyone else gets a back, and nothing of the card is in their
  payload to draw.
* **``face_down_look``** (Aven Soulgazer): the looker's prompt, read and
  dismissed.
* **The top of a library** (Future Sight, Conspicuous Snoop, Radha): the
  revealed card (``library_top``) or the owner's private look
  (``library_top_private``) on the pile, and the cast from it carrying the
  card's cast spec (``castable_from_zones[].card``).

The Onslaught cards are put into the session by hand: Onslaught is a measured
set on this branch, so the catalog a session deals from does not hold them.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from engine.face_down import face_down_card
from engine.models import Permanent
from tests.helpers import resolve_stack, run_app_js
from web.app import app, store
from web.runtime import CARD_BY_NAME
from web.state_view import build_state

client = TestClient(app)

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"
#: The page loads the canvas before ``app.js``; the face-down and library-top
#: readers live in the canvas file and ``app.js`` calls them.
PAGE = ("battlefield-canvas.js", "app.js")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node is not on PATH; the client half cannot run",
)


def _table(seed: int):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "Alice", "guest_name": "Bob",
              "host_colors": 2, "guest_colors": 2, "seed": seed},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Bob"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    game.interactive_seats = set()
    for player in game.players:
        player.hand[:] = []
        player.graveyard[:] = []
    game.remove_all_from_battlefield(list(game.all_permanents()))
    game.stack.clear()
    game.active_player_index = session.current_turn = 0
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    game.priority_player_index = 0
    return sid, session, game


def _put(game, seat: int, card, *, face_down: bool = False) -> Permanent:
    permanent = Permanent(card=face_down_card(card) if face_down else card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    game._recompute_continuous_effects()
    return permanent


def _lands(game, seat: int, name: str, count: int) -> None:
    for _ in range(count):
        _put(game, seat, CARD_BY_NAME[name.casefold()])


def _act(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


# ---------------------------------------------------------------------------
# 1. Turning a morph face up — the special action's label and its body
# ---------------------------------------------------------------------------

def test_the_special_action_labels_name_turn_face_up():
    """``renderSpecialActions`` drops a kind with no label; the morph's one is
    there, and the label is handed the entry (the morph cost rides on it)."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    labels = re.search(r"\nconst SPECIAL_ACTION_LABELS = \{.*?\n\};", js, re.S).group(0)
    assert re.search(r"\bturn_face_up:\s*\(name, entry\) => turnFaceUpActionLabel\(entry\)", labels)
    render = re.search(r"\nfunction renderSpecialActions\(.*?\n\}\n", js, re.S).group(0)
    assert "label(entry.name, entry)" in render


@needs_node
def test_a_face_down_angel_turns_up_from_its_button(set_pool):
    ons = set_pool("ONS")
    sid, session, game = _table(seed=701)
    _lands(game, 0, "Plains", 4)
    angel = _put(game, 0, ons["Exalted Angel"], face_down=True)

    mine = build_state(session, 0)
    (entry,) = [e for e in mine["special_actions"] if e["kind"] == "turn_face_up"]
    assert entry["morph_cost"] == "{2}{W}{W}" and entry["name"] == "Face-down creature"
    assert [e for e in build_state(session, 1)["special_actions"] if e["kind"] == "turn_face_up"] == []

    built = run_app_js(
        ["turnFaceUpActionLabel", "turnFaceUpHiddenName", "sendSpecialAction"],
        "return { label: turnFaceUpActionLabel(INPUT.entry), body: await sendSpecialAction(INPUT.entry) };",
        {"entry": entry, "state": mine},
        prelude="let seat = 0; let currentState = INPUT.state; const sendAction = async (body) => body;",
        scripts=PAGE,
    )
    assert built["label"] == "Turn Exalted Angel face up — Morph {2}{W}{W}"
    assert built["body"]["permanent_id"] == angel.permanent_id

    response = _act(sid, {key: value for key, value in built["body"].items() if value is not None})
    assert response.status_code == 200, response.text
    assert angel.card.name == "Exalted Angel"
    assert sum(p.tapped for p in game.players[0].battlefield if p.has_type("land")) == 4
    theirs = build_state(session, 1)["players"][0]["battlefield"]
    (seen,) = [p for p in theirs if p["id"] == angel.permanent_id]
    assert (seen["name"], seen["face_down"]) == ("Exalted Angel", False)


# ---------------------------------------------------------------------------
# 2. A face-down permanent and spell, drawn for each seat (CR 708.5)
# ---------------------------------------------------------------------------

_DISPLAY = """
const out = {};
for (const [who, perm] of Object.entries(INPUT.perms)) {
  const shown = faceDownDisplayCard(perm);
  const preview = faceDownPreviewCard(perm);
  out[who] = {
    name: shown.name, view: shown.face_down_view, image: shown.image_uri,
    pt: [shown.power, shown.toughness],
    preview: preview.name, previewImage: preview.large_image_uri,
    lines: faceDownPreviewLines(preview),
  };
}
return out;
"""


@needs_node
def test_a_face_down_permanent_is_drawn_from_what_each_seat_was_sent(set_pool):
    ons = set_pool("ONS")
    _sid, session, game = _table(seed=702)
    _put(game, 1, ons["Ixidor, Reality Sculptor"])
    colossus = _put(game, 0, ons["Krosan Colossus"], face_down=True)

    mine = build_state(session, 0)
    theirs = build_state(session, 1)
    assert "Krosan Colossus" not in json.dumps(theirs), "nothing of it reaches the opponent"
    pick = lambda state: next(p for p in state["players"][0]["battlefield"] if p["id"] == colossus.permanent_id)  # noqa: E731
    seen = run_app_js(
        ["faceDownDisplayCard", "faceDownPreviewCard", "faceDownPreviewLines"],
        _DISPLAY,
        {"perms": {"controller": pick(mine), "opponent": pick(theirs)}},
        prelude='const BF_CARD_BACK_URL = "/images/card_back.webp"; const faceDownLookMemory = new Map();',
        scripts=PAGE,
    )
    controller, opponent = seen["controller"], seen["opponent"]
    # Its controller: the real card, marked — at the face-down 2/2's own P/T,
    # here 3/3 under the opponent's Ixidor (a face-down creature's P/T is the
    # 2/2's, CR 708.2a; "Face-down creatures get +1/+1" counts).
    assert (controller["name"], controller["view"], controller["pt"]) == ("Krosan Colossus", "controller", [3, 3])
    assert controller["image"] and "card_back" not in controller["image"]
    assert controller["preview"] == "Krosan Colossus" and controller["previewImage"]
    assert any("only you can see" in line for line in controller["lines"])
    assert any("Morph {6}{G}{G}" in line for line in controller["lines"])
    # The opponent: a back, the 3/3 it is, and no name, text or image.
    assert (opponent["name"], opponent["view"], opponent["pt"]) == ("", "hidden", [3, 3])
    assert opponent["image"] == "/images/card_back.webp"
    assert opponent["preview"] == "Face-down creature" and opponent["previewImage"] is None
    assert opponent["lines"] == [
        "Face down: a 3/3 creature with no name, text, subtypes or mana cost (CR 708.2a)."
    ]


@needs_node
def test_a_face_down_spell_on_the_stack_is_drawn_from_what_each_seat_was_sent(set_pool):
    ons = set_pool("ONS")
    _sid, session, game = _table(seed=703)
    game.enforce_mana_costs = False
    game.players[0].hand[:] = [ons["Silent Specter"]]
    assert game.queue_from_hand(0, "Silent Specter", alternative_cost=True).supported

    mine = build_state(session, 0)["stack"][0]
    theirs = build_state(session, 1)["stack"][0]
    assert "Silent Specter" not in json.dumps(build_state(session, 1))
    # The cascade draws, and its hover previews, the card the canvas copied
    # the item's face-down fields onto (`faceDownStackItem`).
    seen = run_app_js(
        ["faceDownStackItem", "faceDownDisplayCard", "faceDownPreviewCard"],
        "return INPUT.items.map((item) => { const c = faceDownStackItem(item).card;"
        " const shown = faceDownDisplayCard(c);"
        " return [c.face_down, shown.name, shown.face_down_view, faceDownPreviewCard(c).name]; });",
        {"items": [mine, theirs]},
        prelude='const BF_CARD_BACK_URL = "/images/card_back.webp";',
        scripts=PAGE,
    )
    assert seen == [
        [True, "Silent Specter", "controller", "Silent Specter"],
        [True, "", "hidden", "Face-down creature"],
    ]

    # It resolves into a face-down permanent, and leaving the battlefield
    # reveals it (CR 708.9): the graveyard holds the real card for both seats.
    resolve_stack(game)
    (specter,) = [p for p in game.players[0].battlefield if p.is_creature]
    game.sacrifice_permanent(specter)
    for viewer in (0, 1):
        assert [c["name"] for c in build_state(session, viewer)["players"][0]["graveyard"]] == ["Silent Specter"]


# ---------------------------------------------------------------------------
# 3. face_down_look — Aven Soulgazer
# ---------------------------------------------------------------------------

@needs_node
def test_the_look_is_read_by_the_looker_alone_and_dismissed(set_pool):
    ons = set_pool("ONS")
    sid, session, game = _table(seed=704)
    game.enforce_mana_costs = False
    _put(game, 0, ons["Aven Soulgazer"])
    hidden = _put(game, 1, ons["Grinning Demon"], face_down=True)
    result = game.activate_permanent_ability(
        0, "Aven Soulgazer", target_player_index=1,
        target_permanent_ids=[hidden.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)

    looker, owner = build_state(session, 0), build_state(session, 1)
    board = next(p for p in looker["players"][1]["battlefield"] if p["id"] == hidden.permanent_id)
    read = run_app_js(
        ["getFaceDownLookInfo", "faceDownLookCaption", "rememberFaceDownLook",
         "faceDownPreviewCard", "faceDownPreviewLines"],
        "seat = 0; const mine = getFaceDownLookInfo(INPUT.looker);"
        " const caption = faceDownLookCaption(mine.permanents[0], INPUT.looker);"
        " const before = faceDownPreviewLines(faceDownPreviewCard(INPUT.board));"
        " rememberFaceDownLook(mine);"
        " const after = faceDownPreviewLines(faceDownPreviewCard(INPUT.board));"
        " const other = faceDownPreviewLines(faceDownPreviewCard({ ...INPUT.board, id: -1 }));"
        " seat = 1; return { mine, caption, before, after, other, theirs: getFaceDownLookInfo(INPUT.owner) };",
        {"looker": looker, "owner": owner, "board": board},
        prelude="let seat = 0; let currentState = null; const faceDownLookMemory = new Map();",
        scripts=PAGE,
    )
    # The board still shows an anonymous 2/2; once looked at, its preview
    # names the card — that permanent's, by id, and no other face-down one's.
    assert not any("You looked at it" in line for line in read["before"] + read["other"])
    assert "You looked at it: Grinning Demon." in read["after"]
    (entry,) = read["mine"]["permanents"]
    assert (entry["id"], entry["card"]["name"]) == (hidden.permanent_id, "Grinning Demon")
    assert read["caption"] == "Bob's face-down creature"
    assert read["theirs"] is None and owner["face_down_look"] is None

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    render = re.search(r"\nfunction renderFaceDownLookModal\(.*?\n\}\n", js, re.S).group(0)
    assert 'sendAction({ seat, action: "dismiss_face_down_look" })' in render
    response = _act(sid, {"seat": 0, "action": "dismiss_face_down_look"})
    assert response.status_code == 200, response.text
    assert build_state(session, 0)["face_down_look"] is None


# ---------------------------------------------------------------------------
# 4. The top of a library — Future Sight, Radha, Conspicuous Snoop
# ---------------------------------------------------------------------------

_PILE = """
const shown = libraryTopCardShown(INPUT.state.players[0]);
const out = {
  shown: shown && [shown.name, shown.library_top_view],
  entry: libraryTopCastEntry(INPUT.state),
};
libraryPileClicked({ seat: 0, kind: "library" });
out.begun = globalThis.__begun || null;
return out;
"""

_PILE_PRELUDE = """
let seat = INPUT.seat;
let currentState = INPUT.state;
let pendingCastTarget = null;
let pendingCastHandCard = null;
const hints = [];
const updateActionHint = (text) => hints.push(text);
const showCardPreview = () => {};
function beginZoneCast(card, zone, entry) {
  globalThis.__begun = { name: card.name, zone, spec: !!card.target_spec, index: entry && entry.index };
}
"""


def _pile(state: dict, seat: int) -> dict:
    return run_app_js(
        ["libraryTopCardShown", "libraryTopCastEntry", "libraryPileClicked"],
        _PILE,
        {"state": state, "seat": seat},
        prelude=_PILE_PRELUDE,
        scripts=PAGE,
    )


@needs_node
def test_future_sight_draws_the_top_card_and_casts_shock_off_it(set_pool):
    ons = set_pool("ONS")
    sid, session, game = _table(seed=705)
    _put(game, 0, ons["Future Sight"])
    _lands(game, 0, "Mountain", 2)
    game.players[0].library.insert(0, ons["Shock"])

    mine, theirs = build_state(session, 0), build_state(session, 1)
    clicked = _pile(mine, 0)
    assert clicked["shown"] == ["Shock", "revealed"]
    assert clicked["entry"]["card"]["name"] == "Shock" and clicked["entry"]["card"]["target_spec"]
    assert clicked["begun"] == {"name": "Shock", "zone": "library", "spec": True, "index": 0}
    # The opponent sees the revealed card on the pile and casts nothing off it.
    watched = _pile(theirs, 1)
    assert watched["shown"] == ["Shock", "revealed"]
    assert watched["entry"] is None and watched["begun"] is None

    response = _act(sid, {"seat": 0, "action": "cast", "card_name": "Shock",
                          "from_zone": "library", "target_seat": 1, "auto_tap": True})
    assert response.status_code == 200, response.text
    resolve_stack(game)
    assert game.players[1].life == 18
    assert [card.name for card in game.players[0].graveyard] == ["Shock"]


@needs_node
def test_radha_shows_the_top_card_to_its_owner_alone_and_snoop_reveals_it(set_pool):
    m21 = set_pool("M21")
    ons = set_pool("ONS")
    _sid, session, game = _table(seed=706)
    _put(game, 0, m21["Radha, Heart of Keld"])
    game.players[0].library.insert(0, ons["Goblin Taskmaster"])

    mine, theirs = build_state(session, 0), build_state(session, 1)
    assert mine["players"][0]["library_top"] is None
    assert mine["players"][0]["library_top_private"]["name"] == "Goblin Taskmaster"
    assert theirs["players"][0]["library_top"] is None
    assert theirs["players"][0]["library_top_private"] is None
    assert "Goblin Taskmaster" not in json.dumps(theirs)
    looked = _pile(mine, 0)
    assert looked["shown"] == ["Goblin Taskmaster", "private"]
    assert looked["begun"] is None, "Radha plays lands from the top, and this is no land"

    # "Play with the top card of your library revealed": public now, so the
    # card moves to `library_top` for both seats and the private key empties.
    _put(game, 0, m21["Conspicuous Snoop"])
    mine, theirs = build_state(session, 0), build_state(session, 1)
    assert mine["players"][0]["library_top_private"] is None
    for state in (mine, theirs):
        assert state["players"][0]["library_top"]["name"] == "Goblin Taskmaster"
    revealed = _pile(mine, 0)
    assert revealed["shown"] == ["Goblin Taskmaster", "revealed"]
    assert revealed["begun"]["name"] == "Goblin Taskmaster", "a Goblin spell, cast from the top"


# ---------------------------------------------------------------------------
# 5. The face-down cast offer says what it costs
# ---------------------------------------------------------------------------

@needs_node
def test_the_morph_offer_owes_its_three_once(set_pool):
    """The hand card's offer is "cast it face down … for {3}" with ``mana_owed``
    "{3}": the whole price, so the note says it as the whole, never "plus
    {3}" — which read as a {6} face-down cast."""
    ons = set_pool("ONS")
    _sid, session, game = _table(seed=707)
    _lands(game, 0, "Forest", 3)
    game.players[0].hand[:] = [ons["Krosan Colossus"]]
    (offer,) = [
        o for o in build_state(session, 0)["players"][0]["hand"][0]["target_spec"]["cost_offers"]
        if o["kind"] == "alternative"
    ]
    assert (offer["label"], offer["mana_owed"]) == ("cast it face down as a 2/2 creature for {3}", "{3}")
    note = run_app_js(
        ["alternativeOfferOwedNote"],
        "return alternativeOfferOwedNote(INPUT.offer);",
        {"offer": offer},
        prelude="const renderSymbolsInline = (text) => text;",
    )
    assert "plus" not in note and "{3} in mana in all" in note


# ---------------------------------------------------------------------------
# 6. A notification closes while a reorder is owed (Spy Network)
# ---------------------------------------------------------------------------

def test_spy_networks_looks_close_while_its_reorders_are_open(set_pool):
    """Spy Network arms the hand look, the face-down look and two library
    reorders. The reorders block; the looks are notifications, and their
    Continue buttons were refused ("complete library reorder before other
    actions") for as long as a reorder stood — clicked in the browser, the
    modal hid on the 400 and came back on the next render. Each closes now,
    and the reorder is still owed after it."""
    ons = set_pool("ONS")
    sid, session, game = _table(seed=708)
    _lands(game, 0, "Island", 1)
    hidden = _put(game, 1, ons["Silent Specter"], face_down=True)
    game.players[1].hand[:] = [CARD_BY_NAME["swamp"]]
    game.players[0].hand[:] = [ons["Spy Network"]]
    response = _act(sid, {"seat": 0, "action": "cast", "card_name": "Spy Network",
                          "target_seat": 1, "auto_tap": True})
    assert response.status_code == 200, response.text
    for seat in (0, 1):
        assert _act(sid, {"seat": seat, "action": "pass_priority"}).status_code == 200

    state = build_state(session, 0)
    assert state["hand_reveal"] and state["reorder_library"] and state["waiting_on_prompt"]
    assert _act(sid, {"seat": 0, "action": "dismiss_hand_reveal"}).status_code == 200
    assert build_state(session, 0)["hand_reveal"] is None
    assert build_state(session, 0)["reorder_library"], "the reorder is still owed"
    # Something else is still refused while it is.
    assert _act(sid, {"seat": 0, "action": "pass_priority"}).status_code == 400

    # Bob's top card, then the look at his face-down creature beside Alice's
    # own top-four reorder.
    assert _act(sid, {"seat": 0, "action": "reorder_library_confirm", "card_order": [0]}).status_code == 200
    state = build_state(session, 0)
    assert [p["id"] for p in state["face_down_look"]["permanents"]] == [hidden.permanent_id]
    assert state["reorder_library"]
    assert _act(sid, {"seat": 0, "action": "dismiss_face_down_look"}).status_code == 200
    state = build_state(session, 0)
    assert state["face_down_look"] is None and state["reorder_library"]
