"""CR 605: a mana ability that asks somebody something, and one that needs priority.

Rhystic Cave ("{T}: Choose a color. Add one mana of that color unless any player
pays {1}. Activate only as an instant.") is the card these rules were found on,
and it is tested in ``tests/sets/test_pcy_lands.py``. What is here is the rule
each part of it is an instance of, asked of invented lands so that a second card
printing the same shape is covered by construction:

* **CR 605.3b / 608.2d.** A mana ability resolves the moment it is activated, so
  the colour its activator names with the activation answers the "Choose a
  color" it makes as it resolves. The engine ignored it and took the prompt's
  default — the colour the *opponents* hold most of.
* **CR 605.1a.** "Could add mana when it resolves" is asked of the whole
  effect, an offer's branches included.
* **CR 304.5 / 602.5e.** "Activate only as an instant" means its controller must
  have priority, which nobody has part-way through paying a cost (CR 601.2g) —
  so the tap-for-mana seam, which is reached exactly there and asks no CR 602.5
  gate, must not run it, and nothing that plans a payment may count it.

Its own file per SET_PLAYBOOK's block convention: a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.mana_payment import is_mana_ability, taps_for_payment, untapped_mana_lands
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card


def _w3g1_land(text: str, name: str = "Invented Grotto"):
    return _mk_card(
        name=name, type_line="Land", oracle_text=text,
        produced_mana=("B", "G", "R", "U", "W"),
    )


def _w3g1_board(card, *, priority: int | None = 0):
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.start_turn(0)
    game._close_current_priority_step()
    land = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, land, None)
    land.metadata["summoning_sickness_turn"] = -99
    if priority is not None:
        game.start_priority_window(priority)
    return game, land  # _w3g1_board


def _w3g1_pool(game, seat: int = 0) -> dict[str, int]:
    return {s: n for s, n in game.players[seat].mana_pool.items() if n}


@pytest.mark.cr("605.3b", "608.2d")
@pytest.mark.parametrize("reference", ["that color", "the chosen color"])
def test_a_mana_abilitys_colour_choice_is_answered_by_its_activation(reference):
    """"{T}: Choose a color. Add one mana of <reference>." Asked for {R}, it
    makes {R} — both spellings of the back-reference, because both name the
    colour *this* resolution chose. It used to make {W}: the choice ignored the
    activation and took the default the prompt stamps for a seat that is not
    asked, which on an empty board is white."""
    card = _w3g1_land(f"{{T}}: Choose a color. Add one mana of {reference}.")
    (ability,) = compile_card_oracle(card).activated_abilities
    assert is_mana_ability(ability)
    for color in ("R", "G"):
        game, land = _w3g1_board(card)
        result = game.activate_permanent_ability(
            0, card.name, permanent_index=game.battlefield_index_of(land),
            mana_color=color,
        )
        assert result.supported, result
        assert _w3g1_pool(game) == {color: 1}
        assert game.pending_choices == []


@pytest.mark.cr("605.3b", "608.2d")
def test_the_tap_seam_answers_the_same_choice_the_same_way():
    """The other inline site. A {T}-alone mana ability with nothing it cannot
    honour is the tap seam's to run (CR 106.12), and the colour the seat asked
    the land for is the colour it chose."""
    card = _w3g1_land("{T}: Choose a color. Add one mana of that color.")
    game, land = _w3g1_board(card, priority=None)
    assert taps_for_payment(land)
    assert game.tap_land_for_mana(0, card.name, "U", permanent_id=land.permanent_id)
    assert _w3g1_pool(game) == {"U": 1}


@pytest.mark.cr("605.1a")
def test_mana_behind_a_toll_is_still_a_mana_ability():
    """"Could add mana to a player's mana pool when it resolves" — the toll
    decides whether it *does*, not whether it could. Without the offer opened,
    the ability read as not a mana ability: it went on the stack, and the AI
    activated it for its own sake."""
    card = _w3g1_land("{T}: Add one mana of any color unless any player pays {1}.")
    (ability,) = compile_card_oracle(card).activated_abilities
    assert ability.instruction.kind == "unless_player_pays"
    assert is_mana_ability(ability)
    assert is_mana_ability(ability.instruction)


@pytest.mark.cr("605.3b", "101.4")
def test_a_toll_inside_a_mana_ability_holds_the_mana_until_the_last_answer():
    """No stack object to hold, and the game still waits: each seat is asked
    in turn from the active player, and the mana is added by the last decline
    rather than by the activation."""
    card = _w3g1_land("{T}: Add one mana of any color unless any player pays {1}.")
    game, land = _w3g1_board(card)
    game.activate_permanent_ability(
        0, card.name, permanent_index=game.battlefield_index_of(land),
        mana_color="B",
    )
    assert not game.stack
    assert [c.player_index for c in game.pending_choices] == [0]
    assert game.waiting_prompt() is not None
    game.confirm_optional_pay(0, accept=False)
    assert _w3g1_pool(game) == {}
    game.confirm_optional_pay(1, accept=False)
    assert _w3g1_pool(game) == {"B": 1}


@pytest.mark.cr("304.5", "602.5e", "601.2g")
def test_a_mana_ability_activated_only_as_an_instant_is_never_tapped_mid_payment():
    """"{T}: Add {C}. Activate only as an instant." No offer at all — the
    restriction alone keeps it out of every path that taps lands while a cost
    is being paid: the seam refuses it and the payment planner does not count
    it. It is activated with priority, through the path that gates it, and
    makes its mana there."""
    card = _w3g1_land("{T}: Add {C}. Activate only as an instant.")
    (ability,) = compile_card_oracle(card).activated_abilities
    assert is_mana_ability(ability)
    assert not is_tap_alone_mana_ability(ability)

    game, land = _w3g1_board(card, priority=None)
    assert not taps_for_payment(land)
    assert untapped_mana_lands(game.controlled_by(0)) == []
    assert game.tap_land_for_mana(0, card.name, "C", permanent_id=land.permanent_id) is False
    assert not land.tapped

    refused = game.activate_permanent_ability(
        0, card.name, permanent_index=game.battlefield_index_of(land),
    )
    assert not refused.supported and not land.tapped

    game.start_priority_window(0)
    result = game.activate_permanent_ability(
        0, card.name, permanent_index=game.battlefield_index_of(land),
    )
    assert result.supported, result
    assert _w3g1_pool(game) == {"C": 1}
