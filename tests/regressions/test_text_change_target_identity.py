"""A text change rewrites the permanent that was named, not the first one.

"Change the text of target spell or permanent by replacing all instances of
one color word with another." (Sleight of Mind.) ``mark_text_modified`` read
its target as a **slot** — ``context.target_permanent_index`` — and, handed
none, took ``battlefield[0]``. An announcement made by ``permanent_id`` alone
names no slot (CR 400.7: the id is the identity, and it is how a headless
caller names a target at all), so the handler rewrote whatever stood first on
that battlefield: aimed at a Darkest Hour beside a Grizzly Bears, the log read
"Sleight of Mind changed B text to W on Grizzly Bears" and the Hour went on
saying black.

Found while driving the layer-3 half of the colour census
(``tests/rules/test_color_effects_timestamp_order.py``), which casts a Sleight
at a static that is not the first permanent on its board. The recolour handler
beside this one was moved onto ``resolve_target_permanent`` rounds ago for the
same reason; this one was left on the slot.

The census is every pool card that compiles the instruction — six — each
announced by id at the **second** of two permanents.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.oracle_types import OracleInstruction

KIND = "mark_text_modified"


def _instructions(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, OracleInstruction):
        yield value
        yield from _instructions(value.payload, seen)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _instructions(item, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _instructions(item, seen)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _instructions(getattr(value, field.name), seen)


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


def _text_changers(pool):
    return sorted(
        card.name for card, program in compiled_units(pool.values())
        if any(step.kind == KIND for step in _instructions(program))
    )


#: The six, pinned so a seventh has to be driven here.
TEXT_CHANGERS = (
    "Balduvian Shaman", "Crystal Spray", "Magical Hack", "Mind Bend",
    "Sleight of Mind", "Whim of Volrath",
)


def test_the_text_changers_are_the_ones_driven_here(pool):
    assert tuple(_text_changers(pool)) == TEXT_CHANGERS
    assert len(pool) >= 4700


def _settle(game):
    for _ in range(40):
        if game.stack:
            game.resolve_top_of_stack()
        for choice in list(game.pending_choices):
            game.auto_resolve_pending_choices(choice.player_index, kinds=[choice.kind])
        if not game.stack and not game.pending_choices:
            return
    raise AssertionError([choice.kind for choice in game.pending_choices])


@pytest.mark.parametrize("name", TEXT_CHANGERS)
def test_a_text_change_announced_by_id_rewrites_the_permanent_it_named(pool, name):
    """Two permanents on one battlefield, the *second* named by id: it is the
    one whose text is changed, and the first is left alone."""
    game = Game(players=[PlayerState(name="A", life=20), PlayerState(name="B", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    first = Permanent(card=pool["Grizzly Bears"])
    # A white enchantment its controller controls, with no cumulative upkeep
    # and a colour word and a land word nowhere in it — every one of the six
    # may legally name it (Balduvian Shaman's is the narrowest phrase).
    named = Permanent(card=pool["Castle"])
    for perm in (first, named):
        game._put_permanent_onto_battlefield(0, perm, None)

    card = pool[name]
    if card.primary_type in ("instant", "sorcery"):
        game.players[0].hand.append(card)
        done = game.queue_from_hand(
            0, name, target_permanent_ids=[named.permanent_id],
            old_color="W", new_color="B",
        )
    else:
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
        source.metadata["summoning_sickness_turn"] = -99
        index = next(
            index for index, ability in enumerate(
                compile_card_oracle(card).activated_abilities
            )
            if ability.instruction is not None
            and any(step.kind == KIND for step in _instructions(ability.instruction))
        )
        done = game.queue_permanent_ability(
            0, name, ability_index=index,
            target_permanent_ids=[named.permanent_id],
            old_color="W", mana_color="B",
        )
    assert done.supported, done.details
    _settle(game)

    assert named.metadata.get("text_modified") is True, game.log[-4:]
    assert not first.metadata.get("text_modified"), (
        f"{name} was aimed at {named.card.name} and rewrote {first.card.name}"
    )
