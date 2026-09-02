"""Tests for Magic: The Gathering Comprehensive Rules 608.2h, 611.2c and 601.2c.

Covers:
  608.2h — an effect that needs information from an object no longer in the
           public zone it was expected to be in uses that object's **last known
           information**. Here: the toughness of a creature the sentence in
           front of this one exiled.
  613.1  — a card in a hidden zone has no computed characteristics at all,
           which is *why* 608.2h has to be the reading rather than a
           convenience.
  611.2c — the set of objects a resolving effect's continuous effect applies to
           is fixed when that effect begins. Here: which creatures a shield is
           armed on, and which creatures a one-shot debuff reaches.
  601.2c — a spell or ability with a variable number of targets fixes that
           number when it is announced, and the same instance of "target"
           cannot be answered twice.

Written against the three seams this round touched — the scratchpad record a
step writes for the sentence behind it (``lowering/_records.py``'s ``_PRODUCES``
and its readers), the directional shield collection, and the several-targets
description — rather than against one card, so a fourth card printing any of
these sentences is covered by construction. The per-card behaviour lives in
tests/sets/test_all_*.py.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.game_types import OracleExecutionContext
from engine.models import CardDefinition, Permanent
from engine.oracle_types import OracleInstruction
from engine.prevention import COMBAT_SHIELD_BOTH, _COMBAT_SHIELD_DIRECTION_KEY
from tests.helpers import _damage_dealt


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="{1}{G}",
        cmc=2.0,
        type_line="Creature — Test",
        oracle_text="",
        colors=("G",),
        color_identity=("G",),
        keywords=(),
        produced_mana=(),
        raw={},
        power=str(power),
        toughness=str(toughness),
    )


def _duel() -> Game:
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    return game


def _shield_directions(perm: Permanent) -> list[str]:
    """The directions *perm*'s two-way combat shields answer to. A marker rather
    than a ``Shield``: the record is a list of ``[direction, combat_only,
    lifetime]`` entries the interceptors read, which is why it is not in
    ``shields_on``."""
    return [
        entry[0] for entry in (perm.metadata.get(_COMBAT_SHIELD_DIRECTION_KEY) or ())
    ]


def _run(game: Game, instruction: OracleInstruction, context) -> None:
    from engine.handlers import EFFECT_HANDLERS

    EFFECT_HANDLERS[instruction.kind](game, instruction, context)


def _context(game: Game, card: CardDefinition, **kwargs):
    kwargs.setdefault("target", game.players[1])
    return OracleExecutionContext(card=card, caster=game.players[0], **kwargs)


@pytest.mark.cr("608.2h", "613.1")
def test_an_exile_freezes_the_toughness_the_sentence_behind_it_reads():
    """The exile records the victim's toughness before the removal, because by
    the next step the card is in exile and CR 613.1 gives it no computed
    characteristics at all. The *effective* toughness, not the printed one."""
    game = _duel()
    victim = Permanent(card=_creature("Victim", toughness=2))
    game._put_permanent_onto_battlefield(1, victim, None)
    victim.toughness_bonus = 3
    context = _context(
        game, _creature("Spell"), target=game.players[1],
        target_permanent_index=game.battlefield_index_of(victim),
        target_permanent_id=victim.permanent_id,
    )

    _run(
        game,
        OracleInstruction("exile_target_permanent", "", {"type_filter": "creature"}),
        context,
    )

    assert context.results["its_toughness"] == 5
    assert not game.is_on_battlefield(victim), "the object it describes has gone"


@pytest.mark.cr("608.2h")
def test_the_frozen_toughness_is_what_the_life_gain_spends():
    """The two steps compose through the scratchpad rather than through a fused
    kind, which is the whole point of recording it: any "you gain life equal to
    its toughness" behind any producer reads the same key."""
    game = _duel()
    victim = Permanent(card=_creature("Victim", toughness=4))
    game._put_permanent_onto_battlefield(1, victim, None)
    context = _context(
        game, _creature("Spell"), target=game.players[1],
        target_permanent_index=game.battlefield_index_of(victim),
        target_permanent_id=victim.permanent_id,
    )

    _run(
        game,
        OracleInstruction("exile_target_permanent", "", {"type_filter": "creature"}),
        context,
    )
    _run(
        game,
        OracleInstruction(
            "target_gains_life", "",
            {"amount_from": "its_toughness", "recipient": "caster"},
        ),
        context,
    )

    assert game.players[0].life == 24


@pytest.mark.cr("608.2h")
def test_a_gain_with_no_producer_in_front_of_it_gains_nothing():
    """An absent record is a legal zero, never a printed number read off a card
    — which is why the lowering refuses the words outright when no step of the
    same effect records one, rather than leaving this to the handler."""
    game = _duel()
    context = _context(game, _creature("Spell"))

    _run(
        game,
        OracleInstruction(
            "target_gains_life", "",
            {"amount_from": "its_toughness", "recipient": "caster"},
        ),
        context,
    )

    assert game.players[0].life == 20


@pytest.mark.cr("611.2c", "615.1")
def test_a_shield_armed_on_a_recorded_set_reaches_exactly_that_set():
    """A directional shield over "those creatures" is armed once per permanent
    the earlier step recorded, and the set does not grow: a creature that joins
    the board afterwards is not one of them (CR 611.2c)."""
    game = _duel()
    first = Permanent(card=_creature("First"))
    second = Permanent(card=_creature("Second"))
    for perm in (first, second):
        game._put_permanent_onto_battlefield(0, perm, None)
    context = _context(game, _creature("Spell"))
    context.results["untapped_permanents"] = (
        first.permanent_id, second.permanent_id,
    )

    _run(
        game,
        OracleInstruction(
            "prevent_damage_to_target_until_eot", "",
            {
                "combat_only": True,
                "to_and_by": True,
                "permanents_from": "untapped_permanents",
            },
        ),
        context,
    )

    latecomer = Permanent(card=_creature("Latecomer"))
    game._put_permanent_onto_battlefield(0, latecomer, None)
    outsider = Permanent(card=_creature("Outsider"))
    game._put_permanent_onto_battlefield(1, outsider, None)

    assert _damage_dealt(game, first, 3, source=outsider, combat=True) == 0
    assert _damage_dealt(game, second, 3, source=outsider, combat=True) == 0
    assert _damage_dealt(game, outsider, 3, source=first, combat=True) == 0, (
        "the shield reads both ends of the event"
    )
    assert _damage_dealt(game, latecomer, 3, source=outsider, combat=True) == 3, (
        "a creature that joined after the effect began is not in its set"
    )
    assert _shield_directions(first) == [COMBAT_SHIELD_BOTH]
    assert _shield_directions(second) == [COMBAT_SHIELD_BOTH]
    assert _shield_directions(latecomer) == []


@pytest.mark.cr("611.2c")
def test_a_recorded_set_that_lost_a_member_shields_the_rest():
    """A permanent that has left is a different object if it comes back
    (CR 400.7), so it is simply not shielded — and the rest of the recorded set
    still is. An empty record is a legal outcome, not an error: the spell may
    have named no targets at all."""
    game = _duel()
    survivor = Permanent(card=_creature("Survivor"))
    game._put_permanent_onto_battlefield(0, survivor, None)
    context = _context(game, _creature("Spell"))
    context.results["untapped_permanents"] = (survivor.permanent_id, 9999)

    _run(
        game,
        OracleInstruction(
            "prevent_damage_to_target_until_eot", "",
            {
                "combat_only": True,
                "to_and_by": True,
                "permanents_from": "untapped_permanents",
            },
        ),
        context,
    )

    attacker = Permanent(card=_creature("Attacker"))
    game._put_permanent_onto_battlefield(1, attacker, None)
    assert _damage_dealt(game, survivor, 2, source=attacker, combat=True) == 0


@pytest.mark.cr("611.2c")
def test_a_global_debuff_that_excludes_a_type_leaves_that_type_alone():
    """"Nonartifact creatures get -1/-1" fixes its set at resolution and the
    exclusion is part of what the set *is* — a printed narrowing the sweep
    dropped would be a strictly wider effect than the card."""
    game = _duel()
    flesh = Permanent(card=_creature("Flesh"))
    metal_card = CardDefinition(
        name="Metal", mana_cost="{3}", cmc=3.0,
        type_line="Artifact Creature — Construct", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw={},
        power="2", toughness="2",
    )
    metal = Permanent(card=metal_card)
    for perm in (flesh, metal):
        game._put_permanent_onto_battlefield(1, perm, None)

    _run(
        game,
        OracleInstruction(
            "buff_creatures_global", "",
            {"power": -1, "toughness": -1, "exclude_types": ["artifact"], "all": True},
        ),
        _context(game, _creature("Spell")),
    )

    assert (flesh.effective_power, flesh.effective_toughness) == (1, 1)
    assert (metal.effective_power, metal.effective_toughness) == (2, 2)


@pytest.mark.cr("601.2c")
def test_a_variable_target_count_taps_only_what_was_announced():
    """"Tap X target lands" collects a list at announcement and the handler
    resolves that list; a permanent nobody named is not tapped, and the count
    does not change once announced."""
    game = _duel()
    lands = []
    for index in range(3):
        land = Permanent(card=CardDefinition(
            name=f"Land {index}", mana_cost="", cmc=0.0, type_line="Land",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=("G",), raw={},
        ))
        game._put_permanent_onto_battlefield(1, land, None)
        lands.append(land)
    context = _context(
        game, _creature("Dam"), target=game.players[1],
        target_permanent_id=[lands[0].permanent_id, lands[2].permanent_id],
        x_value=2,
    )

    _run(
        game,
        OracleInstruction(
            "tap_target_permanent", "",
            {
                "type_filter": "land",
                "targets": {
                    "quantifier": "exactly", "kind": "object",
                    "filter": {"type_filter": "land"}, "count": "x",
                },
            },
        ),
        context,
    )

    assert [land.tapped for land in lands] == [True, False, True]
