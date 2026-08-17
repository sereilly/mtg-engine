"""CR 601.2 reached through CR 602.2b — activating an ability, in order.

CR 602.2b routes activation through the casting steps, so an ability chooses its
targets at CR 601.2c and pays its costs at CR 601.2h, in that order. The gap
between those two steps is where these live: a cost that *removes a permanent*
renumbers every battlefield slot after it, and a cost of pure generic mana has
no coloured pip to check.

Both were found by working through the nineteen shipped cards no manual pass had
ever looked at (round 45's tracker fix made the list visible). Both cards
reported ``supported`` and did something other than what they print.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CATALOG = {c.name: c for c in load_catalog()}


def _duel(active: int = 0, enforce: bool = False) -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.active_player_index = active
    return game, p1, p2


# ---------------------------------------------------------------------------
# A target chosen before a cost is paid must survive the payment
# ---------------------------------------------------------------------------


@pytest.mark.cr("602.2b", "601.2c", "601.2h")
def test_a_cost_that_removes_a_permanent_does_not_move_the_target():
    """Dwarven Weaponsmith: "{T}, Sacrifice an artifact: Put a +1/+1 counter on
    target creature."

    The target is chosen (601.2c) before the cost is paid (601.2h), so what the
    ability aims at cannot depend on what the payment does to the battlefield.
    An *index* does depend on it: everything after the sacrificed artifact
    slides down one, and the slot the caller named is then either a different
    permanent or out of range.

    The engine's answer everywhere else is to address a permanent by its
    ``permanent_id``, which is stable across a removal. Activation stamps it at
    601.2c now, which is where the choice is made.
    """
    game, p1, _p2 = _duel()
    smith = Permanent(card=_CATALOG["Dwarven Weaponsmith"])
    smith.metadata["summoning_sickness_turn"] = -99
    fuel = Permanent(card=_CATALOG["Black Lotus"])
    bear = Permanent(card=_CATALOG["Grizzly Bears"])
    p1.battlefield += [smith, fuel, bear]
    game.current_turn_phase, game.current_step = "beginning", "upkeep"

    game.activate_permanent_ability(
        0, "Dwarven Weaponsmith", target_player_index=0, target_permanent_index=2
    )
    game._settle()

    assert not game.is_on_battlefield(fuel), "the artifact paid the cost"
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert (smith.effective_power, smith.effective_toughness) == (1, 1)


@pytest.mark.cr("602.2b", "601.2c")
def test_the_same_ability_is_unaffected_when_nothing_renumbers():
    """The control case, which is why this went unseen: with the artifact
    *after* the target, no slot moves and the index still names the creature it
    named. The bug was invisible in exactly half the possible board layouts.
    """
    game, p1, _p2 = _duel()
    smith = Permanent(card=_CATALOG["Dwarven Weaponsmith"])
    smith.metadata["summoning_sickness_turn"] = -99
    bear = Permanent(card=_CATALOG["Grizzly Bears"])
    fuel = Permanent(card=_CATALOG["Black Lotus"])
    p1.battlefield += [smith, bear, fuel]
    game.current_turn_phase, game.current_step = "beginning", "upkeep"

    game.activate_permanent_ability(
        0, "Dwarven Weaponsmith", target_player_index=0, target_permanent_index=1
    )
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (3, 3)


# ---------------------------------------------------------------------------
# A cost of generic mana is still a cost
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.3", "118.3a", "107.4")
def test_a_generic_only_upkeep_cost_cannot_be_paid_with_nothing():
    """"A player can't pay a cost without having the necessary resources to pay
    it fully" (CR 118.3), and generic mana is a resource like any other.

    Energy Flux grants every artifact "sacrifice this artifact unless you pay
    {2}". The pay-or-sacrifice handlers decided payment by testing the coloured
    pips alone — an ``all()`` over an empty sequence, so a cost with no coloured
    pip was paid for free and the enchantment did nothing.
    """
    game, p1, p2 = _duel(active=1, enforce=True)
    p1.battlefield.append(Permanent(card=_CATALOG["Energy Flux"]))
    p2.battlefield.append(Permanent(card=_CATALOG["Millstone"]))
    game._recompute_continuous_effects()

    game.resolve_upkeep(1)

    assert [perm.card.name for perm in p2.battlefield] == []


@pytest.mark.cr("118.3a", "107.4")
def test_paying_a_generic_upkeep_cost_actually_spends_the_mana():
    """"Paying mana is done by removing the indicated mana from a player's mana
    pool" (CR 118.3a) — the half a free payment also skipped."""
    game, p1, p2 = _duel(active=1, enforce=True)
    p1.battlefield.append(Permanent(card=_CATALOG["Energy Flux"]))
    p2.battlefield.append(Permanent(card=_CATALOG["Millstone"]))
    p2.mana_pool["C"] = 2
    game._recompute_continuous_effects()

    game.resolve_upkeep(1)

    assert [perm.card.name for perm in p2.battlefield] == ["Millstone"]
    assert p2.mana_pool["C"] == 0


@pytest.mark.cr("118.3", "107.4")
def test_a_partly_generic_upkeep_cost_checks_both_halves():
    """The shape that made the bug survive review: a cost like {1}{U} *does*
    have a coloured pip, so the old test passed on the {U} and waived the {1}.
    Checked with an invented card rather than a printed one, because the pool
    happens not to print a mixed upkeep cost — the rule is not about the pool.
    """
    import dataclasses

    card = dataclasses.replace(
        _CATALOG["Stasis"],
        name="Test Stasis",
        oracle_text="At the beginning of your upkeep, sacrifice this enchantment unless you pay {1}{U}.",
    )
    game, p1, _p2 = _duel(enforce=True)
    p1.battlefield.append(Permanent(card=card))
    p1.mana_pool["U"] = 1  # the coloured pip alone

    game.resolve_upkeep(0)

    assert [perm.card.name for perm in p1.battlefield] == [], (
        "the {1} is unpaid, so the whole cost is"
    )


# ---------------------------------------------------------------------------
# Paying life is a cost like any other (CR 118.3b, 119.4)
# ---------------------------------------------------------------------------


def _pay_life_card(amount: int):
    """A shipped creature reprinted with a life-payment activation cost.

    Invented rather than printed because the rule is not about the pool. The
    pool's one such card is Tavern Swindler, which is measured and not shipped,
    so ``load_catalog`` cannot see it â€” and a rule test that could only run once
    a particular set ships is testing the set.
    """
    import dataclasses

    return dataclasses.replace(
        _CATALOG["Grizzly Bears"],
        name="Test Bloodletter",
        # The effect is a pump rather than a life gain on purpose: an effect
        # that moves life would make "how much did the cost take?" unreadable
        # from the life total afterwards.
        oracle_text=f"{{T}}, Pay {amount} life: This creature gets +1/+1 until end of turn.",
    )


def _bloodletter(life: int, amount: int = 3):
    game, p1, _p2 = _duel()
    perm = Permanent(card=_pay_life_card(amount))
    perm.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(perm)
    p1.life = life
    game.current_turn_phase, game.current_step = "precombat_main", "precombat_main"
    return game, p1, perm


@pytest.mark.cr("119.4", "118.3b")
def test_life_may_be_paid_down_to_exactly_zero():
    """"the player may do so only if their life total is greater than or equal
    to the amount of the payment" (CR 119.4) â€” greater **or equal**, so a player
    at exactly the cost can pay it. Refusing at equality is the off-by-one this
    pins: it would make every life cost one point more expensive than printed."""
    game, p1, _perm = _bloodletter(life=3)

    result = game.activate_permanent_ability(0, "Test Bloodletter", permanent_index=0)

    assert result.supported, result.details
    assert p1.life == 0


@pytest.mark.cr("119.4", "602.5c")
def test_life_below_the_payment_makes_the_ability_unactivatable():
    """One point short is not a partial payment (CR 601.2h) and not a free
    ability (CR 602.5c): it is an ability that cannot be activated at all."""
    game, p1, perm = _bloodletter(life=2)

    result = game.activate_permanent_ability(0, "Test Bloodletter", permanent_index=0)

    assert not result.supported
    assert "life" in result.details, "refused for the cost, not for being unreadable"
    assert p1.life == 2, "an unpayable cost is not partly paid"
    assert perm.tapped is False, "and no other cost of the same ability is paid either"


@pytest.mark.cr("119.4", "704.5a")
def test_paying_the_last_life_loses_the_game_to_a_state_based_action():
    """CR 119.4 permits the payment; CR 704.5a is what then happens. The two are
    separate rules, and an engine that refused the payment to protect the player
    would be enforcing neither."""
    game, p1, _perm = _bloodletter(life=3)

    game.activate_permanent_ability(0, "Test Bloodletter", permanent_index=0)

    assert p1.life == 0
    assert p1.lost is True


@pytest.mark.cr("119.4b")
def test_a_zero_life_payment_is_not_a_cost_the_parser_admits():
    """"Players can always pay 0 life, no matter what their life total is"
    (CR 119.4b) â€” so a printed 0 restricts nothing, and admitting it would put a
    cost in the ability that no life total can fail."""
    from engine.grammar import compile_line

    result = compile_line("{T}, Pay 0 life: You gain 1 life.")

    assert not result.parsed
    assert result.failure_reason == "only a fixed, positive life payment is charged"
