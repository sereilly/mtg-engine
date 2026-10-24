"""A spell that arms a turn record and changes nothing else is not cast idle.

``engine/turn_replacements.py`` gives every record it arms a CR 614.5 identity
from a per-seat counter that never goes back down. The rehearsal's position
digest reads every field of a ``PlayerState``, so the counter read as a change
that **outlasted the turn** — and a cast whose only lasting trace is that is
proposed at the base score whenever nothing scores higher. Found driving
Judgment's Flaring Pain ("Damage can't be prevented this turn.") through seeded
AI games: cast into a board with no prevention on it, then flashed back for the
same nothing. The same counter made idle casts of the shipped turn records it
was written for (Blind Fury, Plagiarize); each is measured here on a board
where it can change nothing, and was proposed before the counter was named as
bookkeeping (``ai_rehearsal._PLAYER_BOOKKEEPING``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.models import Permanent
from tests.helpers import resolve_stack


def _lands_only(pool, card):
    island = pool["Island"]
    game = Game(players=[
        PlayerState(name="AI", library=[island] * 5),
        PlayerState(name="Opp", library=[island] * 5),
    ])
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    for land in ("Mountain", "Mountain", "Mountain", "Plains", "Island", "Island"):
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[land]), None)
    resolve_stack(game)
    game.players[0].hand = [card]
    return game


@pytest.mark.parametrize("name", ["Blind Fury", "Plagiarize"])
def test_a_shipped_turn_record_spell_is_not_cast_into_nothing(catalog_by_name, name):
    game = _lands_only(catalog_by_name, catalog_by_name[name])
    assert choose_cast_action(game, 0) is None


def test_flaring_pain_is_not_cast_into_a_board_with_nothing_to_unlock(
    set_pool, catalog_by_name,
):
    pool = {**catalog_by_name, **set_pool("JUD")}
    game = _lands_only(pool, pool["Flaring Pain"])
    assert choose_cast_action(game, 0) is None
