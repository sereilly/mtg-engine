"""Torment enchantments, Auras included.

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
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def test_w1g7_last_laugh_sacrifices_itself_once_its_damage_empties_the_board(set_pool):
    """"When no creatures are on the battlefield, sacrifice this enchantment."

    Drop of Honey's state trigger in the other word order. A Bolt kills the
    Elves; Last Laugh's ping kills the Raiders; with no creature left anywhere
    it is sacrificed — and the ping for the Raiders' death still resolves from
    a source that has left, so each player loses 2."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    laugh = _w1g7_Permanent(card=tor["Last Laugh"])
    elves = _w1g7_Permanent(card=lea["Llanowar Elves"])
    raiders = _w1g7_Permanent(card=lea["Mons's Goblin Raiders"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[laugh, elves], hand=[lea["Lightning Bolt"]]),
        _w1g7_PlayerState(name="P1", battlefield=[raiders]),
    ])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[elves.permanent_id])
    _w1g7_resolve_stack(game)
    game._settle()

    assert [c.name for c in game.players[0].graveyard] == [
        "Lightning Bolt", "Llanowar Elves", "Last Laugh",
    ]
    assert [c.name for c in game.players[1].graveyard] == ["Mons's Goblin Raiders"]
    assert [p.life for p in game.players] == [18, 18]
    assert any("Last Laugh sacrificed" in line for line in game.log)


def test_w1g7_last_laugh_stays_while_any_creature_is_on_the_battlefield(set_pool):
    """The set is every battlefield: an opponent's creature keeps it."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    laugh = _w1g7_Permanent(card=tor["Last Laugh"])
    ogre = _w1g7_Permanent(card=lea["Gray Ogre"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[laugh]),
        _w1g7_PlayerState(name="P1", battlefield=[ogre]),
    ])
    game.check_state_based_actions()
    assert laugh in game.players[0].battlefield
    game.remove_from_battlefield(ogre)
    game.check_state_based_actions()
    assert laugh not in game.players[0].battlefield
    assert [c.name for c in game.players[0].graveyard] == ["Last Laugh"]

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================
