"""Mirrodin lands.

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


def _w1g3_override_table(set_pool, mine, theirs):
    """Seat 0 holds an Ornithopter; seat 1 holds Override over three Islands.
    Mana costs enforced; nobody is an interactive seat."""
    mrd = set_pool("MRD")
    w1g3_game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A", hand=[mrd["Ornithopter"]]),
        _W1G3PlayerState(name="W1G3-B", hand=[mrd["Override"]]),
    ])
    w1g3_game.enforce_mana_costs = True
    w1g3_game.interactive_seats = set()
    w1g3_game.active_player_index = 0
    for w1g3_seat, w1g3_names in ((0, mine), (1, ("Island",) * 3 + tuple(theirs))):
        for w1g3_name in w1g3_names:
            w1g3_perm = _W1G3Permanent(card=mrd[w1g3_name])
            w1g3_game._put_permanent_onto_battlefield(w1g3_seat, w1g3_perm, None)
            w1g3_perm.tapped = False
    return w1g3_game  # _w1g3_override_table


def test_w1g3_cloudpost_taps_for_each_locus_and_enters_tapped(set_pool):
    """"This land enters tapped." / "{T}: Add {C} for each Locus on the
    battlefield." Cloudpost is a Locus itself, so alone it makes {C}; beside
    an opponent's Cloudpost ("on the battlefield" is everybody's) one tap
    makes {C}{C}. A Cloudpost put onto the battlefield arrives tapped."""
    mrd = set_pool("MRD")
    game = _W1G3Game(players=[
        _W1G3PlayerState(name="W1G3-A"), _W1G3PlayerState(name="W1G3-B"),
    ])
    mine = _W1G3Permanent(card=mrd["Cloudpost"])
    game._put_permanent_onto_battlefield(0, mine, None)
    assert mine.tapped, "Cloudpost enters tapped"
    mine.tapped = False
    assert game.tap_land_for_mana(0, "Cloudpost", "C", permanent_id=mine.permanent_id)
    assert game.players[0].mana_pool["C"] == 1

    game.players[0].mana_pool["C"] = 0
    mine.tapped = False
    theirs = _W1G3Permanent(card=mrd["Cloudpost"])
    game._put_permanent_onto_battlefield(1, theirs, None)
    assert game.tap_land_for_mana(0, "Cloudpost", "C", permanent_id=mine.permanent_id)
    assert game.players[0].mana_pool["C"] == 2


def test_w1g3_override_is_paid_off_a_cloudpost(set_pool):
    """Override: "Counter target spell unless its controller pays {1} for each
    artifact you control." Its caster controls one artifact (a Seat of the
    Synod), so the toll is {1} — and a lone Cloudpost, which makes {C} by
    counting itself, pays it: the Ornithopter resolves. The effect payment
    plans over ``Game.payment_lands``, which left every board-counted land
    out until the tap census's Cloudpost row (MRD W1G3). With two artifacts
    the toll is {2}, one Cloudpost cannot pay it, and the Ornithopter is
    countered into its owner's graveyard."""
    for theirs, paid in ((("Seat of the Synod",), True),
                         (("Seat of the Synod", "Seat of the Synod"), False)):
        game = _w1g3_override_table(set_pool, ("Cloudpost",), theirs)
        assert game.payment_lands(0), "the Cloudpost is a land this payment plans over"
        game.queue_from_hand(0, "Ornithopter")
        for w1g3_land in [p for p in game.controlled_by(1) if p.card.name == "Island"][:3]:
            assert game.tap_land_for_mana(
                1, "Island", "U", permanent_id=w1g3_land.permanent_id,
            )
        counter = game.cast_from_hand(1, "Override", target_stack_index=0)
        assert counter.supported, counter.details
        _w1g3_resolve(game)
        on_board = [p.card.name for p in game.controlled_by(0)]
        assert ("Ornithopter" in on_board) is paid, (theirs, game.log[-6:])
        assert ([c.name for c in game.players[0].graveyard] == ["Ornithopter"]) is not paid

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
