"""Exodus sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: a per-creature toll charged to each creature's own controller ---
#
# "For each creature, its controller sacrifices a permanent of their choice
# unless they pay {1}." The sentence iterates **creatures** and charges their
# **controllers**, so a player with three creatures answers three times — and
# the seat asked is the iteration's own object's, which is the innermost
# binding (``handlers/_common.bound_permanent``) rather than anything the firing
# event or the spell's target froze.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_G2S_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2s_duel():
    """Seat 0 active, costs off, nobody interactive — so every offer takes its
    registered default. Its own trailing line, kept unlike any other group's."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set()
    return game, game.players[0], game.players[1]


def _g2s_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_fade_away_charges_each_creatures_own_controller(set_pool):
    """The seat is read off the creature the iteration is on, not off the
    caster: Bob's Hill Giant costs *Bob* a permanent, and Alice's Bears costs
    Alice one."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 0, _G2S_LEA["Grizzly Bears"])
    _g2s_put(game, 1, _G2S_LEA["Hill Giant"])
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert [p.card.name for p in game.controlled_by(alice)] == []
    assert [p.card.name for p in game.controlled_by(bob)] == ["Hill Giant"]


def test_w1g2_fade_away_charges_a_seat_once_per_creature(set_pool):
    """The loop is over **creatures**, not players, so two creatures is two
    tolls on one seat — which is the whole difference between this card and
    "each player sacrifices a permanent"."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 1, _G2S_LEA["Hill Giant"])
    _g2s_put(game, 1, _G2S_LEA["Grizzly Bears"])
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    _g2s_put(game, 1, _G2S_LEA["Forest"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    # Two creatures, two sacrifices out of Bob's four permanents.
    assert len(list(game.controlled_by(bob))) == 2
    assert alice.graveyard[-1].name == "Fade Away"


def test_w1g2_fade_away_over_an_empty_board_does_nothing(set_pool):
    """CR 608.2's "as much as possible": no creature is no iteration, so
    nobody is asked and nothing is sacrificed."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert [p.card.name for p in game.controlled_by(bob)] == ["Mountain"]
