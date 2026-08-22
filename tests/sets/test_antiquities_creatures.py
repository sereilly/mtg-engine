"""Per-card tests for Antiquities' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


# ---------------------------------------------------------------------------
# Citanul Druid (round 3) — "whenever an opponent casts an artifact spell"
# ---------------------------------------------------------------------------


def test_citanul_druid_grows_on_an_opponents_artifact_spell(set_pool):
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid])
    p2 = PlayerState(name="P2", hand=[pool["Ornithopter"]])
    game = Game(players=[p1, p2])

    base = druid.effective_power
    game.cast_from_hand(1, "Ornithopter")

    assert druid.effective_power == base + 1


def test_citanul_druid_ignores_your_own_artifact_spell(set_pool):
    """"an **opponent** casts" — the scope half of the narrowing."""
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid], hand=[pool["Ornithopter"]])
    game = Game(players=[p1, PlayerState(name="P2")])

    base = druid.effective_power
    game.cast_from_hand(0, "Ornithopter")

    assert druid.effective_power == base


def test_citanul_druid_ignores_a_nonartifact_spell(set_pool):
    """And the type half."""
    pool = set_pool("ATQ")
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid])
    p2 = PlayerState(name="P2", hand=[pool["Detonate"]])
    game = Game(players=[p1, p2])

    base = druid.effective_power
    game.cast_from_hand(1, "Detonate")

    assert druid.effective_power == base


def test_citanul_druid_compiles_the_narrowed_condition(set_pool):
    program = compile_card_oracle(set_pool("ATQ")["Citanul Druid"])
    (trigger,) = program.triggered_abilities

    assert trigger.supported
    assert trigger.condition.kind == "opponent_casts_spell"
    assert trigger.condition.payload["cast_type"] == "artifact"
