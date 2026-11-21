"""Bushido (CR 702.45), the keyword and the triggered ability it is.

"Bushido N" means "Whenever this creature blocks or becomes blocked, it gets
+N/+N until end of turn." (CR 702.45a.) "If a creature has multiple instances
of bushido, each triggers separately." (CR 702.45b.) One test per clause,
each on an invented card so the rule is what is asked, not a printing:

* both halves of the trigger, and nothing when the creature is unblocked;
* "until end of turn" — gone in the cleanup step (CR 514.2);
* the trigger uses the stack and can be responded to (CR 603.3): the creature
  removed in response, the trigger resolves to nothing;
* CR 702.45b on one keyword line, through a grant (the line-derived channel,
  ``keywords.LINE_DERIVED_KEYWORDS``), and as a person orders two
  distinguishable instances (CR 603.3b);
* a creature that loses all abilities has no bushido to trigger (CR 613.1f);
* Kenzo the Hardhearted's spelling, "Double strike; bushido 2".

The card-by-card tests are in ``tests/sets/test_chk_creatures.py`` (W1G2).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.bushido import bushido_points
from engine.keywords import grant_ability_line, remove_all_abilities
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_creature_card, drive_combat, settle

_REMINDER = "(Whenever this creature blocks or becomes blocked, it gets +{n}/+{n} until end of turn.)"


def _samurai(name: str, power: int, toughness: int, text: str) -> CardDefinition:
    return _mk_creature_card(name, power, toughness, oracle_text=text)


def _bushido(name: str, power: int, toughness: int, n: int) -> CardDefinition:
    return _samurai(name, power, toughness, f"Bushido {n} {_REMINDER.format(n=n)}")


def _table(*, interactive=()):
    filler = _mk_creature_card("Filler", 1, 1)
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[filler] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _put(game, card, seat) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    settle(game)
    return permanent


def _fight(game, attacker, blocker):
    """Seat 0's *attacker* attacks; seat 1's *blocker* (or nobody) blocks.
    Leaves the declare blockers step with its triggers on the stack."""
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=1
    )
    assert ok, why
    settle(game)
    game.advance_combat_phase()
    blocks = {} if blocker is None else {
        game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)
    }
    ok, why = game.declare_blockers(1, blocks)
    assert ok, why


def _pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


@pytest.mark.cr("702.45a")
def test_bushido_triggers_when_the_creature_blocks():
    """The blocking half: a 1/1 with bushido 2 blocks and is a 3/3."""
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, _bushido("Blocking Samurai", 1, 1, 2), 1)
    _fight(game, attacker, samurai)
    assert [item.ability_text for item in game.stack] == ["bushido 2"]
    assert "Blocking Samurai triggered on block (added to stack)" in game.log
    settle(game)
    assert _pt(samurai) == (3, 3)
    drive_combat(game)
    assert game.is_on_battlefield(samurai) is False  # 3 damage on a 3/3
    assert not game.is_on_battlefield(attacker)


@pytest.mark.cr("702.45a")
def test_bushido_triggers_when_the_creature_becomes_blocked():
    """The other half: the attacker is blocked, and its bushido 1 makes a
    2/2 a 3/3 that survives a 2/2 blocker and kills it."""
    game = _table()
    samurai = _put(game, _bushido("Attacking Samurai", 2, 2, 1), 0)
    blocker = _put(game, _mk_creature_card("Bear", 2, 2), 1)
    _fight(game, samurai, blocker)
    assert "Attacking Samurai triggered on becoming blocked (added to stack)" in game.log
    settle(game)
    assert _pt(samurai) == (3, 3)
    drive_combat(game)
    assert game.is_on_battlefield(samurai)
    assert not game.is_on_battlefield(blocker)


@pytest.mark.cr("702.45a", "509.1h")
def test_an_unblocked_bushido_creature_does_not_trigger():
    """Nothing blocks it, so neither half happens: no trigger, printed
    damage."""
    game = _table()
    samurai = _put(game, _bushido("Lonely Samurai", 2, 2, 3), 0)
    _fight(game, samurai, None)
    assert not game.stack
    drive_combat(game)
    assert game.players[1].life == 18


@pytest.mark.cr("702.45a", "514.2")
def test_the_bushido_bonus_ends_in_the_cleanup_step():
    """"…until end of turn": the +N/+N is gone once the turn's cleanup step
    ends the effect."""
    game = _table()
    attacker = _put(game, _mk_creature_card("Wall", 0, 5), 0)
    samurai = _put(game, _bushido("Tired Samurai", 1, 1, 2), 1)
    _fight(game, attacker, samurai)
    settle(game)
    assert _pt(samurai) == (3, 3)
    drive_combat(game)
    assert _pt(samurai) == (3, 3)
    assert game.resolve_cleanup_step(0)
    assert _pt(samurai) == (1, 1)


@pytest.mark.cr("702.45a", "603.3", "400.7")
def test_the_bushido_trigger_can_be_responded_to():
    """The trigger goes on the stack (CR 603.3), so a player may act before
    it resolves: the samurai removed in response, the ability resolves and
    pumps nothing (CR 400.7: the card in the graveyard is a new object)."""
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, _bushido("Doomed Samurai", 1, 1, 2), 1)
    _fight(game, attacker, samurai)
    assert len(game.stack) == 1
    game.remove_from_battlefield(samurai)
    game._permanent_to_graveyard(game.players[1], samurai)
    settle(game)
    assert not game.stack
    assert [c.name for c in game.players[1].graveyard] == ["Doomed Samurai"]
    assert not any("Doomed Samurai gets +2/+2" in line for line in game.log)
    assert "Doomed Samurai: it is no longer on the battlefield" in game.log


@pytest.mark.cr("702.45b")
def test_two_instances_on_one_keyword_line_trigger_separately():
    """"Bushido 1, bushido 2" is two abilities: two objects on the stack,
    and a 1/1 that blocks is a 4/4 once both resolve."""
    card = _samurai("Twice Samurai", 1, 1, "Bushido 1, bushido 2")
    assert len(compile_card_oracle(card).triggered_abilities) == 2
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, card, 1)
    assert bushido_points(samurai.effective_card) == 3
    _fight(game, attacker, samurai)
    assert sorted(item.ability_text for item in game.stack) == ["bushido 1", "bushido 2"]
    settle(game)
    assert _pt(samurai) == (4, 4)


@pytest.mark.cr("702.45b", "613.1f")
def test_a_granted_instance_triggers_beside_the_printed_one():
    """A grant of bushido grants the line (CR 613.1f, the line-derived
    channel): the creature then has two instances, and two triggers."""
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, _bushido("Trained Samurai", 1, 1, 1), 1)
    grant_ability_line(samurai, "Bushido 1")
    assert samurai.has_keyword("bushido")
    assert bushido_points(samurai.effective_card) == 2
    _fight(game, attacker, samurai)
    assert [item.ability_text for item in game.stack] == ["bushido 1", "bushido 1"]
    settle(game)
    assert _pt(samurai) == (3, 3)


@pytest.mark.cr("702.45b", "603.3b")
def test_a_person_orders_two_distinguishable_bushido_triggers():
    """Bushido 2 printed and bushido 1 granted are two different abilities,
    so a person controlling both is asked to order them (CR 603.3b); both
    resolve whichever order is named."""
    game = _table(interactive=(1,))
    attacker = _put(game, _mk_creature_card("Ogre", 5, 5), 0)
    samurai = _put(game, _bushido("Ordered Samurai", 1, 1, 2), 1)
    grant_ability_line(samurai, "Bushido 1")
    _fight(game, attacker, samurai)
    owed = settle(game, defaults=False)
    assert owed is not None and owed.kind == "order_triggers", owed
    assert game.resolve_pending_choice("order_triggers", 1, order=[1, 0])
    settle(game)
    assert _pt(samurai) == (4, 4)


@pytest.mark.cr("702.45a", "613.1f")
def test_a_creature_that_lost_its_abilities_has_no_bushido():
    """CR 613.1f takes the printed line away, so there is nothing to
    trigger: blocked while it has lost all abilities, the 2/2 stays a 2/2."""
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, _bushido("Humbled Samurai", 2, 2, 2), 1)
    remove_all_abilities(samurai, duration="end_of_turn")
    assert not samurai.has_keyword("bushido")
    assert bushido_points(samurai.effective_card) == 0
    _fight(game, attacker, samurai)
    assert not game.stack
    settle(game)
    assert _pt(samurai) == (2, 2)


@pytest.mark.cr("702.45a")
def test_kenzos_semicolon_spelling_is_one_double_strike_and_one_bushido():
    """"Double strike; bushido 2" (Kenzo the Hardhearted's face): the
    semicolon joins two keywords on one line, so the creature has double
    strike and one bushido 2 trigger."""
    card = _samurai(
        "Semicolon Samurai", 3, 4,
        f"Double strike; bushido 2 {_REMINDER.format(n=2)}",
    )
    program = compile_card_oracle(card)
    assert program.supported
    assert [t.source_line for t in program.triggered_abilities] == ["bushido 2"]
    game = _table()
    attacker = _put(game, _mk_creature_card("Ogre", 3, 3), 0)
    samurai = _put(game, card, 1)
    assert samurai.has_keyword("double strike") and samurai.has_keyword("bushido")
    _fight(game, attacker, samurai)
    settle(game)
    assert _pt(samurai) == (5, 6)
