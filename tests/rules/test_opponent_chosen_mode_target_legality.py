"""CR 608.2b for the targets of a mode **an opponent** chose (CR 700.2e).

"An opponent chooses one — • You draw three cards. • You destroy up to two
target creatures **that player** controls. They can't be regenerated. That
player draws up to three cards." (Fatal Lore — the one card in the pool whose
opponent-chosen mode names a target; Misfortune's and Library of Lat-Nam's
modes name none.)

The targets are named after the choice, against the chooser's seat. That seat
has been on the stack item since the mode's own "that player" needed it, and
the resolution's re-check of what the card printed did not read it: the
description was simply not re-asked for these spells. So with both named
creatures taken by the caster in response — neither any longer "a creature
that player controls" — Fatal Lore resolved, destroyed nothing, and the
opponent still drew three cards.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import resolve_stack


def _cast_and_name(pool):
    """Fatal Lore cast by seat 0, its second mode chosen by seat 1, and seat
    1's two creatures named by seat 0. Both seats are asked, because a seat
    nobody asks takes the first mode before a test can name the second."""
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 12, hand=[pool["Fatal Lore"]]),
        PlayerState("B", library=[pool["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    named = [Permanent(card=pool["Grizzly Bears"]), Permanent(card=pool["Hill Giant"])]
    for permanent in named:
        game._put_permanent_onto_battlefield(1, permanent, None)
    assert game.queue_from_hand(0, "Fatal Lore").supported
    assert game.confirm_opponent_mode_choice(1, 1)
    assert game.confirm_modal_mode_targets(0, [p.permanent_id for p in named])
    return game, named


def _finish(game) -> None:
    game.interactive_seats = set()
    for _ in range(6):
        resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


@pytest.mark.cr("608.2b", "700.2e")
def test_608_2b_targets_that_stopped_being_that_players_stop_the_spell(catalog_by_name):
    game, named = _cast_and_name(catalog_by_name)
    for permanent in named:
        change_control(permanent, 0, source=catalog_by_name["Forest"], until_eot=False)
    game._sync_control()

    _finish(game)

    assert all(game.is_on_battlefield(p) and game.controls(0, p) for p in named)
    assert game.players[1].hand == [], "the sentence behind the targets did not run"
    assert any("every target is illegal (608.2b)" in line for line in game.log[-3:])
    assert [card.name for card in game.players[0].graveyard] == ["Fatal Lore"]


@pytest.mark.cr("608.2b", "700.2e")
def test_608_2b_one_target_still_that_players_and_the_spell_resolves(catalog_by_name):
    """The rule is about *every* target. With one creature taken and one
    left, the one left is destroyed and the sentence behind it runs."""
    game, named = _cast_and_name(catalog_by_name)
    taken, left = named
    change_control(taken, 0, source=catalog_by_name["Forest"], until_eot=False)
    game._sync_control()

    _finish(game)

    assert game.is_on_battlefield(taken) and game.controls(0, taken)
    assert not game.is_on_battlefield(left)
    assert len(game.players[1].hand) == 3


@pytest.mark.cr("608.2b", "700.2e")
def test_608_2b_with_its_targets_untouched_the_chosen_mode_does_all_of_itself(
    catalog_by_name,
):
    """The control: the re-check, asked with the chooser's seat, admits the
    targets that seat's player still controls."""
    game, named = _cast_and_name(catalog_by_name)

    _finish(game)

    assert not any(game.is_on_battlefield(p) for p in named)
    assert len(game.players[1].hand) == 3
