"""Mirrodin instants, the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


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
#
# Awe Strike: CR 615.8's shield keyed on the creature the spell targets, with
# no recipient printed (Penance's reach), and Reverse Damage's CR 615.5 rider
# paid to the caster. The sweep and look-alike boards are in
# tests/rules/test_mrd_w1g12_awe_strike.py.

from engine import Game as _w1g12_Game
from engine import PlayerState as _w1g12_PlayerState
from engine import targeting as _w1g12_targeting
from engine.models import Permanent as _w1g12_Permanent
from engine.oracle import compile_card_oracle as _w1g12_compile
from tests.helpers import _nosick as _w1g12_nosick
from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_card(set_pool, name):
    """A card by name, from Mirrodin first and Alpha for the fillers."""
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _w1g12_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    card = lambda name: _w1g12_card(set_pool, name)  # noqa: E731
    game = _w1g12_Game(players=[
        _w1g12_PlayerState(
            "A", hand=[card(n) for n in hand], library=[card("Forest")] * 12,
        ),
        _w1g12_PlayerState("B", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _w1g12_Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _w1g12_nosick(permanent)
            placed[seat].append(permanent)
    game.start_turn(0)
    game._settle()
    return game, placed[0], placed[1]


def test_w1g12_awe_strike_turns_an_unblocked_attackers_damage_into_life(set_pool):
    awe = _w1g12_card(set_pool, "Awe Strike")
    assert _w1g12_targeting.derive_cast_spec(awe, _w1g12_compile(awe)) == {
        "kind": "creature",
    }
    game, _, (wurm,) = _w1g12_table(set_pool, hand=["Awe Strike"], theirs=["Craw Wurm"])
    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    game.advance_combat_phase()
    assert game.players[0].life == 26
    assert "A gained 6 life from Awe Strike (20 -> 26)" in game.log


def test_w1g12_awe_strike_on_a_creature_that_leaves_does_nothing(set_pool):
    # CR 608.2b: its only target gone, the spell does nothing, and a Wurm that
    # comes back would be a new object the shield never named (CR 400.7).
    game, _, (wurm,) = _w1g12_table(set_pool, hand=["Awe Strike"], theirs=["Craw Wurm"])
    assert game.queue_from_hand(
        0, "Awe Strike", target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g12_resolve_stack(game)
    assert game.players[0].life == 20
    assert not any("the next damage" in line for line in game.log)


# Bloodscent: "All creatures able to block target creature this turn do so."
# Lure's CR 509.1c requirement for a turn, marked on the targeted attacker and
# read where Lure's printed and granted channels are, so it binds every
# creature able to block at declaration — one that entered after the spell
# resolved included (CR 611.2c fixes no set for a requirement).


def _w1g12_lured_attack(set_pool):
    game, (wurm,), theirs = _w1g12_table(
        set_pool, hand=["Bloodscent"], mine=["Craw Wurm"],
        theirs=["Grizzly Bears", "Grizzly Bears", "Llanowar Elves"],
    )
    theirs[2].tapped = True  # a tapped creature is not able to block
    assert game.queue_from_hand(
        0, "Bloodscent", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g12_resolve_stack(game)
    late = _w1g12_Permanent(card=_w1g12_card(set_pool, "Grizzly Bears"))
    game._put_permanent_onto_battlefield(1, late, None)
    _w1g12_nosick(late)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return game, wurm


def test_w1g12_bloodscent_compels_every_untapped_creature_to_block_it(set_pool):
    game, wurm = _w1g12_lured_attack(set_pool)
    bears = [
        game.battlefield_index_of(p) for p in game.controlled_by(1)
        if p.card.name == "Grizzly Bears"
    ]
    assert len(bears) == 3
    assert sorted(req.blocker for req in game.block_requirements(1)) == sorted(bears)
    assert not game.declare_blockers(1, {})[0]
    assert not game.declare_blockers(1, {bears[0]: 0, bears[1]: 0})[0]
    ok, why = game.declare_blockers(1, {slot: 0 for slot in bears})
    assert ok, why
    game.advance_combat_phase()
    assert game.players[1].life == 20


def test_w1g12_bloodscent_ends_with_the_turn(set_pool):
    game, wurm = _w1g12_lured_attack(set_pool)
    bears = [
        game.battlefield_index_of(p) for p in game.controlled_by(1)
        if p.card.name == "Grizzly Bears"
    ]
    assert game.declare_blockers(1, {slot: 0 for slot in bears})[0]
    assert wurm.metadata.get("must_be_blocked_by_all_until_eot")
    game.resolve_cleanup_step(0)  # CR 514.2
    assert not wurm.metadata.get("must_be_blocked_by_all_until_eot")

# ==== end W1G12 ======================================================
