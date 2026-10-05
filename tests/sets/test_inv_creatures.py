"""Invasion creatures.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: odd ones ---
from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_creature_duel(set_pool, *, enforce: bool = False):
    """Two non-interactive seats on seat 0's turn."""
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", life=20, library=[island] * 10)
        for seat in range(2)
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def _w1g8_creature_put(game, card, seat: int):
    """*card* on *seat*'s battlefield, clear of summoning sickness."""
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g8_zombie_in_graveyard(set_pool, *, swamps: int):
    """Pyre Zombie in seat 0's graveyard under a Grizzly Bears, with *swamps*
    untapped Swamps to pay from and costs enforced."""
    game = _w1g8_creature_duel(set_pool, enforce=True)
    lands = [
        _w1g8_creature_put(game, set_pool("LEA")["Swamp"], 0) for _ in range(swamps)
    ]
    game.players[0].graveyard = [
        set_pool("LEA")["Grizzly Bears"], set_pool("INV")["Pyre Zombie"],
    ]
    return game, lands


def test_pyre_zombie_returns_from_the_graveyard_for_one_black_black(set_pool):
    """"At the beginning of your upkeep, if this card is in your graveyard, you
    may pay {1}{B}{B}. If you do, return it to your hand." The ability
    functions from the graveyard (CR 113.6b); three Swamps pay it, and "it" is
    the Zombie — the Grizzly Bears beside it stays."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=3)

    game.resolve_upkeep(0)
    _w1g8_resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Pyre Zombie"]
    assert [card.name for card in game.players[0].graveyard] == ["Grizzly Bears"]
    assert all(land.tapped for land in lands)


def test_pyre_zombie_stays_put_when_its_cost_cannot_be_paid(set_pool):
    """"If you do" — two Swamps do not cover {1}{B}{B}, so nothing is paid and
    nothing returns."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=2)

    game.resolve_upkeep(0)
    _w1g8_resolve_stack(game)

    assert game.players[0].hand == []
    assert "Pyre Zombie" in [card.name for card in game.players[0].graveyard]
    assert not any(land.tapped for land in lands)


def test_pyre_zombie_does_nothing_on_an_opponents_upkeep(set_pool):
    """"**your** upkeep": the graveyard's owner's, not each player's."""
    game, lands = _w1g8_zombie_in_graveyard(set_pool, swamps=3)

    game.resolve_upkeep(1)
    _w1g8_resolve_stack(game)

    assert game.players[0].hand == []
    assert not any(land.tapped for land in lands)


def test_pyre_zombie_is_sacrificed_to_deal_two_damage(set_pool):
    """"{1}{R}{R}, Sacrifice this creature: It deals 2 damage to any target."
    The Zombie goes to its owner's graveyard as the cost and the Grizzly Bears
    takes 2 — lethal — with any target offered by the picker."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    zombie_card = set_pool("INV")["Pyre Zombie"]
    assert derive_activation_spec(
        compile_card_oracle(zombie_card).activated_abilities[0]
    ) == {"kind": "any"}
    game = _w1g8_creature_duel(set_pool)
    zombie = _w1g8_creature_put(game, zombie_card, 0)
    bears = _w1g8_creature_put(game, set_pool("LEA")["Grizzly Bears"], 1)

    assert game.activate_permanent_ability(
        0, "Pyre Zombie", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_resolve_stack(game)

    assert not game.is_on_battlefield(zombie)
    assert not game.is_on_battlefield(bears)
    assert [card.name for card in game.players[0].graveyard] == ["Pyre Zombie"]
    assert "Pyre Zombie dealt 2 damage to Grizzly Bears" in game.log
