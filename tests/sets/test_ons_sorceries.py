"""Onslaught sorceries.

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

# --- W1G3: cycling triggers (CR 702.29c) and the cycling sorceries ----------
#
# The instants' section of `test_ons_instants.py` says how these are driven:
# cycle, resolve the trigger alone (the cycling ability is under it, so nothing
# is drawn yet), read the board, then let the draw resolve.
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, library=5):
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand], library=[filler] * library,
    )
    bob = PlayerState(name="Bob", library=[filler] * library)
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g3_cycle_and_resolve_trigger(game, name):
    assert game.activate_from_hand(0, name).supported
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.stack[-2].ability_text.endswith("Discard this card: Draw a card.")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    if offer is not None:
        assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()
    assert len(game.stack) == 1, "the cycling ability is still waiting to draw"


def test_w1g3_dirge_of_dread_cycled_gives_one_creature_fear(set_pool):
    """"…you may have target creature gain fear until end of turn." — one
    creature, not the spell's "all creatures"."""
    game, alice, _bob = _w1g3_table(set_pool, "Dirge of Dread")
    mine = _w1g3_put(game, 0, _mk_creature_card("Bear", 2, 2))
    other = _w1g3_put(game, 1, _mk_creature_card("Wall", 0, 4))

    _w1g3_cycle_and_resolve_trigger(game, "Dirge of Dread")
    assert mine.has_keyword("fear")
    assert not other.has_keyword("fear")
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]
    game.resolve_cleanup_step(0)
    assert not mine.has_keyword("fear")


def test_w1g3_slice_and_dice_cycled_deals_1_to_each_creature(set_pool):
    """"…you may have it deal 1 damage to each creature." Both boards, the
    card in the graveyard as the source: the 1/1s die, the 2/2 lives."""
    game, alice, bob = _w1g3_table(set_pool, "Slice and Dice")
    small_mine = _w1g3_put(game, 0, _mk_creature_card("Mine", 1, 1))
    small_theirs = _w1g3_put(game, 1, _mk_creature_card("Theirs", 1, 1))
    big = _w1g3_put(game, 1, _mk_creature_card("Big", 2, 2))

    _w1g3_cycle_and_resolve_trigger(game, "Slice and Dice")
    game.check_state_based_actions()
    assert not game.is_on_battlefield(small_mine)
    assert not game.is_on_battlefield(small_theirs)
    assert game.is_on_battlefield(big) and big.damage_marked == 1
    resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Plains"]


#: The Onslaught sorceries that print cycling and nothing triggering on it.
_W1G3_PLAIN_CYCLING_SORCERIES = {
    "Akroma's Vengeance": {"C": 3},
    "Essence Fracture": {"C": 2, "U": 1},
    "Lay Waste": {"C": 2},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_SORCERIES))
def test_w1g3_a_plain_cycling_sorcery_pays_its_cost_and_draws(set_pool, name):
    """Cycling is an activated ability (CR 702.29a), so a sorcery cycles with a
    spell on the stack — not at sorcery speed — and the spell's effect never
    happens."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert len(usable_activated_abilities(program, zone=HAND)) == 1

    game, alice, bob = _w1g3_table(set_pool, name)
    bear = _w1g3_put(game, 1, _mk_creature_card("Bear", 2, 2))
    bob.hand.append(set_pool("ONS")["Shock"])
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_SORCERIES[name])

    assert game.activate_from_hand(0, name).supported, "cycled in response"
    resolve_stack(game)
    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]
    assert game.is_on_battlefield(bear)
    assert alice.life == 18, "the Shock under it resolved"

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


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================
