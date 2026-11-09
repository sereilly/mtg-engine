"""One printed shuffle is one shuffle (CR 701.23a, CR 701.24a).

"When this artifact enters, search your library for five cards, exile them in
a face-down pile, and shuffle that pile. **Then shuffle your library.**"
(Mangara's Tome; Parallel Thoughts prints the same paragraph for seven cards.)
The search prompt's answer shuffles the library it searched — the engine's
standing reading of a search's "then shuffle" — and the trailing sentence was
lowered to a second ``shuffle_library``. Two shuffles for one, invisible until
Psychogenic Probe ("Whenever a spell or ability causes a player to shuffle
their library, this artifact deals 2 damage to that player.") dealt 4.

The trailing sentence is now the search's own deferred shuffle
(``riders._parse_deferred_search_shuffle``, Myr Incubator's reader, widened to
"Then shuffle your library."). A runtime census over every effect in both
manifest roles holding a library-shuffling kind (140 effects that shuffled at
least once) named these two cards and Tithe; Tithe's two searches are a
separate defect, measured and reported (see the W2G4 report).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _table(set_pool, spell_set: str, spell: str):
    lea = set_pool("LEA")
    library = [lea["Island"]] * 6 + [lea["Forest"]] * 6
    game = Game(players=[
        PlayerState(
            name="P0", life=20, library=list(library),
            hand=[set_pool(spell_set)[spell]],
        ),
        PlayerState(name="P1", life=20, library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(
        1, Permanent(card=set_pool("MRD")["Psychogenic Probe"]), None
    )
    game.start_turn(0)
    game._close_current_priority_step()
    return game


@pytest.mark.parametrize(
    ("spell_set", "spell", "found"),
    [("MIR", "Mangara's Tome", 5), ("SCG", "Parallel Thoughts", 7)],
)
def test_the_face_down_pile_search_shuffles_the_library_once(
    set_pool, spell_set, spell, found,
):
    game = _table(set_pool, spell_set, spell)
    shuffles = []
    original = game.shuffle_library_of

    def counting(player, *, below=0):
        shuffles.append(game.players.index(player))
        return original(player, below=below)

    game.shuffle_library_of = counting

    assert game.cast_from_hand(0, spell).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert shuffles == [0], game.log
    # The Probe heard one shuffle: 2 damage, not 4.
    assert game.players[0].life == 18, game.log
    # The search itself still happened in full (CR 701.23d's bare quantity).
    assert len(game.players[0].library) == 12 - found
