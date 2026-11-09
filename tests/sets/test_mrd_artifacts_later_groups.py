"""Mirrodin artifacts, the later groups' sections.

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


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _w1g10_Game, PlayerState as _w1g10_PlayerState
from engine.models import Permanent as _w1g10_Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, hand=(), their_hand=()):
    """Two seats with Forests to draw, costs unenforced, P2 active so the
    next turn begun is P1's."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_Game(players=[
        _w1g10_PlayerState("P1", library=[forest] * 20, hand=list(hand)),
        _w1g10_PlayerState("P2", library=[forest] * 20, hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 1
    game.turn = 1
    return game


def _w1g10_put(game, seat, card):
    permanent = _w1g10_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g10_mindstorm_crown_draws_when_the_turn_began_with_an_empty_hand(set_pool):
    game = _w1g10_table(set_pool)
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()            # P1: untap, upkeep (the Crown), draw step
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    # One from the Crown, one from the draw step.
    assert len(p1.hand) == 2
    assert "P1 drew 1 card(s) (Mindstorm Crown)" in game.log


def test_w1g10_mindstorm_crown_deals_one_when_the_turn_began_with_a_card(set_pool):
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest, forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    # "If you had a card in hand" is one *or more*: two cards still hurt.
    assert p1.life == 19
    assert len(p1.hand) == 3          # only the draw step drew
    assert "Mindstorm Crown dealt 1 damage to P1" in game.log


def test_w1g10_mindstorm_crown_reads_the_hand_the_turn_began_with(set_pool):
    """The 2004-12-01 ruling: two Crowns and an empty hand at the start of the
    turn draw two cards — the first Crown's draw does not turn the second
    into a damage trigger, because the hand asked about is the turn's first."""
    game = _w1g10_table(set_pool)
    crown = set_pool("MRD")["Mindstorm Crown"]
    _w1g10_put(game, 0, crown)
    _w1g10_put(game, 0, crown)
    game.start_next_turn()
    _w1g10_resolve_stack(game)
    p1 = game.players[0]
    assert p1.life == 20
    assert len(p1.hand) == 3
    assert game.log.count("P1 drew 1 card(s) (Mindstorm Crown)") == 2


def test_w1g10_mindstorm_crown_ignores_the_hand_at_the_upkeep(set_pool):
    """A hand emptied after the turn began is still a turn that began with a
    card: the record, not the hand at resolution, is asked."""
    forest = set_pool("LEA")["Forest"]
    game = _w1g10_table(set_pool, hand=[forest])
    _w1g10_put(game, 0, set_pool("MRD")["Mindstorm Crown"])
    game.begin_turn_bookkeeping(0)
    game.turn += 1
    game.players[0].hand.clear()      # gone before the upkeep asks
    game.resolve_untap_step(0)
    game.resolve_upkeep(0)
    _w1g10_resolve_stack(game)
    assert game.players[0].life == 19
    assert not game.players[0].hand


def test_w1g10_platinum_angel_keeps_its_controller_in_the_game(set_pool):
    """A Lightning Bolt to 0 life with the Angel out: no loss, and the game
    goes on; the Angel dies and the next state-based check takes the game.
    The whole of CR 104.3 is in tests/rules/test_mrd_w1g10_cant_lose_the_game.py."""
    game = _w1g10_table(set_pool, their_hand=[set_pool("LEA")["Lightning Bolt"]])
    angel = _w1g10_put(game, 0, set_pool("MRD")["Platinum Angel"])
    game.players[0].life = 2
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g10_resolve_stack(game)
    game.check_state_based_actions()
    assert game.players[0].life == -1
    assert not game.players[0].lost and not game.is_game_over()
    game.remove_from_battlefield(angel)
    game._permanent_to_graveyard(game.players[0], angel)
    game.check_state_based_actions()
    assert game.players[0].lost
    assert game.get_winner() is game.players[1]

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================
