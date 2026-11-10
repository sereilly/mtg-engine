"""An entry P/T counter lands in the store its readers ask (CR 122.1a).

The four "enters with … counters" loops in ``mixins/permanent_state`` wrote
the non-+1/+1 kinds out by hand: +1/+0 into ``plus_1_0_counters`` (which
``pt.pt_counter_key`` reads) and +0/+1 into ``plus_0_1_counters`` — a key
nothing reads, since ``pt_counter_key("+0/+1")`` is ``+0/+1_counters``, the
store Living Armor, Coral Reef and Dwarven Armorer already fill. So a creature
entering with two +0/+1 counters got the toughness and had, to every question
about counters, none ("counters_on" answered 0; a "remove a +0/+1 counter"
cost would find nothing). ROADMAP recorded it with no card behind it: the
entry templates admit "+0/+1" and no printed card enters with one, which a
text census of the pool confirms (MRD W2G3). The loops now place every kind
through ``Game.place_pt_counters``, the seam that existed for exactly this.
"""

from __future__ import annotations

from engine import PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import _game, _mk_creature_card


def _enters(card):
    game = _game(PlayerState(name="A"), PlayerState(name="B"))
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, permanent, None)
    game._settle()
    return permanent


def test_a_creature_entering_with_plus_0_plus_1_counters_has_them():
    wall = _enters(_mk_creature_card(
        "Entry Wall", 1, 1, "This creature enters with two +0/+1 counters on it.",
    ))
    assert (wall.effective_power, wall.effective_toughness) == (1, 3)
    assert counters_on(wall, "+0/+1") == 2


def test_the_shipped_plus_1_plus_0_entry_is_unchanged(set_pool):
    """Clockwork Avian ("enters with four +1/+0 counters"): the +1/+0 arm took
    the same road before and after — the store Clockwork Beast's cap reads."""
    avian = _enters(set_pool("ATQ")["Clockwork Avian"])
    assert counters_on(avian, "+1/+0") == 4
    assert (avian.effective_power, avian.effective_toughness) == (4, 4)
