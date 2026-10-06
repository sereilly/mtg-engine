"""The castable glow, card by card, where the old arithmetic was wrong.

``web/state_view`` counted an untapped land once per colour it lists, so three
Tropical Islands were six mana to a {4}{G}{G} spell. It asks
``engine.board_payment.board_can_pay`` now. The pool-wide census is
``tests/engine/test_castable_highlight_asks_the_planner.py``; these are the
named boards, driven over the wire and through the cast the glow promises —
each one tapping its lands the way a player would and then casting.

Both directions are here on purpose: a glow that lies (the measured defect) and
a card left dark that the board can pay for (what a stricter check would
introduce, and what the old sum already did to a land that makes two mana a
tap).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.models import Permanent
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}


def _w2g3_session(lands, hand, *, others=(), pool=None):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4244,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.players[0].battlefield = [
        Permanent(card=_CARDS[name]) for name in [*lands, *others]
    ]
    game.players[1].battlefield = []
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].mana_pool.update(pool or {})
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _w2g3_glowing(sid, hand) -> list[str]:
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return [hand[index] for index in state["players"][0]["playable_hand_indices"]]


def _w2g3_tap_all(game, color_for) -> None:
    for land in list(game.controlled_by(0)):
        if land.has_type("land") and not land.tapped:
            game.tap_land_for_mana(
                0, land.card.name, color_for(land), permanent_id=land.permanent_id,
            )


def test_w2g3_three_dual_lands_are_three_mana_not_six():
    """W1G4's named case. Craw Wurm ({4}{G}{G}) over three Tropical Islands
    glowed; tapped for everything they make, the cast is refused."""
    sid, game = _w2g3_session(["Tropical Island"] * 3, ["Craw Wurm"])
    assert _w2g3_glowing(sid, ["Craw Wurm"]) == []
    _w2g3_tap_all(game, lambda land: "G")
    refused = game.cast_from_hand(0, "Craw Wurm")
    assert not refused.supported and "insufficient mana" in refused.details

    sid, game = _w2g3_session(["Tropical Island"] * 6, ["Craw Wurm"])
    assert _w2g3_glowing(sid, ["Craw Wurm"]) == ["Craw Wurm"]
    _w2g3_tap_all(game, lambda land: "G")
    assert game.cast_from_hand(0, "Craw Wurm").supported


def test_w2g3_one_dual_land_does_not_pay_both_of_its_colours():
    """{G}{U} over one Tropical Island was the smallest board that lied."""
    hand = ["Wood Sage", "Grizzly Bears", "Wall of Kelp"]
    sid, _game = _w2g3_session(["Tropical Island"], hand)
    assert _w2g3_glowing(sid, hand) == []

    sid, game = _w2g3_session(["Tropical Island"] * 2, hand)
    # {G}{U}, {1}{G} and {U}{U}: two Islands that are also Forests pay any.
    assert _w2g3_glowing(sid, hand) == hand
    colours = iter("GU")
    _w2g3_tap_all(game, lambda land: next(colours))
    assert game.cast_from_hand(0, "Wood Sage").supported


def test_w2g3_floating_mana_and_a_land_are_matched_together():
    """Mana already in the pool is a source like any other: a floating {U} and
    one Tropical Island pay {G}{U}, and a floating {G} does not pay {U}{U}."""
    hand = ["Wood Sage", "Wall of Kelp"]
    sid, _game = _w2g3_session(["Tropical Island"], hand, pool={"U": 1})
    assert _w2g3_glowing(sid, hand) == hand
    sid, _game = _w2g3_session(["Tropical Island"], hand, pool={"G": 1})
    assert _w2g3_glowing(sid, hand) == ["Wood Sage"]


def test_w2g3_the_flexible_land_is_kept_for_the_pip_only_it_can_pay():
    """A Swamp and an Underground Sea pay {U}{B} — the board a greedy pass
    strands by spending the dual on the {B} — and do not pay {U}{U}."""
    hand = ["Vodalian Zombie", "Wall of Kelp"]
    sid, game = _w2g3_session(["Swamp", "Underground Sea"], hand)
    assert _w2g3_glowing(sid, hand) == ["Vodalian Zombie"]
    _w2g3_tap_all(game, lambda land: "U" if land.card.name == "Underground Sea" else "B")
    assert game.cast_from_hand(0, "Vodalian Zombie").supported


def test_w2g3_a_land_that_makes_two_mana_pays_for_two():
    """The other direction, and one the old sum already had wrong: Ancient
    Tomb makes {C}{C} and counted as one, so a {2} artifact stayed dark over
    it."""
    sid, game = _w2g3_session(["Ancient Tomb"], ["Howling Mine"])
    assert _w2g3_glowing(sid, ["Howling Mine"]) == ["Howling Mine"]
    _w2g3_tap_all(game, lambda land: "C")
    assert game.cast_from_hand(0, "Howling Mine").supported


def test_w2g3_a_condition_on_the_board_decides_what_a_tap_makes():
    """The Urza lands: {C} each, and seven between them once all three are
    out ("…add {C}{C} instead", three on the Tower). Craw Wurm needs green, so
    the six generic is what is being counted: a Forest and one more beside the
    assembled three pay it, and beside an unassembled pair they do not."""
    tron = ["Urza's Mine", "Urza's Power Plant", "Urza's Tower"]
    sid, game = _w2g3_session([*tron, "Forest", "Forest"], ["Craw Wurm"])
    assert _w2g3_glowing(sid, ["Craw Wurm"]) == ["Craw Wurm"]
    _w2g3_tap_all(game, lambda land: "G" if land.card.name == "Forest" else "C")
    assert game.cast_from_hand(0, "Craw Wurm").supported

    sid, _game = _w2g3_session([*tron[:2], "Forest", "Forest"], ["Craw Wurm"])
    assert _w2g3_glowing(sid, ["Craw Wurm"]) == []


def test_w2g3_restricted_mana_counts_only_toward_what_it_may_pay():
    """Mishra's Workshop: "{T}: Add {C}{C}{C}. Spend this mana only to cast
    artifact spells." Three toward Howling Mine and nothing toward Grizzly
    Bears, which the old sum counted one generic for beside a Forest."""
    hand = ["Howling Mine", "Grizzly Bears"]
    sid, game = _w2g3_session(["Mishra's Workshop", "Forest"], hand)
    assert _w2g3_glowing(sid, hand) == ["Howling Mine"]
    _w2g3_tap_all(game, lambda land: "G" if land.card.name == "Forest" else "C")
    assert not game.cast_from_hand(0, "Grizzly Bears").supported
    assert game.cast_from_hand(0, "Howling Mine").supported


def test_w2g3_a_storage_land_with_nothing_stored_is_not_a_mana():
    """A land the tap seam refuses is not counted: Sand Silos makes mana only
    by removing counters it does not have yet, and its summary lists {U}."""
    hand = ["Wall of Kelp"]
    sid, _game = _w2g3_session(["Sand Silos", "Island"], hand)
    assert _w2g3_glowing(sid, hand) == []
    sid, _game = _w2g3_session(["Island", "Island"], hand)
    assert _w2g3_glowing(sid, hand) == hand


def test_w2g3_an_aura_on_the_land_adds_what_the_tap_adds():
    """Wild Growth: "Whenever enchanted land is tapped for mana, its
    controller adds an additional {G}." The seam adds it on every tap, so one
    enchanted Forest pays for Grizzly Bears — and the old sum, which read the
    land alone, left it dark."""
    from engine.auras import attach_aura

    sid, game = _w2g3_session(["Forest"], ["Grizzly Bears"], others=["Wild Growth"])
    forest, growth = game.players[0].battlefield
    attach_aura(growth, forest)
    forest.metadata["attached_aura"] = growth
    assert _w2g3_glowing(sid, ["Grizzly Bears"]) == ["Grizzly Bears"]
    _w2g3_tap_all(game, lambda land: "G")
    assert game.cast_from_hand(0, "Grizzly Bears").supported


def test_w2g3_a_spending_permission_is_read_per_unit_of_mana():
    """Chromatic Orrery's "as though it were mana of any color" was the one
    permission the old arithmetic knew; it still holds, and {C} in a cost still
    wants colourless."""
    sid, game = _w2g3_session(["Forest", "Forest"], ["Wall of Kelp"])
    assert _w2g3_glowing(sid, ["Wall of Kelp"]) == []
    # The Orrery's own mana is an artifact's, which the glow does not count
    # (lands only); what it changes here is what the two Forests may pay.
    sid, game = _w2g3_session(
        ["Forest", "Forest"], ["Wall of Kelp"], others=["Chromatic Orrery"],
    )
    assert game.players[0].spends_mana_as_any_color
    assert _w2g3_glowing(sid, ["Wall of Kelp"]) == ["Wall of Kelp"]
    _w2g3_tap_all(game, lambda land: "G")
    assert game.cast_from_hand(0, "Wall of Kelp").supported


def test_w2g3_white_as_red_is_the_other_permission_the_sum_knew():
    """Sunglasses of Urza: a Plains pays a red pip, and nothing else does."""
    sid, _game = _w2g3_session(["Plains"], ["Lightning Bolt"])
    assert _w2g3_glowing(sid, ["Lightning Bolt"]) == []
    sid, game = _w2g3_session(
        ["Plains"], ["Lightning Bolt"], others=["Sunglasses of Urza"],
    )
    assert game.players[0].can_spend_white_as_red
    assert _w2g3_glowing(sid, ["Lightning Bolt"]) == ["Lightning Bolt"]
    sid, _game = _w2g3_session(
        ["Forest"], ["Lightning Bolt"], others=["Sunglasses of Urza"],
    )
    assert _w2g3_glowing(sid, ["Lightning Bolt"]) == []


def test_w2g3_a_hand_ability_button_is_priced_by_the_same_matching():
    """Cycling {2} beside one Tropical Island: one mana, so the button is not
    payable — the old sum read the Island as a {G} and a {U} and said it was."""
    sid, _game = _w2g3_session(["Tropical Island"], ["Clear"])
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = state["hand_abilities"]
    assert entry["name"] == "Clear" and entry["payable"] is False

    sid, _game = _w2g3_session(["Tropical Island"] * 2, ["Clear"])
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    (entry,) = state["hand_abilities"]
    assert entry["payable"] is True


@pytest.mark.parametrize("land", ["Lotus Vale"])
def test_w2g3_mana_of_any_one_color_shares_its_colour(land):
    """"Add three mana of any one color": three, and all alike. {U}{U}
    ({2}{U}{U} would be four) glows; a cost wanting two different colours of
    it does not."""
    hand = ["Wall of Kelp", "Wood Sage"]
    sid, _game = _w2g3_session([land], hand)
    assert _w2g3_glowing(sid, hand) == ["Wall of Kelp"]
