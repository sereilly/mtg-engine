"""``ai_valuation.CounterProfile.can_counter`` asks a spell's colour with its seat.

"Counter target blue spell" (Red Elemental Blast) is a question about the
spell's colour, which is CR 105's question of an object (CR 613.1e): under its
controller's Celestial Dawn a Counterspell is white and is not a legal target.
The predicate read the printed ``card.colors`` — the last entry in
``tests/engine/test_layer_reads.py``'s ``PRINTED_COLOR_BASELINE`` that was not
the layer system's own input. It takes ``game=``/``seat=`` now and asks
``object_colors.card_colors``; with neither it answers from the printed
colours, as before.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_valuation import counters_a_spell
from engine.models import Permanent


def test_a_dawn_makes_a_blue_spell_no_target_for_red_elemental_blast(set_pool):
    pool = dict(set_pool("4ED"))
    dawn = set_pool("6ED")["Celestial Dawn"]
    game = Game(players=[
        PlayerState(name="P0", battlefield=[Permanent(card=dawn)]),
        PlayerState(name="P1"),
    ])
    game._sync_control()

    profile = counters_a_spell(pool["Red Elemental Blast"])
    blue = pool["Counterspell"]

    assert profile is not None and profile.color == "U"
    assert profile.can_counter(blue)  # no seat: the printed colours
    assert not profile.can_counter(blue, game=game, seat=0)  # the Dawn's seat
    assert profile.can_counter(blue, game=game, seat=1)
