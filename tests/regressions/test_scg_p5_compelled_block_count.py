"""A creature owed blocks by several attackers is planned onto the one that
holds the most of them (SCG Phase 5, the LGN block-commitment census).

CR 509.1c counts requirements obeyed, and two instances of provoke are two
requirements (CR 702.39b): a creature provoked once by Goblin Grappler and
twice by a Crypt Sliver (every Sliver had provoke from each of two Hunter
Slivers) obeys two by blocking the Sliver and one by blocking the Grappler, so
the engine's maximisation (``Game.obeying_block_declaration``) puts it on the
Sliver whatever the seat declares. ``ai_compelled_blocks.compelled_blocks``
planned it onto "the first requirement" — the Grappler — and the chooser then
traded its Hunter Sliver with the Crypt Sliver; the engine moved the Turncoat
over, two blockers on a 1/1 the Turncoat killed alone, and the Grappler went
unblocked. Seen on LGN seed 17 once Beacon of Destiny stopped tapping itself
in its own main phase (``ai_valuation.DAMAGE_REPLACEMENT_KINDS``) and the game
reached that board.
"""
from __future__ import annotations

from engine.ai_compelled_blocks import compelled_blocks
from engine.ai_declarations import choose_combat_blockers
from engine.combat_permissions import MUST_BLOCK_ATTACKERS_THIS_COMBAT
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick


def _board(set_pool, provokes) -> Game:
    """Seat 0 attacks with Goblin Grappler and Crypt Sliver; seat 1 holds
    Goblin Turncoat (2/1), marked by *provokes* (one entry per provoke, by
    attacker name), and a Grizzly Bears (2/2). The declare-blockers step."""
    lgn, lea = set_pool("LGN"), set_pool("LEA")
    game = Game(players=[PlayerState(name="Attacker"), PlayerState(name="Defender")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].battlefield = [
        _nosick(Permanent(card=lgn["Goblin Grappler"])),
        _nosick(Permanent(card=lgn["Crypt Sliver"])),
    ]
    game.players[1].battlefield = [
        _nosick(Permanent(card=lgn["Goblin Turncoat"])),
        _nosick(Permanent(card=lea["Grizzly Bears"])),
    ]
    game._sync_control()
    game._recompute_continuous_effects()
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok, why
    by_name = {p.card.name: p for p in game.players[0].battlefield}
    game.players[1].battlefield[0].metadata[MUST_BLOCK_ATTACKERS_THIS_COMBAT] = [
        by_name[name].permanent_id for name in provokes
    ]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    return game


def test_the_turncoat_is_planned_onto_the_attacker_holding_two_of_its_requirements(set_pool):
    game = _board(set_pool, ["Goblin Grappler", "Crypt Sliver", "Crypt Sliver"])
    assert compelled_blocks(game, 1) == {0: 1}


def test_one_requirement_each_keeps_the_first(set_pool):
    """A tie is planned where it always was: the first requirement."""
    game = _board(set_pool, ["Goblin Grappler", "Crypt Sliver"])
    assert compelled_blocks(game, 1) == {0: 0}


def test_the_declaration_puts_one_blocker_on_each_attacker(set_pool):
    """The whole declaration, as the engine will take it: the Turncoat on
    the Crypt Sliver (two requirements obeyed, the most any declaration can),
    and the Bears on the Grappler — not beside the Turncoat on a 1/1 it
    kills alone."""
    game = _board(set_pool, ["Goblin Grappler", "Crypt Sliver", "Crypt Sliver"])
    blocks = choose_combat_blockers(game, 1)
    assert blocks.get(0) == 1, blocks
    assert blocks.get(1) != 1, blocks
    ok, why = game.declare_blockers(1, dict(blocks))
    assert ok, why
