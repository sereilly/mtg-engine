"""Per-card tests for Antiquities' creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.damage_events import deal_damage
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


# ---------------------------------------------------------------------------
# Argothian Treefolk / Argothian Pixies (round 4) — artifact-source shields
# ---------------------------------------------------------------------------


def test_argothian_treefolk_is_unharmed_by_an_artifact_source(set_pool):
    pool = set_pool("ATQ")
    treefolk = Permanent(card=pool["Argothian Treefolk"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[treefolk])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    outcome = deal_damage(
        game, {"recipient": treefolk, "amount": 3, "source": thopter, "combat": False}
    )

    assert outcome.dealt == 0


def test_argothian_treefolk_still_takes_damage_from_a_creature(set_pool):
    """The narrowing under load: the shield names artifact sources, so an
    ordinary creature gets through."""
    pool = set_pool("ATQ")
    treefolk = Permanent(card=pool["Argothian Treefolk"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[treefolk])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    outcome = deal_damage(
        game, {"recipient": treefolk, "amount": 3, "source": druid, "combat": False}
    )

    assert outcome.dealt == 3


def test_argothian_pixies_cannot_be_blocked_by_an_artifact_creature(set_pool):
    pool = set_pool("ATQ")
    pixies = Permanent(card=pool["Argothian Pixies"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[pixies])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(thopter, pixies) is False


def test_argothian_pixies_can_still_be_blocked_by_an_ordinary_creature(set_pool):
    """The restriction names artifact creatures; a flesh-and-blood blocker is
    unaffected. Without this the test above would pass against a rule that
    stopped every block."""
    pool = set_pool("ATQ")
    pixies = Permanent(card=pool["Argothian Pixies"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[pixies])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    assert game._can_block_attacker(druid, pixies) is True
