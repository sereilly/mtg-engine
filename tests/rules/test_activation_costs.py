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
from engine.oracle import parse_activated_ability_cost

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


# ---------------------------------------------------------------------------
# W2G2 — CR 601.2c's *variable* target count, and CR 611.2a's absent duration
# ---------------------------------------------------------------------------


def _w2g2_card(name, type_line, oracle_text, mana_cost="{3}{B}{B}", cmc=5.0):
    from engine.models import CardDefinition

    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "1", "1"
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text=oracle_text, colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(), raw=raw,
    )


@pytest.mark.cr("601.2c")
def test_a_printed_enumeration_is_a_ceiling_on_the_target_count():
    """"If the spell has a variable number of targets, the player announces how
    many targets they will choose before they announce those targets. ... Once
    the number of targets the spell has is determined, that number doesn't
    change."

    A distribution printed "among one or two target creatures" bounds that
    announcement at two. The ceiling travels on the compiled target description
    so the announcement gate and the picker read one answer; "among any number
    of" prints no ceiling and must carry no key, because an absent key is what
    every reader written before the bound existed already means.
    """
    from engine.grammar import compile_line

    bounded = compile_line(
        "Distribute two -2/-1 counters among one or two target creatures.",
        card_name="Bounded",
    )
    assert bounded.instructions[0].payload["targets"]["max_targets"] == 2

    wider = compile_line(
        "Distribute three +1/+1 counters among one, two, or three target creatures.",
        card_name="Wider",
    )
    assert wider.instructions[0].payload["targets"]["max_targets"] == 3

    unbounded = compile_line(
        "Distribute two -2/-1 counters among any number of target creatures.",
        card_name="Unbounded",
    )
    assert "max_targets" not in unbounded.instructions[0].payload["targets"]


@pytest.mark.cr("601.2c")
def test_an_announcement_past_the_printed_ceiling_is_illegal():
    """The ceiling is checked at announcement, where CR 601.2c puts it, and
    **before** the division CR 601.2d asks for — so a seat that announced no
    shares at all still may not name three targets. That ordering is the whole
    of why it is not folded into the division check: the even-split fallback
    that legitimately excuses an absent division would otherwise excuse an
    over-long target list too."""
    from engine.divided_damage import division_refusal

    three = [(0, 0, 1), (0, 1, 1), (1, 0, 1)]
    assert division_refusal(2, three, division="chosen", max_targets=2)
    assert division_refusal(3, three, division="chosen", max_targets=3) is None

    bare = [(0, 0), (0, 1), (1, 0)]
    assert division_refusal(2, bare, division="chosen", max_targets=2)
    assert division_refusal(2, bare, division="chosen") is None


@pytest.mark.cr("601.2c")
def test_a_bounded_spell_refuses_the_cast_with_nothing_spent():
    """CR 601.2c is announcement, and CR 601.2e returns the game to the moment
    before an illegal proposal — so an over-long list costs the caster nothing.
    Read off the hand, because the cast path pays at CR 601.2h, after the
    targets are checked: a refusal that arrived too late would show as a spell
    that left the hand and did nothing."""
    from engine.models import Permanent

    spell = _w2g2_card(
        "Bounded Distribution", "Instant",
        "Distribute two -2/-1 counters among one or two target creatures.",
    )
    game, p1, p2 = _duel()
    p1.hand.append(spell)
    for _ in range(3):
        p2.battlefield.append(Permanent(card=_CATALOG["Grizzly Bears"]))
    game._settle()

    refused = game.cast_from_hand(
        0, "Bounded Distribution", divided_targets=[(1, 0, 1), (1, 1, 1), (1, 2, 0)],
    )

    assert not refused.supported
    assert [c.name for c in p1.hand] == ["Bounded Distribution"]
    assert not game.stack

    allowed = game.cast_from_hand(
        0, "Bounded Distribution", divided_targets=[(1, 0, 1), (1, 1, 1)],
    )
    game._settle()

    assert allowed.supported, allowed.details
    shrunk = [
        (p.effective_power, p.effective_toughness) for p in game.controlled_by(1)
    ]
    assert shrunk.count((0, 1)) == 2, "one counter each, not both on one"


@pytest.mark.cr("611.2a")
def test_a_continuous_effect_with_no_stated_duration_never_ends():
    """"A continuous effect generated by the resolution of a spell or ability
    lasts as long as stated by the spell or ability creating it (such as "until
    end of turn"). **If no duration is stated, it lasts until the end of the
    game.**"

    A control change is the layer-2 case, and the two spellings must reach
    different machinery: cleanup drops an ``until_eot`` contribution and has to
    leave an untimed one alone. So the absent clause is a *reading* rather than
    a gap, and the compiled program says which one it is."""
    from engine.control import base_controller, control_changes
    from engine.grammar import compile_line
    from engine.models import Permanent

    timed = compile_line("Gain control of target creature until end of turn.")
    untimed = compile_line("Gain control of target creature.")
    assert [i.kind for i in timed.instructions] == ["gain_control_until_eot"]
    assert [i.kind for i in untimed.instructions] == ["gain_control_of_target"]

    spell = _w2g2_card(
        "Untimed Steal", "Sorcery", "Gain control of target creature.",
    )
    game, p1, p2 = _duel()
    p1.hand.append(spell)
    stolen = Permanent(card=_CATALOG["Grizzly Bears"])
    p2.battlefield.append(stolen)
    game._settle()

    result = game.cast_from_hand(
        0, "Untimed Steal", target_player_index=1, target_permanent_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert game.controller_index_of(stolen) == 0
    assert [c["until_eot"] for c in control_changes(stolen)] == [False]
    # CR 613.1: the base controller is untouched, so an effect that *did* end
    # would revert to the right seat.
    assert base_controller(stolen) == 1

    game.resolve_cleanup_step(0)
    game._settle()
    assert game.controller_index_of(stolen) == 0


@pytest.mark.cr("602.2b", "601.2h")
def test_a_conjoined_cost_is_unpayable_unless_both_halves_are():
    """CR 602.2b routes an activation through CR 601.2h, which pays the whole
    cost at one moment — so a cost naming two objects is unpayable unless both
    can be found, and nothing is spent when one cannot."""
    from engine.models import Permanent

    line = "{T}, Sacrifice a creature and a Swamp: Draw a card."
    cost = parse_activated_ability_cost(line)
    assert cost.sacrifice_filter == {"type_filter": "creature"}
    assert cost.sacrifice_also_filter == {"subtype_filter": "swamp"}

    game, p1, _p2 = _duel()
    payer = Permanent(card=_w2g2_card(
        "Conjoined Payer", "Creature — Test", line, mana_cost="{1}{B}", cmc=2.0,
    ))
    p1.battlefield.append(payer)
    game._settle()

    # A creature (the source itself) and no Swamp: refused, nothing sacrificed.
    refused = game.activate_permanent_ability(0, "Conjoined Payer")

    assert not refused.supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Conjoined Payer"]
    assert not p1.graveyard


@pytest.mark.cr("122.1a", "601.2h")
def test_a_counter_placing_cost_names_its_counter_in_symbols():
    """CR 122.1a spells a P/T counter as "+X/+Y" and "-X/-Y" — symbols, not a
    word — so a cost clause read through a bare-word pattern matches nothing at
    all, which is not a refused ability but a **free** one. Both readers (the
    production and the charger) go through the counter vocabulary now.

    The chosen-permanent spelling is also the one such cost that can be
    unpayable (CR 601.2h): a marker on the source can always be placed, and a
    counter on "a creature you control" cannot when there is no creature."""
    marker = parse_activated_ability_cost(
        "{2}, Put a page counter on this artifact: Draw a card."
    )
    assert marker.put_counter == "page"
    assert marker.put_counter_filter is None, "the source, and never unpayable"

    chosen = parse_activated_ability_cost(
        "{B}, Put a -1/-1 counter on a creature you control: Draw a card."
    )
    assert chosen.put_counter == "-1/-1"
    assert chosen.put_counter_filter == {"type_filter": "creature"}
