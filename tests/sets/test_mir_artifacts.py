"""Per-card tests for Mirage's artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 4: a player-quantity intervening-if (CR 603.4) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _r4_board(set_pool, artifact_name: str, *, opponent_hand: int = 0,
              opponent_life: int = 20):
    """The artifact on seat 0, with seat 1's hand and life set to taste.

    Seat 1 is the one every card in this section asks about — each fires on an
    opponent's step and tests *that player*, which is the referent the round was
    really about.
    """
    pool = set_pool("MIR")
    artifact = Permanent(card=pool[artifact_name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[artifact], library=[pool["Island"]] * 8),
        PlayerState(
            name="P2", hand=[pool["Island"]] * opponent_hand,
            library=[pool["Island"]] * 8,
        ),
    ])
    game.players[1].life = opponent_life
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


@pytest.mark.parametrize(
    "name", ["Misers' Cage", "Paupers' Cage", "Razor Pendulum"]
)
def test_the_three_cages_compile_supported(set_pool, name):
    """All three print one shape with the threshold as data — "at the beginning
    of each <player>'s <step>, if that player has <N or more/fewer> <quantity>,
    this artifact deals 2 damage to that player" — so they are one production
    asked three ways rather than three cards."""
    program = compile_card_oracle(set_pool("MIR")[name])
    assert program.supported, program.reason


def test_misers_cage_fires_on_a_full_hand(set_pool):
    """"…if that player has five or more cards in hand, this artifact deals 2
    damage to that player." """
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=5)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20 - 2 - 0 or game.players[1].life == 18


def test_misers_cage_holds_below_the_threshold(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would go on the
    stack, so four cards in hand is no trigger at all. Read the *seat* as well
    as the number — the clause says "that player", and a version that fell back
    to the caster would have damaged the Cage's own controller."""
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=4)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20
    assert game.players[0].life == 20


def test_paupers_cage_reads_the_other_end_of_the_same_comparison(set_pool):
    """"…if that player has **two or fewer** cards in hand".

    "Fewer" is English's countable spelling of "less" and the comparison parser
    knew only "less" — so every printed threshold over a countable noun refused.
    The two cages are the pair that shows the word is data.
    """
    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=2)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 18

    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=3)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 20


def test_razor_pendulum_reads_a_life_total(set_pool):
    """"At the beginning of each player's end step, if that player has 5 or less
    life, this artifact deals 2 damage to that player."

    A life total is not a pile, which is why it is its own condition kind rather
    than a zone count with an invented zone name — but it is the same printed
    shape and shares the seat reader with it.
    """
    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=5)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 3

    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=6)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 6


# --- W1G2: an X of a named counter, and the mana it becomes a turn later ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g2_bottle(set_pool):
    bottle = Permanent(card=set_pool("MIR")["Ventifact Bottle"])
    bottle.metadata["summoning_sickness_turn"] = -99
    filler = set_pool("MIR")["Femeref Scouts"]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bottle], library=[filler] * 20, life=20),
        PlayerState(name="P2", library=[filler] * 20, life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    # The activation is sorcery-speed (CR 601.3d), so the game has to be in a
    # main phase with an empty stack before it will be accepted.
    game._enter_main_phase(precombat=True)
    game.resolve_stack()
    return game, bottle


def test_ventifact_bottle_stores_x_charge_counters(set_pool):
    """"{X}{1}, {T}: Put **X** charge counters on this artifact. Activate only
    as a sorcery."

    The named-counter placement admitted a *fixed* number only — the P/T branch
    beside it had learned the cast's announced X and this one had not, so the
    whole card refused on a value the handler was already able to resolve.
    """
    program = compile_card_oracle(set_pool("MIR")["Ventifact Bottle"])
    assert program.supported, program.reason

    game, bottle = _w1g2_bottle(set_pool)
    result = game.activate_permanent_ability(
        0, "Ventifact Bottle", permanent_index=0, x_value=3
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert counters_on(bottle, "charge") == 3, game.log


def test_ventifact_bottle_pays_out_at_the_next_first_main_phase(set_pool):
    """"At the beginning of your first main phase, **if this artifact has a
    charge counter on it**, tap it and remove all charge counters from it. Add
    {C} for each charge counter removed this way."

    Two more halves. The intervening-if knew "one or more" and not the article
    that means the same thing — a presence test, where reading "a" as a count
    would have meant *exactly* one and emptied the Bottle after its second
    activation. And "for each charge counter removed **this way**" had one
    producer, the Mana Batteries' *cost* payment; here the removal is an effect
    two instructions earlier, so the number is in this resolution's scratchpad
    and the lowering is what chooses between the two.
    """
    game, bottle = _w1g2_bottle(set_pool)
    game.activate_permanent_ability(
        0, "Ventifact Bottle", permanent_index=0, x_value=3
    )
    game.resolve_stack()

    game.start_next_turn()          # the opponent's turn
    game.start_next_turn()          # back to the Bottle's controller
    game._enter_main_phase(precombat=True)
    game.resolve_stack()

    assert counters_on(bottle, "charge") == 0, game.log
    assert bottle.tapped, game.log
    assert game.players[0].mana_pool["C"] == 3, game.log


def test_an_empty_ventifact_bottle_does_nothing(set_pool):
    """CR 603.4: the intervening-if is checked as the trigger would go on the
    stack, so a Bottle with no counters is not a trigger at all — and taps
    itself for nothing if it were."""
    game, bottle = _w1g2_bottle(set_pool)

    game.start_next_turn()
    game.start_next_turn()
    game._enter_main_phase(precombat=True)
    game.resolve_stack()

    assert not bottle.tapped, game.log
    assert game.players[0].mana_pool["C"] == 0, game.log
