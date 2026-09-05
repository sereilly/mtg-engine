"""The browser half of CR 601.2b's *optional* prices, and CR 107.3a's X.

Everything here was already true of the engine and untrue of the client.

**CR 107.3a** names four places an X can live — "a mana cost, alternative cost,
additional cost, and/or activation cost". ``web/static/app.js`` asked the first
one, as a substring probe of the printed mana-cost string, so Fire Covenant
({1}{B}{R}, "pay X life") and Infernal Harvest ({1}{B}, "return X Swamps you
control to their owner's hand") were offered no X box and cast at CR 107.3b's
default of 0 — legal, and nothing, on two spells that are nothing but X. Fire
Covenant is an **Ice Age** card, so that was live in the shipped pool.

**CR 118.9 and CR 601.2b's optional half** had a wire (``alternative_cost``,
``alternative_cost_hand_index``, ``optional_cost_payments``) that nothing ever
sent, because ``targeting._cost_picker_spec`` models a cost the caster will
certainly pay and an offer needs a shape of its own. Nine shipped cards were
therefore castable at their printed default price and at no other.

What is pinned here is the payload the picker reads: that an offer is described
at all, that its ceiling is computed from the pool and the board and *moves* as
the answer grows, that CR 601.2c's target count moves with it, and that the
spell is withheld from the hand paying for it (CR 601.2a).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine import load_cards
from engine.card_loader import load_catalog, manifest_set_path, manifest_set_paths
from engine.models import Permanent
from web.app import app, store
from web.state_view import parse_optional_cost_payments

client = TestClient(app)

APP_JS = (Path(__file__).resolve().parents[2] / "web" / "static" / "app.js").read_text(
    encoding="utf-8"
)

_SHIPPED = {c.name: c for c in load_catalog()}
# Infernal Harvest is Visions, which is `measured`: no session can be dealt it,
# so it is placed into a hand directly — the arrangement every other suite over
# a measured card makes.
_POOL = {
    card.name: card
    for path in manifest_set_paths(include_measured=True)
    for card in load_cards(path)
}
_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 4242,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.players[0].battlefield = []
    game.players[1].battlefield = []
    session.current_turn = 0
    game.active_player_index = 0
    return sid, session, game


def _spec(sid: str, card_name: str, **params) -> dict:
    response = client.get(
        f"/api/sessions/{sid}/card_target_spec",
        params={"card_name": card_name, "seat": 0, **params},
    )
    assert response.status_code == 200, response.text
    return response.json()["target_spec"]


# ---------------------------------------------------------------------------
# CR 107.3a — the X box is asked of the costs, not of the mana-cost string
# ---------------------------------------------------------------------------


def test_a_cost_side_x_is_announced_on_the_spec():
    """Fire Covenant ships in Ice Age and prints no {X} anywhere. The spec says
    an X is announced, and caps it at the life a payment could reach
    (CR 119.4)."""
    sid, _, game = _session()
    game.players[0].hand = [_SHIPPED["Fire Covenant"]]
    game.players[0].life = 11

    spec = _spec(sid, "Fire Covenant", hand_index=0)

    assert spec["announces_x"] is True
    assert spec["max_x"] == 11


def test_an_ordinary_spell_announces_no_x():
    """The flag is absent rather than false for every other spell, so a client
    that reads it truthily is unchanged for the whole rest of the pool."""
    sid, _, game = _session()
    game.players[0].hand = [_LEA["Lightning Bolt"]]

    assert "announces_x" not in _spec(sid, "Lightning Bolt", hand_index=0)


def test_the_client_asks_the_spec_for_the_x_and_not_the_mana_cost():
    """The frontend predicate, pinned as text because the browser is where the
    substring probe lived. ``hasXCost`` must read the backend's answer; the
    mana-cost read survives only under the name that says what it is for — the
    mana *pool's* bound on X, which does not apply to an X paid in life."""
    assert (
        'const spec = targetSpecOf(card);\n'
        '  if (typeof spec.announces_x === "boolean") return spec.announces_x;'
    ) in APP_JS
    assert "function xLivesInManaCost(card)" in APP_JS
    # The divided-damage cast had its own copy of the probe, which is the one
    # that made Fire Covenant offer a division of nought damage.
    assert "const fixedTotal = hasXCost(card) && !Number.isInteger(definedX)" in APP_JS
    assert '(card.mana_cost || "").includes("{X}")' not in APP_JS


# ---------------------------------------------------------------------------
# CR 118.9 — the alternative cost is an offer, and the spell cannot pay for it
# ---------------------------------------------------------------------------


def test_the_alternative_cost_offers_the_hand_cards_that_answer_it():
    """Force of Will exiles *a blue card*, so the offer carries the hand
    positions that answer — and not the ones that do not."""
    sid, _, game = _session()
    game.players[0].hand = [
        _SHIPPED["Force of Will"],
        _SHIPPED["Counterspell"],
        _SHIPPED["Lightning Bolt"],
    ]

    (offer,) = _spec(sid, "Force of Will", hand_index=0)["cost_offers"]

    assert offer["kind"] == "alternative"
    assert offer["payable"] is True
    assert offer["hand_choices"] == [{"index": 1, "name": "Counterspell"}]


def test_the_spell_is_withheld_from_the_hand_that_pays_for_it():
    """CR 601.2a puts the spell on the stack before its costs are paid, so Force
    of Will cannot be the blue card it exiles — while a **second copy** in hand
    legitimately can. A deck repeats one immutable definition per copy, so only
    the hand position tells them apart, which is why the index is sent."""
    sid, _, game = _session()
    force = _SHIPPED["Force of Will"]
    game.players[0].hand = [force]

    (offer,) = _spec(sid, "Force of Will", hand_index=0)["cost_offers"]
    assert offer["payable"] is False
    assert offer["hand_choices"] == []

    game.players[0].hand = [force, force]
    (offer,) = _spec(sid, "Force of Will", hand_index=0)["cost_offers"]
    assert offer["payable"] is True
    assert offer["hand_choices"] == [{"index": 1, "name": "Force of Will"}]


def test_a_payable_alternative_cost_makes_the_card_playable_with_no_mana():
    """CR 118.9: paid *rather than* the mana cost. The playable highlight asked
    only whether the mana cost could be met, so the five shipped cards with an
    alternative cost were greyed out on exactly the boards they are famous for
    being cast from."""
    sid, _, game = _session()
    game.players[0].hand = [_SHIPPED["Pyrokinesis"], _SHIPPED["Lightning Bolt"]]
    game.players[0].mana_pool.clear()

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert 0 in state["players"][0]["playable_hand_indices"]

    # …and not when nothing in hand answers the exile.
    game.players[0].hand = [_SHIPPED["Pyrokinesis"], _SHIPPED["Counterspell"]]
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert 0 not in state["players"][0]["playable_hand_indices"]


# ---------------------------------------------------------------------------
# CR 601.2b — the optional additional mana cost, its ceiling and its targets
# ---------------------------------------------------------------------------


def _primitive_justice_session(mountains: int = 4, forests: int = 2):
    sid, _, game = _session()
    game.players[0].hand = [_SHIPPED["Primitive Justice"]]
    game.players[0].battlefield = (
        [Permanent(card=_LEA["Mountain"]) for _ in range(mountains)]
        + [Permanent(card=_LEA["Forest"]) for _ in range(forests)]
    )
    game._settle()
    return sid


def test_each_offer_carries_a_ceiling_computed_from_pool_and_board():
    """Primitive Justice costs {1}{R} and offers {1}{R} and/or {1}{G} any number
    of times. Six mana on the board buys the spell plus two more payments — and
    the count is the same augmenting-path matching the payment itself runs, so
    an offer shown as payable is one the cast accepts."""
    sid = _primitive_justice_session()

    spec = _spec(sid, "Primitive Justice", hand_index=0)
    offers = {o["symbols"]: o for o in spec["cost_offers"]}

    assert offers["{1}{R}"]["max_times"] == 2
    assert offers["{1}{G}"]["max_times"] == 2
    assert offers["{1}{R}"]["repeatable"] is True


def test_taking_one_offer_lowers_what_the_others_can_still_be_paid():
    """The ceilings are joint, not three standalone maxima that cannot all be
    taken: one {1}{R} spends two of the six mana, so {1}{G} drops from two to
    one. That is the whole reason the client re-asks after each click."""
    sid = _primitive_justice_session()

    spec = _spec(
        sid, "Primitive Justice", hand_index=0,
        optional_cost_payments='{"{1}{R}": 1}',
    )
    offers = {o["symbols"]: o for o in spec["cost_offers"]}

    assert offers["{1}{G}"]["max_times"] == 1
    assert offers["{1}{R}"]["times"] == 1


def test_the_target_count_is_recomputed_from_the_answer():
    """CR 601.2c: "Destroy target artifact. For each additional {1}{R} you paid,
    destroy another target artifact." How many targets are named is decided by
    CR 601.2b's payment, one step earlier, and reaches the picker as an ordinary
    ``max_targets`` — through ``oracle_types.cost_target_count``, the same
    arithmetic ``_validate_cast_targets`` gates the announcement by."""
    sid = _primitive_justice_session(mountains=6, forests=0)

    assert "max_targets" not in _spec(sid, "Primitive Justice", hand_index=0), (
        "one artifact is the printed announcement and takes the single picker"
    )
    for paid, expected in (('{"{1}{R}": 1}', 2), ('{"{1}{R}": 2}', 3)):
        spec = _spec(
            sid, "Primitive Justice", hand_index=0, optional_cost_payments=paid,
        )
        assert spec["max_targets"] == expected, paid


def test_an_unaffordable_offer_is_reported_as_unpayable_rather_than_hidden():
    """A ceiling of zero, not a missing row: the caster is told the price exists
    and that this board cannot meet it, which is what the printed card says."""
    sid, _, game = _session()
    game.players[0].hand = [_SHIPPED["Undergrowth"]]
    game.players[0].battlefield = [Permanent(card=_LEA["Forest"])]
    game._settle()

    (offer,) = _spec(sid, "Undergrowth", hand_index=0)["cost_offers"]

    assert offer["symbols"] == "{2}{R}"
    assert offer["repeatable"] is False
    assert offer["max_times"] == 0


def test_a_malformed_offer_map_is_dropped_rather_than_refused():
    """The map is a **picker hint** — it sizes what the browser offers, and the
    cast is gated against the map the *action* carries. So junk on the query
    string costs a wrong range and never a 500."""
    assert parse_optional_cost_payments(None) is None
    assert parse_optional_cost_payments("not json") is None
    assert parse_optional_cost_payments("[1, 2]") is None
    assert parse_optional_cost_payments('{"{1}{R}": 0}') is None
    assert parse_optional_cost_payments('{"{1}{R}": 2}') == {"{1}{R}": 2}


# ---------------------------------------------------------------------------
# The client sends what the offer prompt collected
# ---------------------------------------------------------------------------


def test_the_client_sends_the_announcement_on_the_cast_action():
    """The three fields the wire has carried since Alliances shipped and nothing
    ever sent. They ride ``pendingCastCost``, which every cast path already
    merges into whatever body it finally posts — so the announcement survives
    the target prompt that comes after it (CR 601.2b precedes CR 601.2c)."""
    assert "announced.optional_cost_payments = { ...pending.taken }" in APP_JS
    assert "announced.alternative_cost = true" in APP_JS
    assert "announced.alternative_cost_hand_index = pending.alternative" in APP_JS
    assert "pendingCastCost = { ...(pendingCastCost || {}), ...announced }" in APP_JS


def test_the_offer_prompt_runs_before_the_target_cascade():
    """CR 601.2b is announced before CR 601.2c, and here the order is not merely
    correct but load-bearing: how many artifacts Primitive Justice names is
    decided by what was paid for it. All three places a cast can begin run it
    first."""
    assert APP_JS.count("startCastOfferPrompt(card))") == 3
    for entry in (
        "if (startCastOfferPrompt(card)) {\n          return;\n        }",
        "if (startCastOfferPrompt(card)) return;\n    if (startCastCostPrompt(card)) return;",
        "if (card && startCastOfferPrompt(card)) { return; }",
    ):
        assert entry in APP_JS, entry


def test_the_offer_prompt_is_rendered_before_the_priority_prompt_takes_the_panel():
    """The priority prompt names every client-side cast prompt it must stand
    aside for, and a prompt rendered *below* that guard never appears at all —
    which is exactly what happened to this one until it moved up beside the
    other two CR 601.2b prompts."""
    offers_at = APP_JS.index("  if (pendingCastOffers) {")
    priority_at = APP_JS.index(
        "  if (!pendingActivation && !pendingCastTarget && !pendingCastX"
    )
    assert offers_at < priority_at
