"""CR 612 as a static ability: Swirl the Mists' board-wide colour-word change.

"All instances of color words in the text of spells and permanents are
changed to the chosen color word." One ``COLOR_WORD_ALL`` record per source on
every spell and permanent (``engine/global_text_changes.py``), carrying the
source's timestamp (CR 613.7a) and ordered by CR 613.7 against the one-shot
text changes (Sleight of Mind) on the same object; every colour word changed
in one pass (CR 612.1 — no chaining), card names untouched (CR 612.2).
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.text_changes import (ALL_WORDS, COLOR_WORD_ALL, apply_text_changes,
                                 spell_text_card)
from tests.helpers import settle


def _card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, *, hand=(), mine=(), theirs=()):
    game = Game(players=[
        PlayerState(name="Alice", hand=[_card(set_pool, n) for n in hand],
                    library=[_card(set_pool, "Island")] * 10),
        PlayerState(name="Bob", library=[_card(set_pool, "Island")] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_card(set_pool, name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    settle(game)
    return game, placed[0], placed[1]


def _swirl(game, set_pool, color):
    """A Swirl the Mists under Alice whose chosen word is *color*'s."""
    game.players[0].hand.append(_card(set_pool, "Swirl the Mists"))
    game.interactive_seats = {0}
    assert game.queue_from_hand(0, "Swirl the Mists").supported
    settle(game, answers={
        "enter_choice": lambda game, choice: game.confirm_enter_choice(0, mana_color=color),
    })
    game.interactive_seats = set()
    return [p for p in game.controlled_by(0) if p.card.name == "Swirl the Mists"][-1]


def _protection_line(permanent) -> str:
    return next(
        line for line in permanent.effective_card.oracle_text.splitlines()
        if line.startswith("Protection")
    ).split(" (")[0]


def _sleight(game, set_pool, target, old, new):
    game.players[0].hand.append(_card(set_pool, "Sleight of Mind"))
    assert game.cast_from_hand(
        0, "Sleight of Mind", target_permanent_ids=[target.permanent_id],
        old_color=old, new_color=new,
    ).supported
    settle(game)


@pytest.mark.cr("613.7a", "613.7")
def test_a_sleight_of_mind_older_than_swirl_is_overwritten_by_it(set_pool):
    """Sleight of Mind (white → blue) on Black Knight, then a red Swirl: the
    Sleight is older, so it applies first ("protection from blue") and the
    Swirl, with its own later timestamp (CR 613.7a), turns that word red."""
    game, (knight,), _ = _table(set_pool, mine=["Black Knight"])
    _sleight(game, set_pool, knight, "W", "U")
    assert _protection_line(knight) == "Protection from blue"
    swirl = _swirl(game, set_pool, "R")
    assert _protection_line(knight) == "Protection from red"
    # Swirl gone, the Sleight's change is what is left.
    game.sacrifice_permanent(swirl)
    settle(game)
    assert _protection_line(knight) == "Protection from blue"


@pytest.mark.cr("613.7a", "613.7")
def test_a_sleight_of_mind_newer_than_swirl_changes_its_word(set_pool):
    """A red Swirl, then Sleight of Mind (red → green) on Black Knight: the
    Swirl is older, so its "red" is what the Sleight finds and rewrites. Once
    Swirl leaves, the printed "white" is back and the Sleight finds no red."""
    game, (knight,), _ = _table(set_pool, mine=["Black Knight"])
    swirl = _swirl(game, set_pool, "R")
    assert _protection_line(knight) == "Protection from red"
    _sleight(game, set_pool, knight, "R", "G")
    assert _protection_line(knight) == "Protection from green"
    game.sacrifice_permanent(swirl)
    settle(game)
    assert _protection_line(knight) == "Protection from white"


@pytest.mark.cr("613.7a", "612.1")
def test_two_swirls_the_later_one_wins(set_pool):
    """Two board-wide changes on one object apply in timestamp order: the
    later Swirl's word is every colour word's, whatever the earlier made of
    it; sacrificing the later one leaves the earlier one's word."""
    game, (knight,), _ = _table(set_pool, mine=["Black Knight"])
    _swirl(game, set_pool, "R")
    later = _swirl(game, set_pool, "G")
    assert _protection_line(knight) == "Protection from green"
    game.sacrifice_permanent(later)
    settle(game)
    assert _protection_line(knight) == "Protection from red"


@pytest.mark.cr("612.1", "612.2")
def test_every_colour_word_changes_in_one_pass_and_names_are_kept(set_pool):
    """One effect's substitutions are simultaneous (no word it writes is read
    again, so "nonblack" and "white" both become the chosen word rather than
    chaining), and a card name is not a colour word (CR 612.2): the card's own
    name and a "named …" phrase keep their words."""
    terror = _card(set_pool, "Terror")
    invented = dataclasses.replace(
        terror, name="Red Wizard",
        oracle_text=(
            "Destroy target nonblack creature unless it's white. Red Wizard "
            "deals 1 damage to you. Creatures named Black Knight get +1/+1."
        ),
    )
    record = {"kind": COLOR_WORD_ALL, "from": ALL_WORDS, "to": "green", "timestamp": 1}
    changed = apply_text_changes(invented, [record])
    assert changed.oracle_text == (
        "Destroy target nongreen creature unless it's green. Red Wizard "
        "deals 1 damage to you. Creatures named Black Knight get +1/+1."
    )


@pytest.mark.cr("612.1", "608.2b")
def test_a_spell_on_the_stack_loses_the_change_when_swirl_leaves(set_pool):
    """A Terror cast under a red Swirl reads "nonred"; Swirl leaving before it
    resolves ends the effect (ruling 2004-12-01) and the Terror reads its
    printed "nonblack" again, so its Shivan Dragon target is legal and dies."""
    game, _mine, (dragon,) = _table(set_pool, hand=["Terror"], theirs=["Shivan Dragon"])
    swirl = _swirl(game, set_pool, "R")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[dragon.permanent_id]).supported
    terror = game.stack[-1]
    assert "nonred" in spell_text_card(terror).oracle_text
    game.sacrifice_permanent(swirl)
    game._recompute_continuous_effects()
    assert "nonblack" in spell_text_card(terror).oracle_text
    settle(game)
    assert not game.is_on_battlefield(dragon)
