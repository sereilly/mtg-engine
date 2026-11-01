"""The defending AI commits only the blockers a kill needs.

LGN Phase 5, smoke game 1: the AI triple-blocked a 1/1 and lost Daru Mender,
and triple-blocked a provoked 4/1 Crested Craghorn the provoked creature alone
would have killed, and lost Skinthinner. CR 510.1c (September 25, 2026 — there
is no damage assignment order in this edition): a blocked creature's damage is
"divided as its controller chooses among" its blockers, so each blocker beyond
the kill is one more creature the attacker may choose to destroy.

The over-commitment was not ``_gang_blocks`` (the losing blocks) but the loop
in front of it: every blocker whose block does not lose took its best pair,
so three creatures that each beat a 1/1 all blocked it. Now an attacker the
blocks already kill takes no more (``ai_declarations._blocks_already_kill``),
a block CR 509.1c compels is counted first (``ai_compelled_blocks.
compelled_blocks``), and a gang is the one the attacker can kill back least of.
"""
from __future__ import annotations

from engine.ai_declarations import choose_combat_blockers
from engine.card_loader import load_catalog
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_THIS_COMBAT
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _mk_creature_card, _nosick

_CARDS = {card.name: card for card in load_catalog()}


def _card(spec):
    if isinstance(spec, str):
        return _CARDS[spec]
    name, power, toughness = spec
    return _mk_creature_card(name, power, toughness)


def _board(attackers, blockers, *, compelled=None):
    """Seat 0 attacks seat 1 with *attackers* and seat 1 holds *blockers*
    (card names, or ``(name, power, toughness)``); *compelled* is ``{blocker
    slot: attacker slot}`` blocks seat 1 owes this combat (provoke's mark)."""
    p0, p1 = PlayerState(name="P0"), PlayerState(name="P1")
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    for spec in attackers:
        p0.battlefield.append(_nosick(Permanent(card=_card(spec))))
    for spec in blockers:
        p1.battlefield.append(_nosick(Permanent(card=_card(spec))))
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, why = game.declare_attackers(0, list(range(len(attackers))), defending_player_index=1)
    assert ok, why
    for blocker_idx, attacker_idx in (compelled or {}).items():
        p1.battlefield[blocker_idx].metadata[MUST_BLOCK_ATTACKERS_THIS_COMBAT] = [
            p0.battlefield[attacker_idx].permanent_id
        ]
    game.advance_combat_phase()  # declare blockers
    assert game.current_step == "declare_blockers"
    return game


def _declared(game) -> dict:
    proposed = choose_combat_blockers(game, 1)
    ok, why = game.declare_blockers(1, dict(proposed), acting_index=1)
    assert ok, why
    return proposed


def _names(game, proposed) -> list[str]:
    return sorted(game.permanent_at(1, slot).card.name for slot in proposed)


def test_a_one_one_is_blocked_by_one_creature_that_beats_it():
    """A 1/1 against Daru Mender (1/1) and two 2/2s: one 2/2 kills it and
    survives; nothing else blocks, and Daru Mender is not given away."""
    game = _board([("Token", 1, 1)], ["Daru Mender", ("Bear A", 2, 2), ("Bear B", 2, 2)])
    proposed = _declared(game)
    assert len(proposed) == 1, proposed
    assert _names(game, proposed) != ["Daru Mender"]


def test_the_provoked_creature_alone_meets_the_craghorn():
    """Crested Craghorn (4/1) provoked Daru Mender: the Mender must block it
    and kills it alone, so Skinthinner and the Bear stay home."""
    game = _board(
        ["Crested Craghorn"], ["Skinthinner", "Daru Mender", ("Bear", 2, 2)],
        compelled={1: 0},
    )
    proposed = _declared(game)
    assert proposed == {1: 0}, proposed


def test_a_provoked_creature_that_cannot_win_alone_is_helped_to_a_kill():
    """A 3/3 provoked a 1/1: the 1/1 blocks it whatever happens, and a 2/3 beside
    it makes the kill the 1/1 could not — counted toward the kill first."""
    game = _board([("Brute", 3, 3)], [("Imp", 1, 1), ("Wall", 2, 3)], compelled={0: 0})
    proposed = _declared(game)
    assert proposed == {0: 0, 1: 0}, proposed


def test_two_attackers_are_each_blocked_rather_than_one_twice():
    game = _board([("A", 2, 2), ("B", 2, 2)], [("X", 3, 3), ("Y", 3, 3)])
    proposed = _declared(game)
    assert sorted(proposed.values()) == [0, 1], proposed


def test_creatures_the_attacker_cannot_hurt_still_gang_up_on_it():
    """The four-Sliver gang Phase 5 called sensible: creatures with protection
    from green on a green attacker lose nothing, so as many block as the kill
    needs — Craw Wurm (6/4) takes two Vodalian Zombies (2/2), and the third
    stays free."""
    game = _board(["Craw Wurm"], ["Vodalian Zombie"] * 3)
    proposed = _declared(game)
    assert len(proposed) == 2 and set(proposed.values()) == {0}, proposed


def test_a_gang_is_the_one_that_loses_least():
    """A 3/3 against a 2/3, a 1/2 and two 1/1s: the 1/1s and the 1/2 kill it and
    it kills two of them back; the 2/3 and a 1/1 kill it and it kills one back.
    The cheapest-first gang never reached the second (it gave up on the
    first)."""
    game = _board([("Brute", 3, 3)], [("Wall", 2, 3), ("Imp", 1, 2), ("Rat", 1, 1), ("Bat", 1, 1)])
    proposed = _declared(game)
    assert len(proposed) == 2 and 0 in proposed, proposed
