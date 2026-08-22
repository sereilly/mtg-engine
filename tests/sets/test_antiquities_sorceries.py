"""Per-card tests for Antiquities' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Detonate (round 23) — a target bound to the cast's X
# ---------------------------------------------------------------------------


def _detonate(set_pool, target_name):
    """Detonate in P1's hand, *target_name* on P2's battlefield."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Detonate"]])
    victim = Permanent(card=pool[target_name])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, victim


def test_detonate_destroys_the_artifact_and_burns_its_controller(set_pool):
    """Su-Chi's mana value is 4, so X is 4 and so is the damage."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")
    life = p2.life

    result = game.cast_from_hand(
        0, "Detonate", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert "Su-Chi" not in {perm.card.name for perm in p2.battlefield}
    assert p2.life == life - 4, game.log


def test_the_damage_scales_with_the_target_rather_than_being_printed(set_pool):
    """The control on the test above: nothing about Detonate is a fixed 4. An
    Ornithopter costs nothing, so X is 0 and the artifact dies for free."""
    game, p1, p2, victim = _detonate(set_pool, "Ornithopter")
    life = p2.life

    game.cast_from_hand(0, "Detonate", target_player_index=1, target_permanent_index=0)

    assert "Ornithopter" not in {perm.card.name for perm in p2.battlefield}
    assert p2.life == life, "X is 0, and CR 120.8 makes 0 damage no damage at all"


def test_an_x_that_does_not_match_the_target_cannot_be_cast(set_pool):
    """CR 601.2c: "target artifact with mana value X" is one restriction over
    two announcements, and an X naming a value the chosen artifact does not have
    makes the choice illegal — not a spell that resolves and fizzles."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")

    result = game.cast_from_hand(
        0, "Detonate", target_player_index=1, target_permanent_index=0, x_value=1,
    )

    assert not result.supported
    assert "Su-Chi" in {perm.card.name for perm in p2.battlefield}


def test_the_damage_goes_to_the_player_not_the_destroyed_artifact(set_pool):
    """The sentence names a player, and the destroy in front of it leaves a
    permanent index on the resolution context. A damage clause that inferred
    "player" from the *absence* of that index aimed this one at the artifact it
    had just destroyed, and the spell dealt no damage at all."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")

    game.cast_from_hand(0, "Detonate", target_player_index=1, target_permanent_index=0)

    assert any("dealt 4 damage to P2" in entry for entry in game.log), game.log
