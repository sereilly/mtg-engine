"""Torment instants.

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


def _w1g2_table(set_pool, *, hand0=(), gy0=(), bf1=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name="P0", life=20, hand=[pool[n] for n in hand0],
            graveyard=[pool[n] for n in gy0], library=[pool["Forest"]] * 10,
        ),
        _w1g2_PlayerState(name="P1", life=20, library=[pool["Forest"]] * 10),
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for name in bf1:
        perm = _w1g2_Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(1, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Temporary Insanity: a target bounded by the caster's graveyard ----------

def test_temporary_insanity_offers_only_creatures_under_the_graveyard_count(set_pool):
    """"…target creature with power **less than** the number of cards in your
    graveyard" — strictly less, counted as the spell is announced (CR 601.2c),
    so a 3-power creature is no target over a graveyard of three."""
    def offered(graveyard_size):
        game = _w1g2_table(
            set_pool, hand0=["Temporary Insanity"],
            gy0=["Forest"] * graveyard_size,
            bf1=["Grizzly Bears", "Hill Giant", "Craw Wurm"],
        )
        spec = game.cast_target_spec(0, game.players[0].hand[0])
        return [target["name"] for target in spec["valid_targets"]]

    assert offered(2) == []
    assert offered(3) == ["Grizzly Bears"]
    assert offered(4) == ["Grizzly Bears", "Hill Giant"]
    assert offered(7) == ["Grizzly Bears", "Hill Giant", "Craw Wurm"]

    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Hill Giant"],
    )
    giant = _w1g2_on_board(game, 1, "Hill Giant")
    assert not game.cast_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert [card.name for card in game.players[0].hand] == ["Temporary Insanity"]


def test_temporary_insanity_untaps_steals_and_hastes_until_end_of_turn(set_pool):
    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Grizzly Bears"],
    )
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    bears.tapped = True
    assert game.cast_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert game.controller_index_of(bears) == 0
    assert not bears.tapped
    assert game._has_keyword(bears, "haste")
    game.resolve_cleanup_step(0)
    assert game.controller_index_of(bears) == 1
    assert not game._has_keyword(bears, "haste")


def test_temporary_insanity_asks_the_bound_again_as_it_resolves(set_pool):
    """CR 608.2b: a graveyard that shrank in response leaves the creature's
    power no longer under the count, so its one target is illegal and the
    spell does nothing — the creature stays tapped and stays put."""
    game = _w1g2_table(
        set_pool, hand0=["Temporary Insanity"], gy0=["Forest"] * 3,
        bf1=["Grizzly Bears"],
    )
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    bears.tapped = True
    assert game.queue_from_hand(
        0, "Temporary Insanity", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.players[0].graveyard.pop()
    _w1g2_resolve_stack(game)
    assert game.controller_index_of(bears) == 1 and bears.tapped
    assert any("every target is illegal" in line for line in game.log)

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
