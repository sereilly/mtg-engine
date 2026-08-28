"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _city(set_pool, extra=()):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            _nosick(Permanent(card=pool["City of Shadows"])),
            *[_nosick(Permanent(card=pool[name])) for name in extra],
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, pool


def test_city_of_shadows_eats_a_creature_for_a_storage_counter(set_pool):
    """"{T}, **Exile a creature you control**: Put a storage counter on this
    land."

    The exile is a *cost* (CR 601.2b), so it is charged as the ability is
    activated and nothing about it is a target - protection and shroud have
    nothing to say about what may pay (idiom 10)."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool, extra=["Rag Man"])
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert result.supported, result.details
    assert counters_on(city, "storage") == 1, game.log
    assert [perm.card.name for perm in p1.battlefield] == ["City of Shadows"]
    assert [card.name for card in p1.exile] == ["Rag Man"]


def test_city_of_shadows_cannot_be_activated_with_no_creature(set_pool):
    """The control: with nothing to pay the cost, the ability is not activated
    at all (CR 602.2b) — the land is not even tapped."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert not result.supported
    assert counters_on(city, "storage") == 0
    assert city.tapped is False, game.log


def test_city_of_shadows_taps_for_one_mana_per_storage_counter(set_pool):
    """"{T}: Add {C} **for each storage counter on this land**." Counted off the
    source at resolution, which is what tells it from the batteries' "for each
    counter removed this way" — those are gone by then."""
    from engine.named_counters import add_counters

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]
    add_counters(city, "storage", 3)

    result = game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert result.supported, result.details
    assert p1.mana_pool["C"] == 3, (dict(p1.mana_pool), game.log)


def test_city_of_shadows_with_no_counters_makes_no_mana(set_pool):
    """The control on the multiplier: nothing times a counter is nothing, not
    the flat {C} the pips alone would add."""
    game, p1, p2, pool = _city(set_pool)

    game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert sum(p1.mana_pool.values()) == 0, (dict(p1.mana_pool), game.log)
