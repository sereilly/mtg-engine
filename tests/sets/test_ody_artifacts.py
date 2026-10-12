"""Odyssey artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.ai_valuation import planned_mana_yield as _w1g2_planned_mana_yield
from engine.board_payment import board_can_pay as _w1g2_board_can_pay
from engine.mana_payment import is_mana_ability as _w1g2_is_mana_ability
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile

#: "{2}, {T}, Sacrifice this artifact: Add <two colours>. Draw a card."
_W1G2_EGGS = [
    ("Darkwater Egg", {"U": 1, "B": 1}),
    ("Mossfire Egg", {"R": 1, "G": 1}),
    ("Shadowblood Egg", {"B": 1, "R": 1}),
    ("Skycloud Egg", {"W": 1, "U": 1}),
    ("Sungrass Egg", {"G": 1, "W": 1}),
]


def _w1g2_egg_game(set_pool, name, *, pool):
    """A game that charges mana with *name* on seat 0's battlefield, entered
    this turn — an Egg is not a creature, so {T} needs no haste (CR 302.6)."""
    lea = set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState("Caster", library=[lea["Forest"]] * 10),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    egg = _w1g2_Permanent(card=set_pool("ODY")[name])
    game._put_permanent_onto_battlefield(0, egg, None)
    return game, egg  # _w1g2_egg_game


def _w1g2_egg_floating(game) -> dict:
    return {k: v for k, v in game.players[0].mana_pool.items() if v}  # _w1g2_egg_floating


@_w1g2_pytest.mark.parametrize("name, made", _W1G2_EGGS)
def test_an_egg_is_a_mana_ability_that_also_draws(set_pool, name, made):
    """"{2}, {T}, Sacrifice this artifact: Add {U}{B}. Draw a card." CR 605.1a
    asks only that the ability could add mana, has no target and is not a
    loyalty ability — so the draw rides a mana ability: it resolves inline
    (CR 605.3b), with a spell already on the stack, and never goes on it."""
    lea = set_pool("LEA")
    (ability,) = _w1g2_compile(set_pool("ODY")[name]).activated_abilities
    assert _w1g2_is_mana_ability(ability)

    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 2, "R": 1})
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    result = game.queue_permanent_ability(0, name, ability_index=0)

    assert result.supported and result.details == "resolved"
    assert len(game.stack) == 1, "the Bolt alone: the Egg never used the stack"
    assert _w1g2_egg_floating(game) == made
    assert not game.is_on_battlefield(egg)
    assert [card.name for card in game.players[0].graveyard] == [name]
    assert len(game.players[0].hand) == 1 and len(game.players[0].library) == 9


@_w1g2_pytest.mark.parametrize("name, made", _W1G2_EGGS)
def test_an_egg_is_not_cracked_for_less_than_its_cost(set_pool, name, made):
    """Refused with one mana floating and refused once tapped: nothing is
    spent, nothing is sacrificed and no card is drawn (CR 601.2h)."""
    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 1})
    short = game.queue_permanent_ability(0, name, ability_index=0)
    assert not short.supported and game.is_on_battlefield(egg)
    assert _w1g2_egg_floating(game) == {"C": 1} and game.players[0].hand == []

    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 2})
    egg.tapped = True
    tapped = game.queue_permanent_ability(0, name, ability_index=0)
    assert not tapped.supported and game.is_on_battlefield(egg)
    assert _w1g2_egg_floating(game) == {"C": 2}


def test_no_automatic_payment_counts_an_egg(set_pool):
    """The three doors an Egg's mana could come through, and the two it does
    not: the castable highlight counts lands alone (an Egg is an activation
    the player makes first), and the AI's tap planner declines a source whose
    ability costs mana, sacrifices it, or does anything beside adding mana —
    an Egg is all three."""
    game, _egg = _w1g2_egg_game(set_pool, "Darkwater Egg", pool={"C": 2})
    assert not _w1g2_board_can_pay(game, 0, {"U": 1})
    assert _w1g2_board_can_pay(game, 0, {"generic": 2}), "the pool, not the Egg"

    (ability,) = _w1g2_compile(set_pool("ODY")["Darkwater Egg"]).activated_abilities
    assert _w1g2_planned_mana_yield(ability.instruction) is None


def test_an_eggs_draw_is_a_real_draw(set_pool):
    """The card comes off the top of the library through the draw seam: with
    an empty library the Egg still makes its mana and its controller has
    drawn from nothing (CR 704.5b)."""
    game, _egg = _w1g2_egg_game(set_pool, "Sungrass Egg", pool={"C": 2})
    game.players[0].library.clear()

    assert game.queue_permanent_ability(0, "Sungrass Egg", ability_index=0).supported
    game._settle()

    assert _w1g2_egg_floating(game) == {"G": 1, "W": 1}
    assert game.players[0].lost

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
