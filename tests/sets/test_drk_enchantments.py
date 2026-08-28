"""Per-card tests for The Dark's enchantments.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# --- G5: zones and characteristics (The Dark) ---------------------------------


def _forest() -> CardDefinition:
    return CardDefinition(
        name="Forest", mana_cost="", cmc=0.0,
        type_line="Basic Land - Forest", oracle_text="",
        colors=(), color_identity=("G",), keywords=(), produced_mana=("G",),
        raw={"name": "Forest", "type_line": "Basic Land - Forest"},
    )


def _touch(set_pool, hand=()):
    pool = set_pool("DRK")
    touch = Permanent(card=pool["Gaea's Touch"])
    touch.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[touch], hand=list(hand))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, touch


def test_gaeas_touch_puts_a_basic_forest_onto_the_battlefield(set_pool):
    """"{0}: You may put a basic Forest card from your hand onto the
    battlefield. Activate only as a sorcery and only once each turn."

    The line compiled *supported* with no instruction behind it for as long as
    the restriction clause refused to parse: the ability existed, could be
    activated, and did nothing. This is the behaviour, not the claim.
    """
    game, p1, p2, touch = _touch(set_pool, hand=[_forest()])

    result = game.activate_permanent_ability(0, "Gaea's Touch", permanent_index=0)

    assert result.supported, result.details
    # The offer is a prompt; a seat that answers by default takes it.
    game.auto_resolve_pending_choices()
    assert [perm.card.name for perm in p1.battlefield] == [
        "Gaea's Touch", "Forest",
    ], game.log
    assert p1.hand == []


def test_gaeas_touch_leaves_a_nonbasic_land_in_hand(set_pool):
    """The control: "**basic** Forest card" is carried into the offer, so a land
    that is not one is never a legal answer."""
    pool = set_pool("DRK")
    game, p1, p2, touch = _touch(set_pool, hand=[pool["City of Shadows"]])

    game.activate_permanent_ability(0, "Gaea's Touch", permanent_index=0)
    game.auto_resolve_pending_choices()

    assert [card.name for card in p1.hand] == ["City of Shadows"], game.log
    assert [perm.card.name for perm in p1.battlefield] == ["Gaea's Touch"]


def test_gaeas_touch_can_still_be_sacrificed_for_two_green(set_pool):
    """The card's other ability, checked here because the round that fixed the
    first one rewrote how its lines are read: "Sacrifice this enchantment: Add
    {G}{G}"."""
    game, p1, p2, touch = _touch(set_pool)

    result = game.activate_permanent_ability(
        0, "Gaea's Touch", permanent_index=0, ability_index=1,
    )

    assert result.supported, result.details
    assert p1.mana_pool["G"] == 2, (dict(p1.mana_pool), game.log)
    assert p1.battlefield == []
