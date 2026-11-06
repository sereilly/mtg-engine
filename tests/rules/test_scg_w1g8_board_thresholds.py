"""CR 602.5's "Activate only if you control N or more <noun>" — a threshold
read as a count (Scourge W1G8, Temple of the False God).

The presence row ("you control a Swamp") refuses a threshold rather than
reading it as "at least one"; this row reads it through the grammar's own
condition reader, the one Land Tax's and Tithe's intervening "if"s answer
through. Driven from an invented card so the row is demonstrated as a template
— the noun and the number are payload — and from the printed Temple.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_restrictions import activation_denial, activation_restriction_line
from engine.models import CardDefinition, Permanent, PlayerState
from tests.helpers import _nosick


def _w1g8_card(name: str, type_line: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=text,
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


_W1G8_LINE = "{T}: You gain 1 life. Activate only if you control two or more snow lands."


def _w1g8_board(snow_lands: int, plain_lands: int):
    source = Permanent(card=_w1g8_card("Threshold Engine", "Artifact", _W1G8_LINE))
    lands = [
        Permanent(card=_w1g8_card("Snowy Plains", "Basic Snow Land — Plains", "({T}: Add {W}.)"))
        for _ in range(snow_lands)
    ] + [
        Permanent(card=_w1g8_card("Bare Plains", "Basic Land — Plains", "({T}: Add {W}.)"))
        for _ in range(plain_lands)
    ]
    mine = PlayerState(name="P1", battlefield=[source, *lands])
    theirs = PlayerState(name="P2", battlefield=[
        Permanent(card=_w1g8_card("Snowy Plains", "Basic Snow Land — Plains", "({T}: Add {W}.)"))
        for _ in range(3)
    ])
    game = Game(players=[mine, theirs])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    _nosick(source)
    return game, source


@pytest.mark.cr("602.5")
def test_602_5_a_threshold_clause_counts_the_activators_own_board():
    """One snow land is not two — three non-snow lands are not either, and an
    opponent's snow lands are not the activator's; two snow lands are."""
    assert activation_restriction_line(_W1G8_LINE.split(". ", 1)[1])
    for snow, plain, allowed in ((1, 3, False), (0, 4, False), (2, 0, True), (3, 1, True)):
        game, source = _w1g8_board(snow, plain)
        denial = activation_denial(game, 0, source, _W1G8_LINE)
        assert (denial is None) is allowed, (snow, plain, denial)
        if not allowed:
            assert "two or more snow lands" in str(denial)


@pytest.mark.cr("602.5", "605.1a")
def test_605_1a_the_temples_conditioned_mana_ability_is_tapped_by_asking(set_pool):
    """A mana ability with a CR 602.5 clause is still a mana ability (CR
    605.1a), and Temple of the False God's is its only one — so a tap asked
    for {C} activates it (CR 605: asking for a symbol picks the ability),
    gated by its clause at the tap seam: refused on four lands, {C}{C} on
    five."""
    temple = set_pool("SCG")["Temple of the False God"]
    plains = set_pool("LEA")["Plains"]
    for others, made in ((3, 0), (4, 2)):
        source = Permanent(card=temple)
        mine = PlayerState(name="P1", battlefield=[source] + [Permanent(card=plains) for _ in range(others)])
        game = Game(players=[mine, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.active_player_index = 0
        game._sync_control()
        _nosick(source)
        tapped = game.tap_land_for_mana(0, temple.name, "C", permanent_id=source.permanent_id)
        assert tapped is (made > 0)
        assert mine.mana_pool.get("C", 0) == made
