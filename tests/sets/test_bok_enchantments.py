"""Betrayers of Kamigawa enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_named(game, name, seat=None):
    return [
        perm for perm in game.all_permanents()
        if perm.card.name == name
        and (seat is None or game.controller_index_of(perm) == seat)
    ]


def test_w1g7_in_the_web_of_war_gives_an_entering_creature_haste_it_attacks_with(set_pool):
    """Whenever a creature you control enters, it gets +2/+0 and gains haste
    until end of turn. "It" is the entering creature (the id the entry froze),
    not the enchantment: a Grizzly Bears cast under it is a 4/2 with haste and
    is declared as an attacker the turn it arrived. An opponent's creature is
    not "a creature you control", and the bonus ends in the cleanup step."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool, hand=[bok["In the Web of War"], lea["Grizzly Bears"]])
    assert game.cast_from_hand(0, "In the Web of War").supported
    _w1g7_settle(game)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    (bears,) = _w1g7_named(game, "Grizzly Bears", seat=0)
    assert (bears.effective_power, bears.effective_toughness) == (4, 2)
    assert game._has_keyword(bears, "haste")
    assert "Grizzly Bears gains haste until end of turn (In the Web of War)" in game.log
    # The opponent's creature entering triggers nothing.
    _w1g7_put(game, lea["Grizzly Bears"], seat=1)
    _w1g7_settle(game)
    (theirs,) = _w1g7_named(game, "Grizzly Bears", seat=1)
    assert theirs.effective_power == 2 and not game._has_keyword(theirs, "haste")
    # Haste is what lets the summoning-sick Bears attack this turn.
    game._set_phase_and_step("combat", "declare_attackers")
    slot = game.battlefield_index_of(bears)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    game.resolve_cleanup_step(0)
    assert bears.effective_power == 2 and not game._has_keyword(bears, "haste")

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
