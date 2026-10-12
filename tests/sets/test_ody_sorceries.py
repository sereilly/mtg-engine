"""Odyssey sorceries.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
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
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState  # noqa: E402
from engine.models import Permanent as _W1G5Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w1g5_resolve_stack  # noqa: E402


def test_w1g5_touch_of_invisibility_makes_its_target_unblockable_for_the_turn(
    catalog_by_name, set_pool,
):
    """"Target creature can't be blocked this turn. Draw a card." Cast in the
    main phase (a sorcery), the Hill Giant attacks, a Wall of Stone may not
    block it, three damage lands, and the caster drew."""
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        _W1G5PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    giant = _W1G5Permanent(card=catalog_by_name["Hill Giant"])
    wall = _W1G5Permanent(card=catalog_by_name["Wall of Stone"])
    game._put_permanent_onto_battlefield(0, giant, None)
    game._put_permanent_onto_battlefield(1, wall, None)
    game.turn = 3
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].hand = [set_pool("ODY")["Touch of Invisibility"]]

    assert game.cast_from_hand(
        0, "Touch of Invisibility", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Island"]

    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {0: 0})[0]
    assert game.declare_blockers(1, {})[0]
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert game.players[1].life == 17

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
