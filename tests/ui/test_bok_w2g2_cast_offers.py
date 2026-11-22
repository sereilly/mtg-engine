"""Betrayers of Kamigawa's cast-time offers as a person meets them (BOK
wave 2, the client group W2G2): a splice cost that is not mana, offering, the
Shoals' pitched X, a target bounded by the announced X and an X paid in
counters.

Every one of these was clicked in a browser first, on a session with the set
promoted (``MTG_PROMOTE=BOK``; the report says what was clicked); this file
holds what the clicks found. Each payload is the server's own, read from a web
session's state; each client function is the real source, lifted out of
``app.js`` by ``run_app_js``. Where the client builds a body, the body is then
sent over HTTP and the board read back, so the announcement the client makes is
the cast the server performs.

Betrayers of Kamigawa is a measured set until it is promoted, so no deck the web
app deals holds one of its cards: each test puts the cards it names onto a
session's board, from ``set_pool``, which works on either manifest role.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.named_counters import add_counters
from web.app import app, store
from web.state_view import build_card_target_spec

from tests.helpers import run_app_js, seat_plays_first, settle

client = TestClient(app)


def _w2g2_card(set_pool, name: str):
    """The card named *name*: Betrayers of Kamigawa's first, then each set of
    the manifest in printing order (the shipped role and the measured one)."""
    from engine.card_loader import manifest_measured_sets, manifest_sets

    codes = ["BOK"] + [
        entry["code"] for entry in (*manifest_sets(), *manifest_measured_sets())
        if entry["code"] != "BOK"
    ]
    for code in codes:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g2_session(set_pool, *, mine=(), theirs=(), hand=(), graveyard=(), seed: int = 7):
    """A human-vs-AI session, seat 0 in its precombat main phase with the
    stack empty, its board, hand and graveyard replaced by the cards named.
    Returns ``(sid, game, mine, theirs)`` — the permanents placed, in order."""
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
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        row = []
        for name in names:
            permanent = Permanent(card=_w2g2_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            row.append(permanent)
        placed.append(row)
    game.players[0].hand = [_w2g2_card(set_pool, name) for name in hand]
    game.players[0].graveyard = [_w2g2_card(set_pool, name) for name in graveyard]
    game._sync_control()
    game._recompute_continuous_effects()
    return sid, game, placed[0], placed[1]


def _w2g2_state(sid: str, seat: int = 0) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _w2g2_hand(state: dict, name: str) -> dict:
    return next(card for card in state["players"][0]["hand"] if card["name"] == name)


def _w2g2_act(sid: str, body: dict):
    return client.post(f"/api/sessions/{sid}/action", json=body)


# ---------------------------------------------------------------------------
# Splice onto Arcane with a cost that is not mana (CR 702.47a)
# ---------------------------------------------------------------------------

_W2G2_SPLICE_PRELUDE = """
var seat = 0;
var currentState = null;
var pendingModalChoice = null;
var pendingSpliceCollection = null;
var pendingCastSplice = null;
var pendingCastFromZone = null;
var hints = [];
var opened = [];
var continued = [];
var renders = 0;
const _CAST_ACTIONS = new Set(["cast", "debug_cast_free", "debug_cast_free_opponent"]);
function renderActivationPrompt() { renders += 1; }
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

_W2G2_SPLICE_FUNCTIONS = [
    "castSpliceOffers", "spliceOfferRefusal", "startCastSplicePrompt", "spliceOfferCard",
    "spliceChoiceView", "toggleSpliceChoice", "confirmSpliceChoice", "spliceTargetCard",
    "promptNextSpliceTarget", "finishSpliceCollection", "spliceEntryFromBody",
    "captureSpliceTarget", "carrySpliceCards", "spliceCostWords", "splicePriceRefusal",
    "splicePriceAsks", "splicePayersOf", "splicePayersTakenElsewhere", "prefillSplicePayers",
    "toggleSplicePayer", "splicePaymentRows", "splicePaymentRowsHtml", "splicePaymentFields",
]


def _w2g2_splice_board(set_pool, *, graveyard=("Island", "Lightning Bolt", "Mountain")):
    return _w2g2_session(
        set_pool,
        mine=("Savannah Lions", "White Knight", "Merfolk of the Pearl Trident",
              "Mountain", "Mountain", "Mountain", "Island", "Swamp", "Forest"),
        theirs=("Hill Giant", "Grizzly Bears"),
        hand=("Glacial Ray", "Hundred-Talon Strike", "Hundred-Talon Strike",
              "Horobi's Whisper", "Torrent of Stone", "Veil of Secrecy", "Roar of Jukai"),
        graveyard=graveyard,
    )


def test_w2g2_the_splice_prompt_says_each_price_and_greys_one_the_board_cannot_pay(set_pool):
    """A splice cost that is not mana is said in words, never "{0}"; Horobi's
    Whisper with three cards in the graveyard is greyed with the server's
    reason (CR 601.2h), its "can't be spliced onto" head dropped; Veil of
    Secrecy's price names the colour its payer must be."""
    sid, _game, _mine, _theirs = _w2g2_splice_board(set_pool)
    state = _w2g2_state(sid)
    host = _w2g2_hand(state, "Glacial Ray")
    seen = run_app_js(
        _W2G2_SPLICE_FUNCTIONS,
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        startCastSplicePrompt(host, "cast");
        return spliceChoiceView(pendingModalChoice);
        """,
        {"state": state},
        prelude=_W2G2_SPLICE_PRELUDE,
    )
    labels = [(button["label"], button["disabled"]) for button in seen["buttons"]]
    assert labels[0] == ("Hundred-Talon Strike — splice: tap an untapped white creature you control", False)
    whisper_label, whisper_disabled = labels[2]
    assert whisper_disabled is True
    assert whisper_label.startswith("Horobi's Whisper — splice: exile 4 cards from your graveyard (")
    assert "can't be spliced onto" not in whisper_label and "3 card" in whisper_label
    assert labels[3] == ("Torrent of Stone — splice: sacrifice 2 Mountains", False)
    assert labels[4] == (
        "Veil of Secrecy — splice: return a blue creature you control to its owner's hand", False,
    )
    assert labels[5] == ("Roar of Jukai — splice: have an opponent gain 5 life", False)
    # Nothing picked: nothing owed, the confirm casts the spell alone.
    assert seen["payRows"] == [] and seen["ready"] is True
    assert {offer["name"] for offer in host["splice_offers"]} >= {"Veil of Secrecy"}


def test_w2g2_a_picked_price_asks_its_payers_one_permanent_paying_one_splice(set_pool):
    """Picking a priced card opens its payment row; the confirm waits for the
    printed count; a permanent named for one Hundred-Talon Strike is greyed
    for the other, and a half whose free candidates are exactly its count
    (Veil's one blue creature, the second Strike's last white creature) is
    named at once. Unpicking a card frees its payers."""
    sid, _game, mine, _theirs = _w2g2_splice_board(set_pool)
    lions, knight, merfolk = mine[0].permanent_id, mine[1].permanent_id, mine[2].permanent_id
    mountains = [perm.permanent_id for perm in mine[3:6]]
    state = _w2g2_state(sid)
    seen = run_app_js(
        _W2G2_SPLICE_FUNCTIONS,
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        startCastSplicePrompt(host, "cast");
        toggleSpliceChoice(0);                       // the first Strike: two white creatures
        const strikeOpen = spliceChoiceView(pendingModalChoice);
        confirmSpliceChoice();                       // refused: nothing named yet
        const heldOpen = pendingModalChoice !== null;
        toggleSplicePayer(0, "permanent", INPUT.lions);
        toggleSpliceChoice(1);                       // the second Strike: one white creature left
        const twoStrikes = spliceChoiceView(pendingModalChoice);
        toggleSplicePayer(1, "permanent", INPUT.lions);   // greyed: Lions pays the first
        const stillKnight = pendingModalChoice.splicePayers[1].permanent.slice();
        toggleSpliceChoice(1);                       // unpicked: the Knight is free again
        const freed = spliceChoiceView(pendingModalChoice);
        toggleSpliceChoice(3);                       // Torrent of Stone: three Mountains for two
        toggleSplicePayer(3, "permanent", INPUT.mountains[0]);
        toggleSplicePayer(3, "permanent", INPUT.mountains[2]);
        toggleSplicePayer(3, "permanent", INPUT.mountains[1]);   // a third is not taken
        toggleSpliceChoice(4);                       // Veil: its one blue creature, named at once
        const ready = spliceChoiceView(pendingModalChoice);
        return {strikeOpen, heldOpen, twoStrikes, stillKnight, freed, ready, hints,
                payers: pendingModalChoice.splicePayers};
        """,
        {"state": state, "lions": lions, "mountains": mountains},
        prelude=_W2G2_SPLICE_PRELUDE,
    )
    row = seen["strikeOpen"]["payRows"][0]
    assert row["short"] is True and seen["strikeOpen"]["ready"] is False
    assert [button["label"] for button in row["buttons"]] == ["Tap Savannah Lions", "Tap White Knight"]
    assert seen["heldOpen"] is True
    assert any("Choose what pays Hundred-Talon Strike" in hint for hint in seen["hints"])
    second = [r for r in seen["twoStrikes"]["payRows"] if r["index"] == 1][0]
    assert [(b["label"], b["on"], b["disabled"]) for b in second["buttons"]] == [
        ("Tap Savannah Lions", False, True), ("Tap White Knight", True, False),
    ]
    assert seen["stillKnight"] == [knight]
    assert all(not b["disabled"] for r in seen["freed"]["payRows"] for b in r["buttons"])
    assert seen["payers"]["3"]["permanent"] == [mountains[0], mountains[2]]
    assert seen["payers"]["4"]["permanent"] == [merfolk]
    assert seen["ready"]["ready"] is True


def test_w2g2_the_named_payers_ride_the_splice_choice_and_the_server_takes_them(set_pool):
    """The confirm records each chosen card's payers on its splice choice
    (`cost_permanent_ids`, `cost_graveyard_indices`), the targets are
    collected as before, and the cast the client builds is the one the server
    performs: the named white creature is tapped (not the other), the named
    Mountains are sacrificed (not the third), the four named graveyard cards
    are exiled, and the opponent gains 5."""
    sid, game, mine, theirs = _w2g2_splice_board(
        set_pool, graveyard=("Island", "Lightning Bolt", "Mountain", "Giant Growth", "Shock"),
    )
    game.enforce_mana_costs = False
    lions, knight = mine[0], mine[1]
    mountains = mine[3:6]
    giant, bears = theirs
    state = _w2g2_state(sid)
    seen = run_app_js(
        _W2G2_SPLICE_FUNCTIONS,
        """
        currentState = INPUT.state;
        const host = INPUT.state.players[0].hand[0];
        startCastSplicePrompt(host, "cast");
        toggleSpliceChoice(0);                                    // Hundred-Talon Strike
        toggleSplicePayer(0, "permanent", INPUT.knight);
        toggleSpliceChoice(2);                                    // Horobi's Whisper
        for (const slot of [4, 0, 1, 3]) toggleSplicePayer(2, "graveyard", slot);
        toggleSpliceChoice(3);                                    // Torrent of Stone
        toggleSplicePayer(3, "permanent", INPUT.mountains[1]);
        toggleSplicePayer(3, "permanent", INPUT.mountains[2]);
        toggleSpliceChoice(5);                                    // Roar of Jukai
        confirmSpliceChoice();
        captureSpliceTarget({seat: 0, action: "cast", card_name: host.name,
          target_seat: 0, target_permanent_id: INPUT.lions});        // Strike: Lions
        captureSpliceTarget({seat: 0, action: "cast", card_name: host.name,
          target_seat: 1, target_permanent_id: INPUT.giant});        // Whisper: the Giant
        captureSpliceTarget({seat: 0, action: "cast", card_name: host.name,
          target_seat: 1, target_permanent_id: INPUT.bears});        // Torrent: the Bears
        await new Promise((resolve) => setTimeout(resolve, 5));
        const body = carrySpliceCards({seat: 0, action: "cast", card_name: host.name,
          target_seat: 1, permanent_id: INPUT.bears});
        return {body, continued};
        """,
        {"state": state, "knight": knight.permanent_id, "lions": lions.permanent_id,
         "giant": giant.permanent_id, "bears": bears.permanent_id,
         "mountains": [perm.permanent_id for perm in mountains]},
        prelude=_W2G2_SPLICE_PRELUDE,
    )
    cards = seen["body"]["splice_cards"]
    assert cards[0]["cost_permanent_ids"] == [knight.permanent_id]
    assert cards[1]["cost_graveyard_indices"] == [4, 0, 1, 3]
    assert cards[2]["cost_permanent_ids"] == [mountains[1].permanent_id, mountains[2].permanent_id]
    assert "cost_permanent_ids" not in cards[3] and "cost_graveyard_indices" not in cards[3]
    response = _w2g2_act(sid, seen["body"])
    assert response.status_code == 200, response.text
    settle(game)
    assert knight.tapped and not lions.tapped
    on_board = {perm.permanent_id for perm in game.players[0].battlefield}
    assert mountains[0].permanent_id in on_board
    assert mountains[1].permanent_id not in on_board and mountains[2].permanent_id not in on_board
    assert sorted(card.name for card in game.players[0].exile) == [
        "Giant Growth", "Island", "Lightning Bolt", "Shock",
    ]
    assert game.players[1].life == 25
    assert giant not in game.players[1].battlefield and bears not in game.players[1].battlefield


# ---------------------------------------------------------------------------
# Offering (CR 702.48)
# ---------------------------------------------------------------------------

_W2G2_OFFER_PRELUDE = """
var seat = 0;
var pendingCastOffers = null;
var pendingCastHandCard = null;
var pendingCastCost = null;
var pendingCastAlternativeOwed = null;
var pendingCastFromZone = null;
var hints = [];
var refreshes = 0;
var continued = [];
const EMPTY_TARGET_SPEC = { kind: "none", valid_targets: [] };
function renderActivationPrompt() {}
function updateActionHint(text) { hints.push(text); }
function escapeHtml(value) { return String(value ?? ""); }
function renderSymbolsInline(value) { return String(value ?? ""); }
function normalizeCardName(card) { return typeof card === "string" ? card : (card && card.name) || ""; }
function refreshCastOffers() { refreshes += 1; }
function startCastCostPrompt() { return false; }
function continueCastAfterCost(card, castAction) { continued.push([card.name, castAction]); }
"""

_W2G2_OFFER_FUNCTIONS = [
    "targetSpecOf", "castCostOffers", "castOffersAreLive", "startCastOfferPrompt",
    "offeringOfferRowsHtml", "offeringRequiredWords", "takeRequiredCastOffers",
    "castOfferIsRequired", "setCastOfferTimes", "offeringPickerRowsHtml",
    "confirmCastOffers", "alternativeOfferIndex", "pitchedCardX",
    "alternativeHandChoiceLabel", "castXAnnouncedByCost", "altPermanentIds",
]


def _w2g2_patron_board(set_pool, *, plains: int):
    return _w2g2_session(
        set_pool,
        mine=("Kitsune Blademaster", "Kitsune Diviner") + ("Plains",) * plains,
        theirs=("Grizzly Bears", "Mountain"),
        hand=("Patron of the Kitsune",),
    )


def test_w2g2_an_offering_shows_each_foxs_price_and_makes_the_patron_castable(set_pool):
    """Four Plains cannot pay {4}{W}{W}, but offering Kitsune Blademaster
    ({2}{W}) leaves {2}{W} (CR 702.48c): the hand card is castable, and the
    offer lists each Fox with the price the cast is then charged — Kitsune
    Diviner's {4}{W} said to be unpayable. At sorcery speed the offering is
    optional: nothing is required, and "Don't offer" is a button."""
    sid, _game, mine, _theirs = _w2g2_patron_board(set_pool, plains=4)
    state = _w2g2_state(sid)
    patron = _w2g2_hand(state, "Patron of the Kitsune")
    assert state["players"][0]["playable_hand_indices"] == [0]
    offer = patron["target_spec"]["cost_offers"][0]
    assert offer["label"] == "offering" and offer["max_times"] == 1
    assert offer["offering_prices"] == [
        {"id": mine[0].permanent_id, "name": "Kitsune Blademaster", "mana_owed": "{2}{W}", "payable": True},
        {"id": mine[1].permanent_id, "name": "Kitsune Diviner", "mana_owed": "{4}{W}", "payable": False},
    ]
    assert "required" not in offer
    seen = run_app_js(
        _W2G2_OFFER_FUNCTIONS,
        """
        const opened = startCastOfferPrompt(INPUT.patron, "cast");
        return {opened, refreshes, taken: pendingCastOffers.taken,
                rows: offeringOfferRowsHtml(pendingCastOffers.offers[0], pendingCastOffers)};
        """,
        {"patron": patron},
        prelude=_W2G2_OFFER_PRELUDE,
    )
    assert seen["opened"] is True and seen["refreshes"] == 0 and seen["taken"] == {}
    html = "".join(seen["rows"])
    assert "Kitsune Blademaster → {2}{W}" in html
    assert "Kitsune Diviner → {4}{W} (you can't pay that now)" in html
    assert 'data-offer-times="0">Don\'t offer' in html and "Required now" not in html


def test_w2g2_at_instant_speed_the_offering_is_required_taken_and_not_declinable(set_pool):
    """With a spell on the stack the Patron can be cast only by paying its
    offering (CR 601.3c, 601.2e): the wire says `required` with the cast
    path's own reason, the prompt takes the offering from the start and
    re-asks the spec, "Don't offer" is disabled, and a click on it is refused
    with that reason rather than leaving a cast the engine would refuse."""
    sid, game, _mine, _theirs = _w2g2_patron_board(set_pool, plains=6)
    game.players[1].hand = [_w2g2_card(set_pool, "Lightning Bolt")]
    game.players[1].mana_pool["R"] = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.priority_player_index = 0
    state = _w2g2_state(sid)
    patron = _w2g2_hand(state, "Patron of the Kitsune")
    offer = patron["target_spec"]["cost_offers"][0]
    assert offer["required"] is True
    assert "only by paying its offering" in offer["required_reason"]
    seen = run_app_js(
        _W2G2_OFFER_FUNCTIONS,
        """
        startCastOfferPrompt(INPUT.patron, "cast");
        const takenAtOpen = {...pendingCastOffers.taken};
        const refreshedAtOpen = refreshes;
        setCastOfferTimes("sacrifice a fox", 0);
        return {takenAtOpen, refreshedAtOpen, taken: pendingCastOffers.taken, hints,
                rows: offeringOfferRowsHtml(pendingCastOffers.offers[0], pendingCastOffers)};
        """,
        {"patron": patron},
        prelude=_W2G2_OFFER_PRELUDE,
    )
    assert seen["takenAtOpen"] == {"sacrifice a fox": 1} and seen["refreshedAtOpen"] == 1
    assert seen["taken"] == {"sacrifice a fox": 1}
    assert seen["hints"][-1].startswith("Required now: Patron of the Kitsune can be cast")
    html = "".join(seen["rows"])
    assert 'data-offer-times="0" disabled>Don\'t offer' in html
    assert "Required now" in html


def test_w2g2_the_fox_picker_says_each_price_and_the_cast_charges_it(set_pool):
    """With the offering taken the spec is the Fox picker, and its rows say
    what the cast then costs with each; the cast naming Kitsune Blademaster
    out of three white mana is charged {2}{W} and sacrifices that Fox."""
    sid, game, mine, _theirs = _w2g2_patron_board(set_pool, plains=0)
    blademaster, diviner = mine[0], mine[1]
    # The spec the offer prompt re-asks for (`card_target_spec`, whose route
    # finds a card in the shipped catalog — a measured set's is not there).
    spec = build_card_target_spec(
        store.get(sid), _w2g2_card(set_pool, "Patron of the Kitsune"), 0,
        hand_index=0, optional_cost_payments='{"sacrifice a fox": 1}',
    )["target_spec"]
    assert spec["sacrifice_cost"] is True
    rows = run_app_js(
        _W2G2_OFFER_FUNCTIONS,
        "return offeringPickerRowsHtml({name: 'Patron of the Kitsune', target_spec: INPUT});",
        spec,
        prelude=_W2G2_OFFER_PRELUDE,
    )
    assert "Kitsune Blademaster → {2}{W}" in rows and "Kitsune Diviner → {4}{W} (can't pay)" in rows
    game.players[0].mana_pool.update({"W": 3})
    response = _w2g2_act(sid, {
        "seat": 0, "action": "cast", "card_name": "Patron of the Kitsune",
        "optional_cost_payments": {"sacrifice a fox": 1},
        "cost_permanent_ids": [blademaster.permanent_id],
    })
    assert response.status_code == 200, response.text
    settle(game)
    names = [perm.card.name for perm in game.players[0].battlefield]
    assert "Patron of the Kitsune" in names and "Kitsune Blademaster" not in names
    assert diviner in game.players[0].battlefield
    assert sum(game.players[0].mana_pool.values()) == 0


# ---------------------------------------------------------------------------
# The Shoals' pitch: the chosen card is the X
# ---------------------------------------------------------------------------


def test_w2g2_a_pitched_shoal_sends_the_chosen_cards_x_and_asks_no_x(set_pool):
    """Blazing Shoal's pitch offers each red card with the X it names; taking
    Lava Axe announces X = 5 on the cast (`x_value`, read by
    `castXAnnouncedByCost`, so no X box opens) — the box's own value was
    refused as a mismatch. Paying the mana cost announces nothing. The cast
    the client builds gives the Bears +5/+0."""
    sid, game, mine, _theirs = _w2g2_session(
        set_pool, mine=("Grizzly Bears",), theirs=("Hill Giant",),
        hand=("Blazing Shoal", "Hill Giant", "Lava Axe"),
    )
    bears = mine[0]
    state = _w2g2_state(sid)
    shoal = _w2g2_hand(state, "Blazing Shoal")
    pitch = next(o for o in shoal["target_spec"]["cost_offers"] if o["kind"] == "alternative")
    assert [(c["name"], c["x"]) for c in pitch["hand_choices"]] == [("Hill Giant", 4), ("Lava Axe", 5)]
    seen = run_app_js(
        _W2G2_OFFER_FUNCTIONS,
        """
        startCastOfferPrompt(INPUT.shoal, "cast");
        pendingCastOffers.alternative = 2;            // Lava Axe's place in the hand
        pendingCastOffers.alternativeIndex = 0;
        confirmCastOffers();
        const pitched = {cost: {...pendingCastCost}, x: castXAnnouncedByCost()};
        pendingCastCost = null;
        startCastOfferPrompt(INPUT.shoal, "cast");     // pay the mana cost instead
        confirmCastOffers();
        const paid = {cost: pendingCastCost, x: castXAnnouncedByCost()};
        const label = alternativeHandChoiceLabel("Exile", INPUT.pitch, INPUT.pitch.hand_choices[1]);
        return {pitched, paid, label};
        """,
        {"shoal": shoal, "pitch": pitch},
        prelude=_W2G2_OFFER_PRELUDE,
    )
    assert seen["pitched"]["x"] == 5
    assert seen["pitched"]["cost"]["alternative_cost"] is True
    assert seen["pitched"]["cost"]["alternative_cost_hand_index"] == 2
    assert seen["paid"]["x"] is None
    assert seen["label"] == "Exile Lava Axe (X = 5)"
    response = _w2g2_act(sid, {
        "seat": 0, "action": "cast", "card_name": "Blazing Shoal",
        "target_seat": 0, "target_permanent_id": bears.permanent_id,
        **seen["pitched"]["cost"],
    })
    assert response.status_code == 200, response.text
    settle(game)
    assert bears.effective_power == 7
    assert [card.name for card in game.players[0].exile] == ["Lava Axe"]


# ---------------------------------------------------------------------------
# A target bounded by the announced X; an X paid in counters
# ---------------------------------------------------------------------------

_W2G2_X_PRELUDE = """
var seat = 0;
var currentState = null;
var pendingCastX = null;
var pendingCastCost = null;
var pendingActivationCost = null;
var hints = [];
var continued = [];
var xPrompts = [];
const EMPTY_TARGET_SPEC = { kind: "none", valid_targets: [] };
function renderActivationPrompt() {}
function updateActionHint(text) { hints.push(text); }
function normalizeCardName(card) { return typeof card === "string" ? card : (card && card.name) || ""; }
function getDefaultTargetSeat() { return 1; }
function xLivesInManaCost(card) { return /\\{x\\}/i.test(card.mana_cost || ""); }
function startCastXPrompt(card, targetSeat, targetPermanentIndex, castAction) {
  pendingCastX = { kind: "cast_x", card, cardName: card.name, targetSeat, castAction };
}
function startActivationXPrompt(card, cardName, targetSeat, permanentIndex, abilityIndex, maxXOverride, options) {
  xPrompts.push({cardName, abilityIndex, maxXOverride, thenTargets: !!(options && options.thenTargets)});
}
function continueCastAfterCost(card, castAction) {
  continued.push([card.name, castAction, (card.target_spec.valid_targets || []).map((t) => t.name)]);
}
function getActivatedAbilityCost(card, abilityIndex) { return (card.__costs || [])[abilityIndex || 0] || ""; }
function findPermanentInState(state, pid) {
  for (const player of (state && state.players) || []) {
    const found = (player.battlefield || []).find((c) => c && c.id === pid);
    if (found) return { card: found };
  }
  return null;
}
function getCurrentPlayerState(state) { return state && state.players ? state.players[seat] : null; }
"""

_W2G2_X_FUNCTIONS = [
    "targetSpecOf", "hasXCost", "castXAnnouncedByCost", "specNarrowedToManaValueX",
    "xBoundAdmits", "specNarrowedToXBound", "xBoundSentence", "startCastXBoundFirst",
    "resumeCastAfterXBound", "abilityXPayable", "castXPayable", "liveXPayable",
    "counterRemovalXKind", "activationAnnouncesCounterX", "counterXSentence",
    "chosenAbilityMana", "activationCostAnswered", "startCounterXBeforeManaChoice",
]


def test_w2g2_an_x_bounded_spec_is_narrowed_to_the_targets_the_x_admits(set_pool):
    """Minamo Sightbender ("power X or less") and Quillmane Baku ("mana value
    X or less") carry `x_bound` and each target's `x_bound_value`; once X is
    announced the picker offers only `x_bound_value <op> X` — and a spec with
    neither bound is returned as it was."""
    sid, _game, mine, theirs = _w2g2_session(
        set_pool,
        mine=("Minamo Sightbender", "Quillmane Baku", "Island", "Island", "Island"),
        theirs=("Grizzly Bears", "Hill Giant", "Craw Wurm"),
    )
    add_counters(mine[1], "ki", 3)
    state = _w2g2_state(sid)
    board = {card["name"]: card for card in state["players"][0]["battlefield"]}
    minamo_spec = board["Minamo Sightbender"]["target_spec"]
    quill_spec = board["Quillmane Baku"]["target_spec"]
    assert minamo_spec["x_bound"] == {"stat": "power", "op": "le"}
    assert quill_spec["x_bound"] == {"stat": "mana_value", "op": "le"}
    seen = run_app_js(
        _W2G2_X_FUNCTIONS,
        """
        const names = (spec) => spec.valid_targets.map((t) => t.name).sort();
        return {
          minamo2: names(specNarrowedToManaValueX(INPUT.minamo, 2)),
          quill2: names(specNarrowedToManaValueX(INPUT.quill, 2)),
          quill5: names(specNarrowedToManaValueX(INPUT.quill, 5)),
          untouched: specNarrowedToManaValueX(INPUT.plain, 2) === INPUT.plain,
          lt: xBoundAdmits("lt", 2, 2), ge: xBoundAdmits("ge", 3, 2), eq: xBoundAdmits("eq", 2, 2),
          sentence: xBoundSentence(INPUT.quill),
        };
        """,
        {"minamo": minamo_spec, "quill": quill_spec,
         "plain": {"kind": "creature", "valid_targets": [{"name": "x"}]}},
        prelude=_W2G2_X_PRELUDE,
    )
    assert seen["minamo2"] == ["Grizzly Bears", "Minamo Sightbender"]
    assert seen["quill2"] == ["Grizzly Bears", "Minamo Sightbender"]
    assert seen["quill5"] == ["Grizzly Bears", "Hill Giant", "Minamo Sightbender", "Quillmane Baku"]
    assert seen["untouched"] is True
    assert (seen["lt"], seen["ge"], seen["eq"]) == (False, True, True)
    assert "mana value X or less" in seen["sentence"]


def test_w2g2_stir_the_grave_asks_x_first_and_offers_the_cards_it_admits(set_pool):
    """A cast whose target the X bounds announces X before its target (CR
    601.2b before 601.2c): Stir the Grave opens the X prompt first, and X = 4
    records the X where every cast body reads it and offers Grizzly Bears and
    Hill Giant, never Craw Wurm. The cast the client builds returns the Giant."""
    sid, game, _mine, _theirs = _w2g2_session(
        set_pool, mine=("Swamp",), hand=("Stir the Grave",),
        graveyard=("Grizzly Bears", "Hill Giant", "Craw Wurm"),
    )
    game.enforce_mana_costs = False
    state = _w2g2_state(sid)
    stir = _w2g2_hand(state, "Stir the Grave")
    assert stir["target_spec"]["x_bound"] == {"stat": "mana_value", "op": "le"}
    seen = run_app_js(
        _W2G2_X_FUNCTIONS,
        """
        const opened = startCastXBoundFirst(INPUT, "cast", null);
        const thenTargets = pendingCastX && pendingCastX.thenTargets;
        resumeCastAfterXBound(pendingCastX, 4);
        const again = startCastXBoundFirst(INPUT, "cast", null);
        return {opened, thenTargets, again, cost: pendingCastCost, continued};
        """,
        stir,
        prelude=_W2G2_X_PRELUDE,
    )
    assert seen["opened"] is True and seen["thenTargets"] is True
    assert seen["again"] is False
    assert seen["cost"] == {"x_value": 4}
    assert seen["continued"] == [["Stir the Grave", "cast", ["Grizzly Bears", "Hill Giant"]]]
    response = _w2g2_act(sid, {
        "seat": 0, "action": "cast", "card_name": "Stir the Grave",
        "target_seat": 0, "target_graveyard_indices": [1], "x_value": 4,
    })
    assert response.status_code == 200, response.text
    settle(game)
    assert "Hill Giant" in [perm.card.name for perm in game.players[0].battlefield]


def test_w2g2_a_removal_x_is_asked_and_said_in_counters(set_pool):
    """"Remove X ki counters" announces an X with no {X} in the cost: the
    server's `counter_bound` says so for Quillmane, Skullmane and Petalmane,
    the prompt words the bound in counters, and Petalmane's mana ability asks
    X before its colour (once: an answered X is not asked again). Minamo's
    {X} is mana, not counters."""
    sid, _game, mine, _theirs = _w2g2_session(
        set_pool,
        mine=("Minamo Sightbender", "Quillmane Baku", "Skullmane Baku", "Petalmane Baku", "Island"),
    )
    for baku in mine[1:4]:
        add_counters(baku, "ki", 3)
    state = _w2g2_state(sid)
    board = {card["name"]: card for card in state["players"][0]["battlefield"]}
    for name in ("Quillmane Baku", "Skullmane Baku", "Petalmane Baku"):
        assert board[name]["ability_x_payable"][0]["counter_bound"] == {"kind": "ki", "count": 3}
    seen = run_app_js(
        _W2G2_X_FUNCTIONS,
        """
        currentState = INPUT.state;
        const b = INPUT.board;
        const announces = Object.fromEntries(Object.entries(b).map(([n, c]) => [n, activationAnnouncesCounterX(c, 0)]));
        const words = counterXSentence({card: b["Quillmane Baku"], cardName: "Quillmane Baku",
          castAction: "activate", activateAbilityIndex: 0, maxX: 3, costString: ""});
        const petal = {...b["Petalmane Baku"], __abilityIndex: 0};
        const asked = startCounterXBeforeManaChoice(petal, "Petalmane Baku", 0, 3, 0);
        pendingActivationCost = {permanentIndex: 3, abilityIndex: 0, fields: {x_value: 2}};
        const askedAgain = startCounterXBeforeManaChoice(petal, "Petalmane Baku", 0, 3, 0);
        const fallback = activationAnnouncesCounterX({__costs: ["{T}, Remove X charge counters from this artifact"]}, 0);
        return {announces, words, asked, askedAgain, fallback, xPrompts};
        """,
        {"state": state, "board": {name: board[name] for name in (
            "Minamo Sightbender", "Quillmane Baku", "Skullmane Baku", "Petalmane Baku")}},
        prelude=_W2G2_X_PRELUDE,
    )
    assert seen["announces"] == {
        "Minamo Sightbender": False, "Quillmane Baku": True,
        "Skullmane Baku": True, "Petalmane Baku": True,
    }
    assert seen["words"].startswith("X ki counters are removed from Quillmane Baku")
    assert "it has 3 ki counters, so X can be at most 3" in seen["words"]
    assert (seen["asked"], seen["askedAgain"], seen["fallback"]) == (True, False, True)
    assert seen["xPrompts"] == [
        {"cardName": "Petalmane Baku", "abilityIndex": 0, "maxXOverride": None, "thenTargets": True},
    ]


def test_w2g2_dominate_a_shipped_x_bounded_cast_asks_x_first_too(set_pool):
    """Nemesis' Dominate ("Gain control of target creature with mana value X
    or less") carries the same `x_bound` on its cast spec, so it is asked the
    same way: X before the target, the picker narrowed to what the X admits —
    it was asked target first, and an X below the target's mana value was
    refused. X = 2 offers the Bears, never the Giant."""
    sid, _game, _mine, _theirs = _w2g2_session(
        set_pool, mine=("Island",), theirs=("Grizzly Bears", "Hill Giant"), hand=("Dominate",),
    )
    dominate = _w2g2_hand(_w2g2_state(sid), "Dominate")
    assert dominate["target_spec"]["x_bound"] == {"stat": "mana_value", "op": "le"}
    seen = run_app_js(
        _W2G2_X_FUNCTIONS,
        """
        const opened = startCastXBoundFirst(INPUT, "cast", null);
        resumeCastAfterXBound(pendingCastX, 2);
        return {opened, continued};
        """,
        dominate,
        prelude=_W2G2_X_PRELUDE,
    )
    assert seen["opened"] is True
    assert seen["continued"] == [["Dominate", "cast", ["Grizzly Bears"]]]
