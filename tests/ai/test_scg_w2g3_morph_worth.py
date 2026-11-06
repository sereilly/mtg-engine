"""A morph is turned face up for what the face-up creature does, never for its
mana value (SCG W2G3).

W1G5: the special-action chooser rehearses a turn-up (CR 702.37e) and reads
the standing, which prices each permanent's cost as CR 613 reads it
(``ai_rehearsal.permanent_worth``) — the face-down blank's is 0 (CR 708.2a),
the face-up card's its own. So every turn-up read as its card's whole mana
value gained, and the AI turned up Scornful Egotist (a 1/1 for {7}{U}) for
its {U} to shrink a 2/2. The turn-up is now rehearsed with the permanent at
its blank's cost on both copies (``ai_rehearsal.priced_as_their_blanks``).

And Mischievous Quanar's "{3}{U}{U}: Turn this creature face down." was
scored flat (2.5, ``ai_abilities``) and activated every main phase with no
spell for its turn-up trigger to copy; it is now a rewrite of what its source
is, rehearsed (``ai_abilities._OWN_REWRITE_KINDS``).

Validated backwards: on ``843cf32a`` the census reads 124 of its 188
decisions differently for a card and its cost-stripped twin, 29 of them a
turn-up taken only for the mana value (Scornful Egotist, Zombie Cutthroat,
Skinthinner, Daru Healer, Voidmage Prodigy, …).
"""

from __future__ import annotations

import dataclasses

import pytest

from engine.ai_abilities import choose_activation_action
from engine.ai_special_actions import choose_special_action
from engine.card_loader import load_catalog
from engine.face_down import face_down_card, morph_cost
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick

#: How many morph creatures the census must weigh (94 across both roles on
#: the base: Onslaught's, Legions' and Scourge's, and their reprints).
_MORPH_FLOOR = 80

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _pool(set_pool) -> dict:
    return {**{card.name: card for card in load_catalog()}, **set_pool("SCG")}


def _table(pool, own, other=(), *, lands=None) -> Game:
    """Seat 0 in its precombat main phase with *own* (cards, or permanents)
    and *lands* (three of every basic by default), seat 1 with *other*."""
    game = Game(players=[
        PlayerState(name="AI", library=[pool["Island"]] * 10),
        PlayerState(name="Opp", library=[pool["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    lands = [name for name in _BASICS for _ in range(3)] if lands is None else lands
    for permanent in [*own, *(Permanent(card=pool[name]) for name in lands)]:
        game.players[0].battlefield.append(_nosick(permanent))
    for name in other:
        game.players[1].battlefield.append(_nosick(Permanent(card=pool[name])))
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def _face_down(card) -> Permanent:
    return Permanent(card=face_down_card(card))


def _turn_up(pool, card, other=()):
    choice = choose_special_action(_table(pool, [_face_down(card)], other), 0)
    return None if choice is None else round(choice.worth, 6)


@pytest.mark.full
def test_a_morph_is_turned_up_the_same_whatever_its_mana_value(set_pool):
    """Each morph creature face down alone over three of every basic, against
    an empty board and a Grizzly Bears: the turn-up is weighed exactly as it
    is for the same card with no mana cost — the cost is the card's whether
    it is face up or down, and not what turning it up buys."""
    pool = _pool(set_pool)
    morphs = sorted(
        (
            card for card in pool.values()
            if card.primary_type == "creature" and morph_cost(card) is not None
        ),
        key=lambda card: card.name,
    )
    differ = []
    for card in morphs:
        twin = dataclasses.replace(card, mana_cost="", cmc=0.0)
        for other in ((), ("Grizzly Bears",)):
            real, free = _turn_up(pool, card, other), _turn_up(pool, twin, other)
            if real != free:
                differ.append((card.name, other, real, free))
    assert len(morphs) >= _MORPH_FLOOR, len(morphs)
    assert not differ, differ


@pytest.mark.parametrize("other", [(), ("Grizzly Bears",)])
def test_scornful_egotist_is_not_turned_up_to_shrink(set_pool, other):
    pool = _pool(set_pool)
    assert _turn_up(pool, pool["Scornful Egotist"], other) is None


def test_a_turn_up_that_buys_a_bigger_body_is_still_taken(set_pool):
    """Titanic Bulvox face up is a 7/4 trampler: worth its {4}{G}{G}{G}."""
    pool = _pool(set_pool)
    game = _table(pool, [_face_down(pool["Titanic Bulvox"])], ["Grizzly Bears"])
    choice = choose_special_action(game, 0)
    assert choice is not None and choice.kind == "turn_face_up"


def test_mischievous_quanar_does_not_turn_itself_face_down_for_nothing(set_pool):
    """Face up, five Islands, nothing on the stack for its turn-up trigger to
    copy: paying {3}{U}{U} to become the blank 2/2 is not proposed."""
    pool = _pool(set_pool)
    game = _table(
        pool, [Permanent(card=pool["Mischievous Quanar"])], ["Grizzly Bears"],
        lands=["Island"] * 5,
    )
    assert choose_activation_action(game, 0) is None
