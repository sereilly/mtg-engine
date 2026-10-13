"""A person's "pay" is an answer or it is refused — never a "don't".

CR 608.2d: a player announcing a choice an effect offers "can't choose an
option that's illegal or impossible", and CR 118.3: "A player can't pay a cost
without having the necessary resources to pay it fully." So a seat that says
"pay" for a price it cannot be made to pay has not chosen anything — and it
has certainly not chosen the other branch.

The engine pays an effect's price for its payer out of the pool and by
tapping **free land abilities only** (CR 605.3a gives the payer the right to
activate mana abilities; the engine exercises it for lands). Everything else
that makes mana — a Sol Ring, a filter land's "{1}, {T}: Add {U}{B}", a land
whose mana is restricted — is the player's own to tap. A plan that could not
pay was read as the *player* being unable, and:

* **Mana Leak on a human's Lightning Bolt**, an Island, a filter land and a
  Sol Ring untapped: "Pay" was a 200, the Bolt was countered, nothing was
  tapped and nothing was said;
* **"Sacrifice it unless you pay {2}"** beside a Sol Ring was not offered at
  all: the permanent was sacrificed without a prompt.

A seat the engine answers for keeps declining what its plan cannot collect —
there is nobody to ask. The plan itself is honest now too
(``tests/engine/test_payment_plan_honesty_census.py``).
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.game_types import OracleExecutionContext, StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card


def _ready(card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(catalog_by_name, *names, interactive=True) -> Game:
    me = PlayerState(
        name="P0", life=20, library=[catalog_by_name["Forest"]] * 5,
        battlefield=[_ready(catalog_by_name[name]) for name in names],
    )
    game = Game(players=[me, PlayerState(name="P1", life=20)])
    if interactive:
        game.interactive_seats = {0, 1}
    return game


def _leak(game, catalog_by_name):
    """A Mana Leak's price put to seat 0 about its own Lightning Bolt."""
    bolt = StackItem(
        card=catalog_by_name["Lightning Bolt"], caster_index=0,
        target_player_index=1, target_permanent_index=None, x_value=None,
    )
    game.stack.append(bolt)
    game.arm_pending_choice(
        "mana_payment", 0, amount=3, card_name="Mana Leak",
        counter_card=catalog_by_name["Mana Leak"], stack_item=bolt,
    )
    return bolt


@pytest.mark.cr("118.3", "608.2d")
def test_118_3_pay_on_a_price_the_plan_cannot_collect_is_refused(catalog_by_name):
    """An Island and a Sol Ring are {3}; the plan taps the Island and stops."""
    game = _game(catalog_by_name, "Island", "Sol Ring")
    bolt = _leak(game, catalog_by_name)
    choice = game.pending_choice_of("mana_payment", 0)

    assert not game.mana_payment_is_payable(choice)
    assert game.confirm_mana_payment(0, True) is False

    # Nothing happened: the spell is where it was, the question is still
    # owed, and nothing was tapped for a payment that was not made.
    assert any(item is bolt for item in game.stack)
    assert game.pending_choice_of("mana_payment", 0) is choice
    assert not any(permanent.tapped for permanent in game.controlled_by(0))
    assert not any("countered" in line for line in game.log)


@pytest.mark.cr("605.3a", "118.3")
def test_605_3a_the_payer_taps_what_the_plan_does_not_and_answers_again(
    catalog_by_name,
):
    """The mana abilities are theirs to activate while the effect is asking
    (CR 605.3a). With the Sol Ring's {C}{C} in the pool the plan covers the
    rest from the Island, and "pay" is an answer."""
    game = _game(catalog_by_name, "Island", "Sol Ring")
    bolt = _leak(game, catalog_by_name)
    me = game.players[0]
    assert game.confirm_mana_payment(0, True) is False

    ring = next(p for p in game.controlled_by(0) if p.card.name == "Sol Ring")
    game.become_tapped(ring)
    me.mana_pool["C"] = me.mana_pool.get("C", 0) + 2
    assert game.mana_payment_is_payable(game.pending_choice_of("mana_payment", 0))

    assert game.confirm_mana_payment(0, True) is True
    assert any(item is bolt for item in game.stack), "paid for, not countered"
    assert game.pending_choice_of("mana_payment", 0) is None
    assert sum(me.mana_pool.values()) == 0
    assert all(p.tapped for p in game.controlled_by(0))


@pytest.mark.cr("118.12a")
def test_118_12a_declining_is_still_an_answer(catalog_by_name):
    game = _game(catalog_by_name, "Island", "Sol Ring")
    bolt = _leak(game, catalog_by_name)

    assert game.confirm_mana_payment(0, False) is True
    assert not any(item is bolt for item in game.stack)
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]


@pytest.mark.cr("118.3")
def test_118_3_a_seat_the_engine_answers_for_still_declines(catalog_by_name):
    """Nobody to ask, so an unpayable price is a price not paid — the reading
    every headless and AI game already had."""
    game = _game(catalog_by_name, "Island", "Sol Ring", interactive=False)
    bolt = _leak(game, catalog_by_name)

    assert game.confirm_mana_payment(0, True) is True
    assert not any(item is bolt for item in game.stack)


# -- "…unless you pay": the offer, and its answer ---------------------------

_TOLL = _mk_card(
    "Census Toll", "{2}", "Enchantment",
    "At the beginning of your upkeep, return Census Toll to its owner's hand "
    "unless you pay {2}.",
)


def _toll(game) -> Permanent:
    """Resolve the toll's upkeep trigger for seat 0, as its controller."""
    program = compile_card_oracle(_TOLL)
    assert program.supported, program
    toll = _ready(_TOLL)
    me = game.players[0]
    me.battlefield.append(toll)
    game._execute_oracle_instruction(
        program.triggered_abilities[0].instruction,
        OracleExecutionContext(
            caster=me, target=me, card=_TOLL, source_permanent=toll,
        ),
    )
    return toll


@pytest.mark.cr("118.12a", "605.3a")
def test_118_12a_a_person_holding_mana_the_plan_does_not_tap_is_asked(
    catalog_by_name,
):
    """ "[Do something] unless [a player does something else]" means the
    player *may* do the something else (CR 118.12a). With a Sol Ring untapped
    they can — so the offer is made, where it used to be skipped and the
    enchantment returned unasked."""
    game = _game(catalog_by_name, "Sol Ring")
    toll = _toll(game)

    assert game.is_on_battlefield(toll)
    offers = game.pending_choices_of("optional_pay", 0)
    assert len(offers) == 1

    # "Yes" before tapping is refused and the offer stands…
    assert game.confirm_optional_pay(0, accept=True) is False
    assert game.pending_choices_of("optional_pay", 0) == offers
    assert game.is_on_battlefield(toll)

    # …and with the Ring tapped for its mana it is paid.
    ring = next(p for p in game.controlled_by(0) if p.card.name == "Sol Ring")
    game.become_tapped(ring)
    game.players[0].mana_pool["C"] = 2
    assert game.confirm_optional_pay(0, accept=True) is True
    assert game.is_on_battlefield(toll)
    assert game.players[0].mana_pool.get("C", 0) == 0
    assert not game.pending_choices_of("optional_pay", 0)


@pytest.mark.cr("118.3")
def test_118_3_nobody_is_asked_a_question_with_one_answer(catalog_by_name):
    """Nothing this seat controls makes mana, so nothing it could do pays the
    {2}: the offer is not made and the other half follows at once."""
    game = _game(catalog_by_name)
    toll = _toll(game)

    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.is_on_battlefield(toll)


@pytest.mark.cr("118.3")
def test_118_3_the_engine_s_own_seat_is_not_offered_what_it_cannot_plan(
    catalog_by_name,
):
    game = _game(catalog_by_name, "Sol Ring", interactive=False)
    toll = _toll(game)

    assert not game.pending_choices_of("optional_pay", 0)
    assert not game.is_on_battlefield(toll)


@pytest.mark.cr("118.12a")
def test_118_12a_a_toll_whose_payment_fails_part_way_is_not_forgiven(
    catalog_by_name, monkeypatch,
):
    """The plan held when it was made and a planned land then made nothing
    (a tap a watcher answered by changing the board). The price was not paid,
    so "unless" carries out its other half — it used to do neither: nothing
    was paid and nothing was returned."""
    game = _game(catalog_by_name, "Forest", "Forest", interactive=False)
    game.interactive_seats = set()
    monkeypatch.setattr(Game, "tap_land_for_mana", lambda self, *a, **k: False)
    # The stated policy pays a toll by tapping; the tap is what fails.
    toll = _toll(game)
    game.auto_resolve_pending_choices()

    assert not game.is_on_battlefield(toll)


@pytest.mark.cr("608.2d")
def test_608_2d_a_person_whose_payment_fails_part_way_is_asked_again(
    catalog_by_name, monkeypatch,
):
    game = _game(catalog_by_name, "Forest", "Forest")
    toll = _toll(game)
    (offer,) = game.pending_choices_of("optional_pay", 0)
    monkeypatch.setattr(Game, "tap_land_for_mana", lambda self, *a, **k: False)

    assert game.confirm_optional_pay(0, accept=True) is False

    assert game.pending_choices_of("optional_pay", 0) == [offer]
    assert game.is_on_battlefield(toll)
