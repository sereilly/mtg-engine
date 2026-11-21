"""The wire for a flip card (CR 710): what a client is sent to draw one.

A flipped permanent's every characteristic field is already its bottom half's
(``engine/flip_cards.py`` substitutes the card), so what the wire adds is the
status itself — ``flipped``, CR 710.3's "clear at all times" — the physical
card under it (``printed_name``: what a zone change carries away, CR 710.4)
and both halves for the card viewer (``flip``). A card in hand is the top
half alone (CR 710.2) and carries the halves the same way.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.flip_cards import flip_permanent
from engine.models import Permanent
from web.serialization import _card_preview, _serialize_permanent

_CHK = {card.name: card for card in load_cards(manifest_set_path("CHK", include_measured=True))}


def _game_with_jushi():
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    jushi = Permanent(card=_CHK["Jushi Apprentice"])
    game._put_permanent_onto_battlefield(0, jushi, None)
    return game, jushi


def test_an_unflipped_flip_card_is_sent_as_its_top_half_with_both_halves():
    game, jushi = _game_with_jushi()
    payload = _serialize_permanent(jushi, game)
    assert (payload["name"], payload["printed_name"], payload["flipped"]) == (
        "Jushi Apprentice", "Jushi Apprentice", False,
    )
    assert payload["type"] == "Creature — Human Wizard"
    assert (payload["power"], payload["toughness"]) == (1, 2)
    assert payload["flip"]["top"]["name"] == "Jushi Apprentice"
    assert payload["flip"]["bottom"]["name"] == "Tomoya the Revealer"
    assert payload["flip"]["bottom"]["mana_cost"] == "{1}{U}"


def test_a_flipped_permanent_is_sent_flipped_over_its_printed_card():
    game, jushi = _game_with_jushi()
    flip_permanent(game, jushi)
    payload = _serialize_permanent(jushi, game)
    assert (payload["name"], payload["printed_name"], payload["flipped"]) == (
        "Tomoya the Revealer", "Jushi Apprentice", True,
    )
    assert payload["type"] == "Legendary Creature — Human Wizard"
    assert (payload["power"], payload["toughness"]) == (2, 3)
    assert payload["mana_cost"] == "{1}{U}" and payload["colors"] == ["U"]
    assert payload["flip"]["bottom"]["oracle_text"].startswith("{3}{U}{U}, {T}:")


def test_a_flip_card_in_a_zone_previews_both_halves():
    preview = _card_preview(_CHK["Akki Lavarunner"])
    assert preview["name"] == "Akki Lavarunner"
    assert preview["flip"]["top"]["type"] == "Creature — Goblin Warrior"
    assert preview["flip"]["bottom"]["name"] == "Tok-Tok, Volcano Born"
    assert preview["flip"]["bottom"]["power"] == "2"
    single = _card_preview(_CHK["Isamaru, Hound of Konda"])
    assert "flip" not in single
