"""A trigger whose line names a seat without targeting it announces no target.

Fire sites hand a triggered object the seat its event was about in
``target_player_index`` ("that player loses 5 life": the causer of a discard),
and one stamps a seat it already knows (the unblocked-attack site, its
controller's). The "becomes the target" announcement read that field through
the kind table's spec — which answers "player" for ``lose_life`` and
``discard_target_cards`` whatever the line said — so every such seat was
announced as targeted. The trigger picker had always asked the narrower
question (``targeting.announces_a_target``, CR 603.3d); the announcement now
asks it too.

``MTG_FULL_CENSUS=1`` found it at Onslaught's promotion (Mindstab Thrull and
Dauthi Mindripper, pinned in ``test_kg_stackid_about_object``); a spy over
``tests/sets``, ``tests/regressions`` and ``tests/rules`` found the rest of
its reach: Alley Grifters and Psychic Purge. Rayne, Academy Chancellor is the
one shipped card that watches a seat become a target, and Psychic Purge's is
the seat it sees.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.mark.cr("603.2", "115.1")
def test_rayne_draws_nothing_when_psychic_purge_names_its_controller(catalog_by_name):
    """"When a spell or ability an opponent controls causes you to discard this
    card, that player loses 5 life." Rayne's controller casts Coercion and takes
    the Purge: they lose 5, and nothing targeted them — Rayne ("Whenever you …
    become the target of a spell or ability an opponent controls, you may draw
    a card") had drawn one."""
    pool = catalog_by_name
    game = Game(players=[
        PlayerState("Purge", library=[pool["Forest"]] * 10,
                    hand=[pool["Psychic Purge"], pool["Forest"]]),
        PlayerState("Rayne", library=[pool["Forest"]] * 10, hand=[pool["Coercion"]]),
    ])
    game.enforce_mana_costs = False
    rayne = Permanent(card=pool["Rayne, Academy Chancellor"])
    game._put_permanent_onto_battlefield(1, rayne, None)
    resolve_stack(game)

    assert game.queue_from_hand(1, "Coercion", target_player_index=0).supported
    for _ in range(4):
        resolve_stack(game)
        game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].graveyard] == ["Psychic Purge"], game.log
    assert game.players[1].life == 15, game.log
    assert game.players[1].hand == [], game.log
    assert not any("Rayne" in line and "trigger" in line for line in game.log), game.log
