"""Per-card tests for Homelands' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G1: untap denial ---

from engine import Game, PlayerState
from engine.game_types import CardDefinition
from engine.models import Permanent


def _g1_creature(name: str, subtype: str):
    """A plain 2/2 with a printed creature type, which is the whole of what
    An-Zerrin Ruins asks about."""
    type_line = f"Creature - {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _g1_ruins_game(set_pool, opponent_creatures, interactive=False):
    """An-Zerrin Ruins in hand over an opponent's *opponent_creatures*, each
    entering tapped so the untap step has something to refuse."""
    permanents = [
        Permanent(card=_g1_creature(name, subtype), tapped=True)
        for name, subtype in opponent_creatures
    ]
    p1 = PlayerState(name="P1", hand=[set_pool("HML")["An-Zerrin Ruins"]])
    p2 = PlayerState(name="P2", battlefield=permanents)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.start_turn(0)
    return game, p1, permanents


def test_an_zerrin_ruins_holds_down_the_chosen_type_and_nothing_else(set_pool):
    """"As this enchantment enters, choose a creature type." / "Creatures of
    the chosen type don't untap during their controllers' untap steps."

    CR 614.1c's entry choice feeding a board-wide untap restriction: the
    sentence names no creature type at all, so the derivation reads the word
    off the permanent. The Bear beside the Goblins is the control - a
    narrowing the untap step could not test would hold the whole board down.
    """
    game, p1, (goblin, other_goblin, bear) = _g1_ruins_game(
        set_pool,
        [("Goblin One", "Goblin"), ("Goblin Two", "Goblin"), ("Bear One", "Bear")],
    )

    assert game.cast_from_hand(0, "An-Zerrin Ruins").supported
    game._settle()

    # The stated default (idiom 8): the type the opponents have most of, so the
    # enchantment is never inert for want of anyone making the choice.
    assert p1.battlefield[-1].metadata["chosen_creature_type"] == "goblin"

    game.resolve_untap_step(1)
    assert goblin.tapped is True
    assert other_goblin.tapped is True
    assert bear.tapped is False


def test_an_zerrin_ruins_asks_its_controller_and_takes_the_answer(set_pool):
    """The default is stamped before the prompt so a headless seat never
    blocks; an interactive controller's answer overwrites it, and the untap
    step reads the new word rather than the old one."""
    game, p1, (goblin, bear) = _g1_ruins_game(
        set_pool,
        [("Goblin One", "Goblin"), ("Bear One", "Bear")],
        interactive=True,
    )

    assert game.cast_from_hand(0, "An-Zerrin Ruins").supported
    game._settle()
    assert game.pending_enter_choice["needs_creature_type"]
    assert game.pending_enter_choice["default_creature_type"] in ("goblin", "bear")

    assert game.confirm_enter_choice(0, creature_type="Bear")
    assert p1.battlefield[-1].metadata["chosen_creature_type"] == "bear"

    game.resolve_untap_step(1)
    assert bear.tapped is True
    assert goblin.tapped is False


def test_an_zerrin_ruins_refuses_a_word_that_is_not_a_creature_type(set_pool):
    """CR 205.3m bounds the choice by the catalog, and an answer outside it is
    refused rather than repaired: quietly keeping the default would tell the
    player they had chosen something they had not."""
    game, _p1, _permanents = _g1_ruins_game(
        set_pool, [("Goblin One", "Goblin")], interactive=True
    )

    assert game.cast_from_hand(0, "An-Zerrin Ruins").supported
    game._settle()

    assert not game.confirm_enter_choice(0, creature_type="mountain")
    assert not game.confirm_enter_choice(0, creature_type="not a type")
    assert game.pending_enter_choice is not None


def test_an_zerrin_ruins_stops_restricting_when_it_leaves(set_pool):
    """The restriction is derived from the enchantment's own text every untap
    step, so it ends the moment the enchantment is gone - there is no marker on
    the creatures to clear."""
    game, p1, (goblin,) = _g1_ruins_game(set_pool, [("Goblin One", "Goblin")])

    assert game.cast_from_hand(0, "An-Zerrin Ruins").supported
    game._settle()
    game.resolve_untap_step(1)
    assert goblin.tapped is True

    game.remove_from_battlefield(p1.battlefield[-1])
    game._settle()
    game.resolve_untap_step(1)
    assert goblin.tapped is False
