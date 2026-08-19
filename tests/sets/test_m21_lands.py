"""Core Set 2021 (M21) lands.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def test_temple_of_mystery_etb_scry_is_claimed(set_pool):
    program = compile_card_oracle(set_pool("M21")["Temple of Mystery"])
    assert any(
        t.instruction is not None and t.instruction.kind == "scry"
        for t in program.triggered_abilities
    )


# --- The dead-ability round: a search whose tail was never read -------------


def test_fabled_passage_compiles_its_ability_supported(set_pool):
    """The card compiled `supported` on the strength of having *an* ability;
    its only one did not. The permanent gate is any-of, so a second working
    ability is all it takes to hide a dead one — which is why this asks about
    the ability rather than about the card."""
    program = compile_card_oracle(set_pool("M21")["Fabled Passage"])
    assert program.supported, program.reason
    assert [a.supported for a in program.activated_abilities] == [True]


def _passage_board(set_pool, other_lands: int):
    pool = set_pool("M21")
    passage = Permanent(card=pool["Fabled Passage"])
    p1 = PlayerState(
        name="P1",
        battlefield=[passage] + [Permanent(card=pool["Forest"]) for _ in range(other_lands)],
        library=[pool["Island"], pool["Shock"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    _nosick(passage)
    return game, p1, passage


@pytest.mark.parametrize(
    "other_lands, expect_tapped",
    [
        # The Passage sacrifices itself, so what is counted afterwards is the
        # other lands plus the land just found: three others is four, two is
        # three. Both sides of the printed threshold, on one board shape.
        (3, False),
        (2, True),
    ],
)
def test_fabled_passage_untaps_the_found_land_only_at_four(
    set_pool, other_lands, expect_tapped
):
    """"…put it onto the battlefield **tapped**, then shuffle. Then if you
    control four or more lands, untap that land."

    Both riders are what this reads: the land enters tapped, and the untap is
    the count's answer. Neither is a separate sentence — "that land" is the card
    the search just found, and a statement after the search would run before the
    player has answered its prompt.
    """
    game, p1, _passage = _passage_board(set_pool, other_lands)

    assert game.activate_permanent_ability(0, "Fabled Passage").supported
    game._settle()
    game.confirm_search_library(0, 0, zone="library")
    game._settle()

    found = [p for p in game.controlled_by(0) if p.card.name == "Island"]
    assert [p.card.name for p in found] == ["Island"]
    assert found[0].tapped is expect_tapped
