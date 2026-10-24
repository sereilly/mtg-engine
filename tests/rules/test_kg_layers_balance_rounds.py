"""Balance's three rounds, each counted as it starts, through the layers.

"Each player chooses a number of lands they control equal to the number of
lands controlled by the player who controls the fewest, then sacrifices the
rest. Players discard cards and sacrifice creatures the same way."

The ruling (2016-06-08): "First the player whose turn it is chooses which lands
(if any) to keep ... All of the unchosen lands are then sacrificed
simultaneously. Then the process is repeated for cards in hand ... Lastly, the
process is repeated for creatures" — and "Each type of object is counted during
the corresponding part of the process. ... a land creature sacrificed to the
first part of the spell would not be counted when determining how many
creatures are on the battlefield for the last part."

On the base tree (``c42aec75``) all three counts were taken before anything was
sacrificed, one prompt per seat: a Mishra's Factory given up as a land was
still owed as a creature, and a seat the other seat's land choice had evened up
was still made to sacrifice a creature (or, the other way round, kept one the
rules take).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


@pytest.fixture(scope="module")
def by_name():
    catalog = load_catalog()
    named = {card.name: card for card in catalog}
    named.update({unit.name: unit for unit in compilation_units(catalog)})
    return named


def _game(by_name, seats=2):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, by_name, name, seat):
    perm = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, perm, None)
    _nosick(perm)
    game._recompute_continuous_effects()
    return perm


def _animated_factory(game, by_name, seat):
    factory = _put(game, by_name, "Mishra's Factory", seat)
    result = game.activate_permanent_ability(
        seat, "Mishra's Factory",
        permanent_index=game.battlefield_index_of(factory), ability_index=1,
    )
    assert result.supported, result
    resolve_stack(game)
    game._recompute_continuous_effects()
    assert factory.is_creature and factory.has_type("land")
    return factory


def _cast_balance(game, by_name, seat=0):
    game.players[seat].hand.append(whole_card(by_name["Balance"]))
    result = game.cast_from_hand(seat, "Balance")
    assert result.supported, result
    game.resolve_top_of_stack()


def _names(perms):
    return sorted(perm.card.name for perm in perms)


def _card_names(cards):
    return sorted(card.name for card in cards)


def _board(by_name, interactive=()):
    """P0: an animated Mishra's Factory and a Plains (two lands, one creature).
    P1: a Forest and Grizzly Bears (one land, one creature)."""
    game = _game(by_name)
    factory = _animated_factory(game, by_name, 0)
    plains = _put(game, by_name, "Plains", 0)
    _put(game, by_name, "Forest", 1)
    bears = _put(game, by_name, "Grizzly Bears", 1)
    game.interactive_seats = set(interactive)
    return game, factory, plains, bears


@pytest.mark.cr("608.2c", "613.1d", "701.21a")
def test_a_land_creature_given_up_with_the_lands_is_not_counted_among_the_creatures(by_name):
    """P0 keeps the Plains and sacrifices the Factory as its extra land. Then
    the creatures are counted: P0 has none, P1 has its Bears — so P1 is the
    one who sacrifices a creature. Counted up front, P0 owed nothing and P1
    kept its Bears."""
    game, factory, plains, bears = _board(by_name, interactive={0})

    _cast_balance(game, by_name)
    assert game.confirm_balance(0, land_indices=[game.battlefield_index_of(factory)])
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert not game.is_on_battlefield(factory)
    assert game.is_on_battlefield(plains)
    assert not game.is_on_battlefield(bears)
    assert _names(game.controlled_by(1)) == ["Forest"]
    assert "Grizzly Bears" in _card_names(game.players[1].graveyard)
    assert not game.pending_choices
    assert "Balance" in _card_names(game.players[0].graveyard)


@pytest.mark.cr("608.2c", "613.1d", "701.21a")
def test_a_land_creature_kept_with_the_lands_is_counted_among_the_creatures(by_name):
    """The other answer to the same round: P0 sacrifices the Plains and keeps
    the Factory. Then each player has one creature, and nobody sacrifices
    one."""
    game, factory, plains, bears = _board(by_name, interactive={0})

    _cast_balance(game, by_name)
    assert game.confirm_balance(0, land_indices=[game.battlefield_index_of(plains)])
    resolve_stack(game)

    assert game.is_on_battlefield(factory)
    assert not game.is_on_battlefield(plains)
    assert game.is_on_battlefield(bears)
    assert not game.pending_choices
    assert "Balance" in _card_names(game.players[0].graveyard)


@pytest.mark.cr("608.2c", "613.1d")
def test_each_round_is_its_own_prompt_over_what_it_counts(by_name):
    """The shape of the rounds: the land round asks P0 alone, for one land,
    among the two its layer 4 says are lands — the creature count is not part
    of it, and an answer naming a creature that is not a land is refused."""
    game, factory, plains, bears = _board(by_name, interactive={0})

    _cast_balance(game, by_name)

    owed = game.pending_choices_of("balance")
    assert [(c.player_index, c.data["stage"], c.data["plan"]) for c in owed] == [
        (0, "lands", {"lands": 1, "creatures": 0, "hand": 0}),
    ]
    offered = game.balance_candidates(0, "lands")
    assert [perm for _slot, perm in offered] == [factory, plains]
    assert not game.confirm_balance(0, creature_indices=[game.battlefield_index_of(factory)])
    assert game.pending_choices_of("balance") == owed


@pytest.mark.cr("608.2c", "701.21a")
def test_a_seat_nobody_asks_answers_every_round_by_default(by_name):
    """The default keeps the lowest slots, round by round: P0's Plains (the
    later slot) goes with the lands; then each seat has one creature."""
    game, factory, plains, bears = _board(by_name)

    _cast_balance(game, by_name)
    # A table with no interactive seat holds nothing on the stack; its
    # prompts are drained by the defaults, one round arming the next.
    game.auto_resolve_pending_choices()

    assert game.is_on_battlefield(factory)
    assert not game.is_on_battlefield(plains)
    assert game.is_on_battlefield(bears)
    assert not game.pending_choices and not game.stack


@pytest.mark.cr("608.2c", "613.1d")
def test_an_opalescence_enchantment_is_counted_among_the_creatures(by_name):
    """"Each other non-Aura enchantment is a creature" — a Crusade under
    Opalescence is one of its controller's creatures for the last round."""
    game = _game(by_name)
    _put(game, by_name, "Opalescence", 0)
    crusade = _put(game, by_name, "Crusade", 0)
    game.interactive_seats = {0}
    assert crusade.is_creature

    _cast_balance(game, by_name)

    assert not game.confirm_balance(0, creature_indices=[])
    assert game.confirm_balance(0, creature_indices=[game.battlefield_index_of(crusade)])
    resolve_stack(game)

    assert not game.is_on_battlefield(crusade)
    assert _names(game.controlled_by(0)) == ["Opalescence"]


@pytest.mark.cr("608.2c", "701.9a")
def test_the_hand_round_discards_every_seats_cards_together(by_name):
    """"…no cards are revealed until all players have chosen what to
    discard, at which point those cards are all discarded simultaneously."
    The seats are asked in turn order from the active player, and the first
    seat's answer is held while the second still owes one."""
    game = _game(by_name, seats=3)
    game.players[0].hand = [by_name["Forest"], by_name["Island"], by_name["Plains"]]
    game.players[1].hand = [by_name["Swamp"], by_name["Mountain"]]
    # A third seat holding one card, so that both of the others owe a discard
    # (three and two cards once Balance has left its caster's hand).
    game.players[2].hand = [by_name["Forest"]]
    game.interactive_seats = {0, 1}

    _cast_balance(game, by_name)

    def owed():
        return [
            (c.player_index, c.data["plan"]["hand"])
            for c in game.pending_choices_of("balance")
        ]

    # The active player chooses first; the next seat is asked once it has.
    assert owed() == [(0, 2)]
    assert game.confirm_balance(0, hand_indices=[0, 2])
    assert len(game.players[0].hand) == 3, "held until every seat has chosen"
    assert game.players[0].graveyard == []
    assert owed() == [(1, 1)]

    assert game.confirm_balance(1, hand_indices=[1])
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert _card_names(game.players[0].graveyard) == ["Balance", "Forest", "Plains"]
    assert [card.name for card in game.players[1].hand] == ["Swamp"]
    assert _card_names(game.players[1].graveyard) == ["Mountain"]
