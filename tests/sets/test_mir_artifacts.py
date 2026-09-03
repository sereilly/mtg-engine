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


# --- W1G3: damage / prevention / life ---

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_bone_mask_board(set_pool, library_size=5):
    pool = set_pool("MIR")
    mask = _W1G3Permanent(card=pool["Bone Mask"])
    ogre = _W1G3Permanent(card=pool["Wild Elephant"])
    other = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(
        name="P1", battlefield=[mask], life=20,
        library=[pool["Island"]] * library_size,
    )
    p2 = _W1G3PlayerState(name="P2", battlefield=[ogre, other], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, p1, mask, ogre, other


def test_bone_mask_prevents_the_whole_instance_and_pays_from_the_library(set_pool):
    """"{2}, {T}: The next time a source of your choice would deal damage to
    you this turn, prevent that damage. **Exile cards from the top of your
    library equal to the damage prevented this way.**"

    Reverse Damage's printed sentence with a different rider after it, which is
    what made the shape a production: the pool had exactly one card printing
    those seven words, so it sat in `card_hooks.py` under that card's name.
    A second card sharing the shape is the entry bar failing, and the hook is
    gone.

    The rider is CR 615.5's additional effect and runs *inside* the prevention,
    so it is sized by what was absorbed rather than by what was announced — a
    whole instance, however big (CR 615.8).
    """
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    assert mask.tapped

    assert _damage_dealt(game, p1, 4, source=ogre) == 0, "the whole instance"
    assert p1.life == 20
    assert len(p1.library) == 1, "four cards paid for four damage"
    assert len(p1.exile) == 4


def test_bone_mask_waits_for_the_source_it_chose(set_pool):
    """Without this the test above passes for a shield that answers to
    everything — and then the library pays for damage the card never stopped."""
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool)

    game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )

    assert _damage_dealt(game, p1, 3, source=other) == 3
    assert p1.exile == []
    assert _damage_dealt(game, p1, 3, source=ogre) == 0
    assert len(p1.exile) == 3


def test_bone_mask_exiles_what_is_left_of_an_empty_library(set_pool):
    """Running out is not a loss until a draw is attempted (CR 104.3c), and
    this is not a draw — so the rider takes what is there and stops."""
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool, library_size=1)

    game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )
    assert _damage_dealt(game, p1, 5, source=ogre) == 0

    assert p1.library == []
    assert len(p1.exile) == 1
    assert not p1.lost
