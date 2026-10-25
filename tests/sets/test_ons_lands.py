"""Onslaught lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
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

# --- W1G3: Onslaught's five cycling lands -----------------------------------
#
# "This land enters tapped. / {T}: Add {B}. / Cycling {B}" — a mana source on
# the battlefield, "{B}, Discard this card: Draw a card" in a hand, and never
# the second where it is the first (CR 702.29b / 113.6j). Supported on
# arrival; driven here for the first time.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

_W1G3_CYCLING_LANDS = (
    ("Barren Moor", "B"),
    ("Forgotten Cave", "R"),
    ("Lonely Sandbar", "U"),
    ("Secluded Steppe", "W"),
    ("Tranquil Thicket", "G"),
)


def _w1g3_table(set_pool, *hand):
    ons = set_pool("ONS")
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[ons["Plains"]] * 5,
    )
    game = Game(players=[alice, PlayerState(name="Bob", library=[ons["Plains"]] * 5)])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice


@pytest.mark.parametrize(("name", "symbol"), _W1G3_CYCLING_LANDS)
def test_w1g3_a_cycling_land_cycles_from_hand_for_its_colour(set_pool, name, symbol):
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program)] == [
        "{T}: Add {%s}." % symbol
    ]
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{%s}, Discard this card: Draw a card." % symbol
    ]

    game, alice = _w1g3_table(set_pool, name)
    alice.mana_pool[symbol] = 1
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert alice.mana_pool[symbol] == 0
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]


@pytest.mark.parametrize(("name", "symbol"), _W1G3_CYCLING_LANDS)
def test_w1g3_a_cycling_land_enters_tapped_and_only_taps_for_mana(set_pool, name, symbol):
    """Played, it enters tapped; untapped, its first ability adds its colour
    and the cycling ability is not there to reach."""
    game, alice = _w1g3_table(set_pool, name)
    assert game.cast_from_hand(0, name).supported
    (land,) = [p for p in game.controlled_by(0) if p.card.name == name]
    assert land.tapped, "This land enters tapped."

    land.tapped = False
    assert game.activate_permanent_ability(0, name, ability_index=0).supported
    assert alice.mana_pool[symbol] == 1
    assert game.activate_permanent_ability(0, name, ability_index=1).supported is False
    assert len(alice.library) == 5 and alice.graveyard == []
    assert game.is_on_battlefield(land)

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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.type_changes import gain_types as _w1g7_gain_types
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_perm(pool, name):
    return _w1g7_nosick(_w1g7_Permanent(card=pool[name]))


def _w1g7_game(mine=(), theirs=(), *, p1=None, p2=None):
    one = _w1g7_PlayerState(name="P1", battlefield=list(mine), **(p1 or {}))
    two = _w1g7_PlayerState(name="P2", battlefield=list(theirs), **(p2 or {}))
    game = _w1g7_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def test_w1g7_unholy_grotto_puts_a_zombie_card_on_top(set_pool):
    """"{B}, {T}: Put target Zombie card from your graveyard on top of your
    library." The picker offers the Zombie cards in the activator's own pile
    and nothing else; the activation moves the one named."""
    pool = set_pool("ONS")
    grotto = _w1g7_perm(pool, "Unholy Grotto")
    game, p1, p2 = _w1g7_game(
        [grotto],
        p1={"graveyard": [pool["Wirewood Elf"], pool["Gangrenous Goliath"],
                          pool["Shepherd of Rot"]],
            "library": [pool["Swamp"]] * 3},
        p2={"graveyard": [pool["Aphetto Vulture"]]},
    )
    spec = game.activation_target_spec(0, 0, ability_index=1)
    offered = {
        (entry.get("seat"), entry.get("index")) for entry in spec["valid_targets"]
    }
    assert offered == {(0, 1), (0, 2)}, spec

    result = game.activate_permanent_ability(
        0, "Unholy Grotto", ability_index=1,
        target_role_refs=[{"graveyard_seat": 0, "graveyard_index": 2}],
    )
    assert result.supported, result.details
    _w1g7_resolve(game)
    assert p1.library[0].name == "Shepherd of Rot"
    assert [c.name for c in p1.graveyard] == ["Wirewood Elf", "Gangrenous Goliath"]
    assert grotto.tapped


def test_w1g7_starlit_sanctum_drains_the_sacrificed_clerics_power(set_pool):
    """"{B}, {T}, Sacrifice a Cleric creature: Target player loses life equal
    to the sacrificed creature's power." The power it had as it was
    sacrificed (CR 608.2h) — pumped, not printed — and only a Cleric pays."""
    from engine.pt import add_pt_modifier

    pool = set_pool("ONS")
    sanctum = _w1g7_perm(pool, "Starlit Sanctum")
    cleric = _w1g7_perm(pool, "Daunting Defender")
    elf = _w1g7_perm(pool, "Wirewood Elf")
    game, p1, p2 = _w1g7_game([sanctum, cleric, elf])
    add_pt_modifier(cleric, 2, 0)
    game._recompute_continuous_effects()
    result = game.activate_permanent_ability(
        0, "Starlit Sanctum", ability_index=2, target_player_index=1,
        cost_permanent_ids=[cleric.permanent_id],
    )
    assert result.supported, result.details
    _w1g7_resolve(game)
    assert p2.life == 15
    assert [c.name for c in p1.graveyard] == ["Daunting Defender"]
    assert game.is_on_battlefield(elf)

    # With no Cleric left the cost cannot be paid — the Elf is no Cleric.
    sanctum.tapped = False
    refused = game.activate_permanent_ability(
        0, "Starlit Sanctum", ability_index=2, target_player_index=1,
    )
    assert not refused.supported
    assert game.is_on_battlefield(elf) and p2.life == 15

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


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
