"""Regression: "target creature **defending player controls**" is a seat, and
a spell printing it has to be held to it.

CR 506.2 defines "defending player" only inside a combat phase, and CR 601.2c
makes the printed noun phrase part of what may legally be chosen. The engine
had the seat test — ``defending_player_only``, answered by
``legality._enumerate_targets`` — and only a *trigger* ever reached it: the
combat fire sites freeze the seat into the trigger's context (CR 603.10),
because a trigger's combat may be over by the time it resolves, and nothing
supplied a seat for a spell.

So Blaze of Glory, the pool's one spell printing the phrase, reached the picker
with a spec that said "kind: creature" and nothing else. Its whole printed
restriction — the half that makes it a trick played against an attacker rather
than a Fog for its caster — was enforced nowhere: not by the picker, not by the
cast gate, not by the handler. The caster could aim it at their own creature,
and did.

A spell has no frozen record because it is being cast **now**, so the seat is
the live combat's (``Game.defending_player_index_now``, which unlike the
two-player convenience scalar it wraps answers None outside combat). These
tests drive both halves: the illegal target refuses, and the legal one still
works.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent


@pytest.fixture(scope="module")
def blaze_of_glory():
    for path in manifest_set_paths():
        for card in load_cards(path):
            if card.name == "Blaze of Glory":
                return card
    raise AssertionError("Blaze of Glory is not in the shipped pool")


def _creature(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _attacking(blaze_of_glory):
    """Seat 0 attacking seat 1, with Blaze of Glory in seat 0's hand.

    The caster is the *attacking* player on purpose: that is the seat the
    printed phrase excludes, and the seat a picker with no narrowing offered.
    """
    attacker = Permanent(card=_creature("Raider"))
    attacker.metadata["summoning_sickness_turn"] = -99
    own = Permanent(card=_creature("My Own"))
    theirs = Permanent(card=_creature("Their Wall"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, own], hand=[blaze_of_glory]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    return game, own, theirs


@pytest.mark.cr("506.2", "601.2c")
def test_blaze_of_glory_refuses_the_casters_own_creature(blaze_of_glory):
    """The bug. Nothing crashed and nothing was missing — the spell resolved,
    reported success, and granted the permission to a creature the card does
    not name."""
    game, own, _theirs = _attacking(blaze_of_glory)

    result = game.cast_from_hand(
        0, "Blaze of Glory", target_player_index=0, target_permanent_index=1
    )

    assert not result.supported
    game.resolve_stack()
    game._settle()
    assert not own.metadata.get("can_block_any_number_until_eot")


@pytest.mark.cr("506.2", "509.1b")
def test_blaze_of_glory_still_reaches_the_defenders_creature(blaze_of_glory):
    """The other half, which is what makes the first one a narrowing rather
    than a ban."""
    game, own, theirs = _attacking(blaze_of_glory)

    result = game.cast_from_hand(
        0, "Blaze of Glory", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    assert theirs.metadata.get("can_block_any_number_until_eot")
    assert not own.metadata.get("can_block_any_number_until_eot")


@pytest.mark.cr("506.2")
def test_the_permission_ends_with_the_turn(blaze_of_glory):
    """"…**this turn**", and the sweep is what says so.

    Both of the flags this card writes were read by the blockers step and by
    the AI and cleared by nothing, so one Blaze of Glory made a creature able
    to block every attacker — and obliged to — for the rest of the game.
    """
    game, _own, theirs = _attacking(blaze_of_glory)
    assert game.cast_from_hand(
        0, "Blaze of Glory", target_player_index=1, target_permanent_index=0
    ).supported
    game.resolve_stack()
    game._settle()
    assert game._max_blocks_for(theirs) > 1

    game.resolve_cleanup_step(0)

    assert game._max_blocks_for(theirs) == 1
    assert not theirs.metadata.get("must_block_all_until_eot")
