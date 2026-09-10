"""A choice an effect offers is announced while the effect is applied (UDS W2G3).

CR 608.2d: a choice other than one already made as the spell or ability was put
on the stack is announced *while applying the effect*. Two consequences this
engine has to honour together, and Scrying Glass prints both in one line:

* the choice is made at resolution, not at activation - nothing about a number
  or a colour rides the announcement; and
* a later step of the same resolution that spends the answer cannot run before
  it exists, because CR 608.2 keeps following the instructions in order and
  CR 117.3b gives nobody priority in between.

The failure the second half guards against is silent in the only way that
matters: the resolution runs on with the deterministic default the arming
stamped, the player's real answer lands afterwards, and the card reports itself
supported having asked a question whose answer it ignored.

Its own file per SET_PLAYBOOK's block convention - a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle_types import CHOSEN_COLOR_THIS_WAY, CHOSEN_NUMBER_THIS_WAY

_UDS_PATH = manifest_set_path("UDS", include_measured=True)
_LEA_PATH = manifest_set_path("LEA")


def _w2g3r_card(path, name):
    return next(card for card in load_cards(path) if card.name == name)


def _w2g3r_glass_in_play(opponent_hand):
    """Scrying Glass on seat 0's battlefield, seat 1 holding *opponent_hand*."""
    forest = _w2g3r_card(_LEA_PATH, "Forest")
    glass = Permanent(card=_w2g3r_card(_UDS_PATH, "Scrying Glass"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[glass], library=[forest] * 8, life=20),
        PlayerState(
            name="P2",
            hand=[_w2g3r_card(_LEA_PATH, name) for name in opponent_hand],
            library=[forest] * 8, life=20,
        ),
    ])
    game.interactive_seats = {0}
    game.enforce_mana_costs = False
    game._settle()
    return game


@pytest.mark.cr("608.2d", "602.2b")
def test_a_resolution_choice_is_not_announced_with_the_activation():
    """Nothing is chosen when the ability goes on the stack.

    CR 602.2b announces targets and costs; the number and the colour are
    neither, so CR 608.2d puts both of them off until the ability resolves - and
    the evidence is that activating it *arms a prompt* rather than taking an
    answer with the announcement.
    """
    game = _w2g3r_glass_in_play(["Lightning Bolt"])
    result = game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )
    assert result.supported, result.details
    assert [choice.kind for choice in game.pending_choices] == ["number_choice"]


@pytest.mark.cr("608.2", "608.2d", "117.3b")
def test_the_step_that_spends_a_choice_waits_for_the_answer():
    """The instructions are followed in order, and the order includes the ask.

    CR 608.2 follows a resolving ability's instructions in the order written and
    CR 117.3b hands nobody priority until it is done, so "target opponent reveals
    their hand" is still ahead when the colour has not been named. A prompt that
    let it run would count the revealed hand against a default nobody chose.
    """
    game = _w2g3r_glass_in_play(["Lightning Bolt"])
    game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )
    assert not any("reveals their hand" in line for line in game.log), game.log

    game.confirm_number_choice(0, 1)
    assert [choice.kind for choice in game.pending_choices] == ["color_choice"]
    assert not any("reveals their hand" in line for line in game.log), game.log

    game.confirm_color_choice(0, "R")
    assert not game.pending_choices, game.pending_choices
    assert any("reveals their hand" in line for line in game.log), game.log


@pytest.mark.cr("107.1b", "608.2d")
def test_a_number_greater_than_zero_has_a_floor_and_no_ceiling():
    """"Choose a number greater than 0" bounds the answer below and not above.

    CR 107.1b is where the *lower* bound comes from - a player cannot choose a
    negative number - and the card's own word is what lifts it to one. Nothing
    supplies an upper bound, so CR 608.2d's "can't choose an option that's
    illegal or impossible" refuses zero and admits every number above it; an
    invented ceiling would refuse an answer the card allows.
    """
    game = _w2g3r_glass_in_play(["Lightning Bolt"])
    game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )
    assert not game.confirm_number_choice(0, 0), "zero is not greater than zero"
    assert not game.confirm_number_choice(0, -1), "CR 107.1b has no negatives"
    assert game.confirm_number_choice(0, 99), game.log


@pytest.mark.cr("608.2d", "701.20a")
def test_the_count_reads_the_reveal_this_resolution_made():
    """What was revealed, not what the hand holds when the question is asked.

    CR 701.20a keeps a revealed card revealed "for as long as necessary to
    complete the parts of the effect that card is relevant to", which is exactly
    the record the count reads: the set the reveal step showed, held across the
    decisions in front of it rather than re-read off a zone that may have moved.
    """
    game = _w2g3r_glass_in_play(["Lightning Bolt", "Island"])
    game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )
    game.confirm_number_choice(0, 1)
    game.confirm_color_choice(0, "R")
    assert len(game.players[0].hand) == 1, game.log
    assert len(game.players[1].hand) == 2, "revealing does not move a card"


@pytest.mark.cr("608.2d", "105.1")
def test_both_answers_are_recorded_for_the_sentence_that_spends_them():
    """CR 608.2d's announcement is only useful if something can read it back.

    Both choices land in the resolution's own record under the keys the counting
    sentence reads. A choice nothing records is a question asked and thrown
    away, which is the shape that lets a card compile clean and do nothing.

    And the answer is one of CR 105.1's five or it is refused rather than
    repaired: colourless is CR 105.2c's absence of a colour and not a colour to
    choose, so a seat naming it keeps the answer already recorded instead of
    being told it chose something it did not.
    """
    seen = {}
    game = _w2g3r_glass_in_play(["Lightning Bolt"])
    game.activate_permanent_ability(
        0, "Scrying Glass", permanent_index=0, target_player_index=1
    )
    number_prompt = game.pending_choices[0]
    context = number_prompt.data["_context"]
    game.confirm_number_choice(0, 4)
    seen[CHOSEN_NUMBER_THIS_WAY] = context.results.get(CHOSEN_NUMBER_THIS_WAY)

    assert not game.confirm_color_choice(0, "C"), "colourless is not a colour"
    assert game.pending_choices, "a refused answer leaves the prompt owed"

    game.confirm_color_choice(0, "B")
    seen[CHOSEN_COLOR_THIS_WAY] = context.results.get(CHOSEN_COLOR_THIS_WAY)

    assert seen == {CHOSEN_NUMBER_THIS_WAY: 4, CHOSEN_COLOR_THIS_WAY: "B"}, seen
