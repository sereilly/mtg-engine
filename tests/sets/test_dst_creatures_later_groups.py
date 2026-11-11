"""Darksteel creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Mephitic Ooze: "destroy that creature. The creature can't be regenerated."
# — the destroy's rider read through the one reader of CR 701.19c's spellings,
# driven through a real combat against a regeneration shield.
from engine import Game as _W1G6Game
from engine.models import Permanent as _W1G6Permanent
from engine.models import PlayerState as _W1G6PlayerState

from tests.helpers import declare_attack as _w1g6_declare_attack
from tests.helpers import drive_combat as _w1g6_drive_combat


def _w1g6_table(set_pool):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", library=[lea["Plains"]] * 8),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._settle()
    return game


def _w1g6_put(game, seat, card, *, tapped=False):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    game._sync_control()
    return permanent


def test_w1g6_mephitic_ooze_counts_artifacts_and_destroys_a_shielded_blocker(set_pool):
    """"This creature gets +1/+0 for each artifact you control. Whenever this
    creature deals combat damage to a creature, destroy that creature. The
    creature can't be regenerated." With one artifact the Ooze is 1/5; a
    Wall of Stone (0/8) carrying a regeneration shield blocks it, survives the
    point of damage, and the trigger destroys it all the same — the shield is
    still there, unspent (CR 701.19c)."""
    dst, lea, atq = set_pool("DST"), set_pool("LEA"), set_pool("ATQ")
    game = _w1g6_table(set_pool)
    ooze = _w1g6_put(game, 0, dst["Mephitic Ooze"])
    assert (ooze.effective_power, ooze.effective_toughness) == (0, 5)
    _w1g6_put(game, 0, atq["Ornithopter"], tapped=True)
    game._recompute_continuous_effects()
    assert (ooze.effective_power, ooze.effective_toughness) == (1, 5)
    wall = _w1g6_put(game, 1, lea["Wall of Stone"])
    wall.regeneration_shield = 1
    _w1g6_declare_attack(game, 0, blocks={0: 0})
    _w1g6_drive_combat(game)
    assert not game.is_on_battlefield(wall)
    assert [card.name for card in game.players[1].graveyard] == ["Wall of Stone"]
    assert wall.regeneration_shield == 1, "the shield was never spent"
    assert any("Mephitic Ooze destroyed Wall of Stone" in line for line in game.log)


def test_w1g6_mephitic_ooze_damage_to_a_player_destroys_nothing(set_pool):
    """The trigger is about a *creature* dealt combat damage: unblocked, the
    Ooze's point goes to the player and no creature on either side is
    destroyed."""
    dst, lea, atq = set_pool("DST"), set_pool("LEA"), set_pool("ATQ")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, 0, dst["Mephitic Ooze"])
    _w1g6_put(game, 0, atq["Ornithopter"], tapped=True)
    bear = _w1g6_put(game, 1, lea["Grizzly Bears"])
    _w1g6_declare_attack(game, 0)
    _w1g6_drive_combat(game)
    assert game.players[1].life == 19
    assert game.is_on_battlefield(bear)
    assert not any("Mephitic Ooze destroyed" in line for line in game.log)

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
