"""CR 509.2a / 509.3g: "Whenever this creature attacks and isn't blocked"
triggers as the declaration of blockers completes, and is on the stack before
the active player receives priority in the declare blockers step.

CR 509.3g: the ability "triggers if no creatures are declared as blockers for
that creature". CR 509.2a: "Any abilities that triggered on blockers being
declared or that triggered during the process described in rule 509.1 are put
onto the stack before the active player gets priority; the order in which they
triggered doesn't matter."

The engine fired it from the declare-blockers step's *leaving* pass, after the
step's priority had been given (``declare_blockers`` ends with
``start_priority_window``): at a table with a person both players passed an
empty stack and the step's window then resolved the trigger with nobody asked
(CR 117.4); where the blocks locked with no declaration (a defender with no
legal block) the same call locked them, fired it and resolved it. Every board
below is driven through the engine's own entry points with both seats
interactive, and each test fails on the tree before the fix.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}
_FILLER = _mk_creature_card("Filler", 1, 1)
_BEAR = _mk_creature_card("Plain Bear", 2, 2)
_WALL = _mk_creature_card("Plain Wall", 0, 5)


def _table(seats: int = 2, *, interactive: bool = True) -> Game:
    players = [PlayerState(name=chr(ord("A") + seat)) for seat in range(seats)]
    for player in players:
        player.library = [_FILLER] * 10
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = set(range(seats))
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    for _ in range(4):
        if game.current_step == "declare_attackers":
            return
        game.advance_combat_phase()
    raise AssertionError(game.log[-8:])


def _attack(game: Game, attackers, target: int = 1) -> None:
    """Declare *attackers* at *target* and enter the declare blockers step."""
    _to_declare_attackers(game)
    slots = [game.battlefield_index_of(attacker) for attacker in attackers]
    assert game.declare_attackers(0, slots, defending_player_index=target)[0]
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.log[-6:]


def _names(game: Game) -> list[str]:
    return [item.card.name for item in game.stack]


def _pass_round(game: Game) -> list[str]:
    """Every player passes once, in turn order from the priority holder."""
    results = []
    for _ in range(len(game.players)):
        results.append(game.pass_priority(game.priority_player_index))
    return results


@pytest.mark.cr("509.2a", "509.3g", "117.4")
@pytest.mark.parametrize("road", ["declares_no_blocks", "has_no_creature"])
def test_the_trigger_waits_on_the_stack_for_both_players_to_pass(road):
    """Murk Dwellers ("Whenever this creature attacks and isn't blocked, it
    gets +2/+0 until end of turn") attacks. The defender either declares no
    blocks with a Wall it could block with, or has no creature at all — the
    declaration nobody makes, which the step's advance locks. Either way the
    trigger is on the stack with the active player holding priority and the
    step not left, and it resolves only once both players have passed."""
    game = _table()
    dwellers = _put(game, 0, _CARDS["Murk Dwellers"])
    if road == "declares_no_blocks":
        _put(game, 1, _WALL)
    _attack(game, [dwellers])

    if road == "declares_no_blocks":
        assert game.declare_blockers(1, {})[0]
    else:
        game.advance_combat_phase()
        assert "B has no valid blockers" in game.log

    assert game.current_step == "declare_blockers", game.log[-6:]
    assert game.priority_player_index == 0
    assert _names(game) == ["Murk Dwellers"], game.log[-6:]
    assert dwellers.effective_power == 2

    assert game.pass_priority(0) == "passed"
    assert _names(game) == ["Murk Dwellers"] and dwellers.effective_power == 2
    assert game.pass_priority(1) == "resolved_top"
    assert dwellers.effective_power == 4

    for _ in range(6):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    assert game.players[1].life == 16, game.log[-10:]


@pytest.mark.cr("509.2a", "509.3g")
def test_at_a_table_nobody_sits_at_the_trigger_is_there_when_the_declaration_returns():
    """The same moment headless: ``declare_blockers`` gives the active player
    priority as it returns, and the trigger is already on the stack."""
    game = _table(interactive=False)
    dwellers = _put(game, 0, _CARDS["Murk Dwellers"])
    _put(game, 1, _WALL)
    _attack(game, [dwellers])

    assert game.declare_blockers(1, {})[0]

    assert _names(game) == ["Murk Dwellers"], game.log[-6:]
    assert game.priority_player_index == 0


@pytest.mark.cr("509.2a", "603.3b")
def test_the_unblocked_trigger_is_ordered_with_the_block_triggers():
    """Murk Dwellers and a plain Bear attack; the defender's Goblin Snowman
    ("Whenever this creature blocks, prevent all combat damage that would be
    dealt to and dealt by it this turn") blocks the Bear. Both triggers are
    set off by the one declaration, so they go on the stack together, active
    player first (CR 603.3b): the defender's on top, resolving first. Fired
    by the leaving pass, the Dwellers' landed above it."""
    game = _table()
    dwellers = _put(game, 0, _CARDS["Murk Dwellers"])
    bear = _put(game, 0, _BEAR)
    snowman = _put(game, 1, _CARDS["Goblin Snowman"])
    _attack(game, [dwellers, bear])

    assert game.declare_blockers(1, {
        game.battlefield_index_of(snowman): [game.battlefield_index_of(bear)],
    })[0]

    assert _names(game) == ["Murk Dwellers", "Goblin Snowman"], game.log[-6:]
    assert [item.caster_index for item in game.stack] == [0, 1]


@pytest.mark.cr("509.3g", "506.4")
def test_an_attacker_removed_from_combat_after_the_declaration_has_still_triggered():
    """Murk Dwellers attacks, nobody blocks it, and with its trigger on the
    stack its controller activates Reconnaissance ("{0}: Remove target
    attacking creature you control from combat and untap it") on it. The
    ability triggered when no blockers were declared for it (CR 509.3g), so
    it resolves and the Dwellers get +2/+0, though they deal no combat damage
    now. Fired as the step was left, it never triggered at all: the Dwellers
    were no longer attacking by then."""
    game = _table()
    dwellers = _put(game, 0, _CARDS["Murk Dwellers"])
    _put(game, 0, _CARDS["Reconnaissance"])
    _put(game, 1, _WALL)
    _attack(game, [dwellers])
    assert game.declare_blockers(1, {})[0]

    queued = game.queue_permanent_ability(
        0, "Reconnaissance", target_permanent_ids=[dwellers.permanent_id],
    )
    assert queued.supported, queued
    resolve_stack(game)

    assert not dwellers.attacking and not dwellers.tapped
    assert dwellers.effective_power == 4, game.log[-8:]
    for _ in range(6):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    assert game.players[1].life == 20


@pytest.mark.cr("509.2a", "603.7")
def test_a_delayed_attacks_and_isnt_blocked_trigger_is_on_the_stack_too():
    """Delif's Cone ("{T}, Sacrifice this artifact: This turn, when target
    creature you control attacks and isn't blocked, you may gain life equal
    to its power. …") is activated on the Bear in the main phase. The Bear
    attacks and nobody blocks it: the delayed ability is on the stack as the
    declaration returns, with the active player holding priority."""
    game = _table()
    bear = _put(game, 0, _BEAR)
    _put(game, 0, _CARDS["Delif's Cone"])
    _put(game, 1, _WALL)
    game.start_turn(0)
    queued = game.queue_permanent_ability(
        0, "Delif's Cone", target_permanent_ids=[bear.permanent_id],
    )
    assert queued.supported, queued
    resolve_stack(game)
    game._close_current_priority_step()
    for _ in range(4):
        if game.current_step == "declare_attackers":
            break
        game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(bear)])[0]
    resolve_stack(game)
    game.advance_combat_phase()

    assert game.declare_blockers(1, {})[0]

    assert _names(game) == ["Delif's Cone"], game.log[-6:]
    assert game.priority_player_index == 0


@pytest.mark.cr("509.2a", "802.4", "509.3g")
@pytest.mark.parametrize("last_defender", ["declares", "has_no_creature"])
def test_with_two_defenders_the_trigger_waits_for_the_last_declaration(last_defender):
    """Three players: Murk Dwellers attacks B and a Bear attacks C. Blocks are
    declared in APNAP order (CR 802.4), and "isn't blocked" is a question
    about the whole declaration, so the trigger is not on the stack while C
    has still to declare — and is once C has (or, with no creature, once
    the step's advance passes over C)."""
    game = _table(3)
    dwellers = _put(game, 0, _CARDS["Murk Dwellers"])
    bear = _put(game, 0, _BEAR)
    _put(game, 1, _WALL)
    if last_defender == "declares":
        _put(game, 2, _WALL)
    _to_declare_attackers(game)
    slots = {game.battlefield_index_of(dwellers): 1, game.battlefield_index_of(bear): 2}
    assert game.declare_attackers(0, list(slots), attacker_targets=slots)[0]
    resolve_stack(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"

    assert game.declare_blockers(1, {})[0]
    assert _names(game) == [], game.log[-6:]

    if last_defender == "declares":
        assert game.declare_blockers(2, {})[0]
    else:
        game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert _names(game) == ["Murk Dwellers"], game.log[-6:]
    assert game.priority_player_index == 0
