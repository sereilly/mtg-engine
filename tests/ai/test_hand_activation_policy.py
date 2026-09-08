"""An AI seat activates an ability from its **hand** (CR 113.6j).

The policy had one activation loop and it walked the battlefield, so a seat
holding a card whose ability functions only in a hand did nothing with it —
forever. That was one shipped card (Waker of Waves) and it is 34 in Urza's Saga,
where cycling is a third of the set: a seat that never cycles is a seat doing
nothing with a third of what it is dealt, which is the "refused cast" shape
without even the refusal to notice it by.

``choose_hand_activation_action`` is the second pass, and it is deliberately a
separate action from ``ActivationAction``: the engine reaches a hand through a
separate entry point that takes no permanent, no target and no summoning
sickness, and a nullable permanent threaded through the existing action would
have made every reader of it ask a question about nothing.

The policy names no card and no keyword — which abilities are hand-activatable
is ``usable_activated_abilities(program, zone=HAND)``, the same reader the
engine gates on — so the fixtures here are invented cards.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.ai_policy import (choose_activation_action,
                              choose_hand_activation_action)
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent, PlayerState


def _cycler(name: str = "Cycler") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{U}", cmc=2.0, type_line="Instant",
        oracle_text=(
            "Destroy target creature.\n"
            "Cycling {2} ({2}, Discard this card: Draw a card.)"
        ),
        colors=(), color_identity=(), keywords=("Cycling",), produced_mana=(),
        raw={"name": name, "type_line": "Instant"},
    )


def _forest() -> CardDefinition:
    return CardDefinition(
        name="Forest", mana_cost="", cmc=0.0, type_line="Basic Land — Forest",
        oracle_text="({T}: Add {G}.)", colors=(), color_identity=(),
        keywords=(), produced_mana=("G",),
        raw={"name": "Forest", "type_line": "Basic Land — Forest"},
    )


def _seat_with(card: CardDefinition, *, lands: int, library: int = 10):
    forest = _forest()
    player = PlayerState(name="AI", hand=[card], library=[forest] * library)
    game = Game(players=[player, PlayerState(name="Opp")])
    # On, because what is being tested is that the policy plans a payment it can
    # actually make: with costs off there is nothing to plan and the "cannot
    # pay" case below could not exist.
    game.enforce_mana_costs = True
    for _ in range(lands):
        permanent = Permanent(card=forest)
        player.battlefield.append(permanent)
    game._settle()
    return game, player


def test_the_policy_proposes_cycling_when_the_mana_is_there():
    game, player = _seat_with(_cycler(), lands=2)

    action = choose_hand_activation_action(game, 0)

    assert action is not None
    assert action.card_name == "Cycler"
    assert action.ability_index == 0
    assert player.hand[action.hand_index].name == "Cycler"
    assert len(action.land_tap_indices) == 2


def test_the_policy_proposes_nothing_when_the_lands_cannot_pay():
    """CR 601.2h asked before the action is offered, not after it is refused:
    a proposal the engine declines is a seat re-proposing it every turn."""
    game, _player = _seat_with(_cycler(), lands=1)

    assert choose_hand_activation_action(game, 0) is None


def test_a_card_with_no_hand_ability_is_not_proposed():
    bear = CardDefinition(
        name="Bear", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
        oracle_text="{T}: Draw a card.", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": "Bear", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    game, _player = _seat_with(bear, lands=4)

    assert choose_hand_activation_action(game, 0) is None


def test_the_battlefield_loop_does_not_offer_a_hand_only_ability():
    """The other half, and the one that was a live defect: a cycling creature in
    play has a compiled, supported activated ability, and the policy used to
    pick it off ``program.activated_abilities`` and hand it to the engine —
    which ran it, drawing a card and discarding nothing."""
    creature = CardDefinition(
        name="Cycling Bear", mana_cost="{1}{U}", cmc=2.0,
        type_line="Creature — Bear",
        oracle_text="Cycling {2} ({2}, Discard this card: Draw a card.)",
        colors=(), color_identity=(), keywords=("Cycling",), produced_mana=(),
        raw={"name": "Cycling Bear", "type_line": "Creature — Bear",
             "power": "2", "toughness": "2"},
    )
    game, player = _seat_with(creature, lands=4)
    player.hand.clear()
    permanent = Permanent(card=creature)
    permanent.metadata["summoning_sickness_turn"] = -99
    player.battlefield.append(permanent)
    game._settle()

    assert choose_activation_action(game, 0) is None


def test_the_policy_will_not_deck_the_seat_it_is_playing():
    """``_score_activation``'s CR 704.5b floor reaches this pass too, because
    the score is the same function: an empty library makes the draw worth
    -100 and the action is not proposed."""
    game, player = _seat_with(_cycler(), lands=2, library=0)

    assert choose_hand_activation_action(game, 0) is None


@pytest.mark.slow
def test_an_ai_seat_actually_cycles_a_card_in_a_real_game():
    """The Rock Hydra test for the policy: a whole game, over the set that
    prints the keyword, with a cycling card pinned into both decks."""
    report = run_ai_simulation(
        cards_path=manifest_set_path("USG", include_measured=True),
        games=2,
        seed=909,
        max_turns=12,
        required_cards=["Polluted Mire", "Rejuvenate"],
    )

    assert report.games_completed == 2
    # Urza's Saga is still `measured`, so the deck holds cards other groups have
    # not landed yet and the run reports them. What this test owns is that
    # nothing *leaked*: a cycled card leaves a hand and reaches a graveyard, and
    # the zone census is what would notice it doing neither.
    leaks = [issue for issue in report.issues
             if "Zone conservation" in issue.message]
    assert leaks == [], leaks
    cycled = [line for line in report.log_lines if "from hand" in line]
    assert cycled, "no seat activated an ability from its hand in two games"
