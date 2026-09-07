"""Stronghold instants.

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
from engine.targeting import derive_cast_spec


def _w1g3_rebound_game(set_pool, spell, spell_set="LEA"):
    """Rebound in seat 0's hand, *spell* in seat 1's, a creature on seat 0's board."""
    perm = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[set_pool("STH")["Rebound"]],
            battlefield=[perm], life=20,
        ),
        PlayerState(name="P2", hand=[set_pool(spell_set)[spell]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    return game, perm


def _w1g3_rebound_spec(set_pool):
    card = set_pool("STH")["Rebound"]
    return derive_cast_spec(card, compile_card_oracle(card))


def test_rebound_is_supported_and_bounds_both_ends(set_pool):
    """"Change the target of target spell that targets only a player. The new
    target must be a player."

    Both printed restrictions land on the payload: the clause is CR 115.9a's
    count plus the shape of the one target — the same node Meddle builds from a
    condition and Reflecting Mirror from a noun phrase plus an "if".
    """
    card = set_pool("STH")["Rebound"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_new_spell_target", "change_target_spell_target",
    ]
    assert steps[0].payload["current_target_type"] == "player"
    assert steps[0].payload["new_target"] == "player"
    assert _w1g3_rebound_spec(set_pool)["stack_single_target_type"] == "player"


def test_rebound_re_aims_a_spell_at_the_other_player(set_pool):
    """CR 115.7a: everything else the spell announced stays, and only the face
    it points at moves — so the Lava Burst's caster takes its own damage."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Rebound", target_stack_index=0)
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    assert game.players[1].life == 17, game.log


def test_rebound_is_not_offered_a_spell_aimed_at_a_creature(set_pool):
    """The clause is a restriction, not decoration: a production that consumed
    "that targets only a player" and dropped it would let Rebound re-aim a
    Terror, which is a strictly larger card than the one printed."""
    game, perm = _w1g3_rebound_game(set_pool, "Terror", spell_set="LEA")
    game.queue_from_hand(1, "Terror", target_permanent_ids=[perm.permanent_id])

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert offered == [], game.log


def test_rebound_is_offered_a_spell_aimed_at_a_player(set_pool):
    """The other side of the same gate, so the test above is not passing for
    the wrong reason."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert [entry["name"] for entry in offered] == ["Lightning Bolt"], game.log
