"""The AI takes a CR 116.2d special action when the attack it buys is worth
the price (``engine/ai_special_actions.py``).

Volrath's Curse and Lost in Thought ("Enchanted creature can't attack or
block, and its activated abilities can't be activated. <Its controller> may
<pay> for that player to ignore this effect until end of turn.") make their
host's controller an offer every main phase. No AI path took it, so a cursed
creature never attacked again in a simulated game. The chooser rehearses the
action through the turn's fight against the table with nothing taken, and adds
what no standing sees (cards out of a graveyard) to the price.

Each pair below drives the decision both ways on one board shape: an attack
worth more than the price is bought, one worth less is not — and the price,
when paid, is paid with what the seat misses least, never with the creature
being freed.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState
from engine.ai_combat import run_ai_combat_phase
from engine.ai_simulator import run_ai_simulation
from engine.ai_special_actions import choose_special_action, special_action_before_combat
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_IGNORE = "ignore_attached_static_until_eot"


def _card(set_pool, name):
    for code in ("JUD", "TMP", "LEA", "ODY"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)


def _put(game, set_pool, seat, name):
    permanent = Permanent(card=_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _cursed(set_pool, aura, host, *, lands=2, graveyard=(), opponent=()):
    """Seat 1 enchants seat 0's *host* with *aura* on its own turn; then it is
    seat 0's precombat main phase, with *lands* Forests of its own, *graveyard*
    in its graveyard and *opponent*'s creatures across the table."""
    forest = _card(set_pool, "Forest")
    game = Game(players=[
        PlayerState("A", library=[forest] * 20),
        PlayerState("B", library=[forest] * 20, hand=[_card(set_pool, aura)]),
    ])
    game.enforce_mana_costs = False
    creature = _put(game, set_pool, 0, host)
    for _ in range(lands):
        _put(game, set_pool, 0, "Forest")
    for name in opponent:
        _put(game, set_pool, 1, name)
    game.players[0].graveyard.extend(_card(set_pool, name) for name in graveyard)
    game.start_turn(1)
    cast = game.cast_from_hand(1, aura, target_permanent_ids=[creature.permanent_id])
    assert cast.supported, cast.details
    resolve_stack(game)
    assert not game.can_attack(creature, 1)
    game.start_turn(0)
    return game, creature


def test_lost_in_thought_is_ignored_for_an_attack_worth_three_cards(set_pool):
    """A 6/4 held home by Lost in Thought, nothing to block it, four lands in
    the graveyard: three of them buy six damage, and the Wurm attacks."""
    game, wurm = _cursed(
        set_pool, "Lost in Thought", "Craw Wurm", graveyard=["Forest"] * 4,
    )
    # The simulator's main phase records nobody holding priority (each cast
    # there settles its own window); the active seat holds it all the same
    # (CR 117.3a), so the window is opened to ask in and put back after.
    game.clear_priority_window()
    taken = special_action_before_combat(game, 0)
    assert taken is not None
    choice, refusal = taken
    assert refusal is None and choice.kind == _IGNORE and choice.sacrificed_id is None
    assert choice.worth > 0
    assert game.priority_player_index is None
    assert [card.name for card in game.players[0].graveyard] == ["Forest"]
    assert [card.name for card in game.players[0].exile] == ["Forest"] * 3
    assert "A ignores Lost in Thought's effect until end of turn (CR 116.2d)" in game.log
    run_ai_combat_phase(game, 0)
    assert game.players[1].life == 14


def test_lost_in_thought_is_not_ignored_when_the_cards_are_worth_more(set_pool):
    """The same bargain over a 1/1 and a graveyard of three flashback spells:
    the three cards are spells the seat still holds (CR 702.34a) and one
    damage does not buy them. Nothing is exiled and nothing attacks."""
    game, _elves = _cursed(
        set_pool, "Lost in Thought", "Llanowar Elves", graveyard=["Firebolt"] * 3,
    )
    assert special_action_before_combat(game, 0) is None
    assert len(game.players[0].graveyard) == 3 and game.players[0].exile == []
    run_ai_combat_phase(game, 0)
    assert game.players[1].life == 20


def test_volraths_curse_is_paid_with_a_spare_land_not_the_creature(set_pool):
    """Eight Forests and a 6/4 under Volrath's Curse: a land beyond the six a
    seat needs is the price its standing feels least, so a Forest goes —
    never the Wurm the action is taken for."""
    game, wurm = _cursed(set_pool, "Volrath's Curse", "Craw Wurm", lands=8)
    taken = special_action_before_combat(game, 0)
    assert taken is not None and taken[1] is None
    assert taken[0].sacrificed_id != wurm.permanent_id
    assert "A sacrificed Forest (Volrath's Curse, CR 116.2d)" in game.log
    assert Counter(p.card.name for p in game.controlled_by(0)) == Counter(
        {"Craw Wurm": 1, "Forest": 7}
    )
    run_ai_combat_phase(game, 0)
    assert game.players[1].life == 14


def test_volraths_curse_is_not_paid_for_an_attack_a_blocker_stops(set_pool):
    """Two Forests, a 1/1 under the Curse and a Wall across the table: a land
    the seat needs is not given up for an attack that deals nothing."""
    game, _elves = _cursed(
        set_pool, "Volrath's Curse", "Llanowar Elves", opponent=["Wall of Stone"],
    )
    assert special_action_before_combat(game, 0) is None
    assert Counter(p.card.name for p in game.controlled_by(0)) == Counter(
        {"Llanowar Elves": 1, "Forest": 2}
    )


def test_the_offer_is_not_weighed_with_no_combat_ahead(set_pool):
    """The good a CR 116.2d offer buys that the rehearsal can see is an
    attack, so the chooser is asked only with the seat's combat still to come
    — never in its postcombat main phase, where a bought turn is a price paid
    for nothing."""
    game, _wurm = _cursed(
        set_pool, "Lost in Thought", "Craw Wurm", graveyard=["Forest"] * 4,
    )
    game.start_priority_window(0)
    game.turn_phases_remaining = [
        phase for phase in game.turn_phases_remaining if phase != "combat"
    ]
    assert choose_special_action(game, 0) is None
    assert len(game.players[0].graveyard) == 4


@pytest.mark.full
@pytest.mark.parametrize("code, aura, seed", [
    # Seed 12 until ONS W2G5: its first game diverges at G1 T2, where Hapless
    # Researcher is no longer sacrificed to loot (the self-sacrifice rehearsal
    # gate), and the run never reaches the offer. Seed 3 took it until the AI
    # began to take mulligans (kg2), which changed its games; seed 7 takes it
    # twice (4, 5 and 6 never do).
    ("JUD", "Lost in Thought", 7),
    # TMP seed 6 until kg4, when the AI's activations moved (a permanent's
    # later abilities weighed, every ability held to the "moves nothing"
    # rehearsal) and its two games stopped reaching the offer; 7 never does,
    # 8 takes it once.
    ("TMP", "Volrath's Curse", 8),
])
def test_a_seeded_run_takes_the_offer(code, aura, seed):
    """A seeded run with the Aura pinned into both decks: a seat bought its
    creature a turn at least once (a floor of one — that the decision was
    reached, not how often it is made), counted in the report and logged, and
    nothing it took was refused."""
    report = run_ai_simulation(
        manifest_set_path(code, include_measured=True), games=2, seed=seed,
        max_turns=12, required_cards=[aura],
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert report.special_actions_taken[_IGNORE] >= 1, (
        "the run never took the offer; pick another seed"
    )
    assert not report.refused_special_actions, report.refused_special_actions
    assert any(
        f"special action {_IGNORE} ({aura}) -> taken" in line
        for line in report.log_lines
    )
