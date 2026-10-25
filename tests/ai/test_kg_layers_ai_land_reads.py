"""The AI's counts of a seat's lands ask what each permanent **is**
(CR 613.1d), not the word its card was printed with.

Four reads in the AI's policy asked ``perm.card.primary_type == "land"`` of a
permanent on the battlefield — the land-drop ranking's "colours my lands
already make" (``ai_policy._land_drop_value``) and three land counts in
``ai_scoring``: the tutor's "am I short of lands?" and "how much can I spend?"
(``_tutor_score``), and a land drop's worth (``_score_cast``). Each is a count
of permanents, so each is a layer-4 question.

The board that tells them apart is a **Clone that copied a Forest** (CR 707.2):
a Forest — under Living Lands a Forest creature — on a card printed "Creature —
Shapeshifter". The census asks every site the same question twice, once with
the Clone and once with a real Forest in its place, and requires the same
answer: a permanent that is a Forest is weighed as one. On the base tree
(``c42aec75``) all four sites answered differently.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _land_drop_value, choose_land_drop
from engine.ai_scoring import _score_cast, _tutor_score
from engine.card_loader import load_catalog
from engine.faces import whole_card
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def by_name():
    return {card.name: card for card in load_catalog()}


def _board(by_name, *, clone: bool, mine=(), hand=(), enforce=False):
    """Seat 0 on its main phase with *mine* and one Forest of its own — a
    Clone that copied seat 1's Living Lands Forest, or a real one."""
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"

    def put(name, seat):
        perm = Permanent(card=by_name[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        _nosick(perm)
        game._recompute_continuous_effects()
        return perm

    put("Living Lands", 1)
    theirs = put("Forest", 1)
    for name in mine:
        put(name, 0)
    if clone:
        card = whole_card(by_name["Clone"])
        game.players[0].hand.append(card)
        result = game.cast_from_hand(
            0, "Clone", target_permanent_ids=[theirs.permanent_id]
        )
        assert result.supported, result
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        forest = next(p for p in game.controlled_by(0) if p.card.name == "Clone")
        _nosick(forest)
        game._recompute_continuous_effects()
        assert forest.has_type("forest") and forest.card.primary_type == "creature"
    else:
        forest = put("Forest", 0)
    assert forest.has_type("land") and not forest.tapped
    game.players[0].hand = [by_name[name] for name in hand]
    game.enforce_mana_costs = enforce
    return game


def _both(by_name, ask, **board):
    return ask(_board(by_name, clone=True, **board)), ask(_board(by_name, clone=False, **board))


def test_the_land_drop_ranking_sees_the_green_a_clone_of_a_forest_makes(by_name):
    """"The colours the hand wants that no land of mine makes": a Clone that
    is a Forest makes green, so the Island is the land that adds a colour."""
    hand = ("Forest", "Island", "Grizzly Bears", "Merfolk of the Pearl Trident")
    with_clone, with_forest = _both(
        by_name,
        lambda game: _land_drop_value(game, 0, by_name["Forest"]),
        hand=hand,
    )
    assert with_clone == with_forest == (0, 1)

    played = choose_land_drop(_board(by_name, clone=True, hand=hand), 0)
    assert played is not None and played.card_name == "Island"


def test_a_land_drop_is_worth_less_on_a_board_with_four_untapped_lands(by_name):
    """``_score_cast``'s land weight: under four untapped lands a land drop is
    worth playing, at four it is filler. The Clone is the fourth."""
    mine = ("Plains", "Plains", "Plains")
    with_clone, with_forest = _both(
        by_name,
        lambda game: _score_cast(game, 0, by_name["Forest"], 0, None),
        mine=mine,
    )
    assert with_clone == with_forest == 0.2


def test_a_tutor_counts_a_clone_of_a_forest_among_the_lands(by_name):
    """"Lands are only worth tutoring when mana-screwed": a Plains and a
    Forest are two lands, however the Forest was printed."""
    with_clone, with_forest = _both(
        by_name,
        lambda game: _tutor_score(game, 0, by_name["Forest"]),
        mine=("Plains",),
    )
    assert with_clone == with_forest


def test_a_tutor_counts_a_clone_of_a_forest_among_the_untapped_mana(by_name):
    """The tutor's "how far short of casting it am I": the untapped lands are
    the mana, and the Clone is one of them."""
    with_clone, with_forest = _both(
        by_name,
        lambda game: _tutor_score(game, 0, by_name["Craw Wurm"]),
        mine=("Plains",), enforce=True,
    )
    assert with_clone == with_forest
