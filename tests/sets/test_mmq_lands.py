"""Mercadian Masques lands.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W2G1: counters as a resource — the depletion lands ---
import pytest as _w2g1_pytest
from engine import Game as _W2G1Game
from engine import PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent
from engine.named_counters import counters_on as _w2g1_counters_on
from engine.oracle import compile_card_oracle as _w2g1_compile

#: The five depletion lands and the two mana each taps for. One printed
#: template with the colour as data, which is the whole claim of the round that
#: landed them: "This land enters tapped with two depletion counters on it" is
#: `enter_effects.ENTERS_WITH_NAMED_COUNTER` with the tapping word folded in,
#: and no card here has an entry of its own anywhere in the engine.
_W2G1_DEPLETION_LANDS = {
    "Hickory Woodlot": "G",
    "Peat Bog": "B",
    "Remote Farm": "W",
    "Sandstone Needle": "R",
    "Saprazzan Skerry": "U",
}


def _w2g1_land_in_play(set_pool, name):
    """A two-seat game with that depletion land newly entered under seat 0.

    Through ``_put_permanent_onto_battlefield`` rather than by appending to the
    list, because the entry state is the subject: the counters and the tapping
    are both CR 614.1c replacements ``_initialize_permanent_state`` performs as
    the permanent arrives, and a permanent placed on the list never arrived.
    """
    game = _W2G1Game(players=[
        _W2G1PlayerState(name="P0"), _W2G1PlayerState(name="P1"),
    ])
    game.interactive_seats = set()
    land = _W2G1Permanent(card=set_pool("MMQ")[name])
    game._put_permanent_onto_battlefield(0, land, None)
    return game, land


@_w2g1_pytest.mark.parametrize("name", sorted(_W2G1_DEPLETION_LANDS))
def test_w2g1_depletion_land_enters_tapped_carrying_two_counters(set_pool, name):
    """"This land enters tapped with two depletion counters on it."

    Both halves, because the sentence composes two entry-state phrases and each
    is performed by a different reader — the tapping by ``ENTERS_TAPPED``'s
    substring probe over the whole card, the counters by the named-counter
    pattern anchored on the line. Asserting only the counters would leave the
    land untapped and pass.
    """
    _game, land = _w2g1_land_in_play(set_pool, name)

    assert land.tapped is True
    assert _w2g1_counters_on(land, "depletion") == 2


@_w2g1_pytest.mark.parametrize(
    "name,symbol", sorted(_W2G1_DEPLETION_LANDS.items())
)
def test_w2g1_depletion_land_taps_for_two_and_spends_a_counter(
    set_pool, name, symbol
):
    """"{T}, Remove a depletion counter from this land: Add <two mana>."

    The amount matters as much as the colour: a land that taps for one is a
    strictly worse card and nothing static can see the difference.
    """
    game, land = _w2g1_land_in_play(set_pool, name)
    land.tapped = False

    result = game.activate_permanent_ability(0, name)

    assert result.supported is True
    assert game.players[0].mana_pool[symbol] == 2
    assert _w2g1_counters_on(land, "depletion") == 1


@_w2g1_pytest.mark.parametrize("name", sorted(_W2G1_DEPLETION_LANDS))
def test_w2g1_depletion_land_sacrifices_itself_when_the_last_counter_goes(
    set_pool, name
):
    """"If there are no depletion counters on this land, sacrifice it."

    A printed restriction is only done when something enforces it, and this one
    is the card's whole cost: a land that keeps tapping after its second
    activation is an unbounded mana source. The second activation still makes
    its mana — the sacrifice is the tail of the same ability, not a replacement
    of it.
    """
    game, land = _w2g1_land_in_play(set_pool, name)
    player = game.players[0]
    for _ in range(2):
        land.tapped = False
        game.activate_permanent_ability(0, name)

    assert not any(perm is land for perm in player.battlefield)
    assert [card.name for card in player.graveyard] == [name]
    assert player.mana_pool[_W2G1_DEPLETION_LANDS[name]] == 4


@_w2g1_pytest.mark.parametrize("name", sorted(_W2G1_DEPLETION_LANDS))
def test_w2g1_depletion_land_compiles_with_no_name_keyed_entry(set_pool, name):
    """Supported, and supported as a *template*.

    The five differ only by their colour, so a hook on any of them would be a
    hook on all five — the check that keeps this round's claim honest is that
    ``CARD_LINE_INSTRUCTIONS`` never hears of them.
    """
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS

    assert _w2g1_compile(set_pool("MMQ")[name]).supported is True
    assert name not in CARD_LINE_INSTRUCTIONS
