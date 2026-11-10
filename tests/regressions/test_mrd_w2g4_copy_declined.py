"""The copy-as-it-enters "may" can be answered no (CR 707.5, CR 614.12a).

"You may have this creature enter as a copy of any creature on the
battlefield." (Clone; Vesuvan Doppelganger; Copy Artifact's and Sculpting
Steel's artifact spelling.) The rulings: "You can choose not to copy anything.
In that case, Clone enters as a 0/0 Shapeshifter creature, and is probably put
into the graveyard immediately." (Clone, 2025-10-02); "Sculpting Steel stays
on the battlefield as an artifact that doesn't do much of anything."
(2007-07-15).

The engine announces the copy target at cast (``cast_targets.
_cast_target_spec``'s ``optional`` picker), and a cast naming none fell back
to the first permanent of the type (``Game._enter_as_a_copy``) — so a seat
that chose not to copy was copied anyway. The decline is announced now
(``decline_copy``, ridden to the entry as ``enter_effects.COPY_DECLINED``);
a cast naming nothing and declining nothing still copies, which is what keeps
an AI seat and a headless cast copying.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, copier_set: str, copier: str, model, *, interactive=False):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="P0", library=[lea["Island"]] * 5,
                    hand=[set_pool(copier_set)[copier]]),
        PlayerState(name="P1", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    target = Permanent(card=model)
    game._put_permanent_onto_battlefield(1, target, None)
    game.start_turn(0)
    game._close_current_priority_step()
    return game, target


def _named(game, name):
    return [p for p in game.all_permanents() if p.card.name == name]


@pytest.mark.parametrize("interactive", [False, True])
def test_a_declined_clone_enters_as_a_zero_zero_and_dies(set_pool, interactive):
    game, _wurm = _table(
        set_pool, "LEA", "Clone", set_pool("LEA")["Craw Wurm"],
        interactive=interactive,
    )

    result = game.cast_from_hand(0, "Clone", decline_copy=True)
    resolve_stack(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert "Clone entered as itself, copying nothing" in game.log
    # A 0/0 Shapeshifter: put into its owner's graveyard (CR 704.5f).
    assert [c.name for c in game.players[0].graveyard] == ["Clone"]
    assert [p.card.name for p in game.all_permanents()] == ["Craw Wurm"]


def test_a_clone_naming_nothing_and_declining_nothing_still_copies(set_pool):
    """The default a headless or AI cast takes: copying is better than a 0/0."""
    game, _wurm = _table(set_pool, "LEA", "Clone", set_pool("LEA")["Craw Wurm"])

    assert game.cast_from_hand(0, "Clone").supported
    resolve_stack(game)
    game.check_state_based_actions()

    copies = [p for p in game.controlled_by(0)]
    assert [p.effective_card.name for p in copies] == ["Craw Wurm"], game.log
    assert copies[0].effective_power == 6


def test_naming_a_model_and_declining_is_refused_before_anything_is_paid(set_pool):
    game, wurm = _table(set_pool, "LEA", "Clone", set_pool("LEA")["Craw Wurm"])

    result = game.cast_from_hand(
        0, "Clone", target_player_index=1,
        target_permanent_ids=[wurm.permanent_id], decline_copy=True,
    )

    assert not result.supported
    assert "decline to copy" in result.details
    assert [c.name for c in game.players[0].hand] == ["Clone"]
    assert not game.stack


def test_a_declined_vesuvan_doppelganger_gains_no_upkeep_ability(set_pool):
    """The granted re-copy ability is part of the copy (CR 707.9a): declined,
    there is nothing to grant, and the 0/0 dies."""
    game, _wurm = _table(
        set_pool, "LEA", "Vesuvan Doppelganger", set_pool("LEA")["Craw Wurm"],
    )

    assert game.cast_from_hand(0, "Vesuvan Doppelganger", decline_copy=True).supported
    resolve_stack(game)
    game.check_state_based_actions()

    assert [c.name for c in game.players[0].graveyard] == ["Vesuvan Doppelganger"]


def test_a_declined_copy_artifact_stays_an_enchantment_that_does_nothing(set_pool):
    """Copy Artifact's ruling (2004-10-04) for the case with no artifact is the
    case with one declined: "this card enters as an enchantment that has no
    effect"."""
    game, _sol = _table(
        set_pool, "LEA", "Copy Artifact", set_pool("LEA")["Sol Ring"],
    )

    assert game.cast_from_hand(0, "Copy Artifact", decline_copy=True).supported
    resolve_stack(game)

    mine = list(game.controlled_by(0))
    assert [p.effective_card.name for p in mine] == ["Copy Artifact"], game.log
    assert mine[0].has_type("enchantment") and not mine[0].has_type("artifact")


def test_decline_copy_is_ignored_by_a_card_that_offers_no_copy(set_pool):
    game, _wurm = _table(
        set_pool, "LEA", "Grizzly Bears", set_pool("LEA")["Craw Wurm"],
    )
    game.players[0].hand = [set_pool("LEA")["Grizzly Bears"]]

    assert game.cast_from_hand(0, "Grizzly Bears", decline_copy=True).supported
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]
