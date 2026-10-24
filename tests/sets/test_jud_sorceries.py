"""Judgment sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# Rats' Feast (supported on arrival, driven here): "Exile X target cards from a
# single graveyard." The X cards are targets announced with the spell
# (CR 601.2c), all in one pile, and a card gone in response is not replaced
# (CR 608.2b).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.stack_targets import chosen_targets as _w1g3_chosen_targets
from tests.helpers import resolve_stack as _w1g3_resolve

_W1G3_THEIRS = ("Swamp", "Hill Giant", "Terror", "Craw Wurm")


def _w1g3_feast_game(set_pool):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Rats' Feast"]], graveyard=[lea["Grizzly Bears"]],
            library=[lea["Swamp"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in _W1G3_THEIRS],
            library=[lea["Island"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def test_w1g3_rats_feast_names_x_cards_of_one_pile_and_does_not_replace_a_lost_one(set_pool):
    game = _w1g3_feast_game(set_pool)
    spec = game.cast_target_spec(0, set_pool("JUD")["Rats' Feast"])
    assert spec["single_graveyard"] and spec["x_targets"]
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}

    assert game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1, 3],
    ).supported
    named = _w1g3_chosen_targets(game, game.stack[-1])
    assert [(t.stamp.seat, t.stamp.card.name) for t in named] == [
        (1, "Hill Giant"), (1, "Craw Wurm"),
    ]
    victim = game.players[1]
    victim.hand.append(victim.graveyard.pop(1))            # the Giant, in response
    _w1g3_resolve(game)

    assert [c.name for c in victim.exile] == ["Craw Wurm"]
    assert [c.name for c in victim.graveyard] == ["Swamp", "Terror"]
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Rats' Feast"]


def test_w1g3_rats_feast_names_exactly_x_and_x_zero_names_none(set_pool):
    game = _w1g3_feast_game(set_pool)
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=2, target_player_index=1, target_permanent_index=[1],
    ).supported
    assert not game.queue_from_hand(
        0, "Rats' Feast", x_value=1, target_player_index=1, target_permanent_index=[1, 2],
    ).supported
    assert game.stack == []
    assert game.queue_from_hand(0, "Rats' Feast", x_value=0).supported
    _w1g3_resolve(game)
    assert game.players[1].exile == [] and len(game.players[1].graveyard) == 4

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
