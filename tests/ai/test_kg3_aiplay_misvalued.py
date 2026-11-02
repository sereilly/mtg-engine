"""Three cards the AI censuses pinned as mis-valued (kg3 `aiplay`, part 2),
fixed by class.

* **Drain Power** pays {U}{U} to take one {U} off an opponent with one
  Island, and was proposed because a cast that leaves mana in its caster's
  pool reads as one that left something (``Rehearsal.made_mana``) — however
  little. Mana is that only beyond what the cast cost
  (``ai_rehearsal._made_more_mana_than_it_cost``).
* **Threaten** ("Untap target creature and gain control of it until end of
  turn. That creature gains haste") and **Debt of Loyalty** ("Regenerate
  target creature. You gain control of that creature if it regenerates this
  way") were aimed by their gifts — the untap, the haste, the regeneration —
  because the steal names no target of its own: Threaten's reads the untap's
  record, Debt of Loyalty's is a delayed trigger bound to the target. A step
  spent on the earlier target is read with it
  (``ai_target_sides._spent_on_the_earlier_target``), and the steal is a
  denial, so the target is the opponent's.

The boards are the censuses' own (``test_ai_idle_cast_census.board``,
``test_ai_combat_trick_census.board``), so what is asserted here is the row
each pin stood for.
"""
from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.ai_rehearsal import deliberating
from engine.ai_scoring import _announcement, _rehearse_announcement
from engine.ai_target_sides import spell_target_side
from engine.card_loader import load_catalog
from tests.ai import test_ai_combat_trick_census as trick
from tests.ai import test_ai_idle_cast_census as idle

_CARDS = {card.name: card for card in load_catalog()}

#: Every shipped spell whose steal, sacrifice or exile is spent on an earlier
#: step's target — the six whose side the fix moved, each to the opponent's.
_SPENT_ON_THE_TARGET = (
    "Barrin's Spite", "Cannibalize", "Debt of Loyalty", "Disharmony",
    "Temporary Insanity", "Threaten",
)


@pytest.mark.parametrize("name", _SPENT_ON_THE_TARGET)
def test_a_steal_spent_on_the_earlier_target_aims_across_the_table(name):
    assert spell_target_side(_CARDS[name]) == "opponent"


def test_drain_power_is_not_cast_for_less_mana_than_it_costs():
    """The idle census's mirror board: one Island and one nonbasic land on
    the opposing side, forty mana in the caster's pool and nothing to spend
    it on. Drain Power would pay {U}{U} for the two the opponent's lands make
    — no mana gained, and nothing else changed by the end of the turn."""
    game = idle.board(idle.POOL["Drain Power"], "mirror")
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Drain Power", action


def test_a_ritual_still_reads_as_mana_made():
    """Dark Ritual makes three for one: still mana its next cast is paid
    with, which is why a cast of it is not nothing."""
    game = idle.board(_CARDS["Dark Ritual"], "own")
    with deliberating():
        rehearsal = _rehearse_announcement(
            game, 0, _CARDS["Dark Ritual"],
            _announcement(_CARDS["Dark Ritual"], target=0, caster=0),
        )
    assert rehearsal is not None and rehearsal.accepted and rehearsal.made_mana


def test_debt_of_loyalty_is_aimed_at_the_opposing_twin():
    """The idle census's mirror board: the opposing creature, which the
    turn's fight destroys and the shield regenerates into the caster's
    control — not the caster's own (3.0 against 11.5 when it was pinned)."""
    game = idle.board(idle.POOL["Debt of Loyalty"], "mirror")
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Debt of Loyalty"
    assert action.target_player_index == 1
    named = game.permanent_by_id(action.target_permanent_ids[0])
    assert game.controller_index_of(named) == 1


@pytest.mark.parametrize("board", ["rival", "wall", "after", "sick"])
def test_threaten_steals_the_creature_across_the_table(board):
    """The combat-trick census's boards on which a cast by hand wins: the
    policy now proposes Threaten, at the opposing creature, where it held it
    (rival, wall, after) or cast it at its own (sick)."""
    game = trick.board(trick.POOL["Threaten"], board)
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Threaten", action
    named = game.permanent_by_id(action.target_permanent_ids[0])
    assert game.controller_index_of(named) == 1
