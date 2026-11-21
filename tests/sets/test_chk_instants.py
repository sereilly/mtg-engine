"""Champions of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# "Counter target Spirit or Arcane spell." (Hisoka's Defiance) — a subtype
# union with the head noun "spell", read into the ``any_classes`` the
# counter, its picker and the stack enumeration test.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.legality import cast_spec_of as _w1g4_cast_spec
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_table(set_pool, *, hand=(), opponent_hand=()):
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(1)
    _w1g4_settle(game)
    return game


@_w1g4_pytest.mark.parametrize("code, name", [
    ("CHK", "Reach Through Mists"),    # Instant — Arcane
    ("CHK", "Kami of the Hunt"),       # Creature — Spirit
])
def test_w1g4_hisokas_defiance_counters_a_spirit_or_arcane_spell(set_pool, code, name):
    """Bob casts it on his turn; Alice counters it, and it goes to his
    graveyard without resolving (no card drawn, no Kami on the battlefield)."""
    chk = set_pool("CHK")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]], opponent_hand=[set_pool(code)[name]],
    )
    assert game.queue_from_hand(1, name).supported
    hand_before = len(game.players[1].hand)
    assert game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=0).supported
    _w1g4_settle(game)
    assert name in [card.name for card in game.players[1].graveyard], game.log
    assert not list(game.controlled_by(1))
    assert len(game.players[1].hand) == hand_before


def test_w1g4_hisokas_defiance_offers_only_spirit_and_arcane_spells(set_pool):
    """The picker over a stack of an Arcane instant, a Spirit creature spell
    and a Grizzly Bears spell names the first two and never the Bears — and a
    cast aimed at the Bears is refused."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g4_table(
        set_pool, hand=[chk["Hisoka's Defiance"]],
        opponent_hand=[chk["Reach Through Mists"], chk["Kami of the Hunt"],
                       lea["Grizzly Bears"]],
    )
    for name in ("Reach Through Mists", "Kami of the Hunt", "Grizzly Bears"):
        assert game.queue_from_hand(1, name).supported
    defiance = chk["Hisoka's Defiance"]
    offered = game._enumerate_targets(0, defiance, _w1g4_cast_spec(defiance), for_cast=True)
    assert sorted(o["name"] for o in offered) == ["Kami of the Hunt", "Reach Through Mists"]
    # ``target_stack_index`` indexes the stack bottom-first: 2 is the Bears.
    assert not game.queue_from_hand(0, "Hisoka's Defiance", target_stack_index=2).supported
    assert [item.card.name for item in game.stack][-1] == "Grizzly Bears"

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
