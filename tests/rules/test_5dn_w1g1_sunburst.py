"""Sunburst — CR 702.44.

CR 702.44a *defines* the keyword: "If this object is entering as a creature,
ignoring any type-changing effects that would affect it, it enters with a +1/+1
counter on it for each color of mana spent to cast it. Otherwise, it enters
with a charge counter on it for each color of mana spent to cast it."
``engine/sunburst.py`` rewrites the printed line into that sentence;
``enter_effects.enters_with_counters_per_color_spent`` reads it, and the entry
state counts the colours the cast's payment measured. These tests cast through
the real cast path with costs enforced, so the number is the payment's and not
a stamp a test wrote.

The per-card tests for Fifth Dawn's seventeen are in
``tests/sets/test_5dn_artifacts.py`` and ``tests/sets/test_5dn_creatures.py``.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import CardDefinition, PlayerState
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.sunburst import (SUNBURST_RULES_TEXT, color_spreading_costs,
                             unread_sunburst_line)

from tests.helpers import settle

_CREATURE_REMINDER = (
    "Sunburst (This creature enters with a +1/+1 counter on it for each color "
    "of mana spent to cast it.)"
)


def _fixture(name, text, *, mana_cost="{2}", type_line="Artifact Creature — Test"):
    """A 0/0 printing *text*, with no ingested keywords: the printed line is
    what is read."""
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=2.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "0", "toughness": "0"},
    )


def _table(set_pool, *, hand=(), graveyard=()) -> Game:
    """Two seats on seat 0's first main phase, costs enforced."""
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
            graveyard=list(graveyard) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = True
    game.start_turn(0)
    settle(game)
    return game


def _cast(game, name, pool, **announce):
    game.players[0].mana_pool.update(pool)
    result = game.cast_from_hand(0, name, **announce)
    assert result.supported, (result, game.log[-5:])
    settle(game)
    return next(
        (p for p in game.all_permanents() if p.card.name == name), None
    )


@pytest.mark.cr("702.44a")
def test_the_keyword_is_rewritten_into_the_rule_s_own_sentence():
    card = _fixture("Test Sunburst", _CREATURE_REMINDER)
    assert expand_ability_lines(card.oracle_text) == SUNBURST_RULES_TEXT
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    # A sunburst-shaped line nothing reads keeps the card unsupported naming
    # it, rather than an artifact entering with nothing on it.
    odd = _fixture("Test Odd Sunburst", "Sunburst 2", type_line="Artifact")
    assert unread_sunburst_line(expand_ability_lines(odd.oracle_text)) == "Sunburst 2"
    assert not compile_card_oracle(odd).supported


@pytest.mark.cr("702.44a")
def test_a_creature_gets_a_plus_one_counter_for_each_color_and_none_for_colorless(set_pool):
    """Colourless is not a colour (Engineered Explosives, 2020-08-07)."""
    myr = set_pool("5DN")["Suntouched Myr"]
    game = _table(set_pool, hand=[myr])
    permanent = _cast(game, "Suntouched Myr", {"W": 1, "U": 1, "C": 1})
    assert counters_on(permanent, "+1/+1") == 2
    assert counters_on(permanent, "charge") == 0
    assert (permanent.effective_power, permanent.effective_toughness) == (2, 2)


@pytest.mark.cr("702.44a")
def test_one_color_spent_three_times_is_one_color(set_pool):
    myr = set_pool("5DN")["Suntouched Myr"]
    game = _table(set_pool, hand=[myr])
    permanent = _cast(game, "Suntouched Myr", {"G": 3})
    assert counters_on(permanent, "+1/+1") == 1


@pytest.mark.cr("702.44a")
def test_a_noncreature_gets_charge_counters(set_pool):
    prism = set_pool("5DN")["Pentad Prism"]
    game = _table(set_pool, hand=[prism])
    permanent = _cast(game, "Pentad Prism", {"R": 1, "G": 1})
    assert counters_on(permanent, "charge") == 2
    assert counters_on(permanent, "+1/+1") == 0


@pytest.mark.cr("702.44a")
def test_the_kind_ignores_type_changing_effects(set_pool):
    """Under March of the Machines a noncreature sunburst artifact enters as a
    creature *only* by a type-changing effect, which the rule ignores: charge
    counters, and the 2/2 March makes of it carries no +1/+1."""
    prism = set_pool("5DN")["Pentad Prism"]
    game = _table(set_pool, hand=[prism])
    from engine.models import Permanent

    march = Permanent(card=set_pool("MRD")["March of the Machines"])
    game._put_permanent_onto_battlefield(0, march, None)
    permanent = _cast(game, "Pentad Prism", {"R": 1, "G": 1})
    assert permanent.is_creature
    assert counters_on(permanent, "charge") == 2
    assert counters_on(permanent, "+1/+1") == 0


@pytest.mark.cr("702.44a", "707.2")
def test_a_copy_entering_as_an_artifact_creature_counts_its_own_cast(set_pool):
    """Copy Artifact copying Suntouched Myr enters *as* an artifact creature —
    the copy effect is its copiable values, not a type change — with sunburst,
    from the stack as a resolving spell: one +1/+1 counter for each colour
    spent on Copy Artifact, whatever was spent on the Myr."""
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = _table(set_pool, hand=[fdn["Suntouched Myr"], lea["Copy Artifact"]])
    myr = _cast(game, "Suntouched Myr", {"R": 1, "G": 1, "B": 1})
    assert counters_on(myr, "+1/+1") == 3
    copy = _cast(
        game, "Copy Artifact", {"U": 1, "W": 1},
        target_permanent_ids=[myr.permanent_id],
    )
    assert copy.effective_card.name == "Suntouched Myr"
    assert counters_on(copy, "+1/+1") == 2


@pytest.mark.cr("702.44b")
def test_no_counters_for_a_permanent_that_was_not_cast(set_pool):
    """Animate Dead returns Suntouched Myr from a graveyard: it enters, but not
    from the stack as a resolving spell, so it gets nothing and dies a 0/0."""
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = _table(set_pool, hand=[lea["Animate Dead"]], graveyard=[fdn["Suntouched Myr"]])
    game.players[0].mana_pool.update({"B": 1, "R": 1})
    result = game.cast_from_hand(0, "Animate Dead", target_player_index=0)
    assert result.supported, result
    settle(game)
    assert any("reanimated Suntouched Myr" in line for line in game.log)
    assert not any("Suntouched Myr enters with" in line for line in game.log)
    assert any("Suntouched Myr died" in line for line in game.log)
    assert "Suntouched Myr" in [card.name for card in game.players[0].graveyard]


@pytest.mark.cr("702.44b")
def test_mana_spent_on_an_additional_cost_counts(set_pool):
    """Kicker's mana is spent to cast the spell (CR 702.44b: "including
    additional or alternative costs"): {2} paid with colourless and a kicked
    {R} is one colour."""
    text = "Kicker {R}\n" + _CREATURE_REMINDER
    kicked = _fixture("Test Kicked Sunburst", text)
    unkicked = _fixture("Test Unkicked Sunburst", text)
    game = _table(set_pool, hand=[kicked, unkicked])
    permanent = _cast(
        game, "Test Kicked Sunburst", {"C": 2, "R": 1},
        optional_cost_payments={"{R}": 1},
    )
    assert counters_on(permanent, "+1/+1") == 1
    game.players[0].mana_pool.update({"C": 2})
    assert game.cast_from_hand(0, "Test Unkicked Sunburst").supported
    settle(game)
    assert "Test Unkicked Sunburst" in [c.name for c in game.players[0].graveyard]


@pytest.mark.cr("702.44a")
def test_spending_mana_as_though_another_color_counts_the_mana_spent(set_pool):
    """The Pentad Prism ruling (2020-08-07): "If an effect allows you to spend
    mana 'as though it were mana' of any color or type, … it doesn't change
    what mana you spent." Under Sunglasses of Urza two white pay {1}{R}: one
    colour, white."""
    lea = set_pool("LEA")
    red = _fixture("Test Red Sunburst", _CREATURE_REMINDER, mana_cost="{1}{R}")
    game = _table(set_pool, hand=[red])
    from engine.models import Permanent

    game._put_permanent_onto_battlefield(0, Permanent(card=lea["Sunglasses of Urza"]), None)
    permanent = _cast(game, "Test Red Sunburst", {"W": 2})
    assert counters_on(permanent, "+1/+1") == 1
    assert permanent.metadata["mana_spent_to_cast"] == {"W": 2}


@pytest.mark.cr("702.44a")
def test_floating_mana_pays_with_as_many_colors_as_it_holds(set_pool):
    """The payer's choice (CR 601.2h), and the one a payer makes for a
    sunburst spell: {3} out of W, W, U, U, B floating is W, U and B."""
    myr = set_pool("5DN")["Suntouched Myr"]
    game = _table(set_pool, hand=[myr])
    permanent = _cast(game, "Suntouched Myr", {"W": 2, "U": 2, "B": 1})
    assert counters_on(permanent, "+1/+1") == 3
    assert game.players[0].mana_pool.get("W") == 1
    assert game.players[0].mana_pool.get("U") == 1
    assert list(color_spreading_costs({"generic": 1, "W": 1}))[0] == {
        "generic": 0, "W": 1, "U": 1,
    }


@pytest.mark.cr("702.44c", "702.43a")
def test_modular_sunburst_counts_colors_and_passes_them_on(set_pool):
    """Arcbound Wanderer's "Modular—Sunburst" is CR 702.44c's own example: it
    enters with a +1/+1 counter for each colour, and when it dies its counters
    go onto target artifact creature — the counters it left with (the
    2004-12-01 ruling)."""
    lea, fdn = set_pool("LEA"), set_pool("5DN")
    game = _table(set_pool, hand=[fdn["Arcbound Wanderer"], fdn["Suntouched Myr"], lea["Shatter"]])
    wanderer = _cast(game, "Arcbound Wanderer", {"W": 1, "U": 1, "B": 1, "R": 1, "C": 2})
    assert counters_on(wanderer, "+1/+1") == 4
    myr = _cast(game, "Suntouched Myr", {"G": 3})
    assert counters_on(myr, "+1/+1") == 1
    game.players[0].mana_pool.update({"R": 1, "C": 1})
    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[wanderer.permanent_id]
    ).supported
    settle(game)
    assert not game.is_on_battlefield(wanderer)
    assert counters_on(myr, "+1/+1") == 5


@pytest.mark.cr("702.44d")
def test_two_instances_each_work(set_pool):
    twice = _fixture("Test Twice Sunburst", _CREATURE_REMINDER + "\n" + _CREATURE_REMINDER)
    game = _table(set_pool, hand=[twice])
    permanent = _cast(game, "Test Twice Sunburst", {"W": 1, "B": 1})
    assert counters_on(permanent, "+1/+1") == 4
