"""Exodus sorceries.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: a buyback that is a list of costs ---
#
# Flowstone Flood's "Buyback—Pay 3 life, Discard a card at random" (CR 702.27a
# over CR 601.2b), which is the first buyback in the pool whose cost is more
# than one clause. Imports are in this block, per the header's convention.

import random as _g5s_random

from engine import Game as _G5sGame
from engine.cast_costs import (additional_costs as _g5s_costs,
                               expand_buyback_line as _g5s_expand)
from engine.card_loader import load_catalog as _g5s_catalog
from engine.models import PlayerState as _G5sPlayer, Permanent as _G5sPermanent
from tests.helpers import resolve_stack as _g5s_drain

_G5S_POOL = {card.name: card for card in _g5s_catalog()}

_G5S_BUYBACK = "pay 3 life, discard a card at random"


def _g5s_flood_game(set_pool, spares=2):
    caster = _G5sPlayer(
        name="A",
        hand=[set_pool("EXO")["Flowstone Flood"]] + [_G5S_POOL["Hill Giant"]] * spares,
    )
    victim = _G5sPlayer(name="B")
    game = _G5sGame(players=[caster, victim])
    game.enforce_mana_costs = False
    victim.battlefield.append(_G5sPermanent(card=_G5S_POOL["Mountain"]))
    game._settle()
    return game, caster, victim


def test_flowstone_flood_reads_every_clause_of_its_buyback(set_pool):
    """CR 702.27a's cost is "[cost]", and Magic prints a *list* of them behind
    the em dash — capitalising each item, because each opens where a sentence
    would.

    Both facts are asserted because both were the gap: the rewrite lowercased
    only the first letter of the whole line, so "Discard" arrived capitalised in
    the middle of a sentence whose clause table is lowercase, matched nothing,
    and took the entire cost down with it by the all-or-nothing rule. A cost
    nothing reads is a spell cast for less than it prints.
    """
    printed = set_pool("EXO")["Flowstone Flood"].oracle_text.split("\n")[0]
    assert _g5s_expand(printed) == (
        "As an additional cost to cast this spell, you may "
        "pay 3 life, discard a card at random."
    )

    (cost,) = _g5s_costs(set_pool("EXO")["Flowstone Flood"])
    assert cost.optional_key == _G5S_BUYBACK
    assert cost.pay_life == 3
    assert cost.discard_cards == 1 and cost.discard_at_random


def test_flowstone_flood_charges_both_halves_and_comes_back(set_pool):
    """The life and the discard are one offer, taken whole or declined whole
    (CR 601.2b), and taking it buys the card back (CR 702.27a)."""
    _g5s_random.seed(11)
    game, caster, victim = _g5s_flood_game(set_pool)

    result = game.queue_from_hand(
        0, "Flowstone Flood", target_player_index=1, target_permanent_index=0,
        optional_cost_payments={_G5S_BUYBACK: 1},
    )
    _g5s_drain(game)

    assert result.supported, result.details
    assert caster.life == 17
    assert len(caster.graveyard) == 1, "one card, chosen by chance"
    assert victim.battlefield == [], "Destroy target land"
    assert "Flowstone Flood" in [c.name for c in caster.hand]


def test_flowstone_flood_declined_charges_neither_half(set_pool):
    """The flag is on the *cost*, not on each clause, because the sentence it
    comes from is one offer — so a caster who declines pays no life and discards
    nothing."""
    game, caster, victim = _g5s_flood_game(set_pool)

    game.queue_from_hand(
        0, "Flowstone Flood", target_player_index=1, target_permanent_index=0,
    )
    _g5s_drain(game)

    assert caster.life == 20 and caster.graveyard[-1].name == "Flowstone Flood"
    assert victim.battlefield == [], "the spell still does what it says"
# end of the W1G5 sorceries block
