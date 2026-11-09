"""Mirrodin artifacts, the later groups' sections.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_scales_board(set_pool, *, theirs=(), interactive=()):
    """Culling Scales (mana value 3) and a Forest on seat 0; *theirs* (LEA
    names) on seat 1."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    scales = _w1g9_Permanent(card=mrd["Culling Scales"])
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P0", battlefield=[scales, _w1g9_Permanent(card=lea["Forest"])]
        ),
        _w1g9_PlayerState(
            name="P1", battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs]
        ),
    ])
    game.interactive_seats = set(interactive)
    return game, scales


def test_w1g9_culling_scales_destroys_the_lowest_nonland_permanent(set_pool):
    """"…destroy target nonland permanent with the lowest mana value." The
    Forest (mana value 0) is a land and out of the set; the Elves (1) are the
    lowest of what is left, the Bears (2) and the Scales (3) survive."""
    game, scales = _w1g9_scales_board(
        set_pool, theirs=["Llanowar Elves", "Grizzly Bears"]
    )
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert [c.name for c in game.players[1].graveyard] == ["Llanowar Elves"]
    assert {p.card.name for p in game.all_permanents()} == {
        "Culling Scales", "Forest", "Grizzly Bears",
    }
    assert "Culling Scales destroyed Llanowar Elves" in game.log


def test_w1g9_culling_scales_offers_only_the_tied_lowest(set_pool):
    """The picker (CR 601.2c) offers the permanents tied for lowest and
    nothing else — "If two or more permanents are tied for lowest, target any
    one of them." An interactive controller picks; the Giant (4) is never on
    offer."""
    game, _ = _w1g9_scales_board(
        set_pool, theirs=["Llanowar Elves", "Birds of Paradise", "Hill Giant"],
        interactive=(0,),
    )
    game.resolve_upkeep(0)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("trigger_target", 0)
    ]
    offered = game.pending_choices[0].data["targets"]
    assert sorted(t["name"] for t in offered) == ["Birds of Paradise", "Llanowar Elves"]
    birds = next(p for p in game.all_permanents() if p.card.name == "Birds of Paradise")
    assert game.confirm_trigger_target(0, permanent_id=birds.permanent_id) is True
    _w1g9_resolve_stack(game)
    game._settle()
    assert [c.name for c in game.players[1].graveyard] == ["Birds of Paradise"]


def test_w1g9_culling_scales_target_no_longer_lowest_is_not_destroyed(set_pool):
    """The ruling (2004-12-01): "If the targeted permanent doesn't have the
    lowest mana value when the ability resolves, the ability doesn't resolve
    and the permanent isn't destroyed." A Black Lotus (0) entering in response
    makes the targeted Elves illegal at CR 608.2b."""
    game, _ = _w1g9_scales_board(set_pool, theirs=["Llanowar Elves"], interactive=(0,))
    game.resolve_upkeep(0)
    elves = next(p for p in game.all_permanents() if p.card.name == "Llanowar Elves")
    assert game.confirm_trigger_target(0, permanent_id=elves.permanent_id) is True
    assert game.stack, "the trigger waits on the stack for its resolution"
    lotus = _w1g9_Permanent(card=set_pool("LEA")["Black Lotus"])
    game._put_permanent_onto_battlefield(1, lotus, None)
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.is_on_battlefield(elves)
    assert game.is_on_battlefield(lotus)
    assert not game.players[1].graveyard


def test_w1g9_culling_scales_can_destroy_itself(set_pool):
    """The ruling (2004-12-01): "If the lowest mana value is 3, Culling Scales
    can destroy itself." With only a Hill Giant (4) beside it, the Scales are
    the one legal target."""
    game, scales = _w1g9_scales_board(set_pool, theirs=["Hill Giant"])
    game.resolve_upkeep(0)
    _w1g9_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(scales)
    assert [c.name for c in game.players[0].graveyard] == ["Culling Scales"]


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
