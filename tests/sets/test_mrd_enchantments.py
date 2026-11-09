"""Mirrodin enchantments, Auras included.

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

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from engine.targeting import derive_cast_spec as _w1g9_derive_cast_spec
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_domineer_board(set_pool, theirs):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(name="P0", hand=[mrd["Domineer"]]),
        _w1g9_PlayerState(
            name="P1", battlefield=[_w1g9_Permanent(card=lea[n]) for n in theirs]
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _w1g9_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def test_w1g9_domineer_offers_only_artifact_creatures(set_pool):
    """"Enchant artifact creature": the ruling (2004-12-01) — "The enchanted
    permanent must be both an artifact and a creature." The picker offers the
    Juggernaut and neither the Bears (a creature) nor the Sol Ring (an
    artifact)."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears", "Sol Ring"])
    domineer = set_pool("MRD")["Domineer"]
    spec = _w1g9_derive_cast_spec(domineer, _w1g9_compile(domineer))
    offered = game._enumerate_targets(0, domineer, spec, for_cast=True)
    assert sorted(t["name"] for t in offered) == ["Juggernaut"]


def test_w1g9_domineer_takes_control_of_the_artifact_creature(set_pool):
    """"You control enchanted artifact creature." The Juggernaut changes
    sides as Domineer attaches (CR 613 layer 2, the attachment sweep), and a
    cast aimed at the Bears is refused."""
    game = _w1g9_domineer_board(set_pool, ["Juggernaut", "Grizzly Bears"])
    bears = _w1g9_named(game, "Grizzly Bears")
    refused = game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not getattr(refused, "supported", True) or not game.stack
    assert [c.name for c in game.players[0].hand] == ["Domineer"]
    juggernaut = _w1g9_named(game, "Juggernaut")
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[juggernaut.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(juggernaut) == 0
    assert _w1g9_named(game, "Domineer").metadata.get("attached_to") is juggernaut


def test_w1g9_domineer_falls_off_an_artifact_that_stops_being_a_creature(set_pool):
    """The ruling (2004-12-01): "Domineer 'falls off' and is put into the
    graveyard if the artifact creature it's enchanting stops being an artifact
    or stops being a creature." A Sol Ring animated by Animate Artifact is
    stolen; destroying Animate Artifact ends the creature type, the CR 704.5m
    sweep bins Domineer, and the Sol Ring goes home."""
    lea = set_pool("LEA")
    game = _w1g9_domineer_board(set_pool, ["Sol Ring"])
    ring = _w1g9_named(game, "Sol Ring")
    game.players[1].hand.append(lea["Animate Artifact"])
    game.cast_from_hand(
        1, "Animate Artifact", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert ring.is_creature
    game.cast_from_hand(
        0, "Domineer", target_player_index=1,
        target_permanent_ids=[ring.permanent_id],
    )
    _w1g9_resolve_stack(game)
    game._settle()
    assert game.controller_index_of(ring) == 0
    game._destroy_target_permanent(
        game.players[1], described={"named": "Animate Artifact"}
    )
    game._settle()
    assert not ring.is_creature
    assert [c.name for c in game.players[0].graveyard] == ["Domineer"]
    assert game.controller_index_of(ring) == 1


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
