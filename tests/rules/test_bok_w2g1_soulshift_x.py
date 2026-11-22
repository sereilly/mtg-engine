"""Soulshift X with a where-clause — CR 702.46a, counted as it triggers.

"Kodama of the Center Tree has soulshift X, where X is the number of Spirits
you control." ``engine/soulshift.py`` rewrites a card's self-grant of the
keyword to CR 702.46a's sentence with X for N and the clause kept; the X
bounds the trigger's target, so it is counted as the ability triggers
(CR 603.3d: the target is chosen as it is put on the stack) and, for a
leaves-the-battlefield trigger, off the board immediately before the event
(CR 603.10a) — ``engine/frozen_trigger_x.py``. These tests hold the rewrite,
the lowering's admission and refusals, and the look-back on a sweep and on a
sacrifice, with invented cards; Kodama's own tests are in
``tests/sets/test_bok_creatures_later_groups.py`` (W2G1's section).
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.oracle_types import X_COUNTED_AT_TRIGGER, X_FROM_COUNT
from engine.soulshift import SOULSHIFT_RULES_TEXT, expand_soulshift_x_line

from tests.helpers import settle

_KODAMA_LINE = (
    "Kodama of the Center Tree has soulshift X, where X is the number of "
    "Spirits you control. (When this creature dies, you may return target "
    "Spirit card with mana value X or less from your graveyard to your hand.)"
)


def _card(name: str, cost: int, type_line: str, text: str = "",
          power: str = "2", toughness: str = "2") -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power=power, toughness=toughness)
    return CardDefinition(
        name=name, mana_cost="{%d}" % cost if cost else "", cmc=float(cost),
        type_line=type_line, oracle_text=text, colors=(), color_identity=(),
        keywords=(), produced_mana=(), raw=raw,
    )


def _shifter(count_phrase: str = "the number of Spirits you control") -> CardDefinition:
    return _card(
        "Counted Shifter", 4, "Creature — Spirit",
        f"This creature has soulshift X, where X is {count_phrase}.",
    )


def _spirit(name: str, cost: int) -> CardDefinition:
    return _card(name, cost, "Creature — Spirit")


def _table(graveyard=(), interactive=()):
    filler = _card("Filler", 0, "Creature — Test", power="1", toughness="1")
    game = Game(players=[
        PlayerState(name="P0", graveyard=list(graveyard), library=[filler] * 10),
        PlayerState(name="P1", library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _put(game, card, seat=0) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _offered(game):
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "trigger_target", prompt
    return sorted(target["name"] for target in prompt.data["targets"])


@pytest.mark.cr("702.46a")
def test_the_self_grant_is_the_rules_sentence_with_its_clause():
    """The rule's sentence with X for N and the where-clause kept; another
    card's name, or a line that is not the self-grant, is not rewritten."""
    sentence = expand_soulshift_x_line(_KODAMA_LINE, "Kodama of the Center Tree")
    assert sentence == (
        SOULSHIFT_RULES_TEXT.format(count="X")[:-1]
        + ", where X is the number of Spirits you control."
    )
    assert expand_soulshift_x_line(_KODAMA_LINE, "Some Other Card") is None
    assert expand_soulshift_x_line("Soulshift 3", "Kodama of the Center Tree") is None
    assert expand_soulshift_x_line(
        "This creature has soulshift X, where X is the number of Spirits you control.",
        None,
    ) is not None


@pytest.mark.cr("702.46a", "603.3d")
def test_the_count_is_marked_to_be_taken_as_the_ability_triggers():
    """The where-clause bounds the target, so its count carries the flag
    that freezes it as the ability triggers — a pump's where-clause (which
    bounds nothing) keeps being counted as it resolves."""
    program = compile_card_oracle(_shifter())
    assert program.supported, program
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "dies"
    spec = trigger.instruction.payload[X_FROM_COUNT]
    assert spec.get(X_COUNTED_AT_TRIGGER) is True
    pump = _card(
        "Counted Pump", 2, "Creature — Test",
        "Whenever this creature blocks, it gets +X/+X until end of turn, "
        "where X is the number of Spirits you control.",
    )
    (pump_trigger,) = compile_card_oracle(pump).triggered_abilities
    assert X_COUNTED_AT_TRIGGER not in pump_trigger.instruction.payload[X_FROM_COUNT]


@pytest.mark.cr("603.10a")
@pytest.mark.parametrize("count_phrase", [
    "the number of cards in your hand",
    "the number of Spirit cards in your graveyard",
    "the number of Spirits target opponent controls",
])
def test_a_count_the_look_back_cannot_take_refuses_the_line(count_phrase):
    """Only a count of permanents a seat the controller names holds is
    taken off the board the death left; a hand, a graveyard (which the death
    has already changed) or a target's board refuses the line rather than
    freeze a number the card does not print."""
    program = compile_card_oracle(_shifter(count_phrase))
    assert not program.supported, program


@pytest.mark.cr("603.10a", "603.3d")
def test_a_sweep_counts_every_spirit_it_took(set_pool):
    """Destroyed beside two Spirits by one sweep: each was there immediately
    before (CR 603.10a), so X is 3 — the 3-cost Spirit card is offered and
    the 4-cost one is not."""
    wrath = set_pool("LEA")["Wrath of God"]
    game = _table(
        graveyard=[_spirit("Three Spirit", 3), _spirit("Four Spirit", 4)],
        interactive=(0,),
    )
    game.players[0].hand.append(wrath)
    for card in (_shifter(), _spirit("Spirit A", 5), _spirit("Spirit B", 5)):
        _put(game, card)
    assert game.queue_from_hand(0, "Wrath of God").supported
    assert _offered(game) == ["Three Spirit"]
    assert [item.x_value for item in game.stack] == [3]


@pytest.mark.cr("603.10a", "117.2a")
def test_a_sacrifice_takes_it_off_first_and_it_still_counts_itself(set_pool):
    """Sacrificed as a spell's cost, the creature leaves the battlefield
    before its trigger is put on the stack (held until the cast is
    announced, CR 117.2a), and still counts itself: alone, X is 1."""
    sacrifice = set_pool("LEA")["Sacrifice"]
    game = _table(
        graveyard=[_spirit("One Spirit", 1), _spirit("Two Spirit", 2)],
        interactive=(0,),
    )
    game.players[0].hand.append(sacrifice)
    shifter = _put(game, _shifter())
    assert game.queue_from_hand(
        0, "Sacrifice", cost_permanent_ids=[shifter.permanent_id],
    ).supported
    assert _offered(game) == ["One Spirit"]
