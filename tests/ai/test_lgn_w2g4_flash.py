"""The AI casts what it may cast at instant speed, not only instants.

``ai_policy.choose_combat_instant_cast_action`` skipped every card whose
``primary_type`` was not "instant" (W1G3's census: 42 shipped non-instant cards
castable at instant speed by their own text, and every creature under Quick
Sliver's or Vernal Equinox's permission, were only ever cast in their caster's
own main phase). Whether a card may be cast now is the engine's question
(``cast_timing.casts_at_instant_speed``); when a creature is worth casting at
instant speed is the policy's (``ai_policy._weighed_at_instant_speed_now``):
another seat's end step, or in response to a spell its entry trigger names.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.ai_policy import cast_chosen_instant, choose_combat_instant_cast_action
from engine.models import Permanent, PlayerState

from tests.helpers import resolve_stack


def _table(set_pool, hand, lands, *, active=1, mine=()):
    """The AI is seat 0 holding *hand*, with *lands* (and *mine*) on its
    battlefield; seat 1, the active player unless *active* says otherwise,
    has six Forests and a Craw Wurm in hand."""
    lea = set_pool("LEA")
    ai = PlayerState(name="AI", hand=list(hand), library=[lea["Island"]] * 10)
    opponent = PlayerState(name="Opp", hand=[lea["Craw Wurm"]], library=[lea["Forest"]] * 10)
    game = Game(players=[ai, opponent])
    game.enforce_mana_costs = True
    for card in (*[lea[name] for name in lands], *mine):
        ai.battlefield.append(Permanent(card=card))
    opponent.battlefield.extend(Permanent(card=lea["Forest"]) for _ in range(6))
    game.active_player_index = active
    return game


def _at(game, phase: str, step: str) -> None:
    game.current_turn_phase = phase
    game.current_phase = {"precombat_main": "main", "ending": "ending"}.get(phase, phase)
    game.current_step = step


def _cast(game, action):
    card, result = cast_chosen_instant(game, 0, action)
    assert result.supported, result.details
    resolve_stack(game)
    return card


def test_a_flash_creature_is_cast_in_the_opponents_end_step(set_pool):
    """Benalish Knight (Flash, first strike) held to the opponent's end step:
    cast there, it resolves onto the AI's battlefield."""
    game = _table(set_pool, [set_pool("WTH")["Benalish Knight"]], ["Plains"] * 3)
    _at(game, "ending", "end")
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Benalish Knight"
    _cast(game, action)
    assert "Benalish Knight" in [p.card.name for p in game.controlled_by(0)]
    assert game.players[0].hand == []


def test_a_flash_creature_is_held_through_the_rest_of_the_turn(set_pool):
    """Not in the opponent's main phase with nothing on the stack (the end
    step is still to come), and not in the AI's own turn — whose main phase
    casts it with the same mana."""
    knight = set_pool("WTH")["Benalish Knight"]
    game = _table(set_pool, [knight], ["Plains"] * 3)
    _at(game, "precombat_main", "main")
    assert choose_combat_instant_cast_action(game, 0) is None
    own = _table(set_pool, [knight], ["Plains"] * 3, active=0)
    _at(own, "ending", "end")
    assert choose_combat_instant_cast_action(own, 0) is None


def test_mystic_snake_counters_a_spell_in_response(set_pool):
    """"When this creature enters, counter target spell." The one creature
    worth casting in response: cast as the opponent's Craw Wurm is on the
    stack, its trigger counters the Wurm."""
    game = _table(
        set_pool, [set_pool("APC")["Mystic Snake"]], ["Island", "Island", "Forest", "Forest"],
    )
    _at(game, "precombat_main", "main")
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, "Craw Wurm").supported
    game.enforce_mana_costs = True
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Mystic Snake"
    _cast(game, action)
    assert "Mystic Snake" in [p.card.name for p in game.controlled_by(0)]
    assert [c.name for c in game.players[1].graveyard] == ["Craw Wurm"]
    assert not any(p.card.name == "Craw Wurm" for p in game.controlled_by(1))


def test_a_flash_creature_without_a_counter_is_not_cast_in_response(set_pool):
    """Benalish Knight's arrival is not about the stack: held for the end step
    rather than spent in response to the opponent's spell."""
    game = _table(set_pool, [set_pool("WTH")["Benalish Knight"]], ["Plains"] * 3)
    _at(game, "precombat_main", "main")
    game.enforce_mana_costs = False
    assert game.queue_from_hand(1, "Craw Wurm").supported
    game.enforce_mana_costs = True
    assert choose_combat_instant_cast_action(game, 0) is None


def test_quick_slivers_permission_reaches_the_ai(set_pool):
    """"Any player may cast Sliver spells as though they had flash." With
    Quick Sliver on the AI's battlefield, a Plated Sliver (no flash of its
    own) is cast in the opponent's end step; without it, it waits."""
    lgn = set_pool("LGN")
    game = _table(
        set_pool, [lgn["Plated Sliver"]], ["Plains"] * 2, mine=[lgn["Quick Sliver"]],
    )
    _at(game, "ending", "end")
    action = choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Plated Sliver"
    _cast(game, action)
    assert "Plated Sliver" in [p.card.name for p in game.controlled_by(0)]

    without = _table(set_pool, [lgn["Plated Sliver"]], ["Plains"] * 2)
    _at(without, "ending", "end")
    assert choose_combat_instant_cast_action(without, 0) is None


def test_mystic_snake_is_held_in_its_own_main_phase(set_pool):
    """Cast in its controller's main phase the trigger has nothing to counter
    and the card is a 2/2 for four: the main-phase chooser leaves it for the
    opponent's turn (``ai_policy._held_for_a_spell_to_answer``) — and there,
    with no spell cast, the end step takes it as the creature it is."""
    from engine.ai_policy import choose_cast_action

    snake = set_pool("APC")["Mystic Snake"]
    own = _table(set_pool, [snake], ["Island", "Island", "Forest", "Forest"], active=0)
    _at(own, "precombat_main", "main")
    assert choose_cast_action(own, 0) is None

    theirs = _table(set_pool, [snake], ["Island", "Island", "Forest", "Forest"])
    _at(theirs, "ending", "end")
    action = choose_combat_instant_cast_action(theirs, 0)
    assert action is not None and action.card_name == "Mystic Snake"
    _cast(theirs, action)
    assert "Mystic Snake" in [p.card.name for p in theirs.controlled_by(0)]


@pytest.mark.full
def test_a_simulated_seat_flashes_mystic_snake_in_response():
    """The whole turn, seeded: with Mystic Snake pinned into both APC decks,
    a seat holds it through its own main phase and casts it in response to
    another seat's spell, through the executor the honesty counts read
    (``casts_in_response``). A floor of one: that it happened, not how often
    a seed's story makes it happen."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_paths

    (apc,) = [p for p in manifest_set_paths() if p.stem.upper().startswith("APC")]
    report = run_ai_simulation(apc, games=2, seed=1, required_cards=["Mystic Snake"])
    flashed = [
        line for line in report.log_lines
        if " cast Mystic Snake -> " in line and "[in response to " in line
    ]
    assert flashed, "no seat cast Mystic Snake in response"
    assert report.casts_in_response >= 1
    assert not any("Mystic Snake" in key for key in report.refused_instant_casts)
    assert not report.issues, [issue.message for issue in report.issues]
