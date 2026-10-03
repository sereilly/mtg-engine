"""Regressions: a toll's branch spends the role it was announced for, however
the offer is answered.

Found at Prophecy wave 2 (W2G1) while building Withdraw, whose second bounce
sits inside "…unless its controller pays {1}". A line that announces two
targets and spends them a step at a time puts the shared ``roles`` list on each
step and lets ``handlers/control_flow._role_scoped`` narrow the context per
step (Lunge, Crooked Scales). Two paths ran a step *without* that narrowing:

* the offer itself: a ``may`` names no role of its own, so "its controller"
  was read off the unscoped list — the first target's controller, not the
  creature the toll is about;
* an offer answered through its prompt: ``choices._run_optional_steps`` ran
  the branch against the context it froze, again unscoped.

The second was live on a shipped card. Crooked Scales ("If you lose the flip,
destroy target creature you control unless you pay {3} and repeat this
process"), declined by a seat that *could* pay, ran its destroy against the
first announced target — the opponent's creature — which fails "you control",
and **destroyed nothing**. The existing tests declined by being unable to pay,
which takes the other path (``_offer_to_seat`` runs the branch through ``_run``)
and was always right.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack


def _scales_game(set_pool):
    scales = Permanent(card=set_pool("MMQ")["Crooked Scales"])
    mine = Permanent(card=_mk_creature_card("My Bear", 2, 2))
    theirs = Permanent(card=_mk_creature_card("Their Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="A", battlefield=[scales, mine]),
        PlayerState(name="B", battlefield=[theirs]),
    ])
    for permanent in (scales, mine, theirs):
        permanent.summoning_sick = False
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"C": 20})
    return game, mine, theirs


@pytest.mark.cr("608.2b")
def test_crooked_scales_declined_at_the_prompt_destroys_your_own_creature(set_pool):
    """The decline answered by a seat that can pay: the payer's own creature —
    the role the toll is about — is destroyed, and the opponent's is not."""
    game, mine, theirs = _scales_game(set_pool)
    with patch("engine.handlers.control_flow.flip_coin", side_effect=lambda: False):
        assert game.activate_permanent_ability(
            0, "Crooked Scales",
            target_permanent_ids=[theirs.permanent_id, mine.permanent_id],
        ).supported
        game.resolve_top_of_stack()
        assert [c.player_index for c in game.pending_choices] == [0]
        assert game.confirm_optional_pay(0, accept=False)
        resolve_stack(game)

    assert not game.is_on_battlefield(mine)
    assert game.is_on_battlefield(theirs)
    assert "Crooked Scales destroyed My Bear" in game.log


@pytest.mark.cr("608.2b")
def test_crooked_scales_paid_at_the_prompt_repeats_against_both_roles(set_pool):
    """Paid at the prompt, the repeat runs the whole flip again under the
    toll's own scope — and the won arm still finds the *opponent's* creature,
    because a scoped context resolves every role against the announcement it
    was cut from (``OracleExecutionContext.announced_targets``)."""
    game, mine, theirs = _scales_game(set_pool)
    coins = iter([False, True])
    with patch(
        "engine.handlers.control_flow.flip_coin",
        side_effect=lambda: next(coins, False),
    ):
        game.activate_permanent_ability(
            0, "Crooked Scales",
            target_permanent_ids=[theirs.permanent_id, mine.permanent_id],
        )
        game.resolve_top_of_stack()
        assert game.confirm_optional_pay(0, accept=True)
        resolve_stack(game)

    assert game.is_on_battlefield(mine)
    assert not game.is_on_battlefield(theirs)
