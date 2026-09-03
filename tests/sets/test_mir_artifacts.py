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


# --- W1G4: the zones / cards / library family ---

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def _w1g4_duel(set_pool, *, seat0_battlefield=(), seat0_hand=(), seat0_library=()):
    """A two-seat game with mana costs off and no interactive seat.

    Every test in this block drives one card end to end rather than reading its
    compiled program, so the board is set up here once and the assertions are
    about what actually moved.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1",
            battlefield=[_W1G4Permanent(card=pool[n]) for n in seat0_battlefield],
            hand=[pool[n] for n in seat0_hand],
            library=[pool[n] for n in (seat0_library or ("Island",) * 5)],
        ),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    return game, pool


def test_lions_eye_diamond_pays_its_whole_cost_and_makes_three_of_one_colour(set_pool):
    """"Discard your hand, Sacrifice this artifact: Add three mana of any one
    color."

    Every piece of this line already worked -- the two-part cost, the hand
    discard, the any-one-colour mana -- and the card was unsupported for the
    *sentence after* it. That is the whole finding: the refusal named "expected
    a subject", which reads as a broken effect clause and is really a missing
    row in ``engine/activation_restrictions.py``.
    """
    game, _ = _w1g4_duel(
        set_pool,
        seat0_battlefield=("Lion's Eye Diamond",),
        seat0_hand=("Island", "Island", "Mountain"),
    )
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Lion's Eye Diamond", permanent_index=0, mana_color="R"
    )

    assert result.supported, result.details
    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].graveyard] == [
        "Island", "Island", "Mountain", "Lion's Eye Diamond",
    ]
    assert not game.players[0].battlefield
    assert game.players[0].mana_pool["R"] == 3


def test_lions_eye_diamond_is_refused_without_priority(set_pool):
    """CR 602.5e / CR 304.5: "Activate only as an instant" means the activator
    must have priority.

    Not a tautology, and this is the assertion that says why. CR 605.3a lets an
    activated *mana* ability be activated in two windows where nobody has
    priority -- while a spell's cost is being paid, and whenever a rule asks for
    a mana payment -- and taking those away is the whole of what the clause
    does. A row that answered True would be a restriction nothing checks.
    """
    game, _ = _w1g4_duel(
        set_pool,
        seat0_battlefield=("Lion's Eye Diamond",),
        seat0_hand=("Island",),
    )
    game.start_turn(0)
    game.priority_player_index = None

    result = game.activate_permanent_ability(
        0, "Lion's Eye Diamond", permanent_index=0, mana_color="R"
    )

    assert not result.supported
    assert "priority" in result.details
    assert game.players[0].hand, "a refused activation pays nothing"
    assert game.players[0].battlefield, "…and sacrifices nothing"
