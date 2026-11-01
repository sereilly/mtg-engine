"""A where-clause count of "their hand" / "that player's hand" under an upkeep
trigger counts the upkeep player's hand.

Found driving Dreamborn Muse (Legions, W1G7): "At the beginning of each
player's upkeep, that player mills X cards, where X is the number of cards in
**their** hand." The parse reads the possessive as the owner word, and a count
whose owner it could not resolve fell back to ``context.target or
context.caster`` — for an upkeep trigger that chose nothing, the controller's
default opponent. The lowering now moves the possessive onto the seat the
event froze (CR 603.10), the one "that player" in the same sentence reads
(``lowering/where_x._their_zone_on_frozen_seat``).

Dark Suspicions (Planeshift, shipped) printed the same count and was right in
a duel only because the default opponent *is* the upkeep's player there; at
three seats the second opponent lost life by the first one's hand.
"""

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack


def _table(set_pool, hands):
    lea = set_pool("LEA")
    players = [
        PlayerState(
            name=name,
            hand=[lea[card] for card in hands.get(seat, ())],
            library=[lea["Plains"]] * 8,
        )
        for seat, name in enumerate(("Alice", "Bob", "Cara"))
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game


def test_dark_suspicions_counts_each_opponents_own_hand_at_three_seats(set_pool):
    """"At the beginning of each opponent's upkeep, that player loses X life,
    where X is the number of cards in that player's hand minus the number of
    cards in your hand." Alice holds one card, Bob two, Cara five: Bob loses
    1 in his upkeep and Cara 4 in hers — on the base Cara lost 1, Bob's
    count."""
    game = _table(set_pool, {0: ["Plains"], 1: ["Island"] * 2, 2: ["Island"] * 5})
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("PLS")["Dark Suspicions"]), None,
    )
    resolve_stack(game)
    for seat in (1, 2):
        game.active_player_index = seat
        game.resolve_upkeep(seat)
        resolve_stack(game)
    assert game.players[1].life == 19
    assert game.players[2].life == 16
    assert game.players[0].life == 20
