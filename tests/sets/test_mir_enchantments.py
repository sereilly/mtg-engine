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
