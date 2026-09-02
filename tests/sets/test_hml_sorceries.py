"""Per-card tests for Homelands' sorceries.

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


# --- W1G3: prevention, redirection and filtered damage ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g3_cast(set_pool, spell, *battlefield, poison=0):
    """Cast *spell* from HML at seat 1, with *battlefield* on the opponent's
    board, and resolve it.

    ``(set_code, name)`` pairs for the creatures, because these two spells are
    both about which permanents a printed noun phrase names and the pool has to
    contain ones it does *not*.
    """
    perms = [Permanent(card=set_pool(code)[name]) for code, name in battlefield]
    p0 = PlayerState(name="P0", hand=[set_pool("HML")[spell]])
    p1 = PlayerState(name="P1", battlefield=perms)
    p1.poison_counters = poison
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()
    result = game.cast_from_hand(0, spell, target_player_index=1)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return game, result, p1, perms


def test_evaporate_burns_every_white_or_blue_creature_and_nothing_else(set_pool):
    """"Evaporate deals 1 damage to each white and/or blue creature."

    The printed conjunction is a **union** (CR 105.2 gives an object one or more
    colours), so a white creature and a blue one are both in the set and a green
    one is not. Read as an intersection the spell would hit nothing at all; read
    with the conjunction dropped it would hit the whole board.
    """
    game, result, _p1, (white, blue, green) = _g3_cast(
        set_pool, "Evaporate",
        ("LEA", "White Knight"),
        ("LEA", "Merfolk of the Pearl Trident"),
        ("LEA", "Grizzly Bears"),
    )

    assert result.supported, result.details
    assert white.damage_marked == 1
    assert not game.is_on_battlefield(blue), "a 1/1 took lethal damage"
    assert green.damage_marked == 0, "green is neither white nor blue"


def test_leeches_deals_the_number_of_counters_it_actually_removed(set_pool):
    """"Target player loses all poison counters. Leeches deals that much damage
    to that player."

    "That much" is the count the *first* sentence took off, read out of the
    resolution's scratchpad — by the time the damage runs the store holds zero,
    so a reading that asked the player again would deal nothing.
    """
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=3)

    assert result.supported, result.details
    assert victim.poison_counters == 0
    assert victim.life == 17


def test_leeches_deals_nothing_to_an_unpoisoned_player(set_pool):
    """The same back-reference from the other end: nothing was removed, so
    nothing is dealt. A "that much" that fell back to a printed number would
    make this spell a burn spell."""
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=0)

    assert result.supported, result.details
    assert victim.life == 20
