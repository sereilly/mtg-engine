"""Weatherlight lands.

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


# --- W2G5: enforcement, entry replacement and the last statics ---

from engine import Game, PlayerState  # noqa: E402
from engine.card_loader import load_cards, manifest_set_path  # noqa: E402
from engine.models import Permanent  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402

_W2G5_TOLL_LANDS = ("Lotus Vale", "Scorched Ruins")


def _w2g5_forest():
    return {c.name: c for c in load_cards([manifest_set_path("LEA")])}["Forest"]


def _w2g5_board(set_pool, name: str, lands: int, *, tapped: bool = False):
    """Seat 0 holds *name* in hand with *lands* Forests already out.

    The taps are applied **after** ``start_turn``: the untap step would
    otherwise undo them, and a test that untapped its own precondition would
    prove the untapped-only clause was honoured when it had never been asked.
    """
    forests = [Permanent(card=_w2g5_forest()) for _ in range(lands)]
    seat = PlayerState(
        name="P0", hand=[set_pool("WTH")[name]], battlefield=forests
    )
    game = Game(players=[seat, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for forest in forests:
        forest.tapped = tapped
    return game, seat


import pytest  # noqa: E402


@pytest.mark.parametrize("name", _W2G5_TOLL_LANDS)
def test_the_toll_lands_sacrifice_two_untapped_lands_to_enter(set_pool, name):
    """"If this land would enter, sacrifice two untapped lands instead. If you
    do, put this land onto the battlefield."

    The five Alliances lands print the same paragraph asking for **one** land,
    and the reader could only ever see a printed article — so a count in front
    of a bare plural refused the whole card. Two go, and the land arrives.
    """
    game, seat = _w2g5_board(set_pool, name, 3)

    game.cast_from_hand(0, name)
    game.resolve_stack()
    game._settle()

    assert [p.card.name for p in seat.battlefield] == ["Forest", name], game.log
    assert [c.name for c in seat.graveyard] == ["Forest", "Forest"], game.log


@pytest.mark.parametrize("name", _W2G5_TOLL_LANDS)
def test_the_toll_is_indivisible_with_only_one_land_to_give(set_pool, name):
    """"If you don't, put it into its owner's graveyard."

    The toll is two, so a player holding one pays none of it — the land never
    enters. The predicate behind this used to ask only "is there anything?",
    which would have let the land arrive for half price with nothing failing.
    """
    game, seat = _w2g5_board(set_pool, name, 1)

    game.cast_from_hand(0, name)
    game.resolve_stack()
    game._settle()

    assert [p.card.name for p in seat.battlefield] == ["Forest"], game.log
    assert [c.name for c in seat.graveyard] == [name], game.log


@pytest.mark.parametrize("name", _W2G5_TOLL_LANDS)
def test_the_toll_lands_do_not_accept_tapped_lands(set_pool, name):
    """"…sacrifice two **untapped** lands." Three tapped Forests pay nothing,
    so the land goes to the graveyard with all three still on the table."""
    game, seat = _w2g5_board(set_pool, name, 3, tapped=True)

    game.cast_from_hand(0, name)
    game.resolve_stack()
    game._settle()

    assert len(seat.battlefield) == 3, game.log
    assert [c.name for c in seat.graveyard] == [name], game.log


@pytest.mark.parametrize("name", _W2G5_TOLL_LANDS)
def test_the_toll_lands_keep_their_own_mana_ability(set_pool, name):
    """The second line of each card is what it was worth the toll for, so the
    whole card is checked rather than the paragraph this round read."""
    assert compile_card_oracle(set_pool("WTH")[name]).supported

# --- end W2G5 ---
