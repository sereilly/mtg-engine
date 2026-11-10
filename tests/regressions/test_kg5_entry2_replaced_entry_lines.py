"""The log says what happened to an entry a replacement took away (round rule
8: a log line is an interface), and to a permanent the legend rule moved that
a replacement sent elsewhere.

On round kg5's chain (e245e624c) every road below wrote its "put onto the
battlefield" line after the replacement's own — "Lake of the Dead was put into
P0's graveyard instead of entering the battlefield", then "P0 put Lake of the
Dead onto the battlefield (Show and Tell)" — and the legend rule wrote "Legacy
Weapon put into graveyard" for a Legacy Weapon its own replacement shuffled
into its owner's library. One board per road, each through its real entry
point; the census of every such line is
``tests/engine/test_kg5_entry2_entry_log_lines.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_POOL = {card.name: card for card in load_catalog()}


def _game(*, hand=(), opponent_hand=(), mine=(), theirs=(), graveyard=(),
          library=None) -> Game:
    game = Game(players=[
        PlayerState("P0", hand=[_POOL[n] for n in hand],
                    library=[_POOL[n] for n in (library or ["Island"] * 10)],
                    graveyard=[_POOL[n] for n in graveyard]),
        PlayerState("P1", hand=[_POOL[n] for n in opponent_hand],
                    library=[_POOL["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_POOL[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.pending_choices.clear()
    game.start_turn(0)
    settle(game)
    return game


def _lines_naming(game: Game, name: str) -> list[str]:
    return [line for line in game.log if name in line]


def _claims(lines) -> list[str]:
    return [
        line for line in lines
        if ("onto the battlefield" in line or "to the battlefield" in line
            or "enters the battlefield" in line)
        and "instead of entering" not in line and "can't enter" not in line
    ]


def test_show_and_tell_does_not_claim_an_entry_its_toll_took_away():
    game = _game(hand=["Show and Tell", "Lake of the Dead"])
    assert game.queue_from_hand(0, "Show and Tell").supported
    settle(game)
    lines = _lines_naming(game, "Lake of the Dead")
    assert any("instead of entering the battlefield" in line for line in lines), lines
    assert not _claims(lines), lines
    assert [c.name for c in game.players[0].graveyard].count("Lake of the Dead") == 1


def test_show_and_tell_does_not_claim_a_creature_containment_priest_exiled():
    game = _game(hand=["Show and Tell", "Grizzly Bears"], theirs=["Containment Priest"])
    assert game.queue_from_hand(0, "Show and Tell").supported
    settle(game)
    lines = _lines_naming(game, "Grizzly Bears")
    assert "Grizzly Bears was exiled instead of entering the battlefield" in lines
    assert not _claims(lines), lines
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]


def test_a_search_does_not_claim_a_find_its_toll_took_away():
    game = _game(hand=["Crop Rotation"], mine=["Forest"],
                 library=["Lake of the Dead"] + ["Island"] * 5)
    assert game.queue_from_hand(0, "Crop Rotation").supported
    settle(game)
    lines = _lines_naming(game, "Lake of the Dead")
    assert any("instead of entering the battlefield" in line for line in lines), lines
    assert not _claims(lines), lines
    assert any(line == "P0 searched library" for line in game.log), game.log[-8:]


def test_a_reanimation_does_not_claim_a_creature_containment_priest_exiled():
    game = _game(hand=["Resurrection"], graveyard=["Grizzly Bears"],
                 theirs=["Containment Priest"])
    assert game.queue_from_hand(0, "Resurrection").supported
    settle(game)
    lines = _lines_naming(game, "Grizzly Bears")
    assert "Grizzly Bears was exiled instead of entering the battlefield" in lines
    assert not _claims(lines), lines
    assert not any("no creature card to return" in line for line in game.log)


def test_the_entry_that_happens_is_still_said():
    game = _game(hand=["Show and Tell", "Grizzly Bears"])
    assert game.queue_from_hand(0, "Show and Tell").supported
    settle(game)
    assert "P0 put Grizzly Bears onto the battlefield (Show and Tell)" in game.log


def test_the_legend_rule_says_a_shuffled_legacy_weapon_left_the_battlefield():
    game = _game(mine=["Legacy Weapon", "Legacy Weapon"])
    settle(game)
    weapons = [p for p in game.controlled_by(0) if p.card.name == "Legacy Weapon"]
    assert len(weapons) == 1
    assert "Legacy Weapon" in [c.name for c in game.players[0].library]
    assert "Legacy Weapon left the battlefield (704.5j: legend rule)" in game.log
    assert not any("Legacy Weapon put into graveyard" in line for line in game.log)


@pytest.mark.parametrize("name", ["Hazezon Tamar"])
def test_the_legend_rule_still_says_a_graveyard_when_it_is_one(name):
    game = _game(mine=[name, name])
    settle(game)
    assert f"{name} put into graveyard (704.5j: legend rule)" in game.log
    assert [c.name for c in game.players[0].graveyard] == [name]


def test_mox_diamond_whose_toll_a_seat_nobody_asks_paid_is_said_to_enter():
    """Mox Diamond's toll paid inline re-enters the same permanent inside its
    own replacement (``_resolve_entry_discard_toll``): the outer entry is
    consumed, and the outcome the inner one wrote stands — so the cast's
    ``then`` still says it was put onto the battlefield."""
    game = _game(hand=["Mox Diamond", "Forest"])
    assert game.queue_from_hand(0, "Mox Diamond").supported
    settle(game)
    assert any(p.card.name == "Mox Diamond" for p in game.controlled_by(0))
    assert "P0 discarded Forest to put Mox Diamond onto the battlefield" in game.log
    assert "P0 put Mox Diamond onto battlefield" in game.log
