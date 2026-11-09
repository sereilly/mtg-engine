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

from engine import Game as _W1G1Game, PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def test_w1g1_loxodon_punisher_grows_with_each_equipment_and_shrinks_when_one_moves(set_pool):
    """'This creature gets +2/+2 for each Equipment attached to it.' Equipped
    twice through the real equip ability, then one Equipment moves away."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    island = lea["Island"]
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    def put(card):
        permanent = _W1G1Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        game._settle()
        return permanent

    def equip(gear, creature):
        result = game.activate_permanent_ability(
            0, gear.card.name, permanent_index=game.battlefield_index_of(gear),
            target_permanent_ids=[creature.permanent_id],
        )
        assert result.supported, result
        _w1g1_resolve_stack(game)
        game._settle()

    punisher = put(mrd["Loxodon Punisher"])
    bears = put(lea["Grizzly Bears"])
    scimitar = put(mrd["Leonin Scimitar"])
    splitter = put(mrd["Bonesplitter"])
    assert (punisher.effective_power, punisher.effective_toughness) == (2, 2)
    equip(scimitar, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (5, 5)
    equip(splitter, punisher)
    assert (punisher.effective_power, punisher.effective_toughness) == (9, 7)
    equip(scimitar, bears)
    assert (punisher.effective_power, punisher.effective_toughness) == (6, 4)

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
