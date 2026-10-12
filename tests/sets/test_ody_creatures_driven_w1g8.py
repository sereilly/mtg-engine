"""Odyssey creatures W1G8 drove rather than implemented.

Every card here compiled "supported" on the day of the ingest, which is not the
same as working (SET_PLAYBOOK.md Phase 3: a card is supported when *any* of its
lines is). Each was given a headless game through its whole text — activated
with a legal target, an illegal one and none; its cost paid and refused; its
trigger fired and, where something can respond, answered — and what the game
showed is pinned here.

One of them did not work: **Shifty Doppelganger** never came back. It is first.

In a file of the group's own rather than in `test_ody_creatures.py`'s W1G8
section, so that file keeps its room for the groups still to land (it stood at
2,185 of 2,600 lines when this was written, with four sections empty). The
split is by section, which is the axis `tests/sets/README.md` names once the
type axis has run out.
"""

from __future__ import annotations

import pytest

from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from tests.sets import ody_w1g8_helpers as w1g8


def _crack(game, name, **announcement):
    """Activate *name* (seat 0's) and settle the stack; returns the result."""
    used = game.activate_permanent_ability(0, name, **announcement)
    w1g8.settle(game)
    return used


def _table(set_pool, mana=None, **kwargs):
    """Seat 0's turn, costs enforced, *mana* floating."""
    game = w1g8.table(set_pool, enforce=True, **kwargs)
    game.start_turn(0)
    game.players[0].mana_pool.update(mana or {})
    return game


def _dies(game, permanent):
    w1g8.leave(game, permanent)
    w1g8.settle(game)


def _to_blocks(game, attacker):
    """Seat 0 attacks with *attacker*; returns at the declare-blockers step."""
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared, why = game.declare_attackers(
        0, [list(game.controlled_by(0)).index(attacker)]
    )
    assert declared, why
    game.advance_combat_phase()


# --- Shifty Doppelganger ----------------------------------------------------
# "{3}{U}, Exile this creature: You may put a creature card from your hand
# onto the battlefield. If you do, that creature gains haste until end of
# turn. At the beginning of the next end step, sacrifice that creature. If you
# do, return this card to the battlefield."

def test_shifty_doppelganger_comes_back_from_exile_when_its_guest_is_sacrificed(
    set_pool,
):
    """It compiled, swapped in the creature, sacrificed it at the end step —
    and stayed in exile, logging that it "was no longer in the graveyard".
    "Return this card" names no zone and the lowering read a graveyard; the
    ability's own cost says exile, and that is where it is looked for now."""
    game = _table(set_pool, {"U": 1, "C": 3}, hand=["Shivan Dragon"])
    w1g8.put(game, set_pool, 0, "Shifty Doppelganger")

    assert _crack(game, "Shifty Doppelganger").supported
    assert w1g8.names(game, 0) == ["Shivan Dragon"]
    assert w1g8.pile(game, 0, "exile") == ["Shifty Doppelganger"]
    dragon = next(iter(game.controlled_by(0)))
    assert game._has_keyword(dragon, "Haste") and not game._is_summoning_sick(dragon)

    game.resolve_end_step(0)
    w1g8.settle(game)

    assert w1g8.names(game, 0) == ["Shifty Doppelganger"]
    assert w1g8.pile(game, 0) == ["Shivan Dragon"]
    assert w1g8.pile(game, 0, "exile") == []


@pytest.mark.parametrize("guest_dies_first", [False, True])
def test_shifty_doppelganger_stays_exiled_when_nothing_is_sacrificed(
    set_pool, guest_dies_first
):
    """"If you do": with no creature card to put in, or the creature gone
    before the end step, there is no sacrifice and so no return."""
    hand = ["Shivan Dragon"] if guest_dies_first else []
    game = _table(set_pool, {"U": 1, "C": 3}, hand=hand)
    w1g8.put(game, set_pool, 0, "Shifty Doppelganger")

    assert _crack(game, "Shifty Doppelganger").supported
    if guest_dies_first:
        _dies(game, next(iter(game.controlled_by(0))))
    game.resolve_end_step(0)
    w1g8.settle(game)

    assert w1g8.names(game, 0) == []
    assert w1g8.pile(game, 0, "exile") == ["Shifty Doppelganger"]


def test_a_self_return_reads_exile_only_behind_an_exile_this_cost(set_pool):
    """The zone is the cost's to say. Nether Spirit prints the same sentence
    from a graveyard and must not start looking in exile."""
    def returns(card):
        found = []

        def walk(value):
            if hasattr(value, "kind") and hasattr(value, "payload"):
                if value.kind == "return_self_from_graveyard":
                    found.append(value.payload.get("from"))
                for inner in value.payload.values():
                    walk(inner)
            elif isinstance(value, (list, tuple)):
                for inner in value:
                    walk(inner)

        program = compile_card_oracle(card)
        for ability in (*program.activated_abilities, *program.triggered_abilities):
            walk(ability.instruction)
        return found

    assert returns(set_pool("ODY")["Shifty Doppelganger"]) == ["exile"]
    assert returns(w1g8.card(set_pool, "Nether Spirit")) == [None]
