"""One damage event, one contention set (CR 616.1) — engine/damage_events.py.

CR 616.1 does not separate replacement effects from prevention effects when it
decides what modifies an event: they are gathered together, one is chosen, it is
applied, and the rest are re-asked. The engine implements them in two registries,
so these tests are about the seam — that the union is what runs, that asking the
union costs nothing, that the two registries cannot silently tie, and that the
default choice reproduces the conventions each recipient kind needs.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.damage_events import _assert_one_order_space, damage_candidates, modify_damage
from engine.game import Game
from engine.models import Permanent
from engine.prevention import POOL
from engine.replacements import REPLACEMENTS, replacement_effect
from tests.helpers import _mk_creature_card

FLOOR_TEXT = (
    "damage that would reduce your life total to less than 1 reduces it to 1 instead"
)


def _player_with_a_floor_and_a_pool(life: int = 4, pool: int = 2):
    ali = _mk_creature_card("Life Floor", power=1, toughness=3, oracle_text=FLOOR_TEXT)
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ali)], life=life)
    p1.damage_prevention_pool = pool
    game = Game(players=[p1, PlayerState(name="P2")])
    return game, p1


@pytest.mark.cr("616.1")
def test_616_1_one_damage_event_gathers_both_registries():
    """The effects attempting to modify one damage event are the shields *and*
    the replacements at once. Counting from a single registry can only
    undercount, and that count is exactly what the affected player's choice
    would be over."""
    game, p1 = _player_with_a_floor_and_a_pool()
    event = {"recipient": p1, "amount": 10, "source": None, "combat": False}

    applicable = [c.key for c in damage_candidates(p1) if c.applies(game, event)]

    assert "_prevention_pool" in applicable, "the shield registry contributed"
    assert "_floor_life_at_one" in applicable, "the replacement registry contributed"


@pytest.mark.cr("616.1")
def test_616_1_asking_the_union_applies_nothing():
    """The purity contract holds across the seam, not just within one registry:
    an effect from either side may be asked about and then not chosen."""
    game, p1 = _player_with_a_floor_and_a_pool()
    event = {"recipient": p1, "amount": 10, "source": None, "combat": False}

    before = (p1.life, p1.damage_prevention_pool)
    [c.applies(game, event) for c in damage_candidates(p1)]

    assert (p1.life, p1.damage_prevention_pool) == before, (
        "asking which effects apply to a damage event applied one"
    )


@pytest.mark.cr("616.1")
def test_616_1_the_union_applies_each_side_once_and_composes_them():
    game, p1 = _player_with_a_floor_and_a_pool(life=4, pool=2)

    consumed, amount = modify_damage(
        game, {"recipient": p1, "amount": 10, "source": None, "combat": False}
    )

    assert not consumed
    assert p1.damage_prevention_pool == 0, "the shield applied"
    assert amount == 3, "10 damage, 2 prevented, the remaining 8 floored to 3"


@pytest.mark.cr("616.1")
def test_616_1_a_settled_event_is_not_offered_to_the_other_registry():
    """A shield that absorbs the whole event leaves nothing for a replacement to
    modify, and the stop condition spans both sides rather than each pass
    ending on its own terms."""
    game, p1 = _player_with_a_floor_and_a_pool(life=4, pool=20)

    consumed, amount = modify_damage(
        game, {"recipient": p1, "amount": 10, "source": None, "combat": False}
    )

    assert (consumed, amount) == (False, 0)
    assert p1.damage_prevention_pool == 10
    assert p1.life == 4, "the floor had nothing to floor"


@pytest.mark.cr("616.1e")
def test_616_1e_the_default_order_differs_by_recipient_on_purpose():
    """CR 616.1e lets the affected player pick any order; these are the defaults
    a non-interactive seat takes, and they are opposite for the two recipients
    for reasons that belong to the effects involved. To a permanent the
    replacements are redirects, so they run before a shield can be spent on
    damage that then leaves; to a player the replacement is a floor that has to
    read the life total the shields actually left it."""
    bear = Permanent(card=_mk_creature_card("Bear", 2, 2))
    creature_orders = {c.key: c.order for c in damage_candidates(bear)}
    player_orders = {c.key: c.order for c in damage_candidates(PlayerState(name="P"))}

    assert creature_orders["_redirect_damage_to_player"] < creature_orders["_prevention_pool"]
    assert creature_orders["_prevent_desert_damage"] < creature_orders["_prevention_pool"]
    assert player_orders["_floor_life_at_one"] > player_orders["_prevention_pool"]


@pytest.mark.cr("616.1")
def test_616_1_a_shield_and_a_replacement_may_not_share_an_order():
    """Each registry rejects a duplicate within itself, but a damage event's
    order space spans both — so the tie neither can see on its own has to be
    caught where they are put together, and at import for the same reason."""
    kind = "damage_to_player"
    try:
        replacement_effect(kind, POOL, applies=lambda game, payload: True)(
            lambda game, payload: None
        )
        with pytest.raises(ValueError, match="share one order space"):
            _assert_one_order_space()
    finally:
        REPLACEMENTS[kind] = [c for c in REPLACEMENTS[kind] if c.order != POOL]
    _assert_one_order_space()
