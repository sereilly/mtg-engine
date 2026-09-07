"""Stronghold wave 2, group 2: the CR sections behind Reins of Power.

Three rules about a control change that moves a whole *set* rather than one
named permanent, each of which is about the mechanism rather than the printing
— which is the line SET_PLAYBOOK.md draws between `tests/sets/` and here. A
second card that swaps two boards is covered by construction.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.control import base_controller, control_changes
from engine.game_types import OracleExecutionContext
from engine.handlers.registry import EFFECT_HANDLERS
from engine.models import CardDefinition, Permanent
from engine.oracle_types import CONTROL_EXCHANGED_PERMANENTS, OracleInstruction

_ARN = {c.name: c for c in load_cards(manifest_set_path("ARN"))}


def _creature(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    )


def _artifact(name: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _swap(game: Game, card: CardDefinition, described: dict) -> OracleExecutionContext:
    """Resolve one mutual control change and hand back its context, so a test
    can read the record the sentence behind it would."""
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=card,
        source_permanent=None,
    )
    handler = EFFECT_HANDLERS["exchange_control_of_sets_until_eot"]
    instruction = OracleInstruction(
        "exchange_control_of_sets_until_eot", "",
        {"filter": described, "other_seat": "that_player"},
    )
    assert handler(game, instruction, context)[0]
    return context


@pytest.mark.cr("611.2c")
def test_611_2c_both_sets_are_fixed_before_either_board_moves():
    """"…the set of objects it affects is determined when that continuous
    effect begins. After that point, the set won't change."

    Two sets and one effect is where the rule bites. Read in sequence — gather
    yours, hand them over, then gather theirs — the second gather finds the
    creatures the first step just gave away and hands them straight back, so a
    two-step reading resolves, logs two control changes and leaves the board
    exactly as it found it. Both sets are read here before any contribution is
    recorded, which is what makes the swap a swap.

    The assertion is that **every** creature crossed: a board where nothing
    moved and a board where everything moved twice are the same board, and only
    counting the crossings tells them apart.
    """
    mine = [Permanent(card=_creature("Mine A")), Permanent(card=_creature("Mine B"))]
    theirs = [Permanent(card=_creature("Yours A"))]
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.interactive_seats = set()

    _swap(game, _creature("The Spell"), {"type_filter": "creature"})

    assert [game.controller_index_of(perm) for perm in mine] == [1, 1]
    assert game.controller_index_of(theirs[0]) == 0


@pytest.mark.cr("613.1b", "611.2a")
def test_613_1b_each_side_is_a_contribution_that_leaves_its_base_controller_alone():
    """Layer 2 is applied to a value it starts from, and that value is the seat
    the permanent entered under — never rewritten by a control change.

    A swap of two sets is 2N contributions under **one** source, which is what
    lets the cleanup sweep end all of them together without knowing they came
    from one sentence (CR 611.2a's stated duration). Each is stamped
    ``until_eot``; each permanent keeps its own base. So the reversion is the
    *absence* of a contribution rather than a second move — nothing has to
    remember a previous controller and nothing can get it wrong.
    """
    mine = [Permanent(card=_creature("Mine A"))]
    theirs = [Permanent(card=_creature("Yours A"))]
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.interactive_seats = set()
    spell = _creature("The Spell")

    _swap(game, spell, {"type_filter": "creature"})

    for permanent, entered in ((mine[0], 0), (theirs[0], 1)):
        recorded = control_changes(permanent)
        assert len(recorded) == 1
        assert recorded[0]["source"] is spell
        assert recorded[0]["until_eot"] is True
        assert base_controller(permanent) == entered

    game.resolve_cleanup_step(0)

    assert control_changes(mine[0]) == []
    assert game.controller_index_of(mine[0]) == 0
    assert game.controller_index_of(theirs[0]) == 1


@pytest.mark.cr("614.17", "701.12a")
def test_614_17_a_permanent_that_cant_change_controllers_stays_and_the_rest_move():
    """"Some effects state that something can't happen."

    Two ordinary control-changing effects happening at once is not CR 701.12a's
    exchange, and this is where the difference is observable: an exchange that
    cannot complete one half does *no part* of itself, while a permanent here
    that can't change controllers simply stays where it is and everything else
    still crosses.

    Guardian Beast is the prohibition the pool has ("other players can't gain
    control of them"), and asking it is the seam's job rather than each
    handler's — a list of the handlers that move control is the fire-site list
    this codebase keeps finding incomplete.

    The record behind the swap is checked too: a permanent that did not move is
    not one "those permanents" names, so a sentence after this one must not
    reach it.
    """
    beast = Permanent(card=_ARN["Guardian Beast"])
    beast.tapped = False
    protected = Permanent(card=_artifact("Protected Relic"))
    theirs = Permanent(card=_artifact("Their Relic"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[beast, protected]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.interactive_seats = set()

    context = _swap(game, _creature("The Spell"), {"type_filter": "artifact"})

    assert game.controller_index_of(protected) == 0
    assert game.controller_index_of(theirs) == 0
    assert context.results[CONTROL_EXCHANGED_PERMANENTS] == [theirs.permanent_id]
