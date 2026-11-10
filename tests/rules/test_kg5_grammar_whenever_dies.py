"""CR 603.1: "when" and "whenever" open one kind of triggered ability.

The trigger-condition table asked a "when" line it missed of the *whenever*
table (Juju Bubble's "when you play a card"), and never the reverse — so
"**Whenever** this creature dies, …" parsed in the grammar and was refused at
the condition table, the card reported unsupported. No shipped card prints it
(``tests/engine/test_kg5_grammar_whenever_retry_census.py`` reads every
"whenever" line the retry reaches); the
synthetic cards are a future set's.

The reverse retry is narrower than the forward one on purpose, and both
limits are tested: it asks the "when" table only for the source's own events
("whenever this …", which a card naming itself collapses to), only when no
"whenever" row matched (a row that matched and refused its phrase is a
refusal, not a miss — the forward retry has the same gate now), and never
takes a condition spanning the comma, which the "when" table's bare-`.+`
self-name rows would otherwise read into the effect.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.line_normalization import normalize_creature_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.trigger_conditions import _parse_trigger_condition

from tests.helpers import CARDS_BY_NAME, settle


def _creature(name: str, oracle_text: str) -> CardDefinition:
    raw = {"name": name, "type_line": "Creature — Test", "power": "2", "toughness": "2"}
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw, power="2", toughness="2",
    )


def _table(creature: CardDefinition) -> tuple[Game, Permanent]:
    mine = PlayerState(name="P1", life=20, hand=[CARDS_BY_NAME["Lightning Bolt"]])
    theirs = PlayerState(name="P2", life=20)
    game = Game(players=[mine, theirs])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    permanent = Permanent(card=creature)
    game._put_permanent_onto_battlefield(0, permanent, None)
    return game, permanent


@pytest.mark.cr("603.1", "700.4")
@pytest.mark.parametrize("text", [
    "Whenever this creature dies, you gain 2 life.",
    # The card's own name, collapsed to "this creature" by the table's
    # self-reference fallback before the retry is asked.
    "Whenever Kg5 Mourner dies, you gain 2 life.",
])
def test_whenever_this_creature_dies_triggers_as_it_dies(text):
    mourner = _creature("Kg5 Mourner", text)
    program = compile_card_oracle(mourner)
    assert program.supported, program.reason
    (ability,) = program.triggered_abilities
    assert ability.condition.kind == "dies"
    assert ability.condition.trigger == "whenever", "the printed word is reported"

    game, permanent = _table(mourner)
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id],
    )
    assert result.supported, result
    settle(game)

    assert not game.is_on_battlefield(permanent)
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt", "Kg5 Mourner"] or \
        "Kg5 Mourner" in [card.name for card in game.players[0].graveyard]
    assert game.players[0].life == 22, game.log[-6:]


@pytest.mark.cr("603.1")
def test_whenever_this_creature_leaves_the_battlefield_is_the_leave_trigger():
    """The same retry for the leave event — the other one-shot event the
    "when" table holds for the source alone."""
    leaver = _creature("Kg5 Leaver", "Whenever this creature leaves the battlefield, you gain 3 life.")
    program = compile_card_oracle(leaver)
    assert program.supported, program.reason
    assert program.triggered_abilities[0].condition.kind == "leaves_battlefield"

    game, permanent = _table(leaver)
    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[permanent.permanent_id])
    settle(game)
    assert game.players[0].life == 23, game.log[-6:]


@pytest.mark.cr("603.1")
def test_the_reverse_retry_never_reads_a_condition_across_the_comma():
    """The "when" table's `dies` row ends in a bare `.+` (a short self-name:
    "when barrin dies"). Asked of a "whenever" line about an event neither
    table names, that row would read "this creature xyzzies, target creature"
    as the dying object and fire the effect on the wrong event."""
    line = normalize_creature_line("Whenever this creature xyzzies, target creature dies.")
    as_when = "when " + line[len("whenever "):]
    swapped, _ = _parse_trigger_condition(as_when)
    assert swapped is not None and swapped.kind == "dies", (
        "the wide row this guards against still reads the 'when' spelling"
    )
    condition, _ = _parse_trigger_condition(line)
    assert condition is None
