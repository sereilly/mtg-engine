"""A prohibition on casting binds casts, and a land is never one (CR 601.3,
CR 305.1).

``engine/cast_prohibitions.py`` asks each printed prohibition only of the
action it binds. Before it, the cast path's run of refusals asked every one of
them of every card that reached it — and a land drop reaches it too — so "Each
player can't cast more than one spell each turn" (Arcane Laboratory) refused a
*land* once its player had cast the turn's spell: "can't cast Forest: Arcane
Laboratory caps this turn's spells". Measured in simulation, not only on a
bench: six seeded INV games with Yawgmoth's Agenda pinned logged that refusal
twice, a seat that could not make its land drop.

The sentences that *do* stop a land say so, and still do.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.cast_prohibitions import LAND, SPELL, action_of, cast_prohibition
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w2g3_table(cards, mine=(), theirs=(), hand=()):
    game = Game(players=[
        PlayerState(name="A", library=[cards["Grizzly Bears"]] * 10),
        PlayerState(name="B", library=[cards["Grizzly Bears"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].battlefield = [Permanent(card=cards[name]) for name in mine]
    game.players[1].battlefield = [Permanent(card=cards[name]) for name in theirs]
    game._recompute_continuous_effects()
    game.players[0].hand = [cards[name] for name in hand]
    game.players[0].mana_pool.update({"W": 5, "U": 5, "B": 5, "R": 5, "G": 5})
    game.turn = 3
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return game, cards


@pytest.mark.cr("305.1", "601.3")
@pytest.mark.parametrize("cap,seat", [("Arcane Laboratory", 1), ("Yawgmoth's Agenda", 0)])
def test_w2g3_a_spell_cap_stops_the_second_spell_and_not_the_land_drop(catalog_by_name, cap, seat):
    """One spell cast under the cap: the next *spell* is refused, and the land
    is played — it was never a spell, so it was never the one too many."""
    mine = [cap] if seat == 0 else []
    theirs = [cap] if seat == 1 else []
    game, cards = _w2g3_table(
        catalog_by_name, mine=mine, theirs=theirs, hand=["Sol Ring", "Ornithopter", "Forest"],
    )
    assert game.cast_from_hand(0, "Sol Ring").supported
    resolve_stack(game)

    refused = game.cast_from_hand(0, "Ornithopter")
    assert not refused.supported and "caps this turn's spells" in refused.details
    assert cast_prohibition(game, 0, cards["Ornithopter"]).kind == "spell_cap_ban"

    assert cast_prohibition(game, 0, cards["Forest"]) is None
    played = game.cast_from_hand(0, "Forest")
    assert played.supported, played.details
    assert [card.name for card in game.players[0].hand] == ["Ornithopter"]
    assert "Forest" in [perm.card.name for perm in game.controlled_by(0)]
    # …and the land drop was not counted as a cast either.
    assert [card.name for card in game.players[0].spells_cast_this_turn] == ["Sol Ring"]


@pytest.mark.cr("305.1", "601.3")
def test_w2g3_a_prohibition_that_names_land_plays_still_stops_one(catalog_by_name):
    """Null Chamber's sentence has both verbs ("…and lands with the chosen
    names can't be played") and Cornered Market spends a line on each: those
    rows bind the land drop, and the basic land Cornered Market exempts is
    still exempt."""
    game, cards = _w2g3_table(
        catalog_by_name, theirs=["Null Chamber", "Cornered Market", "Taiga", "Forest"],
        hand=["Taiga", "Forest", "Savannah"],
    )
    chamber = next(p for p in game.controlled_by(1) if p.card.name == "Null Chamber")
    chamber.metadata["chosen_card_names"] = ["Savannah", ""]

    by_name = cast_prohibition(game, 0, cards["Savannah"])
    assert by_name.kind == "chosen_name_ban" and by_name.source == "Null Chamber"
    assert not game.cast_from_hand(0, "Savannah").supported

    by_board = cast_prohibition(game, 0, cards["Taiga"])
    assert by_board.kind == "same_name_as_permanent_ban"
    assert by_board.source == "Cornered Market"
    assert not game.cast_from_hand(0, "Taiga").supported

    assert cast_prohibition(game, 0, cards["Forest"]) is None
    assert game.cast_from_hand(0, "Forest").supported


@pytest.mark.cr("601.3")
def test_w2g3_two_prohibitions_log_the_one_the_cast_path_always_named(catalog_by_name):
    """The table is asked in the order the run of refusals stood in, so a board
    under two prohibitions reports the earlier one, as it did."""
    game, cards = _w2g3_table(
        catalog_by_name, mine=["Steel Golem"], theirs=["Aether Storm", "Cornered Market", "Grizzly Bears"],
        hand=["Grizzly Bears"],
    )
    found = cast_prohibition(game, 0, cards["Grizzly Bears"])
    assert (found.kind, found.source) == ("own_cast_ban", "Steel Golem")
    refused = game.cast_from_hand(0, "Grizzly Bears")
    assert refused.details == "can't cast Grizzly Bears: Steel Golem"


@pytest.mark.cr("305.1")
def test_w2g3_which_question_a_card_poses(catalog_by_name):
    lea = catalog_by_name
    assert action_of(lea["Forest"]) == LAND
    assert action_of(lea["Taiga"]) == LAND
    assert action_of(lea["Grizzly Bears"]) == SPELL
    assert action_of(lea["Sol Ring"]) == SPELL
