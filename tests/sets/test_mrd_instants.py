"""Mirrodin instants.

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


def test_w1g3_assert_authority_exiles_what_it_counters_at_its_affinity_price(set_pool):
    """"Affinity for artifacts" / "Counter target spell. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." Printed {5}{U}{U}. On the opponent's turn, with five artifact
    lands, it costs {U}{U}: two of them pay, the opponent's Grizzly Bears is
    countered into exile (CR 614.1's replacement of CR 701.6a's graveyard),
    and Assert Authority goes to its caster's graveyard. Mana costs are
    enforced for both seats."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd["Assert Authority"]]),
        _W1G3PlayerState(name="W1G3-B", hand=[lea["Grizzly Bears"]]),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 1
    for w1g3_seat, w1g3_name, w1g3_count in (
        (0, "Seat of the Synod", 5), (1, "Forest", 2),
    ):
        for _ in range(w1g3_count):
            w1g3_card = mrd[w1g3_name] if w1g3_name in mrd else lea[w1g3_name]
            game._put_permanent_onto_battlefield(
                w1g3_seat, _W1G3Permanent(card=w1g3_card), None
            )
    for w1g3_seat, w1g3_color, w1g3_count in ((1, "G", 2), (0, "U", 2)):
        w1g3_lands = [
            p for p in game.controlled_by(w1g3_seat) if p.has_type("land")
        ][:w1g3_count]
        for w1g3_land in w1g3_lands:
            assert game.tap_land_for_mana(
                w1g3_seat, w1g3_land.card.name, w1g3_color,
                permanent_id=w1g3_land.permanent_id,
            )
    game.queue_from_hand(1, "Grizzly Bears")
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    counter = game.cast_from_hand(0, "Assert Authority", target_stack_index=0)
    assert counter.supported, counter.details
    assert sum(game.players[0].mana_pool.values()) == 0
    _w1g3_resolve(game)

    assert not [p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == []
    assert [getattr(c, "name", c) for c in game.players[1].exile] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Assert Authority"]

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
