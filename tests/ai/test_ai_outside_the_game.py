"""The AI and cards from outside the game (the Judgment Wishes, CR 400.11).

The simulator deals no seat a sideboard (``run_ai_simulation``'s
``PlayerState`` calls), so in every seeded run a Wish has nothing to bring in:
the offer is never made (``offers._action_is_takeable``) and the cast moves
nothing but the card itself into exile — which the rehearsal does not propose.
Whether the deal *should* give seats a sideboard (CR 100.4b: in limited play
the card pool's leftovers are the sideboard) moves every seeded game and is a
decision for the integrator, not this file.

What this file holds is the two halves that do not wait on that decision:
the zone-conservation invariant counts a sideboard as the reservoir a card
comes in from (CR 400.11b), and a Wish pinned into a seeded run with nothing
outside the game is never cast for nothing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import _zone_counter, run_ai_simulation
from engine.card_loader import manifest_set_path
from tests.helpers import CARDS_BY_NAME as _C

_WISHES = ("Burning Wish", "Cunning Wish", "Death Wish", "Golden Wish", "Living Wish")


def test_a_card_brought_in_from_outside_the_game_is_not_a_card_starting_to_exist():
    """CR 400.11b: the card moved from the sideboard into the game. Counted
    from the game's zones alone it was an "extra" card — fourteen false
    zone-conservation issues in four Judgment games once seats were given a
    sideboard by hand. The sideboard is the reservoir, so the count before and
    after the move is the same count."""
    game = Game(players=[
        PlayerState(name="A", library=[_C["Island"]] * 2,
                    sideboard=[_C["Lightning Bolt"], _C["Stone Rain"]]),
        PlayerState(name="B", library=[_C["Island"]] * 2),
    ])
    before = _zone_counter(game)
    assert game.bring_card_from_outside_game(0, 1, source_name="a test") is not None
    assert [card.name for card in game.players[0].hand] == ["Stone Rain"]
    assert _zone_counter(game) == before


@pytest.mark.slow
def test_a_wish_is_never_cast_into_an_empty_sideboard():
    """Every Wish pinned into both decks of a seeded Judgment run, no seat with
    anything outside the game: the run plays (a floor on what it did), no cast
    is refused, and no Wish is ever put on the stack — casting one would trade
    a card (and, for Death Wish, half a life total) for nothing, which is the
    rehearsal's "a cast that moves nothing is not proposed"."""
    report = run_ai_simulation(
        manifest_set_path("JUD", include_measured=True), games=2, seed=606,
        max_turns=12, required_cards=list(_WISHES),
    )
    assert report.games_completed == 2
    assert report.interaction_count >= 1
    assert not report.issues, report.issues
    assert not any(
        name in reason for reason in report.refused_casts for name in _WISHES
    ), report.refused_casts
    cast = [
        line for line in report.log_lines
        if any(line.strip().startswith(f"{name} added to stack") for name in _WISHES)
    ]
    assert cast == []
