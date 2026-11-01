"""Legions creatures, W1G4 onward (W1G1-W1G3 are in test_lgn_creatures.py).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("LGN")` / `set_cards("LGN")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: tribal statics and counts ---------------------------------------
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine.models import Permanent as _W1G5Permanent
from engine.models import PlayerState as _W1G5PlayerState
from engine.oracle import compile_card_oracle as _w1g5_compile

from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, *hand, opponent_hand=(), interactive=()):
    """Alice (seat 0, active) holding *hand*, Bob holding *opponent_hand*;
    both over five Swamps, mana costs unenforced."""
    lgn = set_pool("LGN")
    ons = set_pool("ONS")

    def card(name):
        return lgn[name] if name in lgn else ons[name]

    filler = ons["Swamp"]
    alice = _W1G5PlayerState(
        name="Alice", hand=[card(name) for name in hand], library=[filler] * 5,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=[card(name) for name in opponent_hand],
        library=[filler] * 5,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game, alice, bob, card


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


@_w1g5_pytest.mark.parametrize("interactive", [False, True])
def test_w1g5_gempalm_polluter_drains_by_the_zombies_on_the_whole_battlefield(
    set_pool, interactive,
):
    """"When you cycle this card, you may have target player lose life equal
    to the number of Zombies on the battlefield." Zombies on both sides count
    (two here: one each), an Elf does not, and the count is taken as the
    trigger resolves — after a third Zombie arrived in response. An
    interactive Alice names herself; the default seat names Bob."""
    game, alice, bob, card = _w1g5_table(
        set_pool, "Gempalm Polluter", interactive={0} if interactive else (),
    )
    _w1g5_put(game, 0, card("Severed Legion"))
    _w1g5_put(game, 1, card("Severed Legion"))
    _w1g5_put(game, 1, card("Wellwisher"))
    assert _w1g5_compile(card("Gempalm Polluter")).supported

    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    if interactive:
        assert game.pending_choice_of("trigger_target", 0) is not None
        assert game.confirm_trigger_target(0, seat=0)
    loser = alice if interactive else bob
    # A third Zombie before the trigger resolves: the count is the board's at
    # resolution, not at the cycle.
    _w1g5_put(game, 1, card("Gempalm Polluter"))
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, "the 'you may' is asked"
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert loser.life == 17
    assert (alice if loser is bob else bob).life == 20
    assert any(f"{loser.name} lost 3 life" in line for line in game.log)


def test_w1g5_gempalm_polluter_declined_loses_nothing(set_pool):
    """The "you may" declined: nobody loses life, and the cycling still draws."""
    game, alice, bob, card = _w1g5_table(set_pool, "Gempalm Polluter")
    _w1g5_put(game, 1, card("Severed Legion"))
    assert game.activate_from_hand(0, "Gempalm Polluter").supported
    _w1g5_resolve_stack(game)
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, False, None)
    game.auto_resolve_pending_choices()
    assert (alice.life, bob.life) == (20, 20)
    assert len(alice.hand) == 1

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
