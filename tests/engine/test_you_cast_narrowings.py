"""``Whenever you cast a <narrowed> spell`` — every narrowing the table carries
on that scope is one the dispatcher asks.

The three cast scopes ("a player casts", "an opponent casts", "you cast")
print the same narrowings, and ``cast_event_filters._cast_narrowing_admits`` is the one
reader of them. The two board-wide scopes have gone through it since Urza's
Chalice; ``_controller_cast_filter`` kept four tests of its own inline and
asked the helper for nothing else — so a narrowing ``engine/trigger_conditions.py``'s
table carried on the "you" scope and only the helper read was **dropped**:

    Whenever you cast a multicolored spell, …

compiled, reported supported, and fired on every spell its controller cast.
No shipped card prints that line on this scope (Rewards of Diversity is the
opponent's), which is why nothing had noticed; Apocalypse's Dwarven Patrol —
"whenever you cast a **nonred** spell" — is what made somebody read the filter.

Invented permanents, because the point is the template and not a card: each
watcher gains 1 life when it triggers, so the life total is the count.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

#: One spell of each colour shape, from Alpha and Legends.
_SPELLS = {
    "green": "Grizzly Bears",
    "red": "Goblin King",
    "black": "Black Knight",
    "red-green": "Jerrard of the Closed Fist",
    "colourless": "Sol Ring",
}


def _fires_on(set_pool, text: str) -> set[str]:
    """Which of ``_SPELLS`` an enchantment printing *text* triggers on when
    its controller casts them."""
    watcher = _mk_card("Cast Watcher", "{1}", "Enchantment", text)
    program = compile_card_oracle(watcher)
    assert program.supported, program.reason
    fired = set()
    for label, name in _SPELLS.items():
        card = set_pool("LEA").get(name) or set_pool("LEG")[name]
        game = Game(players=[PlayerState(name="A", hand=[card]), PlayerState(name="B")])
        game.enforce_mana_costs = False
        game.current_turn_phase = game.current_step = "precombat_main"
        game._put_permanent_onto_battlefield(0, Permanent(card=watcher), None)
        assert game.queue_from_hand(0, name).supported
        resolve_stack(game)
        if game.players[0].life == 21:
            fired.add(label)
        else:
            assert game.players[0].life == 20
    return fired


@pytest.mark.parametrize("narrowing, fires_on", [
    ("a multicolored", {"red-green"}),
    ("a red", {"red", "red-green"}),
    ("a nonred", {"green", "black", "colourless"}),
    ("a nonblack", {"green", "red", "red-green", "colourless"}),
    ("a creature", {"green", "red", "black", "red-green"}),
    ("a noncreature", {"colourless"}),
    ("a", {"green", "red", "black", "red-green", "colourless"}),
])
def test_a_you_cast_trigger_fires_on_exactly_the_spells_it_prints(
    set_pool, narrowing, fires_on,
):
    """CR 105.2b: a red-green spell is red and is green, so it answers "red",
    does not answer "nonred", and is the only multicolored one here. CR
    105.2c: a colourless spell is no colour, so it is nonred and nonblack."""
    text = f"Whenever you cast {narrowing} spell, you gain 1 life."

    assert _fires_on(set_pool, text) == fires_on


def test_the_colour_narrowings_are_condition_payload_not_a_subtype():
    """``engine/trigger_conditions.py``'s table reads a colour word, and its negation,
    before the row that takes any word for a creature type: "nonred" compiled
    as a trigger narrowed to a *subtype* called "nonred", which no spell has."""
    def payload(text):
        card = _mk_card("Cast Watcher", "{1}", "Enchantment", text)
        (trigger,) = compile_card_oracle(card).triggered_abilities
        return trigger.condition.kind, trigger.condition.payload

    assert payload("Whenever you cast a nonred spell, you gain 1 life.") == (
        "you_cast_spell", {"cast_excluded_color": "red"},
    )
    assert payload("Whenever you cast a red spell, you gain 1 life.") == (
        "you_cast_spell", {"color_word": "red"},
    )


@pytest.mark.parametrize("line", [
    # A negation of nothing the table reads.
    "Whenever you cast a nonsense spell, you gain 1 life.",
    # The union and the negated colour are printed on other scopes only (or
    # not at all); the table has no row, so the grammar must not read one.
    "Whenever you cast a green or white spell, you gain 1 life.",
    "Whenever a player casts a nonred spell, you gain 1 life.",
    "Whenever an opponent casts a nonred spell, you gain 1 life.",
])
def test_a_cast_narrowing_the_table_does_not_carry_refuses_the_line(line):
    """The condition comes from the table and the grammar only has to read the
    whole line — so a line the grammar read that the table reads differently
    would be a trigger watching a set the card does not print."""
    with pytest.raises(GrammarError):
        parse_line(line)
