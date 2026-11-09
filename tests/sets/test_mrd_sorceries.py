"""Mirrodin sorceries.

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
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve


def test_w1g3_thoughtcast_draws_two_for_one_blue_off_four_artifacts(set_pool):
    """"Affinity for artifacts" / "Draw two cards." Printed {4}{U}: four
    artifact lands leave {U}, one pays it, and two cards are drawn. With
    three, it costs {1}{U}, and one land's mana is refused — the keyword the
    card was ingested without is the whole difference."""
    mrd = set_pool("MRD")

    def table(artifacts):
        game = _W1G3Game(players=[
            _W1G3PlayerState(
                name="W1G3-A", hand=[mrd["Thoughtcast"]],
                library=[mrd["Island"]] * 6,
            ),
            _W1G3PlayerState(name="W1G3-B", library=[mrd["Island"]] * 6),
        ])
        game.enforce_mana_costs = True
        game.interactive_seats = set()
        game.active_player_index = 0
        for _ in range(artifacts):
            game._put_permanent_onto_battlefield(
                0, _W1G3Permanent(card=mrd["Seat of the Synod"]), None
            )
        land = next(iter(game.controlled_by(0)))
        assert game.tap_land_for_mana(
            0, land.card.name, "U", permanent_id=land.permanent_id,
        )
        return game

    game = table(4)
    cast = game.cast_from_hand(0, "Thoughtcast")
    assert cast.supported, cast.details
    _w1g3_resolve(game)
    assert [c.name for c in game.players[0].hand] == ["Island", "Island"]
    assert [c.name for c in game.players[0].graveyard] == ["Thoughtcast"]
    assert sum(game.players[0].mana_pool.values()) == 0

    game = table(3)
    refused = game.cast_from_hand(0, "Thoughtcast")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in game.players[0].hand] == ["Thoughtcast"]

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


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
