"""Comprehensive Rules 701.22 — Scry.

Synthetic cards rather than pool ones: the rule is about what scrying does to a
library, not about any set's printing of it.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import CardDefinition, PlayerState


def _mk_card(name: str, type_line: str = "Sorcery", oracle_text: str = "") -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw=raw,
    )


def _game_with_library(oracle_text: str, library_size: int = 5):
    spell = _mk_card("Scry Spell", "Sorcery", oracle_text)
    library = [_mk_card(f"Card {i}", "Creature — Bear") for i in range(library_size)]
    p1 = PlayerState(name="P1", hand=[spell], library=library)
    p2 = PlayerState(name="P2", library=[_mk_card("Filler", "Creature — Bear")])
    return Game(players=[p1, p2]), library


@pytest.mark.cr("701.22a")
def test_scry_asks_the_controller_rather_than_silently_keeping():
    """"Scry N" is a decision, so it must queue one. Keeping the cards is a
    legal *outcome* of a scry but never a legal implementation of one — a
    handler that kept them would report the card supported while playing a
    different card."""
    game, _ = _game_with_library("Scry 2.")
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    assert game.pending_scry is not None
    assert game.pending_scry["top_count"] == 2
    assert game.pending_scry["caster_index"] == 0


@pytest.mark.cr("701.22a")
def test_scry_bottoms_the_chosen_cards_and_keeps_the_rest_in_order():
    game, library = _game_with_library("Scry 3.")
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    # Keep index 2 on top; bottom indices 0 and 1, in that order.
    assert game.confirm_scry(0, [2, 0, 1], bottom_count=2)
    player = game.players[0]
    assert player.library[0] is library[2]
    assert player.library[1] is library[3]   # untouched cards keep their order
    assert player.library[-2] is library[0]
    assert player.library[-1] is library[1]
    assert len(player.library) == len(library)
    assert game.pending_scry is None


@pytest.mark.cr("701.22a")
def test_scry_keeping_everything_leaves_the_library_reordered_only():
    game, library = _game_with_library("Scry 2.")
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    assert game.confirm_scry(0, [1, 0], bottom_count=0)
    player = game.players[0]
    assert player.library[0] is library[1]
    assert player.library[1] is library[0]
    assert player.library[2] is library[2]


@pytest.mark.cr("701.22a")
def test_scry_refuses_an_arrangement_that_is_not_a_permutation():
    """A malformed answer leaves the choice queued rather than silently
    dropping the prompt."""
    game, _ = _game_with_library("Scry 3.")
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    assert not game.confirm_scry(0, [0, 0, 1], bottom_count=1)
    assert game.pending_scry is not None


@pytest.mark.cr("701.22b")
def test_scry_with_an_empty_library_is_not_a_scry_event():
    """"If a player is instructed to scry 0, no scry event occurs." The same
    holds with nothing to look at — nothing is asked, and the resolution is not
    left waiting on a prompt nobody can answer."""
    game, _ = _game_with_library("Scry 2.", library_size=0)
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    assert game.pending_scry is None


@pytest.mark.cr("701.22a")
def test_scry_looks_at_fewer_cards_than_asked_on_a_short_library():
    game, _ = _game_with_library("Scry 3.", library_size=2)
    game.start_turn(0)
    game.cast_from_hand(0, "Scry Spell")

    assert game.pending_scry["top_count"] == 2
    assert game.pending_scry["amount"] == 3
