"""Weatherlight sorceries.

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
from engine.cast_costs import cast_announces_x
from engine.models import CardDefinition


def _w1g1_card(name: str, type_line: str) -> CardDefinition:
    """A vanilla card to stack a graveyard with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _w1g1_misery(set_pool, graveyard):
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Haunting Misery"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_haunting_misery_announces_an_x_its_mana_cost_never_prints(set_pool):
    """CR 107.3a names four places an X can live, and Haunting Misery's is the
    *additional cost*: its printed mana cost is {1}{B}{B} with no {X} in it. A
    reader that probed only the mana cost would offer no X box and the cast
    would take CR 107.3b's default of 0 — legal, and useless."""
    misery = set_pool("WTH")["Haunting Misery"]
    assert "{X}" not in (misery.mana_cost or "")
    assert cast_announces_x(misery)


def test_haunting_misery_exiles_x_creature_cards_and_deals_x(set_pool):
    """"As an additional cost to cast this spell, exile X creature cards from
    your graveyard." The price and the damage read the *same* announced X, and
    the land in the pile is not a creature card and does not pay."""
    game = _w1g1_misery(set_pool, [
        _w1g1_card("Land", "Land"),
        _w1g1_card("Bear One", "Creature — Bear"),
        _w1g1_card("Bear Two", "Creature — Bear"),
        _w1g1_card("Bear Three", "Creature — Bear"),
    ])
    me, them = game.players
    result = game.cast_from_hand(
        0, "Haunting Misery", target_player_index=1, x_value=2
    )
    assert result.supported, result.details
    assert len(me.exile) == 2
    assert all("Bear" in card.name for card in me.exile)
    assert [
        card.name for card in me.graveyard if card.name != "Haunting Misery"
    ] == ["Land", "Bear One"]
    if game.stack:
        game.resolve_top_of_stack()
    assert them.life == 18


def test_haunting_misery_refuses_an_x_the_graveyard_cannot_pay(set_pool):
    """CR 601.2h: an unpayable cost is an uncastable spell. A graveyard holding
    one creature card cannot pay an announced X of three, and a gate that asked
    only whether *one* existed would charge one and deal three."""
    game = _w1g1_misery(set_pool, [_w1g1_card("Bear One", "Creature — Bear")])
    me, them = game.players
    result = game.cast_from_hand(
        0, "Haunting Misery", target_player_index=1, x_value=3
    )
    assert not result.supported
    assert [card.name for card in me.graveyard] == ["Bear One"]
    assert them.life == 20


def test_haunting_miserys_x_is_bounded_by_the_creature_cards_in_the_pile(set_pool):
    """CR 601.2h gives the announcement a ceiling, and it is not the mana pool:
    this X is paid in graveyard cards. The picker reads the same enumeration
    ``_unpayable_additional_cost`` refuses by, so it can neither offer an X the
    cast would reject nor hide one it would accept."""
    game = _w1g1_misery(set_pool, [_w1g1_card("Land", "Land")])
    misery = set_pool("WTH")["Haunting Misery"]
    assert game.cast_target_spec(0, misery)["max_x"] == 0, (
        "a graveyard of lands is an X of zero, not an unbounded offer"
    )
    game.players[0].graveyard.extend(
        _w1g1_card(f"Bear {n}", "Creature — Bear") for n in range(3)
    )
    assert game.cast_target_spec(0, misery)["max_x"] == 3
