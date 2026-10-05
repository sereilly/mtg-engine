"""The AI's roles chooser, for an ability that announces a **seat**.

``ai_policy._choose_activation_role_targets`` walks the picker's own chain of
legal targets and turned every pick into a permanent id or a graveyard slot. A
pick of kind ``"player"`` is neither, so the walk answered "no legal chain" and
the ability was never proposed. Three abilities in the pool announce a seat in
a roles chain, and no AI seat had ever activated one of them:

* Soldevi Heretic (Alliances, shipped) — "Prevent the next 2 damage that would
  be dealt to target creature this turn. **Target opponent** may draw a card."
* Planeswalker's Favor and Planeswalker's Scorn (Planeshift) — "**Target
  opponent** reveals a card at random from their hand. Target creature gets
  ±X/±X …"

Nothing reported it. A simulation with both enchantments pinned into both decks
cast them eighteen times each and logged no activation, no refusal and no
issue: an ability the chooser declines is not a cast the engine refused.

With a seat in the chain the walk also needs a *side* for the object role —
the first option at that level is the first board in seat order, so Scorn's
−X/−X would otherwise land on the activator's own creature whenever the
activator sits first.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _activation_target_side, _choose_activation_role_targets
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _board(cards, source_name, activator):
    """*source_name* and a Grizzly Bears for the activator, a Hill Giant for the
    other seat; one card in each hand. Returns the game, the source's slot and
    the side its ability aims at."""
    mine = [Permanent(card=cards[source_name]), Permanent(card=cards["Grizzly Bears"])]
    theirs = [Permanent(card=cards["Hill Giant"])]
    boards = (mine, theirs) if activator == 0 else (theirs, mine)
    game = Game(players=[
        PlayerState(name="A", battlefield=boards[0], hand=[cards["Shivan Dragon"]]),
        PlayerState(name="B", battlefield=boards[1], hand=[cards["Shivan Dragon"]]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(activator)
    game._sync_control()
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    slot = next(
        index for index, permanent in enumerate(game.players[activator].battlefield)
        if permanent.card.name == source_name
    )
    ability = compile_card_oracle(cards[source_name]).activated_abilities[0]
    side = _activation_target_side(
        game.players[activator].battlefield[slot], ability.instruction
    )
    return game, slot, side


def _described(game, refs):
    """Each ref as ``"seat N"`` or ``"<card> of seat N"``."""
    described = []
    for ref in refs or ():
        if "seat" in ref:
            described.append(f"seat {ref['seat']}")
            continue
        seat, permanent = game.find_permanent_by_id(ref["permanent_id"])
        described.append(f"{permanent.card.name} of seat {seat}")
    return described


def _cards(set_pool, catalog_by_name):
    merged = dict(catalog_by_name)
    merged.update({
        name: set_pool("PLS")[name]
        for name in ("Planeswalker's Favor", "Planeswalker's Scorn")
    })
    return merged


@pytest.mark.parametrize("activator", [0, 1])
def test_favor_names_the_opponent_and_pumps_the_activators_own_creature(
    set_pool, catalog_by_name, activator
):
    game, slot, side = _board(
        _cards(set_pool, catalog_by_name), "Planeswalker's Favor", activator
    )

    refs = _choose_activation_role_targets(game, activator, slot, side=side)

    assert side == "you"
    assert _described(game, refs) == [
        f"seat {1 - activator}", f"Grizzly Bears of seat {activator}",
    ]


@pytest.mark.parametrize("activator", [0, 1])
def test_scorn_names_the_opponent_and_shrinks_the_opponents_creature(
    set_pool, catalog_by_name, activator
):
    """The half the side is for. Seat 0 activating is the case the bare walk got
    wrong: its own board is the first the picker lists."""
    game, slot, side = _board(
        _cards(set_pool, catalog_by_name), "Planeswalker's Scorn", activator
    )

    refs = _choose_activation_role_targets(game, activator, slot, side=side)

    assert side == "opponent"
    assert _described(game, refs) == [
        f"seat {1 - activator}", f"Hill Giant of seat {1 - activator}",
    ]


def test_scorn_is_not_proposed_when_only_the_activator_has_a_creature(
    set_pool, catalog_by_name
):
    """No creature on the side the effect is aimed at is "no legal chain" — the
    single-target chooser's rule, for its reason: an activation that resolves
    and shrinks the creature of the seat that paid for it."""
    game, slot, side = _board(
        _cards(set_pool, catalog_by_name), "Planeswalker's Scorn", 0
    )
    game.remove_from_battlefield(game.players[1].battlefield[0])

    assert _choose_activation_role_targets(game, 0, slot, side=side) is None


def test_soldevi_heretic_is_activated_with_both_of_its_roles(catalog_by_name):
    """The shipped card. The chooser's answer goes through the real activation:
    the shield lands on the activator's own creature and the named opponent is
    the one offered the card."""
    game, slot, side = _board(dict(catalog_by_name), "Soldevi Heretic", 0)

    refs = _choose_activation_role_targets(game, 0, slot, side=side)
    assert _described(game, refs)[1] == "seat 1"
    assert _described(game, refs)[0].endswith("of seat 0")

    result = game.activate_permanent_ability(0, "Soldevi Heretic", target_role_refs=refs)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert result.supported, result.details
    assert any("gains prevention shield" in line for line in game.log), game.log[-4:]
    assert not any("B gains prevention shield" in line for line in game.log)
