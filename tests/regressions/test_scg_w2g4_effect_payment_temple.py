"""A cost an effect collects counts Temple of the False God — when its clause
holds (CR 602.5b, 605.1a).

"{T}: Add {C}{C}. Activate only if you control five or more lands." Its only
mana ability prints a board condition, so it has no default tap
(``LandManaTapsMixin._land_mana_abilities``), and ``Game.payment_lands`` —
the one list every cost with no priority window is planned over (a
counter-unless, an upkeep price, a toll, a "you may pay") — took its lands
from ``mana_payment.taps_for_payment``, which is pure and cannot ask the board.
So the Temple was never planned: Mana Leak's {3} against a seat holding the
Temple and two Mountains read unpayable and countered the spell (W1G8 measured
it and left it: an under-count, never a stranded payment).
``board_payment.conditioned_tap_pays_now`` asks the seam's own reading of the
land, clause and all, and ``payment_lands`` admits a land it says yes to —
asked again after every tap ``Game._pay_planned_cost`` makes.

Backwards on SCG W2G4's base (843cf32a): the first two tests fail — the prompt
reads unpayable and a seat nobody asks lets the Bears be countered.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}
_TEMPLE = next(
    card for card in load_cards(manifest_set_path("SCG", include_measured=True))
    if card.name == "Temple of the False God"
)


def _permanent(card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(mountains: int, *, interactive=()) -> Game:
    island = _POOL["Island"]
    mine = [_permanent(_TEMPLE)] + [_permanent(_POOL["Mountain"]) for _ in range(mountains)]
    game = Game(players=[
        PlayerState("P0", library=[island] * 10, battlefield=mine),
        PlayerState("P1", library=[island] * 10, battlefield=[_permanent(island)]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._sync_control()
    game.active_player_index = 0
    return game


def _leak_the_bears(game) -> None:
    """P0 casts Grizzly Bears; P1 answers with Mana Leak ({3} or countered)."""
    game.players[0].hand.append(_POOL["Grizzly Bears"])
    game.players[1].hand.append(_POOL["Mana Leak"])
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert game.queue_from_hand(1, "Mana Leak", target_stack_index=0).supported


def _tapped_mountains(game, how_many: int) -> None:
    """Two of the Mountains already went to the Bears."""
    for permanent in [p for p in game.controlled_by(0) if p.card.name == "Mountain"][:how_many]:
        permanent.tapped = True


def test_a_person_may_pay_mana_leak_with_the_temple_on_five_lands():
    game = _game(4, interactive=(0,))
    _tapped_mountains(game, 2)
    _leak_the_bears(game)
    game.resolve_top_of_stack(pause_for_choices=True)

    choice = game.pending_choice_of("mana_payment", 0)
    assert choice is not None, game.log[-4:]
    assert game.mana_payment_is_payable(choice), "{C}{C} and {R}{R} cover {3}"
    assert game.resolve_pending_choice("mana_payment", 0, pay=True)
    resolve_stack(game)

    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0)), game.log[-6:]
    temple = next(p for p in game.controlled_by(0) if p.card is _TEMPLE)
    assert temple.tapped, "the Temple paid its {C}{C}"


def test_a_seat_nobody_asks_pays_mana_leak_with_the_temple():
    game = _game(4)
    _tapped_mountains(game, 2)
    _leak_the_bears(game)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0)), game.log[-6:]


def test_on_four_lands_the_temple_still_pays_nothing():
    """The clause is enforced, not dropped: with three Mountains the Temple is
    no mana at all (it makes {C}{C} only on five or more lands), so {3} off
    one untapped Mountain is unpayable and the spell is countered."""
    game = _game(3)
    _tapped_mountains(game, 2)
    plan = game.effect_payment_plan(0, {"generic": 3})
    assert plan is None
    temple = next(p for p in game.controlled_by(0) if p.card is _TEMPLE)
    assert all(land is not temple for land in game.payment_lands(0))
    _leak_the_bears(game)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    assert not any(p.card.name == "Grizzly Bears" for p in game.controlled_by(0))
    assert not temple.tapped
