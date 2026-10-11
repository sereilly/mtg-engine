"""``if there are <N or more> basic land types among <lands>`` — domain held to
a threshold.

Every domain card before Apocalypse *spends* the number ("…for each basic
land type among lands you control"); Mask of Intolerance asks whether it has
reached four. The condition is read by the one reader of the phrase
(``distinct.parse_counted_objects``), carried the way the amounts carry it
(``ObjectFilter.distinct``) and answered by the one evaluator a count has
(``count_from_payload``) — so a land's basic land types are the computed ones
(CR 305.6, CR 613 layer 4) and "that player" is the seat the event froze.

Invented lines beside the card's own: the pool prints the sentence once.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.grammar.errors import GrammarError
from engine.grammar.parser import parse_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack


def _gate(text: str) -> dict:
    card = _mk_card("Domain Watcher", "{1}", "Enchantment", text)
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    return trigger.instruction.payload["intervening_if"]


def test_the_threshold_is_a_count_spec_over_the_named_players_lands():
    yours = _gate(
        "At the beginning of your upkeep, if there are four or more basic land "
        "types among lands you control, you gain 1 life."
    )
    assert yours == {
        "kind": "distinct_among",
        "count": {
            "zone": "battlefield", "owner": "you", "filter": {"type_filter": "land"},
            "aggregate": "distinct_basic_land_types",
        },
        "op": "ge", "value": 4,
    }
    theirs = _gate(
        "At the beginning of each player's upkeep, if there are two or fewer "
        "basic land types among lands that player controls, you gain 1 life."
    )
    assert theirs["count"]["owner"] == "event_subject_player"
    assert (theirs["op"], theirs["value"]) == ("le", 2)


@pytest.mark.parametrize("lands, life", [
    (("Plains", "Island", "Swamp"), 20),
    (("Plains", "Island", "Swamp", "Mountain"), 21),
    # Types, not lands; and a dual land is two of them.
    (("Forest",) * 5, 20),
    (("Tropical Island", "Badlands"), 21),
])
def test_the_threshold_counts_types_among_the_controllers_lands(set_pool, lands, life):
    watcher = _mk_card(
        "Domain Watcher", "{1}", "Enchantment",
        "At the beginning of your upkeep, if there are four or more basic land "
        "types among lands you control, you gain 1 life.",
    )
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game._put_permanent_onto_battlefield(0, Permanent(card=watcher), None)
    for name in lands:
        game._put_permanent_onto_battlefield(
            0, Permanent(card=set_pool("LEA")[name]), None
        )
    # The opponent's five types are not "lands you control".
    for name in ("Plains", "Island", "Swamp", "Mountain", "Forest"):
        game._put_permanent_onto_battlefield(
            1, Permanent(card=set_pool("LEA")[name]), None
        )

    game.resolve_upkeep(0, defer_priority=True)
    resolve_stack(game)

    assert game.players[0].life == life


def test_that_player_with_no_event_to_name_one_is_refused():
    """In a spell nothing froze a seat, so "lands **that player** controls"
    names nobody. Lowered anyway, the count would fall back to the caster's
    board while the line compiled clean."""
    compiled = compile_line(
        "If there are four or more basic land types among lands that player "
        "controls, draw a card."
    )
    assert not compiled.usable
    assert "that player" in (compiled.lowering_error or "")


@pytest.mark.parametrize("line", [
    # Only behind a printed number: an article is presence, and "a basic land
    # type among" is not a sentence.
    "If there is a basic land type among lands you control, draw a card.",
    "If there are no basic land types among lands you control, draw a card.",
])
def test_the_threshold_needs_a_printed_number(line):
    with pytest.raises(GrammarError):
        parse_line(line)
