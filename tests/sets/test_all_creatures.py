"""Per-card tests for Alliances' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the graveyards these tests build."""
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_krovikan_horror_returns_itself_at_the_end_step(set_pool):
    """CR 113.6b: "if this card is in your graveyard …" is where the card states
    which zone the ability functions in, and CR 404.3's order is what "directly
    above it" reads."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])

    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_w1g5_krovikan_horror_answers_to_an_opponents_end_step(set_pool):
    """"At the beginning of **the** end step" — not "your". CR 513.1 gives every
    turn one end step and this ability names whichever comes next, so the scan
    is unseated where Death Spark's upkeep one is not."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])
    game.active_player_index = 1

    game.resolve_end_step(1)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]


def test_w1g5_krovikan_horror_stays_put_with_nothing_above_it(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would fire. On
    top of the pile there is nothing above it, so nothing fires."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([_w1g5_lea("Grizzly Bears"), horror])

    game.resolve_end_step(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[-1] is horror


def test_w1g5_nether_shadows_deeper_condition_still_reads(set_pool):
    """The three-cards-above spelling is the same clause with a different number,
    and it must keep answering the way it did — Nether Shadow's line is claimed
    by a card hook, and a condition production that changed what "above" means
    would have moved it silently."""
    from engine.graveyard_order import satisfies_above

    bear = _w1g5_lea("Grizzly Bears")
    forest = _w1g5_lea("Forest")
    pile = [set_pool("ALL")["Krovikan Horror"], bear, bear, bear]
    spec = {"card_type": "creature", "count": 3, "op": "ge", "directly": False}
    assert satisfies_above(pile, 0, spec)
    assert not satisfies_above([pile[0], bear, forest], 0, spec)
