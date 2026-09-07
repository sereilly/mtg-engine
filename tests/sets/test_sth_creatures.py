"""Stronghold creatures.

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


def _w1g3_creature(name, power, toughness, text="") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_combat(attackers, defenders, *, blocks):
    """A game run to the declare-blockers step with *blocks* declared.

    ``blocks`` is the ``{blocker index: attacker index}`` map ``declare_blockers``
    takes. Seat 0 attacks; seat 1 blocks.
    """
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(attackers)),
        PlayerState(name="P2", battlefield=list(defenders)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for perm in (*attackers, *defenders):
        perm.summoning_sick = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, list(range(len(attackers))))[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, dict(blocks))[0]
    game.resolve_stack()
    return game


def _w1g3_run_out_combat(game):
    """Every remaining combat step, resolving what each one puts on the stack."""
    for _ in range(4):
        game.advance_combat_phase()
        game.resolve_stack()


def test_lowland_basilisk_destroys_what_it_damaged_at_end_of_combat(set_pool):
    """"Whenever this creature deals damage to a creature, destroy that
    creature at end of combat."

    The pronoun is the *damaged* end of the event, not the damager: a permanent
    spells itself "this creature", so the only other creature the sentence has
    is the one it hit. `damage_events._announce` stamps that permanent's id onto
    the stack item, which is what the delayed ability binds — and the creature
    survives the combat damage step, so nothing but the delay destroys it.
    """
    basilisk = Permanent(card=set_pool("STH")["Lowland Basilisk"])
    wall = Permanent(card=_w1g3_creature("Stone Wall", 0, 9))
    game = _w1g3_combat([basilisk], [wall], blocks={0: 0})

    assert [p.card.name for p in game.players[1].battlefield] == ["Stone Wall"]
    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[1].battlefield] == [], game.log
    assert [c.name for c in game.players[1].graveyard] == ["Stone Wall"], game.log


def test_lowland_basilisk_leaves_a_creature_it_did_not_damage_alone(set_pool):
    """The delay is bound to one permanent by id (CR 603.7c), so a second
    creature on the same battlefield is untouched — the failure a sweep-shaped
    reading of "that creature" would produce."""
    basilisk = Permanent(card=set_pool("STH")["Lowland Basilisk"])
    wall = Permanent(card=_w1g3_creature("Stone Wall", 0, 9))
    bystander = Permanent(card=_w1g3_creature("Bystander", 1, 1))
    game = _w1g3_combat([basilisk], [wall, bystander], blocks={0: 0})

    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[1].battlefield] == ["Bystander"], game.log


def test_wall_of_tears_bounces_what_it_blocked_at_end_of_combat(set_pool):
    """"Whenever this creature blocks a creature, return that creature to its
    owner's hand at end of combat."

    The referent is the *blocked* attacker. A block announcement records the
    pair under `blocked_permanent_ids` and makes the stack item's target the
    blocker itself — so the delayed ability binds through the block pair, not
    through the target, or the Wall would bounce itself.
    """
    wall = Permanent(card=set_pool("STH")["Wall of Tears"])
    attacker = Permanent(card=_w1g3_creature("Charging Bull", 3, 3))
    game = _w1g3_combat([attacker], [wall], blocks={0: 0})

    _w1g3_run_out_combat(game)
    assert [p.card.name for p in game.players[0].battlefield] == [], game.log
    assert [c.name for c in game.players[0].hand] == ["Charging Bull"], game.log
    assert [p.card.name for p in game.players[1].battlefield] == ["Wall of Tears"], game.log


def test_wall_of_tears_does_not_bounce_itself(set_pool):
    """The negative case is the one that finds the bug: `binds_target` under a
    blocks trigger resolves the *blocker*, which is the Wall."""
    wall = Permanent(card=set_pool("STH")["Wall of Tears"])
    attacker = Permanent(card=_w1g3_creature("Charging Bull", 1, 1))
    game = _w1g3_combat([attacker], [wall], blocks={0: 0})

    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == attacker.permanent_id, game.log
    assert entry.bound_permanent_id != wall.permanent_id
