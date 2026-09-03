"""Per-card tests for Mirage's enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.
"""

from __future__ import annotations


# --- Round 1: flanking (CR 702.25) ---

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _r1_bear() -> CardDefinition:
    return CardDefinition(
        name="Bear", mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Bear", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _r1_enchanted(set_pool, aura_name: str):
    aura = Permanent(card=set_pool("MIR")[aura_name])
    host = Permanent(card=_r1_bear())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[host, aura]),
        PlayerState(name="P2", battlefield=[]),
    ])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    return game, aura, host


def test_agility_grants_both_halves_of_flanking(set_pool):
    """"Enchanted creature gets +1/+1 and has flanking."

    The card that made flanking's two channels a requirement rather than a
    detail. A keyword grant is normally one word into CR 613 layer 6, and every
    reader of "does it have flying?" looks there — but CR 702.25a *defines*
    flanking as a triggered ability the compiler builds out of a printed line,
    so the word alone would make this bear count as a flanker for the *next*
    flanker's filter while giving it no ability at all. The grant is therefore a
    grant of the line, and the word comes back because layer 6 seeds itself from
    the compiled keyword lines.
    """
    game, _aura, host = _r1_enchanted(set_pool, "Agility")

    assert (host.effective_power, host.effective_toughness) == (3, 3)
    assert game._has_keyword(host, "flanking")
    kinds = [
        trig.instruction.kind
        for trig in compile_card_oracle(host.effective_card).triggered_abilities
        if trig.instruction is not None
    ]
    assert kinds == ["pump_block_pair"]


def test_agility_takes_the_ability_back_when_it_leaves(set_pool):
    """CR 611.3b: removal is the absence of a contribution. The granted line is
    derived from the attachment on every read, so detaching restores the printed
    card with nothing to undo."""
    game, aura, host = _r1_enchanted(set_pool, "Agility")

    detach_aura(aura, host)
    game._recompute_continuous_effects()

    assert (host.effective_power, host.effective_toughness) == (2, 2)
    assert not game._has_keyword(host, "flanking")
    assert compile_card_oracle(host.effective_card).triggered_abilities == ()


# --- Round 3: the flash-Aura cycle (CR 113.6b / 514.1) ---

import pytest

from engine.cast_timing import CAST_AT_INSTANT_SPEED, casts_at_instant_speed

_R3_CYCLE = [
    "Armor of Thorns", "Grave Servitude", "Lightning Reflexes", "Soar",
    "Ward of Lights",
]


def _r3_board(set_pool, aura_name: str):
    """The Aura in hand on seat 0, with a creature of its own to enchant."""
    pool = set_pool("MIR")
    host = Permanent(card=pool["Femeref Knight"])
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[host], hand=[pool[aura_name]],
            library=[pool["Island"]] * 8,
        ),
        PlayerState(name="P2", library=[pool["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game, host


@pytest.mark.parametrize("name", _R3_CYCLE)
def test_the_cycle_casts_at_instant_speed(set_pool, name):
    """"You may cast this spell as though it had flash."

    All five, because the sentence is identical on all five and this is the
    largest single production in the set — the only place Mirage's refusal
    census had more than one card behind one printed line.
    """
    assert casts_at_instant_speed(set_pool("MIR")[name])


def test_an_aura_cast_at_sorcery_speed_stays(set_pool):
    """The rider reads CR 601.3d's timing, so casting it when a sorcery *could*
    have been cast marks nothing and the Aura is a permanent like any other."""
    game, host = _r3_board(set_pool, "Soar")

    result = game.cast_from_hand(
        0, "Soar", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    aura = next(p for p in game.players[0].battlefield if p.card.name == "Soar")
    assert not aura.metadata.get(CAST_AT_INSTANT_SPEED)
    assert (host.effective_power, host.effective_toughness) == (2, 3)

    game.resolve_cleanup_step(0)
    assert any(p.card.name == "Soar" for p in game.players[0].battlefield)


def test_an_aura_flashed_in_is_sacrificed_at_the_next_cleanup(set_pool):
    """"…the controller of the permanent it becomes sacrifices it at the
    beginning of the next cleanup step."

    The half that had to be built with the permission rather than after it: a
    permission granted without its penalty is a strictly better card than the
    one printed, which is the silent wrongness the whole-line claim rule exists
    to stop. The answer is frozen as the spell is announced — by the cleanup
    step the stack is empty and the step has moved on, so nothing on the board
    could be asked the question then.
    """
    game, host = _r3_board(set_pool, "Soar")
    game._close_current_priority_step()
    game.advance_combat_phase()
    assert game.current_turn_phase == "combat"

    result = game.cast_from_hand(
        0, "Soar", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    aura = next(p for p in game.players[0].battlefield if p.card.name == "Soar")
    assert aura.metadata.get(CAST_AT_INSTANT_SPEED) is True
    assert (host.effective_power, host.effective_toughness) == (2, 3)

    game.resolve_cleanup_step(0)

    assert not any(p.card.name == "Soar" for p in game.players[0].battlefield)
    assert (host.effective_power, host.effective_toughness) == (2, 2)
