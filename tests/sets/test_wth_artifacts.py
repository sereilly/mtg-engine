"""Weatherlight artifacts.

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

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_furnace(set_pool, victim_graveyard):
    """Phyrexian Furnace on seat 0, with *victim_graveyard* in seat 1's pile.

    Given bottom-first, the order CR 404.1 produces: an arriving card goes on
    top, so the last element is the top card and the first is the bottom one.
    """
    furnace = Permanent(card=set_pool("WTH")["Phyrexian Furnace"])
    furnace.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[furnace],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", graveyard=list(victim_graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, furnace


def test_phyrexian_furnace_exiles_the_bottom_card_of_the_targeted_pile(set_pool):
    """"{T}: Exile the bottom card of target player's graveyard."

    The ability reported ``supported`` and compiled to **nothing** before this
    round — a hollow line, a parse-coverage finding and a picker finding at
    once. Both ends matter: the *bottom* of the pile (CR 404.1's oldest card,
    index 0) and the pile of the seat the ability targets.
    """
    game, _furnace = _w1g1_furnace(set_pool, [
        _w1g1_card("Oldest", "Creature — Bear"),
        _w1g1_card("Middle", "Land"),
        _w1g1_card("Newest", "Land"),
    ])
    them = game.players[1]
    result = game.activate_permanent_ability(
        0, "Phyrexian Furnace", target_player_index=1, ability_index=0
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert [card.name for card in them.exile] == ["Oldest"]
    assert [card.name for card in them.graveyard] == ["Middle", "Newest"]


def test_phyrexian_furnace_asks_for_a_player_and_not_for_a_card(set_pool):
    """The pile is chosen (CR 115.1) and the card in it is not: the order is
    public and fixed, so "the bottom card" has one answer once the seat is
    known. A card picker here would offer a choice the sentence does not make.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    program = compile_card_oracle(set_pool("WTH")["Phyrexian Furnace"])
    first = program.activated_abilities[0]
    assert first.instruction is not None, "the line is no longer hollow"
    assert derive_activation_spec(first) == {"kind": "player"}


def test_phyrexian_furnace_on_an_empty_pile_resolves_and_exiles_nothing(set_pool):
    """An effect is not a cost. CR 608.2 finishes what it can, so an empty
    graveyard exiles nothing and the ability still resolves — where the *cost*
    reading of the same phrase (Necratog) refuses instead, under CR 118.3."""
    game, _furnace = _w1g1_furnace(set_pool, [])
    result = game.activate_permanent_ability(
        0, "Phyrexian Furnace", target_player_index=1, ability_index=0
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()
    assert game.players[1].exile == []
