"""The X prompt's range is the server's: what the pool pays, and the board.

The client priced X itself (``getMaxAffordableX`` over ``manaPoolCanPayCost``
and ``xSpendColorForCard``): the printed mana cost against the floating pool,
X generic unless the text read "spend only <one colour> mana on X", and for
an activated ability no colour at all. So under a Sphere of Resistance it
offered a Fireball one X too many (the cast then refused), it read Soul
Burn's "black and/or red" as generic, and Crimson Hellkite's "Spend only red
mana on X" not at all — and it offered nothing the untapped lands could pay,
though the payment step taps them ("Tap more mana sources to raise the
limit").

The wire now carries ``x_payable`` on a hand card and on each zone-cast way
whose price prints {X}, and ``ability_x_payable`` per ability on a
permanent: ``{pool, board, colors}`` (``web/offers``), priced at each X by
the charge the engine makes — ``cost_modifiers.cast_mana_charge``,
``Game.alternative_cost_mana``, ``Game.activation_mana_charge`` (extracted
from the activation path for this) — over ``board_payment.board_can_pay``'s
matching. Backwards on the base: neither key exists, and the boards below
read the client's numbers (4, 6, 5) where the engine pays (3, 4, 2).

Beside it, the engine's own answer to "the largest X this pool pays"
(``Game._infer_x_value``, what a cast that announces no X is given) counted
each {X} once: Recall and Part Water ({X}{X}{U}) were inferred X = 10 off
eleven mana, which the payment then refused. It divides by the {X}s printed.
"""
from __future__ import annotations

import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.cost_modifiers import cost_reduction_for_cast, spell_cost_tax, spell_symbol_tax
from engine.models import Permanent
from engine.oracle_types import x_spend_colors_from_text
from tests.helpers import app_js_function_body, client, resolve_stack, run_app_js, stable_sample
from web.app import store

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _table(hand, *, pool, battlefield=(), opponent=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4410,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    for player in game.players:
        player.battlefield = []
        player.hand = []
    game.enforce_mana_costs = False
    for seat, names in ((0, battlefield), (1, opponent)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    game.enforce_mana_costs = True
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].mana_pool.update(pool)
    game._recompute_continuous_effects()
    game.stack.clear()
    game.pending_choices.clear()
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _me(sid):
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["players"][0]


def _cast(sid, game, name, x, **extra):
    body = {"seat": 0, "action": "cast", "card_name": name, "x_value": x, "target_seat": 1}
    body.update(extra)
    return client.post(f"/api/sessions/{sid}/action", json=body)


def test_an_x_spell_under_a_sphere_of_resistance():
    board = dict(pool={"G": 5}, battlefield=["Forest", "Forest"], opponent=["Sphere of Resistance"])
    sid, game = _table(["Hurricane", "Fireball"], **board)
    hand = {card["name"]: card for card in _me(sid)["hand"]}
    # {X}{G} and {1} more: five green pays X = 3; the two Forests two more.
    assert hand["Hurricane"]["x_payable"] == {"pool": 3, "board": 5, "colors": []}
    # Fireball's {R} is not in a green pool at all.
    assert hand["Fireball"]["x_payable"] == {"pool": 0, "board": 0, "colors": []}
    too_many = _cast(sid, game, "Hurricane", 4)
    assert too_many.status_code == 400 and "insufficient mana" in too_many.json()["detail"]
    assert _cast(sid, game, "Hurricane", 3).status_code == 200
    # The board's top is what the auto-tap pays, and one more is not.
    sid, game = _table(["Hurricane"], **board)
    assert _cast(sid, game, "Hurricane", 5, auto_tap=True).status_code == 200
    sid, game = _table(["Hurricane"], **board)
    assert _cast(sid, game, "Hurricane", 6, auto_tap=True).status_code == 400


def test_soul_burn_pays_x_in_black_and_red_alone():
    sid, game = _table(["Soul Burn"], pool={"B": 2, "R": 3, "G": 4})
    payable = {card["name"]: card for card in _me(sid)["hand"]}["Soul Burn"]["x_payable"]
    # {B} from black, {2} from green: X from the black and red left, four.
    assert payable == {"pool": 4, "board": 4, "colors": ["B", "R"]}
    assert _cast(sid, game, "Soul Burn", 5).status_code == 400
    assert _cast(sid, game, "Soul Burn", 4).status_code == 200


def test_crimson_hellkite_spends_only_red_on_x():
    sid, game = _table(
        [], pool={"R": 2, "G": 3}, battlefield=["Crimson Hellkite"], opponent=["Craw Wurm"],
    )
    me = _me(sid)
    kite = next(entry for entry in me["battlefield"] if entry["name"] == "Crimson Hellkite")
    assert kite["ability_x_payable"] == [{"pool": 2, "board": 2, "colors": ["R"]}]
    wurm = next(p for p in game.controlled_by(1) if p.card.name == "Craw Wurm")

    def activate(x):
        return client.post(f"/api/sessions/{sid}/action", json={
            "seat": 0, "action": "activate", "permanent_name": "Crimson Hellkite",
            "permanent_id": kite["id"], "x_value": x, "target_permanent_id": wurm.permanent_id,
        })

    assert activate(3).status_code == 400
    assert activate(2).status_code == 200


def test_an_ability_tax_is_in_the_activation_s_price():
    """Gloom's "{3} more" on a white enchantment's {X} ability: the price the
    activation path charges, read through ``Game.activation_mana_charge``."""
    sid, game = _table([], pool={"W": 5}, battlefield=["Gloom"])
    # "{X}: This enchantment becomes an X/X Wall creature …" — white.
    perm = Permanent(card=_CARDS["Testament of Faith"])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, perm, None)
    resolve_stack(game)
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update({"W": 5})
    entry = next(e for e in _me(sid)["battlefield"] if e["id"] == perm.permanent_id)
    usable = game.usable_abilities_of(perm, card=perm.effective_card)
    index = next(i for i, ability in enumerate(usable) if "{x}" in (ability.source_line or "").lower().split(":", 1)[0])
    untaxed = sum(int(v) for v in usable[index].cost.mana.values())
    assert entry["ability_x_payable"][index]["pool"] == max(0, 5 - 3 - untaxed)


def _pays(game, card, x, tax, pips, reduction) -> bool:
    """Whether the cast path's own payment (``_pay_cast_cost``) pays *card*
    at X = *x* from the pool as it stands — the pool put back either way."""
    player = game.players[0]
    saved = dict(player.mana_pool)
    try:
        return game._pay_cast_cost(
            player, card, x, x_spend_colors_from_text(card.oracle_text),
            extra_generic=tax, reduction=reduction, extra_pips=pips,
        ) is not None
    finally:
        player.mana_pool = saved


def _hand_census(every: int):
    """Every pool card with {X} in its mana cost, in one hand, on two boards:
    a plain pool, and the same pool under a Sphere of Resistance. The server's
    ``pool`` is the X the cast path itself infers from that pool
    (``Game._infer_x_value``, with the cast's own taxes and reductions)."""
    subjects = [
        unit for unit in faces.compilation_units(_CATALOG)
        if unit is _CARDS.get(unit.name) and "{X}" in (unit.mana_cost or "").upper()
        and stable_sample(unit.name, every)
    ]
    pool = {"W": 2, "U": 2, "B": 2, "R": 2, "G": 2, "C": 1}
    judged = 0
    for opponent in ((), ("Sphere of Resistance",)):
        sid, game = _table([unit.name for unit in subjects], pool=pool, opponent=opponent)
        hand = _me(sid)["hand"]
        player = game.players[0]
        for card, entry in zip(player.hand, hand):
            assert entry["name"] == card.name
            tax, _ = spell_cost_tax(game, 0, card)
            pips, _ = spell_symbol_tax(game, 0, card)
            reduction, _ = cost_reduction_for_cast(game, 0, card)
            inferred = game._infer_x_value(
                player, card.mana_cost, tax,
                x_colors=x_spend_colors_from_text(card.oracle_text),
                reduction=reduction, extra_pips=pips,
            )
            found = entry["x_payable"]["pool"]
            assert found == inferred, (card.name, opponent, entry["x_payable"], inferred)
            assert entry["x_payable"]["board"] >= found
            # …and the payment itself pays that X from this pool (where it pays
            # the card at all — Forced March's {B}{B}{B} is not in this pool),
            # and not one more.
            castable = _pays(game, card, 0, tax, pips, reduction)
            assert _pays(game, card, found, tax, pips, reduction) == castable, (card.name, found)
            assert castable or found == 0, (card.name, found)
            assert not _pays(game, card, found + 1, tax, pips, reduction), (card.name, found)
            judged += 1
    return judged


def test_every_x_spell_the_pool_s_x_is_the_cast_path_s():
    # Two boards of every {X} spell in the pool; a sweep that judged nothing
    # would pass as one that found nothing.
    assert _hand_census(1) >= 100


@needs_node
def test_the_prompt_offers_the_board_s_x_and_says_the_pool_s():
    sid, _game = _table(["Fireball"], pool={"R": 5}, battlefield=["Mountain", "Mountain"],
                        opponent=["Sphere of Resistance"])
    fireball = {card["name"]: card for card in _me(sid)["hand"]}["Fireball"]
    out = run_app_js(
        ["castXPayable", "xPayableSentence", "castXCeiling", "targetSpecOf", "xLivesInManaCost"],
        "return { box: castXCeiling(INPUT, castXPayable(INPUT).board),"
        " said: xPayableSentence(castXPayable(INPUT)) };",
        fireball,
        prelude='const EMPTY_TARGET_SPEC = { kind: "none", requires_target: false, valid_targets: [] };',
    )
    assert out["box"] == 5
    assert out["said"].startswith("Your mana pool pays for X up to 3;")
    assert "up to 5" in out["said"]


def test_the_client_prices_no_x_itself():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    for deleted in (
        "function getMaxAffordableX", "function xSpendColorForCard", "function manaPoolCanPayCost",
    ):
        assert deleted not in source, deleted
    assert "liveXPayable(pendingCastX)" in app_js_function_body("renderActivationPrompt")
