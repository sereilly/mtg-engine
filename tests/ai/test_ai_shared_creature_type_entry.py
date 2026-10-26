"""The AI activates Cryptic Gateway when, and only when, the creatures its cost
will tap admit a card in hand.

"Tap two untapped creatures you control: You may put a creature card from your
hand that shares a creature type with each creature tapped this way onto the
battlefield." The policy's floor (``ai_abilities._hand_entry_has_a_card``) asks
the engine's own candidate list, and that list's narrowing names what the cost
taps — which no card can answer until it is resolved against those creatures.
Unresolved, the matcher refuses every card, so the seat never once activated
the Gateway; resolved against every creature, it would activate it for a hand
the tapped pair admits nothing from.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.models import Permanent


def _proposal(set_pool, hand):
    pool = {**set_pool("UDS"), **set_pool("LEG"), **set_pool("ONS")}
    me = PlayerState(name="Me", hand=[pool[n] for n in hand], library=[pool["Forest"]] * 8)
    opp = PlayerState(name="Opp", library=[pool["Island"]] * 8)
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    # An Elf Wizard and a Human Warrior — the 2022-12-08 ruling's own pair.
    for name in ("Cryptic Gateway", "Ivy Seer", "Barktooth Warbeard"):
        perm = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
    game.stack.clear()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("main1", "main")
    return choose_activation_action(game, 0)


def test_the_gateway_is_activated_for_a_card_sharing_a_type_with_each_tapped_creature(set_pool):
    action = _proposal(set_pool, ("Elvish Warrior", "Glory Seeker"))
    assert action is not None and action.permanent_name == "Cryptic Gateway"


def test_the_gateway_is_not_activated_when_no_card_shares_with_both(set_pool):
    """The Elf Druid shares only with the Elf Wizard and the Human Soldier only
    with the Human Warrior: the cost would be paid for nothing."""
    assert _proposal(set_pool, ("Wirewood Elf", "Glory Seeker")) is None
