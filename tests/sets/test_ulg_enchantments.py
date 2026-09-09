"""Urza's Legacy enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Two enchantments whose second sentence spends a number the first one made:
# what the ability's own discard cost threw away (Pyromancy) and how much life
# the trigger's own first sentence took (Subversion). Both are driven in a game,
# because an assertion about instruction kinds passes on a card that resolves
# to zero.

import random

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1e_resolve


def _g1e_seats(count=2, *, mine=(), hand=()):
    """*count* seats, mana enforcement off, seat 0 active and holding *mine*.

    ``_g1e_`` prefixed and ending on ``return game, game.players`` — SET_PLAYBOOK.md's
    note about a union splicing one helper's body onto another's signature.
    """
    seats = [PlayerState(name=f"G1E-{i}") for i in range(count)]
    seats[0].battlefield = [Permanent(card=c) for c in mine]
    seats[0].hand = list(hand)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players


# Pyromancy — "{3}, Discard a card at random: This enchantment deals damage to
# any target equal to the mana value of the discarded card."


def test_g1_pyromancy_deals_the_discarded_cards_mana_value(set_pool):
    """CR 601.2h discards the card before the ability is on the stack, so by
    resolution it is one card among everything else in that graveyard — the
    number is the last-known information the payment recorded (CR 608.2h).

    Shivan Dragon's mana value is 6.
    """
    dragon = set_pool("LEA")["Shivan Dragon"]
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Pyromancy"]], hand=[dragon])

    result = game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert result.supported, result.details
    assert [c.name for c in seats[0].graveyard] == ["Shivan Dragon"]
    assert seats[1].life == 14


def test_g1_pyromancy_scales_with_the_card_rather_than_a_printed_number(set_pool):
    """The control on the test above: an Ornithopter costs nothing, so the
    discard is real and the damage is none (CR 120.8)."""
    game, seats = _g1e_seats(
        mine=[set_pool("ULG")["Pyromancy"]], hand=[set_pool("ATQ")["Ornithopter"]],
    )

    game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert [c.name for c in seats[0].graveyard] == ["Ornithopter"]
    assert seats[1].life == 20


def test_g1_pyromancy_cannot_be_activated_with_an_empty_hand(set_pool):
    """CR 601.2h: a cost that cannot be paid is an activation that does not
    happen — not one that happens and deals nothing."""
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Pyromancy"]])

    result = game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert not result.supported
    assert seats[1].life == 20


def test_g1_pyromancy_discards_at_random_and_burns_for_what_it_took(set_pool):
    """"Discard a card **at random**" — the card is not the payer's choice, and
    the damage follows whichever went. Several seeds, because one seed proves
    the pairing and not the randomness."""
    pool = set_pool("ULG")
    hand = [
        set_pool("LEA")["Shivan Dragon"],      # 6
        set_pool("ATQ")["Ornithopter"],        # 0
        set_pool("LEA")["Lightning Bolt"],     # 1
    ]
    pairs = set()
    for seed in range(30):
        random.seed(seed)
        game, seats = _g1e_seats(mine=[pool["Pyromancy"]], hand=list(hand))
        game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
        _g1e_resolve(game)
        pairs.add((seats[0].graveyard[0].name, 20 - seats[1].life))

    assert pairs == {("Shivan Dragon", 6), ("Ornithopter", 0), ("Lightning Bolt", 1)}


# Subversion — "At the beginning of your upkeep, each opponent loses 1 life. You
# gain life equal to the life lost this way."


def test_g1_subversion_gains_what_the_one_opponent_lost(set_pool):
    """The printed 1 is what each opponent loses; the gain reads what the step
    actually took."""
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Subversion"]])

    game.resolve_upkeep(0)
    _g1e_resolve(game)
    game._settle()

    assert seats[1].life == 19
    assert seats[0].life == 21


def test_g1_subversion_gains_the_table_total_not_the_printed_one(set_pool):
    """The whole reason the number is a *record*: at four seats the loss runs
    three times and the gain is 3, which is a number the card never prints and
    no board read can supply — by then the life totals are the ones this step
    left behind."""
    game, seats = _g1e_seats(4, mine=[set_pool("ULG")["Subversion"]])

    game.resolve_upkeep(0)
    _g1e_resolve(game)
    game._settle()

    assert [p.life for p in seats] == [23, 19, 19, 19]
