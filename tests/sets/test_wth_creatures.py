"""Weatherlight creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: the top of a graveyard as a cost ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with, invented so the only thing
    that varies between the halves of each pair below is the printed type."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w1g1_board(set_pool, name: str, graveyard: list[CardDefinition]):
    """*name* on the battlefield with *graveyard* behind it, ready to activate.

    The graveyard is given **bottom-first**, which is the list order CR 404.1
    produces: a card put into a graveyard goes on top, so the last element is
    the top card and `engine/graveyard_order.py` reads it as such.
    """
    perm = Permanent(card=set_pool("WTH")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


@pytest.mark.parametrize("name", ["Necratog", "Zombie Scavengers"])
def test_the_graveyard_cost_takes_the_creature_card_nearest_the_top(set_pool, name):
    """"Exile the top creature card of your graveyard: …"

    The creature card *nearest the top*, not "the top card if it is a
    creature": CR 404.3 orders the pile and the phrase scans it. Read the other
    way both cards would be unactivatable with a land on top of a graveyard
    full of creatures.
    """
    game, _perm = _w1g1_board(set_pool, name, [
        _w1g1_card("Deep Bear", "Creature — Bear"),
        _w1g1_card("Near Bear", "Creature — Bear"),
        _w1g1_card("Top Land", "Land"),
    ])
    me = game.players[0]
    result = game.activate_permanent_ability(0, name)
    assert result.supported, result.details
    assert [card.name for card in me.exile] == ["Near Bear"]
    assert [card.name for card in me.graveyard] == ["Deep Bear", "Top Land"], (
        "the land on top and the deeper creature both stayed"
    )


@pytest.mark.parametrize("name", ["Necratog", "Zombie Scavengers"])
def test_the_graveyard_cost_is_unpayable_with_no_creature_card(set_pool, name):
    """CR 118.3: a player can't pay a cost without the resources to pay it
    fully, and CR 602.5c makes an unpayable cost an *unactivatable* ability
    rather than a free one. A graveyard of lands pays nothing here — and the
    lands are still there afterwards."""
    game, _perm = _w1g1_board(set_pool, name, [_w1g1_card("Top Land", "Land")])
    me = game.players[0]
    result = game.activate_permanent_ability(0, name)
    assert not result.supported
    assert not game.stack, "the ability never reached the stack"
    assert [card.name for card in me.graveyard] == ["Top Land"]
    assert me.exile == []


def test_necratog_grows_by_eating_its_graveyard(set_pool):
    """"Exile the top creature card of your graveyard: this creature gets +2/+2
    until end of turn." The cost is paid on activation (CR 601.2h/602.2b) and
    the pump arrives when the ability resolves."""
    game, perm = _w1g1_board(
        set_pool, "Necratog", [_w1g1_card("Snack", "Creature — Bear")]
    )
    printed = (perm.effective_power, perm.effective_toughness)
    result = game.activate_permanent_ability(0, "Necratog")
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert (perm.effective_power, perm.effective_toughness) == (
        printed[0] + 2, printed[1] + 2
    )


def test_zombie_scavengers_regenerates_off_its_graveyard(set_pool):
    """"Exile the top creature card of your graveyard: Regenerate this
    creature." (CR 701.15.)"""
    game, perm = _w1g1_board(
        set_pool, "Zombie Scavengers", [_w1g1_card("Snack", "Creature — Bear")]
    )
    result = game.activate_permanent_ability(0, "Zombie Scavengers")
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert perm.regeneration_shield == 1
