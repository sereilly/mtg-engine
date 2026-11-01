"""A seat nobody asks pays what "you may pay {X}" / "any amount of mana" buys.

The ``pay_any_amount`` prompt's default was 0, so an AI Hollow Specter never
made anybody discard (LGN W1G7) and an AI seat under a dying Liege of the
Hollows made no Squirrels. ``ai_prompts.choose_amount_paid`` pays the most
the board can, up to what the sentence that spends the payment can buy: a
card to choose from per mana up to the size of the victim's hand (public,
CR 402.3), a Squirrel per mana with no ceiling but the board's.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState

from tests.helpers import _nosick, declare_attack, resolve_stack


def _specter_connects(set_pool, bob_hand, swamps):
    """A table where Alice's Hollow Specter (an AI seat's) connects with Bob,
    whose hand is *bob_hand*; the combat is dealt and the trigger drained."""
    lgn, lea = set_pool("LGN"), set_pool("LEA")
    alice = PlayerState(name="Alice", library=[lea["Plains"]] * 8)
    bob = PlayerState(
        name="Bob", hand=[lea[name] for name in bob_hand], library=[lea["Plains"]] * 8,
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = True
    alice.battlefield.append(_nosick(Permanent(card=lgn["Hollow Specter"])))
    for _ in range(swamps):
        alice.battlefield.append(Permanent(card=lea["Swamp"]))
    declare_attack(game, 0)
    for _ in range(8):
        resolve_stack(game)
        # The pick among the shown cards is queued for Alice, as every
        # seat's is; a seat nobody asks has it answered by its default.
        game.auto_resolve_pending_choices()
        if game.current_phase != "combat":
            break
        game.advance_combat_phase()
    assert bob.life == 18
    assert not game.pending_choices
    return game


def _swamps_tapped(game) -> int:
    return sum(1 for p in game.controlled_by(0) if p.card.name == "Swamp" and p.tapped)


def test_an_ai_hollow_specter_pays_up_to_the_victims_hand(set_pool):
    """Bob holds two cards and Alice has three Swamps: X is 2 — a third mana
    would show nothing more (the 2004-10-04 ruling's X past the hand reveals
    it all) — and Bob discards one of the two."""
    game = _specter_connects(set_pool, ["Shivan Dragon", "Plains"], 3)
    assert "Alice paid 2 mana" in game.log
    assert _swamps_tapped(game) == 2
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 1


def test_an_ai_hollow_specter_pays_what_its_lands_can(set_pool):
    """Bob holds five, Alice has two Swamps: X is 2."""
    game = _specter_connects(
        set_pool, ["Lightning Bolt", "Plains", "Shivan Dragon", "Island", "Giant Growth"], 2,
    )
    assert "Alice paid 2 mana" in game.log
    assert _swamps_tapped(game) == 2
    assert len(game.players[1].hand) == 4


def test_an_ai_hollow_specter_pays_nothing_at_an_empty_hand(set_pool):
    """Nothing to reveal is nothing to buy: no Swamp taps."""
    game = _specter_connects(set_pool, [], 3)
    assert "Alice paid no mana" in game.log
    assert _swamps_tapped(game) == 0


def test_a_dying_liege_makes_squirrels_for_both_ai_seats(set_pool):
    """"When this creature dies, each player may pay any amount of mana. Then
    each player creates a number of 1/1 green Squirrel creature tokens equal
    to the amount of mana they paid this way." Seat 0 has two Forests, seat 1
    one: two Squirrels and one."""
    wth, lea = set_pool("WTH"), set_pool("LEA")
    p0 = PlayerState(name="P0", library=[lea["Forest"]] * 8)
    p1 = PlayerState(name="P1", library=[lea["Forest"]] * 8)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = True
    liege = Permanent(card=wth["Liege of the Hollows"])
    p0.battlefield.append(liege)
    p0.battlefield.extend(Permanent(card=lea["Forest"]) for _ in range(2))
    p1.battlefield.append(Permanent(card=lea["Forest"]))
    game._destroy_target_permanent(p0, target_permanent_index=0)
    resolve_stack(game)

    def squirrels(seat):
        return sum(1 for p in game.controlled_by(seat) if "Squirrel" in p.card.name)

    assert (squirrels(0), squirrels(1)) == (2, 1), game.log
