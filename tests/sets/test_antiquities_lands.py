"""Per-card tests for Antiquities' lands.

The Urza's cycle is why `engine/oracle.py`'s land gate had to learn the
difference between a land with an unreadable *bonus* ability and one whose
unreadable line is the whole card — see ROADMAP, ATQ round 1. These tests are
the other half: that the assembly, once read, assembles correctly and only
when it should.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _game(pool, *land_names):
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool[name]) for name in land_names]
    )
    return Game(players=[p1, PlayerState(name="P2")]), p1


# ---------------------------------------------------------------------------
# The Urza's cycle (round 2)
# ---------------------------------------------------------------------------


def test_urzas_mine_alone_taps_for_one(set_pool):
    pool = set_pool("ATQ")
    game, p1 = _game(pool, "Urza's Mine")

    assert game.tap_land_for_mana(0, "Urza's Mine")
    assert p1.mana_pool["C"] == 1


def test_urzas_mine_assembles_for_two(set_pool):
    """"If you control an Urza's Power-Plant and an Urza's Tower, add {C}{C}
    instead." Both halves of the conjunction are required, which is the whole
    reason the noun phrase lowers to `subtype_filter_all`."""
    pool = set_pool("ATQ")
    game, p1 = _game(pool, "Urza's Mine", "Urza's Power Plant", "Urza's Tower")

    assert game.tap_land_for_mana(0, "Urza's Mine")
    assert p1.mana_pool["C"] == 2


def test_urzas_tower_assembles_for_three(set_pool):
    pool = set_pool("ATQ")
    game, p1 = _game(pool, "Urza's Mine", "Urza's Power Plant", "Urza's Tower")

    assert game.tap_land_for_mana(0, "Urza's Tower")
    assert p1.mana_pool["C"] == 3


def test_two_thirds_of_the_cycle_does_not_assemble(set_pool):
    """The conjunction under load. An OR'd subtype filter would have let the
    Mine satisfy "an Urza's Tower" on its own — it is an Urza's, after all —
    and the Tower would pay three off two lands."""
    pool = set_pool("ATQ")
    game, p1 = _game(pool, "Urza's Mine", "Urza's Tower")

    assert game.tap_land_for_mana(0, "Urza's Tower")
    assert p1.mana_pool["C"] == 1


def test_the_assembly_reads_your_own_battlefield(set_pool):
    """"If **you** control…" — an opponent's Power-Plant and Tower do not
    complete your Mine's assembly."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Urza's Mine"])])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=pool["Urza's Power Plant"]),
            Permanent(card=pool["Urza's Tower"]),
        ],
    )
    game = Game(players=[p1, p2])

    assert game.tap_land_for_mana(0, "Urza's Mine")
    assert p1.mana_pool["C"] == 1


# ---------------------------------------------------------------------------
# Mishra's Workshop (round 2)
# ---------------------------------------------------------------------------


def test_mishras_workshop_taps_for_three_restricted_mana(set_pool):
    """Three {C}, not the one `produced_mana` records — and carrying the
    restriction, which is the half that cannot be seen in the pool total."""
    pool = set_pool("ATQ")
    program = compile_card_oracle(pool["Mishra's Workshop"])
    (ability,) = program.activated_abilities

    assert ability.supported
    assert ability.instruction.payload["pips"] == (("C", 3),)
    assert ability.instruction.payload["spend_only"] == "artifact"
