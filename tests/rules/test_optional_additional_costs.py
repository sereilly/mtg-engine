"""CR 601.2b's *optional* additional costs, and reading back what was paid.

``engine/cast_costs.py`` implemented every additional cost this pool prints
except the optional one. The distinction is not cosmetic: every other clause in
that table is a **price**, so CR 601.2h's gate turns an unpayable one into an
uncastable spell, while an offer nobody takes costs nothing at all and an offer
taken past what the pool holds is refused by the mana payment itself.

What makes it a subsystem rather than a flag is that the resolution reads the
announcement back — "for each additional {1}{R} you paid", "if this spell's
additional cost was paid" — and by then the mana pool that paid it is empty
(CR 500.4), so the count on the stack item is the only record there is.

These tests are about the *rule*; the cards that print it have their own tests
under ``tests/sets/``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.cast_costs import additional_cost_for_line, additional_costs
from engine.models import Permanent

_ALL = {
    card.name: card
    for card in load_cards(manifest_set_path("ALL", include_measured=True))
}
_LEA = {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _caster(card_name: str, **pool: int) -> tuple[Game, PlayerState]:
    """One seat holding *card_name*, with *pool* already in its mana pool.

    The pool rather than lands, because casting spends the pool (CR 106.4) and
    a test that tapped lands would be testing the mana planner instead.
    """
    caster = PlayerState(name="A", hand=[_ALL[card_name]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    for symbol, count in pool.items():
        caster.mana_pool[symbol] = count
    game._settle()
    return game, caster


# ---------------------------------------------------------------------------
# Announcement (CR 601.2b) and the rewind of an illegal one (CR 601.2e)
# ---------------------------------------------------------------------------

@pytest.mark.cr("601.2b")
def test_an_optional_additional_cost_defaults_to_being_declined():
    """"You **may** pay {1}{G} any number of times." Announcing nothing takes
    the offer zero times, which is the only default that cannot charge a player
    for a price they did not accept."""
    game, caster = _caster("Taste of Paradise", G=4)

    result = game.cast_from_hand(0, "Taste of Paradise")
    game._settle()

    assert result.supported, result.details
    assert caster.life == 23, "the printed 3, and none of the offer"
    assert sum(caster.mana_pool.values()) == 0, "the printed {3}{G} and no more"


@pytest.mark.cr("601.2b")
def test_the_repeat_count_is_charged_and_read_back():
    """Taking the offer twice costs twice and scales the effect twice. The two
    halves are the point: a count charged but not read back is a card that gains
    nothing for the mana, and one read back but not charged is a free spell."""
    game, caster = _caster("Taste of Paradise", G=8)

    result = game.cast_from_hand(
        0, "Taste of Paradise", optional_cost_payments={"{1}{G}": 2},
    )
    game._settle()

    assert result.supported, result.details
    assert caster.life == 29, "3, plus 3 for each of the two extra {1}{G}"
    assert sum(caster.mana_pool.values()) == 0, "{3}{G} plus two {1}{G}"


@pytest.mark.cr("601.2e")
def test_announcing_an_offer_the_card_does_not_print_is_refused():
    """CR 601.2e returns the game to before an illegal proposal. Naming a cost
    the card does not offer is one, and the refusal has to come before anything
    is spent — a clamp to zero would let the caster's announcement be quietly
    replaced by a different one."""
    game, caster = _caster("Taste of Paradise", G=8)

    result = game.cast_from_hand(
        0, "Taste of Paradise", optional_cost_payments={"{1}{R}": 1},
    )
    game._settle()

    assert not result.supported
    assert "{1}{R}" in result.details and "{1}{G}" in result.details
    assert caster.life == 20
    assert [c.name for c in caster.hand] == ["Taste of Paradise"]
    assert sum(caster.mana_pool.values()) == 8, "a refused cast spends nothing"


@pytest.mark.cr("601.2b")
def test_an_offer_without_any_number_of_times_may_be_taken_once():
    """Undergrowth prints "you may pay {2}{R}" with no repeat clause, so taking
    it twice is an announcement the card does not allow — refused rather than
    silently charged once, which would resolve a spell the caster did not
    propose."""
    game, caster = _caster("Undergrowth", G=1, R=6)

    result = game.cast_from_hand(
        0, "Undergrowth", optional_cost_payments={"{2}{R}": 2},
    )
    game._settle()

    assert not result.supported
    assert "once" in result.details
    assert sum(caster.mana_pool.values()) == 7


@pytest.mark.cr("601.2h")
def test_an_offer_taken_past_the_pool_refuses_the_cast_and_spends_nothing():
    """CR 601.2h: an unpayable cost cannot be paid, and CR 601.2's rewind makes
    that "the spell is not cast" rather than "the spell is cast for less". The
    optional cost is deliberately **not** in ``_unpayable_additional_cost`` — it
    is folded into the mana, so the mana payment is the gate, and that payment
    leaves the pool untouched when it fails."""
    game, caster = _caster("Taste of Paradise", G=4)

    result = game.cast_from_hand(
        0, "Taste of Paradise", optional_cost_payments={"{1}{G}": 3},
    )
    game._settle()

    assert not result.supported
    assert caster.life == 20
    assert sum(caster.mana_pool.values()) == 4
    assert [c.name for c in caster.hand] == ["Taste of Paradise"]


@pytest.mark.cr("601.2f")
def test_the_offer_is_charged_in_its_printed_colours():
    """CR 601.2f totals the costs, and a coloured pip stays coloured: {1}{G}
    twice is two generic **and two green**, not four of anything. A pool with
    the right total in the wrong colour cannot pay it."""
    game, caster = _caster("Taste of Paradise", G=1, R=7)

    result = game.cast_from_hand(
        0, "Taste of Paradise", optional_cost_payments={"{1}{G}": 2},
    )
    game._settle()

    assert not result.supported, "two more {G} pips are owed and the pool has none"
    assert caster.life == 20


# ---------------------------------------------------------------------------
# Two independent offers on one sentence
# ---------------------------------------------------------------------------

@pytest.mark.cr("601.2b")
def test_one_sentence_may_offer_two_costs_independently():
    """"…you may pay {1}{R} and/or {1}{G} any number of times." Two offers, each
    taken as often as the caster likes — which is why the cost carries a tuple
    and the record a dict. One count could not say that Primitive Justice's
    caster paid {1}{R} twice and {1}{G} not at all."""
    (cost,) = additional_costs(_ALL["Primitive Justice"])
    assert [(o.symbols, o.repeatable) for o in cost.optional_mana] == [
        ("{1}{R}", True), ("{1}{G}", True),
    ]


@pytest.mark.cr("601.2b")
def test_the_read_back_key_is_canonical_not_as_printed():
    """The offer is spelled through ``mana_payment.mana_cost_label`` on both
    sides — the payment that records it and the sentence that reads it back — so
    a card printing "{R}{1}" would be one offer rather than two. Two readers of
    the symbols would be two answers, and the quiet one is a loop that never
    runs."""
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, you may pay {R}{1}."
    )
    assert cost is not None
    assert [o.symbols for o in cost.optional_mana] == ["{1}{R}"]


@pytest.mark.cr("601.2b")
def test_a_cost_clause_naming_an_unspendable_symbol_refuses_the_whole_line():
    """``_read_cost_clauses`` refuses a sentence whole rather than charging the
    part it read — the direction a cost must never drift in. An {X} in an
    optional additional cost has no payment behind it, so the line stays
    unclaimed and the card stays unsupported instead of castable at a
    discount."""
    assert additional_cost_for_line(
        "As an additional cost to cast this spell, you may pay {X}{G}."
    ) is None


# ---------------------------------------------------------------------------
# The boolean half (CR 601.2b asked at resolution)
# ---------------------------------------------------------------------------

def _combat(pay: bool | None) -> Game:
    """A 3/3 red and a 2/2 green attacking; Undergrowth cast by the defender.

    *pay* of None casts nothing at all, which is the control: without it "the
    damage was prevented" and "no damage was ever dealt" look identical.
    """
    attacker = PlayerState(name="A")
    defender = PlayerState(
        name="B", hand=[_ALL["Undergrowth"]] if pay is not None else [],
    )
    game = Game(players=[attacker, defender])
    game.enforce_mana_costs = True
    red = Permanent(card=_LEA["Hill Giant"])
    green = Permanent(card=_LEA["Grizzly Bears"])
    attacker.battlefield.extend([red, green])
    for perm in (red, green):
        perm.metadata["summoning_sickness_turn"] = -99
    game._settle()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()          # beginning_of_combat
    game.advance_combat_phase()          # declare_attackers
    game.declare_attackers(0, [0, 1])
    if pay is not None:
        # CR 500.4 empties the pool at the end of each step, so the mana goes in
        # here, in the step the spell is actually cast in.
        defender.mana_pool["G"] = 1
        defender.mana_pool["R"] = 3
        result = game.cast_from_hand(
            1, "Undergrowth",
            optional_cost_payments={"{2}{R}": 1} if pay else None,
        )
        game._settle()
        assert result.supported, result.details
    game.advance_combat_phase()          # declare_blockers
    game.declare_blockers(1, {})
    game.advance_combat_phase()          # combat damage, dealt as it is entered
    game._settle()
    return game


@pytest.mark.cr("615.1")
def test_an_unpaid_optional_cost_leaves_the_wide_prevention():
    """Undergrowth cast without its cost is Fog. The control below is what makes
    this an assertion rather than a coincidence."""
    assert _combat(pay=None).players[1].life == 15, "control: 3 + 2 gets through"
    assert _combat(pay=False).players[1].life == 20


@pytest.mark.cr("615.1")
def test_paying_the_optional_cost_narrows_the_prevention_by_source():
    """"…this effect doesn't affect combat damage that would be dealt by red
    creatures." The hole is described by the damage's **source**, which is the
    one thing the turn-wide blanket flag cannot carry — so paying it lets the
    3/3 red attacker through and still stops the 2/2 green one."""
    assert _combat(pay=True).players[1].life == 17, "only the red creature's 3"
