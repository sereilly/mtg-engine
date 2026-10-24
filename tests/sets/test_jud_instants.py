"""Judgment instants.

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
# Cards in a graveyard as targets. Funeral Pyre exiles a card from any
# graveyard and gives the token to that card's **owner** (CR 404.1: a card in a
# graveyard is in its owner's; CR 108.4a: it has no controller).

from engine import Game as _w1g3_Game, PlayerState as _w1g3_PlayerState
from engine.targeting import derive_cast_spec as _w1g3_derive_cast_spec
from engine.oracle import compile_card_oracle as _w1g3_compile
from tests.helpers import resolve_stack as _w1g3_resolve


def _w1g3_pyre_game(set_pool, *, mine=(), theirs=()):
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g3_Game(players=[
        _w1g3_PlayerState(
            name="P0", hand=[jud["Funeral Pyre"]],
            graveyard=[lea[name] for name in mine], library=[lea["Plains"]] * 5,
        ),
        _w1g3_PlayerState(
            name="P1", graveyard=[lea[name] for name in theirs],
            library=[lea["Plains"]] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _w1g3_spirits(player, game):
    return [
        perm for perm in game.controlled_by(game.players.index(player))
        if perm.card.name == "Spirit Token"
    ]


def test_w1g3_funeral_pyre_gives_the_spirit_to_the_exiled_cards_owner(set_pool):
    game = _w1g3_pyre_game(set_pool, mine=("Swamp",), theirs=("Grizzly Bears", "Terror"))
    pyre = set_pool("JUD")["Funeral Pyre"]
    spec = _w1g3_derive_cast_spec(pyre, _w1g3_compile(pyre))
    # Any graveyard, any card: the picker is not scoped to either pile.
    assert spec["kind"] == "graveyard_creature" and spec.get("any_card")
    assert not spec.get("own_graveyard_only")
    offered = {(t["seat"], t["name"]) for t in game.cast_target_spec(0, pyre)["valid_targets"]}
    assert offered == {(0, "Swamp"), (1, "Grizzly Bears"), (1, "Terror")}

    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=1, target_permanent_index=1,
    ).supported
    _w1g3_resolve(game)

    victim = game.players[1]
    assert [c.name for c in victim.exile] == ["Terror"]
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    (spirit,) = _w1g3_spirits(victim, game)
    assert game._has_keyword(spirit, "flying")
    assert (spirit.effective_power, spirit.effective_toughness) == (1, 1)
    assert spirit.card.colors in (("W",), ["W"])
    assert _w1g3_spirits(game.players[0], game) == []


def test_w1g3_funeral_pyre_on_its_casters_own_card_gives_the_caster_the_spirit(set_pool):
    game = _w1g3_pyre_game(set_pool, mine=("Swamp",), theirs=("Grizzly Bears",))
    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=0, target_permanent_index=0,
    ).supported
    _w1g3_resolve(game)

    assert [c.name for c in game.players[0].exile] == ["Swamp"]
    assert len(_w1g3_spirits(game.players[0], game)) == 1
    assert _w1g3_spirits(game.players[1], game) == []


def test_w1g3_funeral_pyre_whose_card_left_in_response_makes_no_spirit(set_pool):
    """CR 608.2b: its one target gone, the spell does not resolve — so there
    is no exiled card, and no owner to hand a token to."""
    game = _w1g3_pyre_game(set_pool, theirs=("Grizzly Bears", "Terror"))
    assert game.queue_from_hand(
        0, "Funeral Pyre", target_player_index=1, target_permanent_index=0,
    ).supported
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(0))          # the Bears, in response

    _w1g3_resolve(game)

    assert [c.name for c in victim.graveyard] == ["Terror"]
    assert _w1g3_spirits(victim, game) == [] and _w1g3_spirits(game.players[0], game) == []

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
