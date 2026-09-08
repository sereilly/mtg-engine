"""Urza's Saga lands.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND, ability_functions_from
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The six cycling lands. Each prints a mana ability *and* a cycling one, which
#: is what makes them the shape that matters: the cycling ability is second in
#: the compiled order, so anything that offers it on the battlefield does not
#: merely add a dead option — it renumbers nothing and simply runs, drawing a
#: card for a land that is not in anybody's hand.
_G1_CYCLING_LANDS = (
    ("Blasted Landscape", "C"),
    ("Drifting Meadow", "W"),
    ("Polluted Mire", "B"),
    ("Remote Isle", "U"),
    ("Slippery Karst", "G"),
    ("Smoldering Crater", "R"),
)


def _g1_land_game(card, *, library=4):
    """A game with *card* in seat 0's hand and a small library to draw from."""
    filler = card
    player = PlayerState(name="G1-A", hand=[card], library=[filler] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name,symbol", _G1_CYCLING_LANDS)
def test_w1g1_a_cycling_land_taps_for_its_colour_and_cycles_from_hand(
    set_pool, name, symbol
):
    """Both abilities, both from the zone that owns them.

    A cycling land is the whole of Urza's Saga's cycling problem in one card: on
    the battlefield it is a mana source and nothing else, and in a hand it is a
    "{2}: draw a card" that costs you the land. Six cards print exactly this.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason

    battlefield = [a.source_line for a in usable_activated_abilities(program)]
    from_hand = [a.source_line for a in usable_activated_abilities(program, zone=HAND)]
    assert battlefield == ["{T}: Add {%s}." % symbol]
    assert from_hand == ["{2}, Discard this card: Draw a card."]

    # From the hand: the land is discarded and a card is drawn.
    game, player = _g1_land_game(card)
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert [c.name for c in player.graveyard] == [name]
    assert len(player.hand) == 1
    assert len(player.library) == 3

    # On the battlefield: the mana ability, and no way to reach the other one.
    game, player = _g1_land_game(card)
    player.hand.clear()
    player.battlefield.append(Permanent(card=card))
    library_before = len(player.library)
    assert game.activate_permanent_ability(0, name, ability_index=0).supported
    assert player.mana_pool.get(symbol, 0) == 1
    assert game.activate_permanent_ability(0, name, ability_index=1).supported is False
    assert len(player.library) == library_before
    assert player.graveyard == []


def test_w1g1_the_cycling_lands_state_the_zone_they_function_in(set_pool):
    """CR 113.6j is derived from the compiled cost, so it answers for every one
    of them without any of them being named."""
    pool = set_pool("USG")
    for name, _ in _G1_CYCLING_LANDS:
        program = compile_card_oracle(pool[name])
        zones = {a.source_line: ability_functions_from(a)
                 for a in program.activated_abilities}
        assert zones["{2}, Discard this card: Draw a card."] == HAND
