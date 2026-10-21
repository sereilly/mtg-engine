"""Torment enchantments, Auras included.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
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

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_duel(set_pool, *, gy0=(), gy1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name=f"P{seat}", life=20, graveyard=[pool[n] for n in gy],
            library=[pool["Forest"]] * 10,
        )
        for seat, gy in enumerate((gy0, gy1))
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g2_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


# --- Mortal Combat: a pile count in subject position, held to CR 603.4 --------

def test_mortal_combat_wins_with_twenty_creature_cards_in_its_graveyard(set_pool):
    game = _w1g2_duel(
        set_pool, bf0=["Mortal Combat"], gy0=["Grizzly Bears"] * 20,
    )
    game.resolve_upkeep(0)
    _w1g2_resolve_stack(game)
    assert game.players[1].lost and not game.players[0].lost


def test_mortal_combat_counts_creature_cards_only_and_only_its_own_upkeep(set_pool):
    """Nineteen creature cards and a pile of lands is nineteen; and twenty in
    the graveyard is asked at *your* upkeep, not an opponent's (CR 603.4: a
    false intervening "if" means the ability never triggers)."""
    game = _w1g2_duel(
        set_pool, bf0=["Mortal Combat"],
        gy0=["Grizzly Bears"] * 19 + ["Forest"] * 10,
        gy1=["Grizzly Bears"] * 25,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert not game.stack
    game.resolve_upkeep(1, defer_priority=True)
    assert not game.stack, "'your graveyard' is the controller's, at their upkeep"
    assert not any(player.lost for player in game.players)


def test_mortal_combat_asks_again_as_it_resolves(set_pool):
    """The card's ruling (2007-07-15): "Mortal Combat's ability has an
    'intervening if' clause, so the condition is checked again when the
    triggered ability resolves. If you don't still have twenty creature cards
    in your graveyard, the ability does nothing.\""""
    game = _w1g2_duel(
        set_pool, bf0=["Mortal Combat"], gy0=["Grizzly Bears"] * 20,
        interactive=(0, 1),
    )
    game.resolve_upkeep(0, defer_priority=True)
    assert len(game.stack) == 1
    game.players[0].graveyard.pop()
    _w1g2_resolve_stack(game)
    assert not any(player.lost for player in game.players)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

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
