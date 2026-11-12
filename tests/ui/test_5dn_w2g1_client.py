"""Fifth Dawn's prompts and gestures as a person meets them (5DN wave 2, the
client group, W2G1).

Every one of these was clicked in a browser first, on a session with the set
promoted (the report says what was clicked); this file holds what the clicks
found. Each payload is the server's own, read from a web session's state (or
its payment preview) after the engine armed the prompt; each client function
is the real source, lifted out of ``app.js`` by ``run_app_js``.

Fifth Dawn is a measured set until it is promoted, so no deck the web app
deals holds one of its cards: each test puts the cards it names onto a
session's board from ``set_pool``, which works on either manifest role.
"""

from __future__ import annotations

from itertools import combinations

from fastapi.testclient import TestClient

from engine.aura_attachment import attach_aura
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.per_color_targets import one_per_color
from web.app import app, store

from tests.helpers import run_app_js, seat_plays_first, settle

client = TestClient(app)

#: The sets the cards below are first printed in.
_W2G1_SETS = ("5DN", "LEA", "INV", "ALL", "STH", "DST", "ATQ")


def _w2g1_card(set_pool, name: str):
    for code in _W2G1_SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g1_const(name: str) -> str:
    """The ``const NAME = [...];`` declaration of ``app.js``, verbatim — the
    real table a lifted function reads (``run_app_js`` lifts functions only)."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
        encoding="utf-8").replace("\r", "")
    start = source.index(f"\nconst {name} = ")
    end = source.index("\n];\n", start)
    return source[start:end + 4]


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


def _w2g1_post(sid: str, action: str, **extra):
    return client.post(
        f"/api/sessions/{sid}/action", json={"seat": 0, "action": action, **extra}
    )


def _w2g1_on_board(state: dict, seat: int, permanent_id: int) -> dict:
    return next(
        entry for entry in state["players"][seat]["battlefield"]
        if entry["id"] == permanent_id
    )


# ---------------------------------------------------------------------------
# Dawn's Reflection: the split a land's tap sets off
# ---------------------------------------------------------------------------


def _w2g1_reflection_board(set_pool):
    sid, game = _w2g1_session()
    forest = _w2g1_place(game, 0, _w2g1_card(set_pool, "Forest"))
    island = _w2g1_place(game, 0, _w2g1_card(set_pool, "Island"))
    wild = _w2g1_place(game, 0, _w2g1_card(set_pool, "Plains"))
    attach_aura(_w2g1_place(game, 0, _w2g1_card(set_pool, "Dawn's Reflection")), forest)
    attach_aura(_w2g1_place(game, 0, _w2g1_card(set_pool, "Wild Growth")), wild)
    game._recompute_continuous_effects()
    return sid, game, forest, island, wild


def test_w2g1_a_land_under_dawns_reflection_says_its_tap_sets_off_a_split(set_pool):
    """The wire names the split on exactly the land whose Aura adds two or
    more units of open colour (`tap_mana_split`): not on a plain Island, not
    under Wild Growth (a printed {G}). The tap that answers it with {U}{B}
    adds the land's {G} and those two — the split a person clicked."""
    sid, game, forest, island, wild = _w2g1_reflection_board(set_pool)
    state = _w2g1_state(sid)
    offer = _w2g1_on_board(state, 0, forest.permanent_id)["tap_mana_split"]
    assert offer == {"count": 2, "colors": ["W", "U", "B", "R", "G"], "source": "Dawn's Reflection"}
    assert _w2g1_on_board(state, 0, island.permanent_id)["tap_mana_split"] is None
    assert _w2g1_on_board(state, 0, wild.permanent_id)["tap_mana_split"] is None

    tapped = _w2g1_post(
        sid, "activate", permanent_name="Forest",
        permanent_index=game.players[0].battlefield.index(forest),
        permanent_id=forest.permanent_id, mana_combination={"U": 1, "B": 1},
    )
    assert tapped.status_code == 200, tapped.text
    pool = game.players[0].mana_pool
    assert (pool["G"], pool["U"], pool["B"]) == (1, 1, 1), pool


def test_w2g1_the_tap_split_is_asked_of_exactly_the_taps_that_owe_it(set_pool):
    """`tapManaSplitFor`, the question `sendAction` asks of every body: a tap
    of the enchanted Forest owes the split; the Island owes nothing, and a
    body that already carries an answer is not asked twice."""
    sid, game, forest, island, _ = _w2g1_reflection_board(set_pool)
    state = _w2g1_state(sid)
    asked = run_app_js(
        ["tapManaSplitFor"],
        """
        currentState = INPUT.state;
        return [
          tapManaSplitFor({action: "activate", permanent_id: INPUT.forest}),
          tapManaSplitFor({action: "tap", permanent_id: INPUT.forest}),
          tapManaSplitFor({action: "activate", permanent_id: INPUT.island}),
          tapManaSplitFor({action: "activate", permanent_id: INPUT.forest, mana_combination: {G: 2}}),
          tapManaSplitFor({action: "cast", permanent_id: INPUT.forest}),
        ];
        """,
        {"state": state, "forest": forest.permanent_id, "island": island.permanent_id},
        prelude="var seat = 0; var currentState = null;",
    )
    split = {"cardName": "Forest", "source": "Dawn's Reflection", "count": 2,
             "colors": ["W", "U", "B", "R", "G"]}
    assert asked == [split, split, None, None, None]


# ---------------------------------------------------------------------------
# All Suns' Dawn: one card per colour, as a matching
# ---------------------------------------------------------------------------

_W2G1_DAWN_PILE = ("Absorb", "Energy Arc", "Reviving Vapors", "Lightning Bolt",
                   "Shock", "Dark Ritual", "Giant Growth")


def test_w2g1_all_suns_dawn_picker_agrees_with_the_engine_on_every_set(set_pool):
    """`perColorAssignment` keeps the chosen set matchable one card to one
    colour: two white-blue cards are the white one and the blue one (ruling
    2004-12-01), a third is refused, and so is Shock beside Lightning Bolt.
    Asked of every subset of the seven-card pile the browser was clicked on,
    against the engine's own gate (`per_color_targets.one_per_color`): the
    two never disagree, and 127 sets were examined."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "All Suns' Dawn")]
    game.players[0].graveyard = [_w2g1_card(set_pool, name) for name in _W2G1_DAWN_PILE]
    state = _w2g1_state(sid)
    spec = state["players"][0]["hand"][0]["target_spec"]
    assert spec["one_target_per_color"] is True
    subsets = [
        list(chosen)
        for size in range(1, len(_W2G1_DAWN_PILE) + 1)
        for chosen in combinations(range(len(_W2G1_DAWN_PILE)), size)
    ]
    answers = run_app_js(
        ["perColorAssignment"],
        """
        currentState = INPUT.state;
        return INPUT.subsets.map((slots) => perColorAssignment(
          slots.map((idx) => ({seat: 0, idx})), INPUT.spec));
        """,
        {"state": state, "spec": spec, "subsets": subsets},
        prelude="var currentState = null;",
    )
    pile = game.players[0].graveyard
    examined = 0
    for slots, answer in zip(subsets, answers):
        engine_says = one_per_color([pile[i].colors for i in slots])
        assert (answer is not None) == engine_says, ([pile[i].name for i in slots], answer)
        if answer is not None:
            assert len(set(answer)) == len(slots)
            assert all(color in pile[i].colors for color, i in zip(answer, slots))
        examined += 1
    assert examined == 127
    by_name = dict(zip(
        ("two_wu", "three_wu", "bolt_shock"),
        run_app_js(
            ["perColorAssignment"],
            """
            currentState = INPUT.state;
            const of = (slots) => perColorAssignment(slots.map((idx) => ({seat: 0, idx})), INPUT.spec);
            return [of([0, 1]), of([0, 1, 2]), of([3, 4])];
            """,
            {"state": state, "spec": spec},
            prelude="var currentState = null;",
        ),
    ))
    assert sorted(by_name["two_wu"]) == ["U", "W"]
    assert by_name["three_wu"] is None and by_name["bolt_shock"] is None


# ---------------------------------------------------------------------------
# Reversal of Fortune: a copy of a card in a revealed hand
# ---------------------------------------------------------------------------


def test_w2g1_reversal_s_offer_opens_on_the_card_in_the_revealed_hand(set_pool):
    """The `copy_cast` offer for a card in a revealed hand carries the card
    and its place, the exile fields null. `copyCastExiledCard` read only the
    exile and found nothing — "no longer in exile" was the only answer to
    "Cast a copy" — and now returns the offer's own card."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "Reversal of Fortune")]
    game.players[1].hand = [_w2g1_card(set_pool, "Lightning Bolt"), _w2g1_card(set_pool, "Grizzly Bears")]
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Reversal of Fortune", target_player_index=1).supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "copy_cast", owed
    info = _w2g1_state(sid)["copy_cast"]
    assert (info["exile_seat"], info["exile_index"]) == (None, None)
    assert (info["hand_seat"], info["hand_index"]) == (1, 0)
    found = run_app_js(
        ["copyCastExiledCard", "copyCastFromHand"],
        "return [copyCastFromHand(INPUT), (copyCastExiledCard(INPUT, {players: [{exile: []}, {exile: []}]}) || {}).name];",
        info,
    )
    assert found == [True, "Lightning Bolt"]


# ---------------------------------------------------------------------------
# Summoner's Egg: an exile face down is said before it is chosen
# ---------------------------------------------------------------------------


def test_w2g1_summoners_egg_offer_says_the_card_goes_face_down(set_pool):
    """`exile_from_hand_choice` carries `face_down` for the Egg's imprint,
    and the prompt says so before the card is chosen (CR 406.3: no player,
    its owner included, may look at it)."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "Summoner's Egg"), _w2g1_card(set_pool, "Craw Wurm")]
    game.enforce_mana_costs = False
    assert game.queue_from_hand(0, "Summoner's Egg").supported
    owed = settle(game, defaults=False, answers={"optional_pay": lambda g, c: g.confirm_optional_pay(0, accept=True)})
    assert owed is not None and owed.kind == "exile_from_hand_choice", owed
    info = _w2g1_state(sid)["exile_from_hand_choice"]
    assert info["face_down"] is True
    shown = run_app_js(
        ["applyExileFromHandPrompt"],
        "applyExileFromHandPrompt(INPUT); return q('promptBody').textContent;",
        info, prelude=_W2G1_PRELUDE,
    )
    assert "face down" in shown and "you included" in shown, shown


# ---------------------------------------------------------------------------
# Plunge into Darkness: the number is life
# ---------------------------------------------------------------------------


def test_w2g1_plunge_into_darkness_number_prompt_reads_pay_life(set_pool):
    """The `number_choice` Plunge's second mode arms carries `pays_life`; the
    prompt is titled "Pay life" and every button says what it pays."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "Plunge into Darkness")]
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Plunge into Darkness", mode_index=1).supported
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "number_choice", owed
    state = _w2g1_state(sid)
    info = state["number_choice"]
    assert info["pays_life"] is True
    shown = run_app_js(
        ["applyNumberChoicePrompt"],
        "currentState = INPUT.state; applyNumberChoicePrompt(INPUT.info);"
        "return [q('promptTitle').textContent, q('promptBody').textContent, q('promptSteps').innerHTML];",
        {"state": state, "info": info},
        prelude=_W2G1_PRELUDE + "var currentState = null;",
    )
    title, body, steps = shown
    assert title == "Pay life"
    assert f"(you have {game.players[0].life})" in body
    assert ">Pay 3 life</button>" in steps and ">3</button>" not in steps


# ---------------------------------------------------------------------------
# Vicious Betrayal and Ion Storm: the cost pickers
# ---------------------------------------------------------------------------


def test_w2g1_vicious_betrayal_opens_the_any_number_sacrifice_picker(set_pool):
    """The cost spec says `any_number`; the set picker opens with no count
    (none is an answer) where the one-click picker named exactly one."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "Vicious Betrayal")]
    for name in ("Grizzly Bears", "Hill Giant"):
        _w2g1_place(game, 0, _w2g1_card(set_pool, name))
    state = _w2g1_state(sid)
    card = state["players"][0]["hand"][0]
    assert card["target_spec"]["cost_spec"]["any_number"] is True
    pending = run_app_js(
        ["startCastPermanentSetCostPrompt", "permanentCostVerb", "permanentIdAt",
         "castCostIsSeparate", "targetSpecOf"],
        """
        currentState = INPUT.state;
        startCastPermanentSetCostPrompt(INPUT.card, "cast", INPUT.card.target_spec.cost_spec);
        return {anyNumber: pendingPermanentCost.anyNumber, count: pendingPermanentCost.count,
                verb: pendingPermanentCost.verb, options: pendingPermanentCost.options.map((o) => o.name)};
        """,
        {"state": state, "card": card},
        prelude=(
            _w2g1_const("PERMANENT_SET_COST_VERBS")
            + "var currentState = null; var pendingPermanentCost = null; var seat = 0;"
            "function normalizeCardName(card) { return card && card.name ? card.name : ''; }"
            "function renderActivationPrompt() {} function updateActionHint() {}"
        ),
    )
    assert pending == {"anyNumber": True, "count": 0, "verb": "sacrifice",
                       "options": ["Grizzly Bears", "Hill Giant"]}


def test_w2g1_ion_storm_offers_only_the_counter_kinds_its_cost_lists(set_pool):
    """"Remove a +1/+1 counter or a charge counter": a permanent holding a
    +1/+1 and a -1/-1 counter is asked nothing and pays the +1/+1 (named
    outright); one holding +1/+1 and charge counters is asked which of those
    two. The kind question used to list every kind the permanent held."""
    from engine.named_counters import add_counters

    sid, game = _w2g1_session()
    storm = _w2g1_place(game, 0, _w2g1_card(set_pool, "Ion Storm"))
    bears = _w2g1_place(game, 0, _w2g1_card(set_pool, "Grizzly Bears"))
    thopter = _w2g1_place(game, 0, _w2g1_card(set_pool, "Ornithopter"))
    add_counters(bears, "+1/+1", 1)
    add_counters(bears, "-1/-1", 1)
    add_counters(thopter, "+1/+1", 2)
    add_counters(thopter, "charge", 1)
    state = _w2g1_state(sid)
    storm_entry = _w2g1_on_board(state, 0, storm.permanent_id)
    cost_spec = storm_entry["target_spec"]["cost_spec"]
    assert cost_spec["counter_kinds"] == ["+1/+1", "charge"]
    answers = run_app_js(
        ["confirmPermanentCost", "permanentCostStep", "permanentCostVerb", "permanentIdAt",
         "counterKindsOnPermanentId", "findPermanentInState"],
        """
        currentState = INPUT.state;
        const out = [];
        for (const id of [INPUT.bears, INPUT.thopter]) {
          RESUMED.length = 0;
          pendingCounterKindChoice = null;
          pendingPermanentCost = {
            card: {name: "Ion Storm"}, cardName: "Ion Storm",
            ...permanentCostStep(INPUT.spec), picked: [id],
            activation: {targetSeat: 1, permanentIndex: 0, abilityIndex: null},
            remaining: [], chosen: [],
          };
          confirmPermanentCost();
          out.push({asked: pendingCounterKindChoice && pendingCounterKindChoice.kinds,
                    paid: RESUMED.length ? RESUMED[0].cost_counter_kind || null : null});
        }
        return out;
        """,
        {"state": state, "spec": cost_spec, "bears": bears.permanent_id, "thopter": thopter.permanent_id},
        prelude=(
            _w2g1_const("PERMANENT_SET_COST_VERBS")
            + "var currentState = null; var pendingPermanentCost = null; var pendingCounterKindChoice = null;"
            "var seat = 0; var RESUMED = [];"
            "function renderActivationPrompt() {} function updateActionHint() {}"
            "function resumeActivationAfterCost(card, activation, fields) { RESUMED.push(fields); }"
            "function openPermanentCostStep() { throw new Error('no second step'); }"
        ),
    )
    assert answers == [
        {"asked": None, "paid": "+1/+1"},
        {"asked": ["+1/+1", "charge"], "paid": None},
    ]


# ---------------------------------------------------------------------------
# Sunburst: what the payment spends, before it is made
# ---------------------------------------------------------------------------


def test_w2g1_the_payment_preview_says_the_colours_a_sunburst_cast_spends(set_pool):
    """`POST …/payment_plan` for Suntouched Myr over Plains, Island, Swamp and
    two Darksteel Citadels reports the colours the trial cast spent — read off
    its own record — and the dialog says "3 colors, so 3 counters"; Grizzly
    Bears' preview carries no such key. The cast the dialog then makes enters
    with exactly that many counters."""
    sid, game = _w2g1_session()
    game.players[0].hand = [_w2g1_card(set_pool, "Suntouched Myr"), _w2g1_card(set_pool, "Grizzly Bears")]
    for name in ("Plains", "Island", "Swamp", "Darksteel Citadel", "Darksteel Citadel", "Forest"):
        _w2g1_place(game, 0, _w2g1_card(set_pool, name))
    plan = client.post(f"/api/sessions/{sid}/payment_plan", json={
        "seat": 0, "action": "cast", "card_name": "Suntouched Myr", "hand_index": 0,
    }).json()
    assert plan["payable"] is True and len(plan["sunburst"]["colors"]) == 3, plan
    bears_plan = client.post(f"/api/sessions/{sid}/payment_plan", json={
        "seat": 0, "action": "cast", "card_name": "Grizzly Bears", "hand_index": 1,
    }).json()
    assert bears_plan["payable"] is True and "sunburst" not in bears_plan, bears_plan
    line = run_app_js(
        ["autoTapSunburstLine"], "return autoTapSunburstLine(INPUT);", plan,
        prelude="function renderSymbolsInline(text) { return String(text); }",
    )
    assert "3 colors, so 3 counters" in line, line
    cast = _w2g1_post(sid, "cast", card_name="Suntouched Myr", hand_index=0, auto_tap=True)
    assert cast.status_code == 200, cast.text
    settle(game)
    myr = next(p for p in game.controlled_by(game.players[0]) if p.card.name == "Suntouched Myr")
    assert counters_on(myr, "+1/+1") == 3
    assert sorted(plan["sunburst"]["colors"]) == sorted(
        symbol for symbol in "WUBRG"
        if any(tap.get("mana_color") == symbol for tap in plan["taps"])
    )


# ---------------------------------------------------------------------------
# Two casts that dropped themselves on "insufficient mana"
# ---------------------------------------------------------------------------

_W2G1_SENDS = (
    "var seat = 0; var pendingAutoTap = null; var SENT = []; var HINT = [];"
    "var pendingCastTarget = null; var _currentStack = [];"
    "function renderActivationPrompt() {} function clearPendingHandCast() { HINT.push('cleared'); }"
    "function updateActionHint(text) { HINT.push(text); }"
    "function getDefaultTargetSeat() { return 1; }"
    "function normalizeCardName(card) { return card && card.name ? card.name : ''; }"
    "function withPermanentId(body) { return body; }"
    "function getActivatedAbilityCost() { return '{G}'; }"
    "function cardRequiresSeveralTargets() { return false; }"
    "function sendAction(body) { SENT.push(body); return Promise.reject(new Error('insufficient mana for it')); }"
)


def test_w2g1_an_untargeted_modal_mode_and_a_stack_target_activation_offer_the_auto_tap():
    """Plunge into Darkness's "Pay any amount of life" mode (`dispatchModalCast`
    with no target) and Ouphe Vandals aimed at an ability on the stack
    (`selectStackSpellTarget`'s activate branch) each ended on "insufficient
    mana" with the mana still on the board. Both now open the auto-tap dialog
    with the body kept for its retry, as every other cast and activation
    send does."""
    modal = run_app_js(
        ["dispatchModalCast", "isManaRefusal"],
        """
        dispatchModalCast({name: "Plunge into Darkness"}, "cast", "none");
        await new Promise((resolve) => setTimeout(resolve, 0));
        return {auto: pendingAutoTap && pendingAutoTap.actionBody, hint: HINT};
        """,
        prelude=_W2G1_SENDS,
    )
    assert modal["auto"] == {"seat": 0, "action": "cast", "card_name": "Plunge into Darkness", "target_seat": 1}
    assert "cleared" not in modal["hint"], modal
    stack = run_app_js(
        ["selectStackSpellTarget", "isManaRefusal"],
        """
        _currentStack = [{type: "ability", label: "Rod of Ruin ability", card: {name: "Rod of Ruin"}}];
        pendingCastTarget = {card: {name: "Ouphe Vandals"}, cardName: "Ouphe Vandals",
                             castAction: "activate", sourcePermanentIndex: 0};
        selectStackSpellTarget(0);
        await new Promise((resolve) => setTimeout(resolve, 0));
        return pendingAutoTap && {body: pendingAutoTap.actionBody, cost: pendingAutoTap.cost};
        """,
        prelude=_W2G1_SENDS + (
            "function pendingPromptTargetsTheStack() { return true; }"
            "function isStackItemValidCastTarget() { return true; }"
        ),
    )
    assert stack == {
        "body": {"seat": 0, "action": "activate", "permanent_name": "Ouphe Vandals",
                 "permanent_index": 0, "target_stack_index": 0},
        "cost": "{G}",
    }


#: Enough of the page for a prompt renderer: every element a recorder of what
#: it was told.
_W2G1_PRELUDE = r"""
var seat = 0;
var SENT = [];
function makeEl(id) {
  return {
    id, textContent: "", disabled: false, _html: "", onclick: null, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    addEventListener() {}, querySelectorAll() { return []; }, querySelector() { return null; },
  };
}
const ELS = {};
function q(id) { if (!ELS[id]) ELS[id] = makeEl(id); return ELS[id]; }
const document = { getElementById: (id) => q(id) };
function escapeHtml(s) { return String(s); }
function setSymbolsHtml(el, text) { el.textContent = text; }
function updateActionHint() {}
async function sendAction(body) { SENT.push(body); }
"""
