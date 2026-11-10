"""A trigger owed exactly N target cards from a single graveyard (Mirrodin's
promotion rehearsal, W2G0).

"Imprint — When this artifact enters, you may exile **two target sorcery
cards from a single graveyard**." (Spellweaver Helix.) A count printed
without "up to" is owed whole (CR 601.2c, through CR 603.3d for a trigger),
and the several-card announcement built for Gravegouger's "up to two" held
it only as a ceiling:

* **a seat nobody asks** picked another seat's pile first whatever it held —
  one sorcery beside two of its own — the default's answer was refused for
  being short, and the Helix imprinted nothing;
* **a cast naming one card** had the one card ride the trigger, and the
  Helix imprinted one sorcery of two.

The default now answers from a pile that can meet the count (another seat's
first, as before), and an announcement short of it is set aside at the push
and chosen again — the permanent half's rule (Petradon's "two target lands")
for a pile. Validated backwards: each test below fails with its fix taken out.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from tests.helpers import settle


def _table(set_pool, mine, theirs, *, interactive=()):
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game = Game(players=[
        PlayerState(name="A", hand=[mrd["Spellweaver Helix"]],
                    library=[lea["Plains"]] * 5, graveyard=[lea[n] for n in mine]),
        PlayerState(name="B", library=[lea["Plains"]] * 5,
                    graveyard=[lea[n] for n in theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _exiled(game) -> list[list[str]]:
    return [[card.name for card in player.exile] for player in game.players]


@pytest.mark.cr("601.2c", "603.3d")
def test_a_seat_nobody_asks_imprints_two_of_its_own_beside_an_opponents_one(set_pool):
    """The opponent's pile holds one sorcery, so it is no answer; the
    controller's holds two, and both are exiled."""
    game = _table(set_pool, ["Wrath of God", "Fireball"], ["Mind Twist"])

    assert game.cast_from_hand(0, "Spellweaver Helix").supported
    settle(game)

    assert _exiled(game) == [["Wrath of God", "Fireball"], []]
    assert [card.name for card in game.players[1].graveyard] == ["Mind Twist"]


@pytest.mark.cr("601.2c", "603.3d")
def test_an_unasked_seat_still_takes_the_opponents_pile_where_it_holds_two(set_pool):
    """The policy the count narrows, unchanged where the opposing pile can
    meet it: another seat's cards first."""
    game = _table(set_pool, ["Wrath of God", "Fireball"], ["Mind Twist", "Stone Rain"])

    assert game.cast_from_hand(0, "Spellweaver Helix").supported
    settle(game)

    assert _exiled(game) == [[], ["Mind Twist", "Stone Rain"]]


@pytest.mark.cr("601.2c", "603.3d")
def test_a_cast_naming_one_card_is_asked_again_for_two(set_pool):
    """Cast naming one sorcery: short of the printed count, the announcement
    is set aside as the trigger goes on the stack and its controller is asked
    for two; answered, both are exiled."""
    game = _table(set_pool, ["Wrath of God", "Fireball", "Stone Rain"], [], interactive={0})

    assert game.queue_from_hand(
        0, "Spellweaver Helix", target_player_index=0, target_permanent_index=0,
    ).supported
    game.resolve_top_of_stack()

    (prompt,) = game.pending_choices_of("trigger_target")
    assert prompt.data.get("exact_targets") and prompt.data["max_targets"] == 2
    assert not game.confirm_trigger_target(0, seat=0, graveyard_index=1), "one is short"
    assert game.confirm_trigger_target(0, seat=0, graveyard_indices=[1, 2])
    settle(game)
    assert _exiled(game) == [["Fireball", "Stone Rain"], []]
    assert [card.name for card in game.players[0].graveyard] == ["Wrath of God"]


@pytest.mark.cr("601.2c", "603.3d")
def test_a_cast_naming_one_card_at_an_unasked_seat_takes_two(set_pool):
    game = _table(set_pool, ["Wrath of God", "Fireball"], [])

    assert game.queue_from_hand(
        0, "Spellweaver Helix", target_player_index=0, target_permanent_index=0,
    ).supported
    settle(game)

    assert _exiled(game) == [["Wrath of God", "Fireball"], []]


@pytest.mark.cr("601.2c")
def test_a_cast_naming_two_cards_stands(set_pool):
    game = _table(set_pool, ["Wrath of God", "Fireball", "Stone Rain"], [], interactive={0})

    assert game.queue_from_hand(
        0, "Spellweaver Helix", target_player_index=0, target_permanent_index=[0, 2],
    ).supported
    game.resolve_top_of_stack()
    assert not game.pending_choices_of("trigger_target")
    settle(game)

    assert _exiled(game) == [["Wrath of God", "Stone Rain"], []]
