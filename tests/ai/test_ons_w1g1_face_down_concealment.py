"""Census: does a cast proposal depend on what an opponent's face-down card is?

CR 708.5: "You can't look at … face-down spells or permanents controlled by
another player." The policy rehearses a candidate cast on a copy of the game,
and a copy holds the card each face-down object hides — so a rehearsal could
read it. ``ai_rehearsal.conceal_from`` deals the hidden cards again on the
copy, pooled with that player's library (``tests/ai/
test_ai_hidden_information_census.py`` is the same census for hands and
libraries).

**Where the hidden card changes an outcome.** A face-down creature is a 2/2
to every reader of a characteristic, but not to every *result*: a creature
Illusionary Mask put face down "would be dealt damage … instead it's turned
face up and … is dealt damage". A Lightning Bolt at a Mask's face-down Grizzly
Bears kills it; the same Bolt at a face-down Force of Nature turns up an 8/8
that survives. So the seat's Bolt is worth something different in two worlds
that differ only in **which** of those two cards is face down and which is in
the opponent's library — and a seat that sees only what it may must propose
the same cast in both.

Validated backwards (``test_the_census_can_tell``): with the face-down half of
the concealment taken out, the two worlds' proposals differ.
"""

from __future__ import annotations

import random
from dataclasses import replace
from unittest import mock

import pytest

from engine import Game, PlayerState, ai_rehearsal
from engine.ai_actions import cast_announcement
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.face_down import MASK_FACE_DOWN, face_down_card
from engine.models import Permanent

_CATALOG = {card.name: card for card in load_catalog()}
ME, OPP = 0, 1


def _world(hidden: str, in_library: str) -> Game:
    mask_creature = Permanent(card=face_down_card(_CATALOG[hidden]))
    mask_creature.metadata[MASK_FACE_DOWN] = True
    mask_creature.metadata["summoning_sickness_turn"] = -99
    library = [_CATALOG["Forest"]] * 6 + [_CATALOG[in_library]]
    game = Game(players=[
        PlayerState(name="AI", hand=[_CATALOG["Lightning Bolt"]],
                    library=[_CATALOG["Mountain"]] * 8),
        PlayerState(name="Opp", battlefield=[mask_creature], library=library,
                    life=20),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game.current_turn_phase = game.current_step = "precombat_main"
    game.players[ME].mana_pool.update({"R": 1})
    game._sync_control()
    return game


def _proposal(hidden: str, in_library: str) -> "dict | None":
    random.seed(4242)
    game = _world(hidden, in_library)
    action = choose_cast_action(game, ME)
    if action is None:
        return None
    named = [
        game.controller_index_of(permanent)
        for permanent in map(game.permanent_by_id, action.target_permanent_ids or ())
        if permanent is not None
    ]
    # By seat, never by id: two boards built alike number their permanents
    # differently (CR 400.7's counter is the process's).
    said = cast_announcement(replace(action, target_permanent_ids=None))
    return {**said, "named": named, "score": action.score}


WORLDS = (("Grizzly Bears", "Force of Nature"), ("Force of Nature", "Grizzly Bears"))


def test_an_opponents_face_down_card_does_not_steer_a_proposal():
    proposals = [_proposal(*world) for world in WORLDS]
    assert proposals[0] == proposals[1], proposals


def test_the_census_can_tell():
    """With the face-down objects left out of the deal, the copy keeps each
    world's real hidden card and the Bolt is weighed against it."""
    with mock.patch.object(ai_rehearsal, "_face_down_objects", lambda game, index: []):
        proposals = [_proposal(*world) for world in WORLDS]
    assert proposals[0] != proposals[1], proposals


@pytest.mark.parametrize("world", WORLDS)
def test_the_seat_still_sees_its_own_face_down_cards(world):
    """CR 708.5's other half: the deal touches other seats' face-down objects
    only. A copy made for the face-down creature's controller keeps it."""
    hidden, in_library = world
    game = _world(hidden, in_library)
    copy = ai_rehearsal.scratch_copy(game)
    random.seed(1)
    ai_rehearsal.conceal_from(copy, OPP)
    (kept,) = copy.players[OPP].battlefield
    assert kept.card.face_down_of is _CATALOG[hidden]
