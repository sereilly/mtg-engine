"""Stronghold enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g3_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_block(attackers, defenders, *, blocks, watchers=()):
    """Seat 0 attacks with *attackers*; seat 1 blocks per *blocks*.

    *watchers* are permanents put on seat 0's battlefield before combat — the
    board-wide enchantments these tests are about, which are in no combat at all.

    ``blocks`` is keyed by position in *attackers* / *defenders*; the watchers
    sitting in front of the attackers on the battlefield are offset here so no
    test has to count them.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*watchers, *attackers]),
        PlayerState(name="P2", battlefield=list(defenders)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (*watchers, *attackers, *defenders):
        perm.summoning_sick = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(
        0, [len(watchers) + i for i in range(len(attackers))]
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {b: a + len(watchers) for b, a in blocks.items()}
    )[0]
    game.resolve_stack()
    return game


def test_heat_of_battle_burns_each_blocking_creatures_controller(set_pool):
    """"Whenever a creature blocks, this enchantment deals 1 damage to that
    creature's controller."

    A board-wide watcher on a third permanent: it is neither combatant, so the
    seat is the one the declare-blockers announcement froze rather than anything
    read off the source. Two blockers, two triggers, two damage.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attackers = [Permanent(card=_w1g3_creature(f"Bear {i}", 2, 2)) for i in range(2)]
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block(attackers, blockers, blocks={0: 0, 1: 1}, watchers=[heat])

    assert game.players[1].life == 18, game.log
    assert game.players[0].life == 20, game.log


def test_heat_of_battle_fires_once_per_blocker_not_once_per_attacker(set_pool):
    """CR 509.3c: a condition with no partner phrase fires once for the creature
    the event is about, however many creatures are on the other side.

    One blocker against one attacker is one trigger — the per-pair announcement
    the narrowed spellings answer to would be the same number here, so the test
    that separates them is the multi-block one below.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blocker = Permanent(card=_w1g3_creature("Wall", 0, 4))
    game = _w1g3_block([attacker], [blocker], blocks={0: 0}, watchers=[heat])

    assert game.players[1].life == 19, game.log


def test_heat_of_battle_fires_once_for_each_of_two_creatures_blocking_one(set_pool):
    """CR 509.3d against CR 509.3c, on the one board that tells them apart.

    Two creatures block a single attacker. "Whenever a creature blocks" is about
    each *blocker*, so it fires twice; the per-pair announcement the narrowed
    spellings (No Quarter) answer to would fire twice here as well — what would
    fire twice *wrongly* is the becomes-blocked side, which is one creature
    becoming blocked and is announced once. Both readings share one fire site,
    so this is the board that would show the pair announcement leaking into the
    bare condition.
    """
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    blockers = [Permanent(card=_w1g3_creature(f"Wall {i}", 0, 4)) for i in range(2)]
    game = _w1g3_block([attacker], blockers, blocks={0: 0, 1: 0}, watchers=[heat])

    assert game.players[1].life == 18, game.log


def test_heat_of_battle_says_nothing_about_an_unblocked_attack(set_pool):
    """The condition is about blocking, not about combat: an attack nobody
    blocks announces no firing at all."""
    heat = Permanent(card=set_pool("STH")["Heat of Battle"])
    attacker = Permanent(card=_w1g3_creature("Bear", 2, 2))
    game = _w1g3_block([attacker], [], blocks={}, watchers=[heat])

    assert game.players[1].life == 20, game.log
