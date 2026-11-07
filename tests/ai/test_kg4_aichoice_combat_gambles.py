"""An AI seat weighs what its creature's own attack or block trigger gambles.

Goblin Psychopath: "Whenever this creature attacks or blocks, flip a coin. If
you lose the flip, the next time it would deal combat damage this turn, it
deals that damage to you instead." The AI declared it as the 5/5 it is — into
an empty board at even life, where half the time the five are its own (kg4).
``ai_combat_triggers.combat_gamble`` reads the gamble off the compiled
program; ``ai_declarations`` declares a gambler only where what the attack or
the block buys pays for it.
"""
from __future__ import annotations

from collections import Counter

import pytest

from engine import Game, PlayerState, load_cards
from engine.ai_combat import declare_ai_blockers, run_ai_combat_phase
from engine.ai_combat_triggers import (ATTACK_CONDITIONS, BLOCK_CONDITIONS,
                                       combat_gamble)
from engine.ai_declarations import choose_attackers, choose_combat_blockers
from engine.ai_rehearsal import rehearsing
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_catalog, manifest_set_path, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_CARDS = {card.name: card for card in load_catalog()}

#: The kinds of a trigger step that leave the outcome to a coin (CR 705).
_COIN_KINDS = frozenset({
    "flip_coin", "coin_flip_remove_attacker_and_tap", "coin_flip_remove_blocker",
})
#: The kinds that harm the trigger's own controller or its source.
_SELF_HARM_KINDS = frozenset({
    "redirect_source_damage_to_you_until_eot", "give_control_of_source_to_player",
    "sacrifice_self", "destroy_self", "put_source_card_on_library_top",
})


def _steps(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _steps(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _steps(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _steps(item)


def test_every_coin_flip_an_attack_or_block_trigger_makes_is_priced():
    """The pool, both manifest roles: every supported card with a trigger that
    fires as it attacks or blocks and leaves something to a coin flip has a
    gamble the declarations weigh (its damage may not arrive, or it costs its
    controller); and every one whose source is certainly lost (a one-shot) is
    marked so, not silently unpriced."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    flipped: dict[str, list] = {}
    one_shots: list[str] = []
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        for blocking, conditions in ((False, ATTACK_CONDITIONS), (True, BLOCK_CONDITIONS)):
            for trigger in program.triggered_abilities:
                if trigger.condition.kind not in conditions or trigger.instruction is None:
                    continue
                kinds = {step.kind for step in _steps(trigger.instruction)}
                if not kinds & (_COIN_KINDS | _SELF_HARM_KINDS):
                    continue
                if any(step.kind == "may" for step in _steps(trigger.instruction)):
                    continue  # a toll, answered at resolution
                permanent = Permanent(card=unit)
                game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
                game._put_permanent_onto_battlefield(0, permanent, None)
                gamble = combat_gamble(game, permanent, blocking=blocking)
                if kinds & _COIN_KINDS:
                    assert gamble.delivered < 1.0 or gamble.costs, (unit.name, blocking, gamble)
                    flipped.setdefault(unit.name, []).append(blocking)
                else:
                    assert gamble.spent or gamble.costs, (unit.name, blocking, gamble)
                    if gamble.spent:
                        one_shots.append(unit.name)
    # A floor on what was examined.
    assert {"Goblin Psychopath", "Mijae Djinn", "Ydwen Efreet", "Fickle Efreet"} <= set(flipped), flipped
    assert flipped["Goblin Psychopath"] == [False, True]
    assert {"Fog Elemental", "Time Elemental"} <= set(one_shots), one_shots


def _permanent(name):
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _combat(mine, theirs, *, my_life=20, their_life=20, active=0):
    """A two-seat table in *active*'s declare-attackers step."""
    me = PlayerState(name="AI", life=my_life, library=[_CARDS["Mountain"]] * 10)
    them = PlayerState(name="Them", life=their_life, library=[_CARDS["Mountain"]] * 10)
    game = Game(players=[me, them])
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, _permanent(name), None)
    game.start_turn(active)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.current_step == "declare_attackers"
    return game, me, them


def test_goblin_psychopath_stays_home_at_even_life():
    """Half the time five to the opponent, half the time five to itself:
    worth nothing at twenty life each, so the combat is fought with nobody."""
    game, me, them = _combat(["Goblin Psychopath"], [])
    log = len(game.log)

    run_ai_combat_phase(game, 0)
    resolve_stack(game)

    assert not any("Goblin Psychopath triggered on attack" in line for line in game.log[log:])
    assert (me.life, them.life) == (20, 20)


@pytest.mark.parametrize("my_life, their_life, attacks", [
    (20, 5, True),     # the flip it wins is the game
    (20, 10, True),    # five is worth more at ten than at twenty
    (5, 20, False),    # the flip it loses is the game
])
def test_goblin_psychopath_attacks_where_the_flip_pays(my_life, their_life, attacks):
    game, me, them = _combat(["Goblin Psychopath"], [], my_life=my_life, their_life=their_life)
    log = len(game.log)

    run_ai_combat_phase(game, 0)
    resolve_stack(game)

    fired = any("Goblin Psychopath triggered on attack" in line for line in game.log[log:])
    assert fired is attacks
    if attacks:
        # One of the two outcomes, and nothing else.
        assert (me.life, them.life) in {(my_life, their_life - 5), (my_life - 5, their_life)}
    else:
        assert (me.life, them.life) == (my_life, their_life)


def test_time_elemental_does_not_attack_into_its_own_five_damage():
    """"When this creature attacks or blocks, at end of combat, sacrifice it
    and it deals 5 damage to you." A 0/2 on an empty opposing board attacked
    for nothing and paid both."""
    game, me, them = _combat(["Time Elemental"], [])

    assert choose_attackers(game, 0) == []
    run_ai_combat_phase(game, 0)
    resolve_stack(game)

    assert (me.life, them.life) == (20, 20)
    assert any(p.card.name == "Time Elemental" for p in game.controlled_by(me))


def _blocks_against_bears(my_life):
    game, me, them = _combat(["Goblin Psychopath"], ["Grizzly Bears"], my_life=my_life, active=1)
    bears = next(p for p in game.controlled_by(them) if p.card.name == "Grizzly Bears")
    ok, why = game.declare_attackers(
        1, [game.battlefield_index_of(bears)], defending_player_index=0,
    )
    assert ok, why
    resolve_stack(game)
    game.advance_combat_phase()  # declare blockers
    assert game.current_step == "declare_blockers"
    return game, me, them


@pytest.mark.parametrize("my_life, blocks", [(20, True), (5, False)])
def test_goblin_psychopath_blocks_where_the_flip_pays(my_life, blocks):
    """At twenty life the Psychopath blocks Grizzly Bears: it kills them when
    the flip is won and costs five when it is lost. At five life the lost
    flip is the game, and two from the Bears is not: it stays out of it."""
    game, me, _them = _blocks_against_bears(my_life)

    assert bool(choose_combat_blockers(game, 0)) is blocks
    assert declare_ai_blockers(game, 0)
    resolve_stack(game)
    while game.current_turn_phase == "combat":
        step = game.current_step
        game.advance_combat_phase()
        resolve_stack(game)
        if game.current_step == step:
            break

    if not blocks:
        assert me.life == my_life - 2
    else:
        assert me.life in {my_life, my_life - 5}


@pytest.mark.full
def test_a_seeded_scourge_game_weighs_goblin_psychopaths_flip(monkeypatch):
    """Goblin Psychopath pinned into every Scourge deck: in the seeded games
    the attack weighing both kept it home and sent it at least once each —
    asked of the real declarations, never of a rehearsal's copies."""
    import engine.ai_declarations as declarations

    asked: Counter = Counter()
    weigh = declarations.attack_is_worth_its_trigger

    def spy(game, attacker, defender):
        answer = weigh(game, attacker, defender)
        if not rehearsing() and attacker.card.name == "Goblin Psychopath":
            asked[answer] += 1
        return answer

    monkeypatch.setattr(declarations, "attack_is_worth_its_trigger", spy)
    report = run_ai_simulation(
        manifest_set_path("SCG"), games=3, seed=1337,
        required_cards=["Goblin Psychopath", "Goblin Psychopath"],
    )
    assert report.games_completed == 3
    assert asked[True] >= 1 and asked[False] >= 1, asked
    assert any("Goblin Psychopath" in line and "coin flip" in line for line in report.log_lines)
