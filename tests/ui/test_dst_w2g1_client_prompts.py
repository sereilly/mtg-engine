"""Darksteel's prompts as a person meets them: the wire each one rides and the
words the client draws from it (Darksteel's wave 2, the client group).

Every one of these was clicked in a browser first (W2G1's report says what);
this file holds what the clicks found. Each payload is the server's own, read
from a web session's state after the engine armed the prompt; each client
function is the real source, lifted out of ``app.js`` by ``run_app_js``.

Darksteel is a measured set until it is promoted, so no deck the web app deals
holds one of its cards: each test puts the cards it names onto a session's
board from ``set_pool``. That works on either manifest role, and these tests
are run on both.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from engine.models import Permanent
from engine.restricted_mana import RESTRICTION_KEYS
from web.app import app, store
from web.prompt_values import RESTRICTED_MANA_WORDS, restricted_mana_words

from tests.helpers import run_app_js, seat_plays_first, settle

client = TestClient(app)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _session(seed: int = 7):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
        "guest_colors": 2, "seed": seed,
    })
    assert created.status_code == 200, created.text
    sid = created.json()["session_id"]
    session = seat_plays_first(sid)
    return sid, session.game


def _place(game, seat: int, card) -> Permanent:
    """*card* onto *seat*'s battlefield through the engine's entry funnel, not
    summoning sick."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _state(sid: str, seat: int = 0) -> dict:
    response = client.get(f"/api/sessions/{sid}/state", params={"seat": seat})
    assert response.status_code == 200, response.text
    return response.json()


def _post(sid: str, action: str, **extra):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": action, **extra}
    )


def _on_board(state: dict, seat: int, permanent_id: int) -> dict:
    return next(
        entry for entry in state["players"][seat]["battlefield"]
        if entry["id"] == permanent_id
    )


#: Enough of the page for a prompt renderer: every element a recorder of what
#: it was told, ``sendAction`` a recorder of what it would send.
_PRELUDE = r"""
var seat = 0;
var SENT = [];
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "", onclick: null, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    get innerText() { return this._html; },
    addEventListener() {}, querySelectorAll() { return []; }, querySelector() { return null; },
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
function setSymbolsHtml(el, text) { el.textContent = text; }
function normalizeCardName(card) { return card && card.name ? card.name : ""; }
function candidatePermanentTileFace(entry, label) { return `[${label}]`; }
function refreshPromptSelection() {}
function updateActionHint() {}
async function sendAction(body) { SENT.push(body); }
"""


def _panel() -> str:
    return """
return {
  title: q("promptTitle").textContent,
  body: q("promptBody").textContent,
  steps: q("promptSteps").innerHTML,
  ok: q("promptOkBtn").textContent,
  okDisabled: q("promptOkBtn").disabled,
  sent: SENT,
};
"""


# ---------------------------------------------------------------------------
# 1. Serum Powder — the keep-or-mulligan offer's third answer (CR 103.5b)
# ---------------------------------------------------------------------------


def _pregame_session():
    for seed in range(1, 60):
        created = client.post("/api/sessions", json={
            "mode": "human_vs_ai", "host_name": "Host", "host_colors": 2,
            "guest_colors": 2, "seed": seed, "enable_pregame": True,
        })
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]
        session = store.get(sid)
        if session.pregame_phase == "coin_flip" and session.coin_flip_winner == 0:
            assert _post(sid, "coin_flip_choose", hand_index=0).status_code == 200
        info = _state(sid)["pregame"]
        if info and info["phase"] == "mulligan" and info.get("is_my_turn"):
            return sid
    raise AssertionError("no seed reached the host's offer")


#: The offer's helpers, lifted with it.
_OFFER_FUNCTIONS = [
    "applyMulliganPrompt", "mulliganViewerHand", "mulliganExchangeSourceName",
    "mulliganExchangeLabel", "mulliganExchangeNote", "applyMulliganExchangePick",
    "sendMulliganExchange",
]
_OFFER_PRELUDE = _PRELUDE + "var currentState = null;\nvar mulliganExchangePick = null;\n"


def _render_offer(state: dict) -> dict:
    return run_app_js(
        _OFFER_FUNCTIONS,
        "currentState = {players: [{hand: INPUT.hand}]};"
        "applyMulliganPrompt(INPUT.info);" + _panel(),
        {"info": state["pregame"], "hand": state["players"][0]["hand"]},
        prelude=_OFFER_PRELUDE,
    )


def _give_powder(sid: str, powder, slot: int = 0) -> None:
    player = store.get(sid).game.players[0]
    player.library.append(player.hand[slot])
    player.hand[slot] = powder


def test_w2g1_the_offer_draws_serum_powder_s_button_over_the_hand_it_counts(set_pool):
    """The offer served with ``hand_exchange`` draws a third button beside
    Keep and Mulligan, named for the card and the cards it draws; without
    one it draws two. Clicked: one POST, the offer redrawn over seven new
    cards."""
    sid = _pregame_session()
    shown = _render_offer(_state(sid))
    assert 'id="mulliganExchangeBtn"' not in shown["steps"], shown
    _give_powder(sid, set_pool("DST")["Serum Powder"])
    shown = _render_offer(_state(sid))
    assert 'id="mulliganExchangeBtn"' in shown["steps"], shown
    assert "Serum Powder: Exile Hand, Draw 7" in shown["steps"], shown
    assert "Your hand has 7 cards." in shown["steps"], shown


def test_w2g1_a_bottom_paid_by_the_exchange_is_not_read_as_a_free_mulligan(set_pool):
    """Two seats: a mulligan owes one card. The exchange after it puts that
    card on the bottom first (``hand_indices``), so the offer that follows owes
    nothing — and said "your first mulligan is free" until the server sent
    ``bottom_paid``. It now says the exchange paid it, and counts six."""
    sid = _pregame_session()
    assert _post(sid, "mulligan_take").status_code == 200
    assert _state(sid)["pregame"]["bottom_owed"] == 1
    _give_powder(sid, set_pool("DST")["Serum Powder"], slot=0)
    taken = _post(sid, "mulligan_exchange", hand_indices=[1])
    assert taken.status_code == 200, taken.text
    state = _state(sid)
    info = state["pregame"]
    assert (info["bottom_owed"], info["bottom_paid"], info["mulligans_taken"]) == (0, 1, 1)
    shown = _render_offer(state)
    assert "free" not in shown["body"], shown
    assert "the exchange already put 1 there" in shown["body"], shown
    assert "Your hand has 6 cards." in shown["steps"], shown


def test_w2g1_the_exchange_s_bottom_pick_keeps_a_powder_in_hand(set_pool):
    """With a card owed, the button opens a pick in hand. A pick holding the
    only Powder cannot be sent (the server refuses it: a card on the bottom is
    not in your hand); any other card can, and the send names it."""
    hand = [{"name": "Serum Powder"}, {"name": "Forest"}, {"name": "Mountain"}]
    info = {"phase": "mulligan", "is_my_turn": True, "mulligans_taken": 1,
            "bottom_owed": 1, "bottom_paid": 0, "may_mulligan": True,
            "hand_exchange": {"source_indices": [0], "bottom_owed": 1}}
    body = (
        "currentState = {players: [{hand: INPUT.hand}]};"
        "mulliganExchangePick = {owed: 1, picked: INPUT.picked};"
        "applyMulliganPrompt(INPUT.info);"
        "if (q('promptOkBtn').onclick) await q('promptOkBtn').onclick();" + _panel()
    )
    payload = {"info": info, "hand": hand}
    refused = run_app_js(_OFFER_FUNCTIONS, body, {**payload, "picked": [0]}, prelude=_OFFER_PRELUDE)
    assert refused["okDisabled"] and refused["sent"] == [], refused
    assert "keep one in your hand" in refused["steps"], refused
    taken = run_app_js(_OFFER_FUNCTIONS, body, {**payload, "picked": [2]}, prelude=_OFFER_PRELUDE)
    assert not taken["okDisabled"], taken
    assert taken["sent"] == [{"seat": 0, "action": "mulligan_exchange", "hand_indices": [2]}], taken


# ---------------------------------------------------------------------------
# 2. Scrounge — the opponent's choice out of their own graveyard
# ---------------------------------------------------------------------------


def test_w2g1_scrounge_asks_the_person_a_choice_and_says_whose_spell(set_pool):
    """The AI casts Scrounge at the person: the pick is served to seat 0 with
    ``destination: "chosen"`` and the caster's name, the status line says the
    seat is choosing (not exiling), and the dialog is worded as a choice."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([lea["Sol Ring"], lea["Grizzly Bears"]])
    game.players[1].hand.append(dst["Scrounge"])
    assert game.cast_from_hand(1, "Scrounge", target_player_index=0).supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "graveyard_exile_pick", owed
    state = _state(sid)
    info = state["graveyard_exile_pick"]
    assert info["destination"] == "chosen" and info["caster_name"] == game.players[1].name
    assert info["legal_indices"] == [0]
    assert state["prompt_owed_by"]["doing"] == "choose cards from that graveyard"
    words = run_app_js(["graveyardPickWords"], "return graveyardPickWords(INPUT.info);",
                       {"info": info}, prelude="var seat = 0;")
    assert words["title"] == "Choose a Card in Your Graveyard" and words["button"] == "Choose"
    picked = _post(sid, "graveyard_exile_confirm", graveyard_indices=[0])
    assert picked.status_code == 200, picked.text
    assert [p.card.name for p in game.controlled_by(1) if p.card.name == "Sol Ring"] == ["Sol Ring"]


# ---------------------------------------------------------------------------
# 3. Sundering Titan — a destruction chosen over every battlefield
# ---------------------------------------------------------------------------


def test_w2g1_sundering_titan_s_choice_is_drawn_per_battlefield_as_a_destruction(set_pool):
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    game.enforce_mana_costs = False
    _place(game, 0, lea["Plains"])
    _place(game, 1, lea["Swamp"])
    _place(game, 1, lea["Taiga"])
    game.players[0].hand.append(dst["Sundering Titan"])
    assert game.cast_from_hand(0, "Sundering Titan").supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "keep_permanents", owed
    info = _state(sid)["keep_permanents"]
    assert info["fate"] == "destroy_chosen" and info["every_battlefield"]
    assert {entry["seat"] for entry in info["candidates"]} == {0, 1}
    prelude = _PRELUDE + "var keepPermanentsSelected = new Set();\nvar currentState = null;\n"
    shown = run_app_js(
        ["renderKeepPermanentsModal"],
        "currentState = {players: INPUT.players.map((name) => ({name}))};"
        "renderKeepPermanentsModal(INPUT.info); return {title: q('keepPermanentsTitle').textContent,"
        " subtitle: q('keepPermanentsSubtitle').textContent, list: q('keepPermanentsList').innerHTML};",
        {"info": info, "players": [p.name for p in game.players]}, prelude=prelude,
    )
    assert shown["title"] == "Destroy Permanents", shown
    assert "The ones you choose are destroyed" in shown["subtitle"], shown
    assert "Your battlefield" in shown["list"] and f"{game.players[1].name}'s battlefield" in shown["list"]
    assert shown["list"].index("Your battlefield") < shown["list"].index("Swamp"), shown
    assert "Taiga: destroy as Mountain / Forest" in shown["list"], shown


# ---------------------------------------------------------------------------
# 4. Well of Lost Dreams — {X} under a ceiling, paid with any mana source
# ---------------------------------------------------------------------------


def test_w2g1_well_of_lost_dreams_pays_with_sol_ring_tapped_while_owed(set_pool):
    """CR 605.3a: a mana ability may be activated "whenever a rule or effect
    asks for a mana payment". The offer counts the pool and the untapped
    lands; Sol Ring is the person's to tap while it is owed, which the
    pay_any_amount prompt refused ("say how much mana you pay before other
    actions") until its spec admitted a mana ability as the other two
    payment prompts do. After the tap the offer reaches the ceiling."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    _place(game, 0, dst["Well of Lost Dreams"])
    _place(game, 0, lea["Island"])
    ring = _place(game, 0, lea["Sol Ring"])
    for permanent in game.controlled_by(0):
        if permanent.card.name not in ("Well of Lost Dreams", "Island", "Sol Ring"):
            permanent.tapped = True
    game._gain_life(game.players[0], 3, "a test")
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "pay_any_amount", owed
    info = _state(sid)["pay_any_amount"]
    assert (info["ceiling"], info["maximum"], info["pays_x"]) == (3, 1, True), info
    tapped = _post(sid, "activate", permanent_id=ring.permanent_id, ability_index=0)
    assert tapped.status_code == 200, tapped.text
    info = _state(sid)["pay_any_amount"]
    assert info["maximum"] == 3, info
    words = run_app_js(["applyPayAnyAmountPrompt"], "applyPayAnyAmountPrompt(INPUT.info);" + _panel(),
                       {"info": {**info, "maximum": 1}}, prelude=_PRELUDE)
    assert "X can be at most 3 (Well of Lost Dreams's limit)." in words["body"], words
    assert "cover up to 1 — tap another mana source first" in words["body"], words
    words = run_app_js(["applyPayAnyAmountPrompt"], "applyPayAnyAmountPrompt(INPUT.info);" + _panel(),
                       {"info": info}, prelude=_PRELUDE)
    assert "untapped lands" not in words["body"], words
    hand = len(game.players[0].hand)
    assert _post(sid, "pay_any_amount_confirm", number=3).status_code == 200
    assert len(game.players[0].hand) == hand + 3


# ---------------------------------------------------------------------------
# 5. Vedalken Engineer — the restriction said where the mana is made
# ---------------------------------------------------------------------------


def test_w2g1_every_mana_restriction_has_its_words():
    """The words table is keyed by the engine's restriction keys: one the
    engine adds without words here fails, never says "certain spells"."""
    assert set(RESTRICTED_MANA_WORDS) == set(RESTRICTION_KEYS)
    assert restricted_mana_words("last_card_exiled_with_source:Shock") == (
        "Spend this mana only to cast Shock."
    )


def test_w2g1_vedalken_engineer_s_colour_prompt_and_pool_say_the_restriction(set_pool):
    sid, game = _session()
    engineer = _place(game, 0, set_pool("DST")["Vedalken Engineer"])
    asked = _post(sid, "activate", permanent_id=engineer.permanent_id, ability_index=0)
    assert asked.status_code == 200, asked.text
    info = _state(sid)["mana_color_choice"]
    assert info["spend_only"] == "artifact_or_artifact_ability"
    words = ("Spend this mana only to cast artifact spells or activate abilities "
             "of artifacts.")
    assert info["spend_only_words"] == words
    shown = run_app_js(["applyManaColorChoicePrompt"], "applyManaColorChoicePrompt(INPUT.info);" + _panel(),
                       {"info": info}, prelude=_PRELUDE)
    assert shown["body"].endswith(words), shown
    assert _post(sid, "mana_color_choice_confirm", mana_color="U").status_code == 200
    me = _state(sid)["players"][0]
    assert me["restricted_mana"] == {"artifact_or_artifact_ability": {"U": 2}}
    assert me["restricted_mana_words"] == {"artifact_or_artifact_ability": words}


# ---------------------------------------------------------------------------
# 6. Granted abilities — the granter by name, never by id
# ---------------------------------------------------------------------------


def test_w2g1_a_granted_ability_names_its_granter(set_pool):
    """"{T}, Unattach Heartseeker: Destroy target creature." reached the host
    as "…unattach the permanent with id 7 that granted this ability…" — the
    engine's binding of the name to one object (CR 201.5a), served verbatim to
    the menu and the preview. Clicked: activated from the Bears by name."""
    from engine.equipment import attach_equipment

    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    bears = _place(game, 0, lea["Grizzly Bears"])
    seeker = _place(game, 0, dst["Heartseeker"])
    trident = _place(game, 0, dst["Surestrike Trident"])
    assert attach_equipment(game, seeker, bears) and attach_equipment(game, trident, bears)
    game._sync_control()
    text = _on_board(_state(sid), 0, bears.permanent_id)["oracle_text"]
    assert "with id" not in text and "granted this ability" not in text, text
    assert "unattach Heartseeker: destroy target creature." in text, text
    assert "unattach Surestrike Trident: this creature deals damage" in text, text
    assert len(text.splitlines()) == 2, "one line per ability: the menu's indices"


# ---------------------------------------------------------------------------
# 7. Panoptic Mirror — two imprints, one copy, offered card by card
# ---------------------------------------------------------------------------


def _imprint(game, mirror, name: str) -> None:
    mirror.tapped = False
    assert game.activate_permanent_ability(
        0, "Panoptic Mirror", permanent_index=game.battlefield_index_of(mirror),
        ability_index=0, x_value=1,
    ).supported
    offer = settle(game, defaults=False)
    assert offer is not None and offer.kind == "optional_pay", offer
    assert game.confirm_optional_pay(0, accept=True)
    pick = settle(game, defaults=False)
    assert pick is not None and pick.kind == "exile_from_hand_choice", pick
    slot = next(i for i, card in enumerate(game.players[0].hand) if card.name == name)
    assert game.confirm_exile_from_hand_choice(0, slot)
    settle(game)


def test_w2g1_panoptic_mirror_s_offer_names_the_card_offered_next(set_pool):
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    game.enforce_mana_costs = False
    mirror = _place(game, 0, dst["Panoptic Mirror"])
    game.players[0].hand.extend([lea["Lightning Bolt"], lea["Ancestral Recall"]])
    shown = run_app_js(["applyExileFromHandPrompt"], "applyExileFromHandPrompt(INPUT.info);" + _panel(),
                       {"info": {"card_name": "Panoptic Mirror", "optional": True, "choices": []}},
                       prelude=_PRELUDE)
    assert "cast it" not in shown["body"], "the Mirror grants no cast from exile"
    _imprint(game, mirror, "Lightning Bolt")
    _imprint(game, mirror, "Ancestral Recall")
    game.start_turn(0)
    offer = settle(game, defaults=False)
    assert offer is not None and offer.kind == "copy_cast", offer
    info = _state(sid)["copy_cast"]
    assert (info["card_name"], info["then_offers"]) == ("Lightning Bolt", ["Ancestral Recall"])
    prelude = _PRELUDE + (
        "var currentState = {players: []};\n"
        "function copyCastExiledCard() { return null; }\n"
        "function normalizeImageUri() { return null; }\n"
    )
    shown = run_app_js(["applyCopyCastPrompt"], "applyCopyCastPrompt(INPUT.info);" + _panel(),
                       {"info": info}, prelude=prelude)
    assert "decline this and you are offered Ancestral Recall next" in shown["steps"], shown
    assert _post(sid, "copy_cast_confirm", accept=False).status_code == 200
    info = _state(sid)["copy_cast"]
    assert info["card_name"] == "Ancestral Recall" and "then_offers" not in info, info


# ---------------------------------------------------------------------------
# 9. Death Cloud and Lich's Tomb — what each sacrifice round asks for
# ---------------------------------------------------------------------------


def test_w2g1_death_cloud_s_rounds_say_creatures_then_lands(set_pool):
    """Both rounds read "Choose 2 permanent(s)"; the renderer sends the
    filter's one noun (``noun``) and the panel says it."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    sid, game = _session()
    game.enforce_mana_costs = False
    for name in ("Grizzly Bears", "Llanowar Elves", "Forest", "Forest"):
        _place(game, 0, lea[name])
    game.players[0].hand.extend([dst["Death Cloud"], lea["Forest"]])
    assert game.cast_from_hand(0, "Death Cloud", x_value=1).supported
    nouns = []
    for _ in range(4):
        owed = settle(game, defaults=False)
        if owed is None:
            break
        state = _state(sid)
        if owed.kind == "discard":
            slot = state["discard_select"]["cards"][0]
            index = next(i for i, c in enumerate(game.players[0].hand) if c.name == slot["name"])
            assert _post(sid, "discard_confirm", discard_indices=[index]).status_code == 200
            continue
        assert owed.kind == "sacrifice", owed
        info = state["sacrifice_select"]
        nouns.append(info.get("noun"))
        shown = run_app_js(["applySacrificeSelectPrompt"],
                           "applySacrificeSelectPrompt(INPUT.info);" + _panel(), {"info": info},
                           prelude=_PRELUDE + "var sacrificeSelection = [];\n")
        assert shown["body"] == f"Choose 1 {info['noun']} to sacrifice.", shown
        answered = _post(sid, "sacrifice_confirm",
                         sacrifice_permanent_ids=[info["permanents"][0]["id"]])
        assert answered.status_code == 200, answered.text
    assert nouns == ["creature", "land"], nouns
