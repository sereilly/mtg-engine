"""A hand card's cost badge says when the board changed what its cast costs.

The wire has carried the charged cost since Scourge's Phase 5 (``mana_cost``,
``web/serialization._cast_price`` over ``cost_modifiers.cast_mana_charge``)
and two flags beside it, ``cost_increased`` and ``cost_reduced`` — and the
client read neither flag: the badge drew the charged cost exactly as it draws
a printed one, so a Goblin Brigand under a Goblin Warchief read ``{R}`` as if
the card printed it.

Now the wire also says what the modifiers were applied to
(``cost_before_modifiers``: the printed cost, or the alternative cost a
permission charges — a flashback cost), and the client's two readers turn the
flags into the badge's ring class and the preview's line. Both are run in node
over the payloads the server serves on three boards.
"""
from __future__ import annotations

import shutil

import pytest

from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, run_app_js, seat_plays_first

_CARDS = {card.name: card for card in load_catalog()}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)


def _session(board, hand=(), graveyard=()):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_name": "H", "host_colors": 2, "guest_colors": 2, "seed": 4405,
    }).json()
    sid = created["session_id"]
    game = seat_plays_first(sid).game
    game.players[0].battlefield = []
    for name in board:
        game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS[name]), None)
    game._recompute_continuous_effects()
    game.players[0].hand = [_CARDS[name] for name in hand]
    game.players[0].graveyard = [_CARDS[name] for name in graveyard]
    return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()["players"][0]


def _named(cards, name):
    return next(card for card in cards if isinstance(card, dict) and card["name"] == name)


def _client_reading(card):
    return run_app_js(
        ["castPriceChange", "castPriceNote"],
        "return { change: castPriceChange(INPUT), note: castPriceNote(INPUT) };",
        card,
    )


@needs_node
def test_a_reduced_cast_is_ringed_and_says_what_it_was_reduced_from():
    me = _session(["Goblin Warchief"], hand=["Goblin Brigand", "Shock"])
    brigand = _named(me["hand"], "Goblin Brigand")
    assert (brigand["printed_mana_cost"], brigand["mana_cost"]) == ("{1}{R}", "{R}")
    assert (brigand["cost_reduced"], brigand["cost_increased"]) == (True, False)
    assert brigand["cost_before_modifiers"] == "{1}{R}"
    assert _client_reading(brigand) == {
        "change": "reduced", "note": "Costs {R} to cast now (reduced from {1}{R}).",
    }
    # A spell the Warchief does not reach is the printed cost, unringed.
    shock = _named(me["hand"], "Shock")
    assert (shock["mana_cost"], shock["cost_before_modifiers"]) == ("{R}", "{R}")
    assert _client_reading(shock) == {"change": None, "note": ""}


@needs_node
def test_an_increased_cast_is_ringed_the_other_way():
    me = _session(["Gloom"], hand=["Holy Strength"])
    strength = _named(me["hand"], "Holy Strength")
    assert (strength["mana_cost"], strength["cost_increased"], strength["cost_reduced"]) == (
        "{3}{W}", True, False,
    )
    assert _client_reading(strength) == {
        "change": "increased", "note": "Costs {3}{W} to cast now (increased from {W}).",
    }


@needs_node
def test_a_flashback_price_is_compared_with_the_flashback_cost():
    """A graveyard copy is charged its flashback cost (CR 702.34a), so that is
    what a tax changed — not the printed cost the card would be cast for from
    a hand."""
    me = _session(["Gloom"], graveyard=["Ray of Revelation"])
    ray = _named(me["graveyard"], "Ray of Revelation")
    assert ray["printed_mana_cost"] == "{1}{W}"
    assert (ray["mana_cost"], ray["cost_before_modifiers"], ray["cost_increased"]) == (
        "{3}{G}", "{G}", True,
    )
    assert _client_reading(ray)["note"] == "Costs {3}{G} to cast now (increased from {G})."


@needs_node
def test_both_directions_at_once_read_as_changed():
    card = {
        "name": "An invented Cleric", "mana_cost": "{4}", "printed_mana_cost": "{1}{W}{B}",
        "cost_before_modifiers": "{1}{W}{B}", "cost_increased": True, "cost_reduced": True,
    }
    assert _client_reading(card) == {
        "change": "changed", "note": "Costs {4} to cast now (changed from {1}{W}{B}).",
    }
