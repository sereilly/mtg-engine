"""A target reselected at random is no player's choice (CR 115.7) — Grip of
Chaos and Psychic Battle together.

Grip of Chaos: "Whenever a spell or ability is put onto the stack, if it has a
single target, reselect its target at random. (Select from among all legal
targets.)" Psychic Battle: "Whenever a player chooses one or more targets, …"

CR 115.7 is about effects that "allow a **player** to change the target(s)" or
"choose new targets"; Grip of Chaos allows nobody anything — the effect draws
the target, and the draw is the engine's seeded RNG. Psychic Battle's rulings
(2004-10-04, 2017-04-18; Scryfall, fetched for W2G4) say nothing about a
random reselection and nothing makes one a choice, so a moved target is not "a
player chooses one or more targets" and Psychic Battle does not hear it. (W1G8
announced it as one, and the Battle triggered a second time for every Bolt
Grip moved.) The new target still **becomes the target** of the spell
(CR 603.2e's "becomes"): Skulking Ghost, drawn as the new target, is
sacrificed.

Backwards on SCG W2G4's base (843cf32a): every seed that moved the Bolt put a
second Psychic Battle trigger on the stack.
"""

from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _cards() -> dict:
    found: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        found.setdefault(card.name, card)
    return found


_CARDS = _cards()


def _put(game, seat, name):
    permanent = Permanent(card=_CARDS[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _bolt_the_bears(seed: int):
    random.seed(seed)
    alice = PlayerState(name="Alice", hand=[_CARDS["Lightning Bolt"]],
                        library=[_CARDS["Plains"]] * 6)
    bob = PlayerState(name="Bob", library=[_CARDS["Island"]] * 6)
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    _put(game, 0, "Grip of Chaos")
    _put(game, 0, "Psychic Battle")
    bears = _put(game, 1, "Grizzly Bears")
    ghost = _put(game, 1, "Skulking Ghost")
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    # The cast is a player choosing a target: the Battle hears that one.
    battles = [item for item in game.stack if item.card.name == "Psychic Battle"]
    assert len(battles) == 1
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game, ghost


@pytest.mark.cr("115.7", "603.2e")
def test_grips_random_reselection_is_no_players_choice_of_targets():
    moved = 0
    onto_the_ghost = 0
    for seed in range(16):
        game, ghost = _bolt_the_bears(seed)
        reselected = [line for line in game.log if "reselected at random" in line]
        # One Psychic Battle trigger — the cast's — whether or not Grip moved
        # the Bolt.
        resolved = [line for line in game.log if line == "Psychic Battle ability resolved"]
        assert len(resolved) == 1, (seed, game.log[-14:])
        if reselected:
            moved += 1
        if any("to Bob's Skulking Ghost" in line for line in reselected):
            onto_the_ghost += 1
            # It became the target (CR 603.2e) and was sacrificed for it.
            assert not game.is_on_battlefield(ghost), (seed, game.log[-10:])
            assert any(card.name == "Skulking Ghost" for card in game.players[1].graveyard)
    assert moved >= 1, "no seed moved the Bolt: the census examined nothing"
    assert onto_the_ghost >= 1, "no seed drew the Ghost: its half examined nothing"
