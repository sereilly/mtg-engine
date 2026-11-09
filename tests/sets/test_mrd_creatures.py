"""Mirrodin creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import Permanent as _w1g6_Permanent
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_table(set_pool, hand=(), mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", hand=list(hand),
                          library=[lea["Island"]] * 10),
        _w1g6_PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = _w1g6_Permanent(card=card)
            permanent.metadata["summoning_sickness_turn"] = -99
            game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return game


def _w1g6_on_board(game, name):
    return [p for p in game.all_permanents() if p.card.name == name]


def test_w1g6_war_elemental_is_sacrificed_on_a_turn_no_opponent_was_damaged(
    set_pool,
):
    """"When this creature enters, sacrifice it unless an opponent was dealt
    damage this turn." Nothing has been dealt: the entry trigger sacrifices
    it."""
    elemental = set_pool("MRD")["War Elemental"]
    game = _w1g6_table(set_pool, hand=[elemental])

    assert game.queue_from_hand(0, "War Elemental").supported
    _w1g6_resolve_stack(game)

    assert not _w1g6_on_board(game, "War Elemental")
    assert "War Elemental" in [c.name for c in game.players[0].graveyard]


@_w1g6_pytest.mark.parametrize("interactive", [False, True])
def test_w1g6_war_elemental_grows_by_each_point_dealt_to_an_opponent(
    set_pool, interactive,
):
    """"Whenever an opponent is dealt damage, put that many +1/+1 counters on
    this creature."

    A Bolt to the face first, so the entry trigger keeps it (the turn's damage
    ledger, not a life total). Then a second Bolt is three counters, and two
    unblocked 2-power attackers dealing damage at once are one trigger for 4
    (the event read from the recipient's side, CR 603.2c) — seven counters in
    all. A Bolt at the Elemental's own controller grows nothing.
    """
    lea = set_pool("LEA")
    elemental = set_pool("MRD")["War Elemental"]
    bolt = lea["Lightning Bolt"]
    game = _w1g6_table(
        set_pool, hand=[bolt, elemental, bolt, bolt],
        mine=[lea["Grizzly Bears"], lea["Savannah Lions"]],
    )
    if interactive:
        game.interactive_seats = {0}

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 17

    assert game.queue_from_hand(0, "War Elemental").supported
    _w1g6_resolve_stack(game)
    (war,) = _w1g6_on_board(game, "War Elemental")
    assert war.metadata.get("plus_counters", 0) == 0

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert war.metadata.get("plus_counters") == 3

    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 17
    assert war.metadata.get("plus_counters") == 3, "its controller is no opponent"

    war.metadata["summoning_sickness_turn"] = 99   # stays home
    game._set_phase_and_step("combat", "declare_attackers")
    slots = [
        slot for slot, p in enumerate(game.players[0].battlefield)
        if p.card.name in ("Grizzly Bears", "Savannah Lions")
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    for _ in range(4):   # blockers (none), then the damage step
        if game.players[1].life < 14:
            break
        game.advance_combat_phase()
        _w1g6_resolve_stack(game)
    assert game.players[1].life == 10
    assert war.metadata.get("plus_counters") == 7, game.log
    assert sum("War Elemental gets" in line for line in game.log) == 2, (
        "one trigger per dealing, not one per attacker"
    )
    assert (war.effective_power, war.effective_toughness) == (8, 8)

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
