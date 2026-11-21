"""Champions of Kamigawa's prompts and gestures as a person meets them (CHK
wave 2, the client group, W2G1).

Every one of these was clicked in a browser first, on a session with the set
promoted (``MTG_PROMOTE=CHK``; the report says what was clicked); this file
holds what the clicks found. Each payload is the server's own, read from a web
session's state after the engine armed it; each client function is the real
source, lifted out of ``app.js`` (or ``battlefield-canvas.js``) by
``run_app_js``.

Champions of Kamigawa is a measured set until it is promoted, so no deck the
web app deals holds one of its cards: each test puts the cards it names onto a
session's board from ``set_pool``, which works on either manifest role.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.flip_cards import flip_permanent
from engine.models import Permanent
from web.app import app

from tests.helpers import run_app_js, seat_plays_first, settle

client = TestClient(app)

#: The sets the cards below are first printed in, searched in this order.
_W2G1_SETS = ("CHK", "LEA", "MIR", "TMP", "5DN", "DST", "MRD", "ONS", "M21")


def _w2g1_card(set_pool, name: str):
    for code in _W2G1_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g1_session(seed: int = 7):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": seed,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = seat_plays_first(sid)
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
    game._sync_control()
    return sid, game


def _w2g1_place(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w2g1_state(sid: str, seat: int = 0) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _w2g1_on_board(state: dict, seat: int, permanent_id: int) -> dict:
    return next(
        entry for entry in state["players"][seat]["battlefield"]
        if entry["id"] == permanent_id
    )


# ---------------------------------------------------------------------------
# Flip cards (CR 710): the marker, and the viewer's two halves
# ---------------------------------------------------------------------------

_W2G1_FLIP_PRELUDE = """
function escapeHtml(value) { return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
function renderSymbolsInline(text) { return escapeHtml(text); }
"""


def test_w2g1_a_flipped_permanent_is_marked_and_its_viewer_shows_both_halves(set_pool):
    """CR 710.3: whether a permanent is flipped is clear at all times. The
    canvas marks exactly the flipped Jushi Apprentice (`_isFlipped`: the art
    turned and a FLIPPED ribbon); the viewer names the half that applies —
    Tomoya the Revealer for the flipped one, Jushi Apprentice for the one that
    has not flipped and for the card in hand (CR 710.2) — and prints the other
    half upside down."""
    sid, game = _w2g1_session()
    jushi = _w2g1_card(set_pool, "Jushi Apprentice")
    flipped = _w2g1_place(game, 0, jushi)
    unflipped = _w2g1_place(game, 0, jushi)
    game.players[0].hand = [jushi]
    assert flip_permanent(game, flipped)
    game._recompute_continuous_effects()
    state = _w2g1_state(sid)
    payloads = [
        _w2g1_on_board(state, 0, flipped.permanent_id),
        _w2g1_on_board(state, 0, unflipped.permanent_id),
        state["players"][0]["hand"][0],
    ]
    assert [entry["name"] for entry in payloads] == [
        "Tomoya the Revealer", "Jushi Apprentice", "Jushi Apprentice",
    ]
    seen = run_app_js(
        ["_isFlipped", "flipPreviewHalves", "flipPreviewLead", "flipPreviewInactiveHtml"],
        """
        return INPUT.map((card) => {
          const halves = flipPreviewHalves(card);
          return {
            marked: _isFlipped(card),
            active: halves.active.name,
            inactive: halves.inactive.name,
            lead: flipPreviewLead(halves),
            upsideDown: flipPreviewInactiveHtml(halves.inactive),
          };
        });
        """,
        payloads,
        prelude=_W2G1_FLIP_PRELUDE,
        scripts=("battlefield-canvas.js", "app.js"),
    )
    assert [(row["marked"], row["active"], row["inactive"]) for row in seen] == [
        (True, "Tomoya the Revealer", "Jushi Apprentice"),
        (False, "Jushi Apprentice", "Tomoya the Revealer"),
        (False, "Jushi Apprentice", "Tomoya the Revealer"),
    ]
    assert seen[0]["lead"].startswith("⇅ Flipped")
    assert "not flipped" in seen[1]["lead"]
    assert "off the battlefield" in seen[2]["lead"]
    assert 'class="preview-flip-inactive"' in seen[0]["upsideDown"]
    assert "Jushi Apprentice 1/2" in seen[0]["upsideDown"]
    assert "Tomoya the Revealer 2/3" in seen[1]["upsideDown"]


def test_w2g1_a_card_with_one_half_has_no_flip_viewer(set_pool):
    """A card printing one half carries no `flip`, and the viewer adds nothing
    for it — nor for a bare name."""
    sid, game = _w2g1_session()
    bears = _w2g1_place(game, 0, _w2g1_card(set_pool, "Grizzly Bears"))
    state = _w2g1_state(sid)
    payload = _w2g1_on_board(state, 0, bears.permanent_id)
    assert "flip" not in payload and payload["flipped"] is False
    seen = run_app_js(
        ["_isFlipped", "flipPreviewHalves"],
        "return [flipPreviewHalves(INPUT), flipPreviewHalves('Grizzly Bears'), _isFlipped(INPUT)];",
        payload,
        scripts=("battlefield-canvas.js", "app.js"),
    )
    assert seen == [None, None, False]


# ---------------------------------------------------------------------------
# Splice onto Arcane (CR 702.47): the cast-time choice, its targets, the stack
# ---------------------------------------------------------------------------

#: What the splice functions reach for that touches the page, as stubs.
_W2G1_SPLICE_PRELUDE = """
var seat = 0;
var currentState = null;
var pendingModalChoice = null;
var pendingSpliceCollection = null;
var pendingCastSplice = null;
var pendingCastFromZone = null;
var hints = [];
var opened = [];
var continued = [];
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
function renderActivationPrompt() {}
function updateActionHint(text) { hints.push(text); }
function escapeHtml(value) { return String(value ?? ""); }
function renderSymbolsInline(value) { return String(value ?? ""); }
function normalizeCardName(card) { return typeof card === "string" ? card : (card && card.name) || ""; }
function getCurrentPlayerState(state) { return state && state.players ? state.players[seat] : null; }
function findPermanentInState(state, pid) {
  for (const [s, player] of (state.players || []).entries()) {
    const at = (player.battlefield || []).findIndex((c) => c && c.id === pid);
    if (at >= 0) return { seat: s, index: at, card: player.battlefield[at] };
  }
  return null;
}
function permanentIdAt(s, i) {
  const c = currentState && currentState.players && currentState.players[s]
    && currentState.players[s].battlefield[i];
  return c && Number.isInteger(c.id) ? c.id : null;
}
// The ordinary picker: opened for a spliced text's spec that names a target,
// as the real cascade is; the spell's own targets are the cast going on.
function startCastTargetCascade(card) {
  const spec = card.target_spec || {};
  if (card.spliced_from && spec.kind && spec.kind !== "none") {
    opened.push([card.name, card.spliced_from, spec.kind]);
    return true;
  }
  return false;
}
function continueCastAfterCost(card, castAction) { continued.push([card.name, castAction]); }
"""


def _w2g1_splice_board(set_pool, *, creatures: bool = True):
    sid, game = _w2g1_session()
    game.players[0].hand = [
        _w2g1_card(set_pool, name)
        for name in ("Reach Through Mists", "Glacial Ray", "Kodama's Might",
                     "Soulless Revival", "Desperate Ritual")
    ]
    game.players[0].graveyard = [_w2g1_card(set_pool, "Grizzly Bears"),
                                 _w2g1_card(set_pool, "Shock")]
    bears = _w2g1_place(game, 1, _w2g1_card(set_pool, "Grizzly Bears")) if creatures else None
    game._recompute_continuous_effects()
    return sid, game, bears


def test_w2g1_the_splice_prompt_offers_each_card_and_greys_the_one_with_no_target(set_pool):
    """"Splice onto Reach Through Mists?" lists every card the server offers,
    in hand order; with no creature anywhere Kodama's Might has nothing to
    target (CR 702.47b) and is greyed, read off its spec; the order picked is
    the order the texts happen, and the confirm says so — or casts the spell
    alone when nothing is picked. A zone cast, a cast whose question is
    answered and a card nothing may be spliced onto are not asked."""
    sid, game, _ = _w2g1_splice_board(set_pool, creatures=False)
    state = _w2g1_state(sid)
    host = state["players"][0]["hand"][0]
    assert [o["name"] for o in host["splice_offers"]] == [
        "Glacial Ray", "Kodama's Might", "Soulless Revival", "Desperate Ritual",
    ]
    seen = run_app_js(
        ["castSpliceOffers", "spliceOfferRefusal", "startCastSplicePrompt", "spliceOfferCard",
         "spliceChoiceView", "toggleSpliceChoice"],
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        const opened = startCastSplicePrompt(host, "cast");
        const before = spliceChoiceView(pendingModalChoice);
        toggleSpliceChoice(1);      // Kodama's Might: refused, nothing picked
        toggleSpliceChoice(3);      // Desperate Ritual first
        toggleSpliceChoice(0);      // then Glacial Ray
        const after = spliceChoiceView(pendingModalChoice);
        pendingModalChoice = null;
        pendingCastFromZone = "graveyard";
        const zone = startCastSplicePrompt(host, "cast");
        pendingCastFromZone = null;
        pendingCastSplice = {cardName: host.name, cards: []};
        const again = startCastSplicePrompt(host, "cast");
        pendingCastSplice = null;
        const plain = startCastSplicePrompt({name: "Shock", target_spec: {kind: "any"}}, "cast");
        return {opened, before, after, zone, again, plain, hints};
        """,
        {"state": state},
        prelude=_W2G1_SPLICE_PRELUDE,
    )
    assert seen["opened"] is True
    assert seen["before"]["title"] == "Splice onto Reach Through Mists?"
    assert seen["before"]["confirm"] == "Cast Reach Through Mists without splicing"
    assert [(b["label"], b["disabled"]) for b in seen["before"]["buttons"]] == [
        ("Glacial Ray — splice {1}{R}", False),
        ("Kodama's Might — splice {G} (no legal target)", True),
        ("Soulless Revival — splice {1}{B}", False),
        ("Desperate Ritual — splice {1}{R}", False),
    ]
    # Each button repeats the text it would add, never its splice line.
    assert seen["before"]["buttons"][0]["text"] == "Glacial Ray deals 2 damage to any target."
    assert [(b["label"], b["on"]) for b in seen["after"]["buttons"]][::3] == [
        ("2. Glacial Ray — splice {1}{R}", True), ("1. Desperate Ritual — splice {1}{R}", True),
    ]
    assert seen["after"]["confirm"] == "Splice Desperate Ritual, then Glacial Ray and cast"
    assert any(
        "can't be spliced onto Reach Through Mists: no legal target" in hint for hint in seen["hints"]
    )
    assert (seen["zone"], seen["again"], seen["plain"]) == (False, False, False)


def test_w2g1_the_spliced_texts_targets_are_collected_then_the_spell_goes_on(set_pool):
    """The confirm walks the picked cards in order: a text that targets
    nothing (Desperate Ritual) is recorded at once, one that does opens the
    picker on its own spec, and the body that picker sends is captured as its
    target rather than sent. Past the last, the announcement is kept and the
    spell's own cast goes on — a tick later, after the last picker's `.then`."""
    sid, game, bears = _w2g1_splice_board(set_pool)
    state = _w2g1_state(sid)
    seen = run_app_js(
        ["castSpliceOffers", "spliceOfferRefusal", "startCastSplicePrompt", "spliceOfferCard",
         "toggleSpliceChoice", "confirmSpliceChoice", "spliceTargetCard",
         "promptNextSpliceTarget", "finishSpliceCollection", "spliceEntryFromBody",
         "captureSpliceTarget"],
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        startCastSplicePrompt(host, "cast");
        toggleSpliceChoice(3);   // Desperate Ritual: no target
        toggleSpliceChoice(0);   // Glacial Ray: any target
        toggleSpliceChoice(2);   // Soulless Revival: a graveyard card
        confirmSpliceChoice();
        const afterConfirm = {opened: opened.slice(), cursor: pendingSpliceCollection.cursor};
        const tap = captureSpliceTarget({action: "tap", permanent_id: 1});
        const ray = captureSpliceTarget({seat: 0, action: "cast", card_name: host.name,
          target_seat: 1, permanent_index: 0, target_permanent_id: INPUT.bears});
        const revival = captureSpliceTarget({seat: 0, action: "cast", card_name: host.name,
          target_seat: 0, target_permanent_indices: [0]});
        const atFinish = {done: pendingSpliceCollection.done, cast: pendingCastSplice,
                          continued: continued.slice()};
        await new Promise((resolve) => setTimeout(resolve, 5));
        return {afterConfirm, tap, ray, revival, atFinish, opened,
                continued, collection: pendingSpliceCollection, cast: pendingCastSplice};
        """,
        {"state": state, "bears": bears.permanent_id},
        prelude=_W2G1_SPLICE_PRELUDE,
    )
    assert seen["afterConfirm"] == {
        "opened": [["Reach Through Mists", "Glacial Ray", "any"]], "cursor": 1,
    }
    assert (seen["tap"], seen["ray"], seen["revival"]) == (False, True, True)
    expected = [
        {"hand_index": 4},
        {"hand_index": 1, "target_seat": 1, "permanent_id": bears.permanent_id},
        {"hand_index": 3, "target_seat": 0, "graveyard_indices": [0]},
    ]
    assert seen["atFinish"] == {
        "done": True, "continued": [],
        "cast": {"cardName": "Reach Through Mists", "cards": expected},
    }
    assert seen["opened"][1] == ["Reach Through Mists", "Soulless Revival", "graveyard_creature"]
    assert seen["continued"] == [["Reach Through Mists", "cast"]]
    assert seen["collection"] is None and seen["cast"]["cards"] == expected


def test_w2g1_the_announcement_the_client_builds_is_the_cast_the_server_performs(set_pool):
    """`carrySpliceCards` puts the collected `splice_cards` on the spell's cast
    body (and the caller's, for an auto-tap retry) and on nothing else; that
    body, sent as the client sends it, performs every gained text in order:
    Desperate Ritual's mana, Glacial Ray's 2 damage to the Bears, Soulless
    Revival's return — the spliced cards still in hand (CR 702.47a)."""
    sid, game, bears = _w2g1_splice_board(set_pool)
    game.enforce_mana_costs = False
    cards = [
        {"hand_index": 4},
        {"hand_index": 1, "target_seat": 1, "permanent_id": bears.permanent_id},
        {"hand_index": 3, "target_seat": 0, "graveyard_indices": [0]},
    ]
    built = run_app_js(
        ["carrySpliceCards"],
        """
        pendingCastSplice = {cardName: "Reach Through Mists", cards: INPUT.cards};
        const actionBody = {seat: 0, action: "cast", card_name: "Reach Through Mists", target_seat: 1};
        const body = carrySpliceCards({...actionBody}, actionBody);
        return {
          body, actionBody,
          other: carrySpliceCards({action: "cast", card_name: "Glacial Ray"}),
          activate: carrySpliceCards({action: "activate", card_name: "Reach Through Mists"}),
        };
        """,
        {"cards": cards},
        prelude=_W2G1_SPLICE_PRELUDE,
    )
    assert built["body"]["splice_cards"] == cards
    assert built["actionBody"]["splice_cards"] == cards
    assert "splice_cards" not in built["other"] and "splice_cards" not in built["activate"]

    sent = client.post(f"/api/sessions/{sid}/action", json=built["body"])
    assert sent.status_code == 200, sent.text
    settle(game)
    hand = [c.name for c in game.players[0].hand]
    assert "Grizzly Bears" in hand, game.log[-8:]
    assert {"Glacial Ray", "Soulless Revival", "Desperate Ritual"} <= set(hand)
    assert bears not in game.players[1].battlefield, game.log[-8:]
    assert game.players[0].mana_pool["R"] >= 3, game.players[0].mana_pool


def test_w2g1_the_stack_shows_what_was_spliced_onto_a_spell(set_pool):
    """The stack item's `spliced` reaches the hover preview — each card's
    name, the text it added and its targets by name — in the order the texts
    happen; a spell with nothing spliced adds nothing."""
    sid, game, bears = _w2g1_splice_board(set_pool)
    game.enforce_mana_costs = False
    game.queue_from_hand(0, "Reach Through Mists", splice_cards=[
        {"hand_index": 2, "target_permanent_ids": [bears.permanent_id]},
        {"hand_index": 1, "target_player_index": 1},
    ])
    state = _w2g1_state(sid)
    item = state["stack"][0]
    assert [entry["name"] for entry in item["spliced"]] == ["Kodama's Might", "Glacial Ray"]
    sections = run_app_js(
        ["stackItemPreviewCard", "stackTargetLabel", "splicedPreviewSections"],
        """
        currentState = INPUT.state;
        return [splicedPreviewSections(stackItemPreviewCard(INPUT.item)),
                splicedPreviewSections(stackItemPreviewCard({card: {name: "Shock"}, spliced: []}))];
        """,
        {"state": state, "item": item},
        prelude=_W2G1_SPLICE_PRELUDE,
    )
    assert len(sections[0]) == 2 and sections[1] == []
    assert "1. Spliced: <b>Kodama's Might</b>" in sections[0][0]
    assert "→ Grizzly Bears" in sections[0][0]
    assert "2. Spliced: <b>Glacial Ray</b>" in sections[0][1]
    assert "→ " + state["players"][1]["name"] in sections[0][1]


# ---------------------------------------------------------------------------
# Masako the Humorless: a tapped creature declared as a blocker
# ---------------------------------------------------------------------------


def test_w2g1_a_tapped_creature_masako_lets_block_is_offered_and_declarable(set_pool):
    """CR 509.1a waived by Masako: the server's `legal_blocker_assignments`
    pairs the tapped Craw Wurm with the attacker (it asked `blocker.tapped`
    where every other gate asks `_tapped_out_of_blocking`, so the client was
    sent no pairing to draw), the permanent says `can_block_while_tapped`, and
    the client's drag gate (`blockAssignmentRejectionReason`) accepts the
    pairing. Without Masako the same tapped Wurm is refused by both."""
    sid, game = _w2g1_session()
    masako = _w2g1_place(game, 0, _w2g1_card(set_pool, "Masako the Humorless"))
    wurm = _w2g1_place(game, 0, _w2g1_card(set_pool, "Craw Wurm"))
    wurm.tapped = True
    _w2g1_place(game, 1, _w2g1_card(set_pool, "Hill Giant"))
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(1, [0], defending_player_index=0)
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    wurm_slot = game.players[0].battlefield.index(wurm)

    def asked():
        state = _w2g1_state(sid)
        verdict = run_app_js(
            ["getCombatState", "getValidBlockerAssignments", "isCombatStep",
             "blockAssignmentRejectionReason"],
            "return blockAssignmentRejectionReason(INPUT.state, INPUT.blocker, 0);",
            {"state": state, "blocker": game.players[0].battlefield.index(wurm)},
            prelude="var seat = 0; var currentState = null; var combatBlockerDraft = {};"
            " function iDeclareBlocks() { return true; }",
        )
        pairs = {
            (pair["blocker_index"], pair["attacker_index"])
            for pair in state["combat"]["legal_blocker_assignments"]
        }
        entry = _w2g1_on_board(state, 0, wurm.permanent_id)
        return pairs, entry["can_block_while_tapped"], verdict

    pairs, may, verdict = asked()
    assert (wurm_slot, 0) in pairs and may is True and verdict == ""

    game.players[0].battlefield.remove(masako)
    game._sync_control()
    pairs, may, verdict = asked()
    assert not any(blocker == game.players[0].battlefield.index(wurm) for blocker, _ in pairs)
    assert may is False and verdict == "Craw Wurm is tapped and can't block."
