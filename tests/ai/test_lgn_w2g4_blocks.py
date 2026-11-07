"""The defending AI does not give a creature away for damage it can take.

``ai_declarations.choose_combat_blockers`` took every legal pair whatever its
score said (W1G2: at twenty life a 2/2 chumped a 5/3 Drinker of Sorrow). A
block that loses its blocker is now made only as part of a gang that kills an
attacker worth more than what it kills back, or as a chump whose saved life is
worth more than the creature on the rehearsal's own scale
(``ai_standing.life_worth`` against ``permanent_worth``).
"""

from __future__ import annotations

from engine.ai_declarations import choose_combat_blockers
from engine.game import Game
from engine.models import Permanent, PlayerState

from tests.helpers import _mk_creature_card, _nosick


def _board(attackers, blockers, *, life: int = 20, attacker_text: str = ""):
    """Seat 0 attacks seat 1 with *attackers* ((power, toughness) each) and
    seat 1 holds *blockers*; the game stands in the declare-blockers step."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1", life=life)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    for index, (power, toughness) in enumerate(attackers):
        p0.battlefield.append(_nosick(Permanent(
            card=_mk_creature_card(f"A{index}", power, toughness, attacker_text)
        )))
    for index, (power, toughness) in enumerate(blockers):
        p1.battlefield.append(Permanent(card=_mk_creature_card(f"B{index}", power, toughness)))
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, why = game.declare_attackers(0, list(range(len(attackers))), defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()  # declare blockers
    assert game.current_step == "declare_blockers"
    return game


def _declared(game) -> dict:
    """The AI's proposal, after checking the engine takes it."""
    proposed = choose_combat_blockers(game, 1)
    ok, why = game.declare_blockers(1, dict(proposed), acting_index=1)
    assert ok, why
    return proposed


def test_no_chump_block_at_twenty_life():
    """A 2/2 in front of a 5/3 at twenty life: five damage is not worth a
    creature, so nothing blocks — and the five arrive."""
    game = _board([(5, 3)], [(2, 2)])
    assert _declared(game) == {}


def test_a_chump_block_where_the_damage_would_kill():
    """The same 2/2 at four life: the five would end the game."""
    game = _board([(5, 3)], [(2, 2)], life=4)
    assert _declared(game) == {0: 0}


def test_a_chump_block_where_the_damage_nearly_kills():
    """At six life five damage leaves one: the life a 1/1 saves (five points
    off the bottom of the scale) is worth more than the 1/1 — but at fourteen
    it is not."""
    near = _board([(5, 3)], [(1, 1)], life=6)
    assert _declared(near) == {0: 0}
    far = _board([(5, 3)], [(1, 1)], life=14)
    assert _declared(far) == {}


def test_the_blocks_that_do_not_lose_are_still_made():
    """A kill, a trade and a bounce are each made at twenty life."""
    kill = _board([(2, 2)], [(3, 3)])
    assert _declared(kill) == {0: 0}
    trade = _board([(3, 3)], [(3, 3)])
    assert _declared(trade) == {0: 0}
    bounce = _board([(1, 1)], [(0, 4)])
    assert _declared(bounce) == {0: 0}


def test_two_small_creatures_gang_block_what_neither_could_kill():
    """Two 2/2s on a 4/4: together they deal four and the 4/4 kills back
    both — more worth of creatures than it, so no. A 2/3 and a 1/2 on a 3/3:
    neither kills it alone, together they do, and its three damage kills only
    one of them back (CR 510.1c)."""
    even = _board([(4, 4)], [(2, 2), (2, 2)])
    assert _declared(even) == {}
    good = _board([(3, 3)], [(2, 3), (1, 2)])
    proposed = _declared(good)
    assert sorted(proposed) == [0, 1] and set(proposed.values()) == {0}, proposed


def test_two_one_ones_do_not_throw_themselves_at_a_five_five():
    """Neither 1/1 kills the 5/5, together they do not either, and the life
    at twenty is not worth one of them."""
    game = _board([(5, 5)], [(1, 1), (1, 1)])
    assert _declared(game) == {}


def test_a_first_striker_is_not_mistaken_for_a_trade():
    """A 2/2 first striker attacking into a 2/2: power against toughness reads
    a trade, but the first strike kills the blocker before it deals damage
    (CR 510.4) — a losing block, not made at twenty life."""
    game = _board([(2, 2)], [(2, 2)], attacker_text="First strike")
    assert _declared(game) == {}
