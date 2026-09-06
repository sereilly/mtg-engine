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


# --- W1G4: animation and printed prohibitions ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt


def _w1g4a_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g4a_game(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_bubble_matrix_shields_every_creature_and_no_player(set_pool):
    """"Prevent all damage that would be dealt to creatures." — CR 615.1.

    The recipient is a described *set of permanents* rather than a player, which
    is what makes it a different reader from Glacial Chasm's "dealt to you" one
    row up: a player has no characteristics to match. The sentence narrows by
    nothing, so it reaches both seats — and it says nothing about players, so a
    face still takes the damage. Both halves are asserted, because a shield that
    covered players too would pass the first.
    """
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([matrix, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 0
    assert _damage_dealt(game, game.players[1], 3) == 3


def test_inner_sanctum_shields_only_its_controllers_creatures(set_pool):
    """The same shield with "you control" on the noun phrase (CR 109.5).

    One row for both cards, so the narrowing has to be *honoured* rather than
    merely carried — dropped, Inner Sanctum is a Bubble Matrix, which is the
    direction a prevention fails silently in.
    """
    sanctum = Permanent(card=set_pool("WTH")["Inner Sanctum"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    theirs = Permanent(card=_w1g4a_creature("Raider", 2, 2))
    game = _w1g4a_game([sanctum, mine], [theirs])

    assert _damage_dealt(game, mine, 3) == 0
    assert _damage_dealt(game, theirs, 3) == 3


def test_the_matrix_stops_shielding_when_it_leaves(set_pool):
    """A static ability ends with its source (CR 611.2), and nothing is swept:
    the next event asks the board again."""
    matrix = Permanent(card=set_pool("WTH")["Bubble Matrix"])
    mine = Permanent(card=_w1g4a_creature("Footman", 2, 2))
    game = _w1g4a_game([matrix, mine], [])
    assert _damage_dealt(game, mine, 3) == 0
    game.remove_from_battlefield(matrix)
    assert _damage_dealt(game, mine, 3) == 3


def test_the_shield_is_claimed_by_the_reader_that_applies_it(set_pool):
    """The gate and the interceptor are one function, so a card cannot be
    admitted with its only line doing nothing — and the two singular
    self-references the source-narrowed readers own must keep refusing here."""
    from engine.prevention import prevent_all_to_matching

    assert compile_card_oracle(set_pool("WTH")["Bubble Matrix"]).supported
    assert compile_card_oracle(set_pool("WTH")["Inner Sanctum"]).supported
    for owned_elsewhere in (
        "Prevent all damage that would be dealt to this creature.",
        "Prevent all damage that would be dealt to enchanted creature.",
        "Prevent all damage that would be dealt to you.",
        "Prevent all damage that would be dealt to this creature by artifact sources.",
    ):
        assert prevent_all_to_matching(owned_elsewhere) is None, owned_elsewhere
