"""CR 603.4's intervening-'if', at **both** of the moments the rule names.

"When/Whenever/At [trigger event], if [condition], [effect]" is asked twice:
once "when the trigger event occurs" — "the ability triggers only if it is
[true]; otherwise it does nothing" — and again as it resolves, where a
now-false condition removes it from the stack.

Only the second half existed, which made the outcome right for the wrong
reason. A false condition produced an ability that went on the stack, sat
there, and then took itself back off. The board ends the same, and the game
does not: the object can be countered, every player has to pass priority on it,
and anything watching for an ability being put onto the stack sees one that
never triggered.

102 supported cards compile the key. The check now lives at ``_stack_push`` —
*the* one place an object goes on the stack — rather than at a fire site, which
is why the halves disagreed in the first place: five fire sites had each grown
their own copy of it and the rest had none.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import _mk_creature_card, _nosick, resolve_stack


def _w3g5_attack_with(attacker_card, defender_cards=()):
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    defenders = []
    for card in defender_cards:
        perm = Permanent(card=card)
        game._put_permanent_onto_battlefield(1, perm, None)
        defenders.append(perm)
    resolve_stack(game)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    return game, attacker, defenders


@pytest.mark.cr("603.4")
def test_a_true_condition_still_triggers(set_pool):
    """Spectral Bears: "Whenever this creature attacks, **if defending player
    controls no black nontoken permanents**, it doesn't untap during your next
    untap step."

    The condition holds — the defender's board is empty — so the ability
    triggers, goes on the stack and resolves. Nothing about the working case
    changes.
    """
    game, bears, _ = _w3g5_attack_with(set_pool("HML")["Spectral Bears"])

    assert game.stack, "CR 603.4: a true condition triggers"
    resolve_stack(game)
    assert bears.metadata.get("skip_next_untap") or any(
        "untap" in line.lower() for line in game.log
    )


@pytest.mark.cr("603.4")
def test_a_false_condition_never_reaches_the_stack(set_pool):
    """The same card with a black creature on the other side. The ability "does
    nothing" — and CR 603.4 means it never triggered, not that it triggered and
    fizzled.

    Before the fire-time half existed the stack held one object here, which
    every player then had to pass priority on and any counter-an-ability effect
    could have answered.
    """
    from dataclasses import replace

    zombie = replace(_mk_creature_card("Zombie", 2, 2), colors=("B",))
    game, _bears, _ = _w3g5_attack_with(set_pool("HML")["Spectral Bears"], [zombie])

    assert game.stack == [], "CR 603.4: it does not trigger at all"
    assert any("didn't trigger" in line for line in game.log)


@pytest.mark.cr("603.4", "509.1")
def test_the_blocker_fire_site_asks_the_same_question(set_pool):
    """Wall of Caltrops: "Whenever this creature blocks a creature, **if at
    least one other Wall creature is blocking that creature and no non-Wall
    creatures are blocking that creature**, this creature gains banding…"

    A second fire site, so this is the evidence that the check is at the seam
    rather than copied per site: with the Wall blocking alone the condition is
    false and no ability is announced.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    attacker = Permanent(card=_mk_creature_card("Bear", 2, 2))
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    wall = Permanent(card=set_pool("LEG")["Wall of Caltrops"])
    game._put_permanent_onto_battlefield(1, wall, None)
    resolve_stack(game)

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    assert game.stack == []
    assert any("didn't trigger" in line for line in game.log)


@pytest.mark.cr("603.4")
def test_the_log_does_not_claim_a_refused_trigger_went_on_the_stack(set_pool):
    """The fire sites log "…triggered on attack (added to stack)" *after*
    pushing, so the refusal had to reach them: a record that says an ability
    was added to the stack immediately under one saying it never triggered is a
    record contradicting itself.
    """
    from dataclasses import replace

    zombie = replace(_mk_creature_card("Zombie", 2, 2), colors=("B",))
    game, _bears, _ = _w3g5_attack_with(set_pool("HML")["Spectral Bears"], [zombie])

    assert not any("added to stack" in line for line in game.log)
