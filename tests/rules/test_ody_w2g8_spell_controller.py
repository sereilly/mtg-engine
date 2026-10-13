"""A spell on the stack has a controller, and a target that names the spell
names that player (CR 112.2, CR 109.4).

"Counter target spell. **Its controller** loses 3 life." (Undermine, shipped
at Invasion.) The possessive is about the spell the sentence chose, and until
Odyssey's wave 2 nothing in the engine could answer it:

* the life loss lowered to the record a **destroy** step writes, which a
  counter step never does — so Undermine compiled supported, logged "no
  destroyed creature, no life lost" and had never made anyone lose life;
* any rider spelled "that spell's controller" or "that player" read the
  resolution's target seat, and a stack target named none: the seat field
  beside it held nothing from a headless caller and the web route's default
  (the caster's opponent) from the browser. Right when the spell was an
  opponent's, wrong when it was the caster's own, and at three seats it was
  ``1 - caster`` whoever had cast the spell.

Three cards stood on the class — Undermine, Divert ("…unless **that spell's
controller** pays {2}", asked of the opponent when the caster Diverted their
own spell) and, by the same lowering reading the same kind of record for a
permanent, Kavu Lair (see ``tests/regressions/test_ody_w2g8_spell_controller_census.py``).

The rule about the counter itself is a ruling, not a memory: Countersquall
prints Undermine's sentence with a different number, and Scryfall's ruling of
2018-12-07 on it reads "A spell that can't be countered is a legal target for
Countersquall. The spell won't be countered when Countersquall resolves, but
its controller still loses 2 life." Undermine has no ruling of its own; the
sentence has no "if you do", and CR 101.3 ignores only the part that is
impossible.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.game_types import StackItem
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack


def _lookup(set_pool, name):
    if not isinstance(name, str):
        return name
    for code in ("INV", "ODY", "LEA", "APC"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _table(set_pool, hand=(), seats=2, interactive=()):
    forest = set_pool("LEA")["Forest"]
    players = [
        PlayerState(f"P{seat + 1}", library=[forest] * 20, hand=[])
        for seat in range(seats)
    ]
    players[0].hand = [_lookup(set_pool, name) for name in hand]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.turn += 1
    game.start_turn(0)
    return game


def _spell_on_stack(game, set_pool, name, controller, owner=None):
    """*name* on the stack as a spell *controller* cast, owned by *owner*."""
    item = StackItem(
        card=_lookup(set_pool, name), caster_index=controller,
        owner_index=controller if owner is None else owner,
        target_player_index=None, target_permanent_index=None, x_value=None,
    )
    game._stack_push(item)
    return item


def _settle(game):
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _lives(game):
    return [player.life for player in game.players]


# --- Undermine ---------------------------------------------------------------

@pytest.mark.cr("112.2", "701.6a")
def test_undermine_drains_the_opponent_whose_spell_it_counters(set_pool):
    game = _table(set_pool, hand=["Undermine"])
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=1)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    _settle(game)

    assert _lives(game) == [20, 17]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("112.2", "109.5")
def test_undermine_at_your_own_spell_drains_you(set_pool):
    """The seat is the spell's controller — not "the caster's opponent", which
    is what every reader of an unnamed seat defaulted to."""
    game = _table(set_pool, hand=["Undermine"])
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=0)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    _settle(game)

    assert _lives(game) == [17, 20]


@pytest.mark.cr("112.2")
def test_undermine_follows_the_spell_past_the_seat_the_wire_sends(set_pool):
    """The web route rides a default seat on every cast (the caster's
    opponent). A stack target is not a chosen player, so that seat is not who
    the spell is about."""
    game = _table(set_pool, hand=["Undermine"])
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=0)

    assert game.queue_from_hand(
        0, "Undermine", target_stack_index=0, target_player_index=1,
    ).supported
    _settle(game)

    assert _lives(game) == [17, 20]


@pytest.mark.cr("112.2", "108.3", "109.4")
def test_undermine_charges_the_controller_of_a_spell_somebody_else_owns(set_pool):
    """An opponent's spell of a card *you* own (cast out of your pile): the
    controller loses the life (CR 112.2) and the card goes to its owner's
    graveyard (CR 701.6a)."""
    game = _table(set_pool, hand=["Undermine"])
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=1, owner=0)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    _settle(game)

    assert _lives(game) == [20, 17]
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard]
    assert game.players[1].graveyard == []


@pytest.mark.cr("112.2")
def test_undermine_names_the_right_player_at_three_seats(set_pool):
    """``1 - caster`` is seat 1; the spell is seat 2's."""
    game = _table(set_pool, hand=["Undermine"], seats=3)
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=2)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    _settle(game)

    assert _lives(game) == [20, 20, 17]


@pytest.mark.cr("101.3", "701.6a")
def test_a_spell_that_cannot_be_countered_still_costs_its_controller(set_pool):
    """Countersquall's ruling (2018-12-07), for the same sentence: the spell
    is a legal target, it is not countered, "but its controller still loses"
    the life."""
    game = _table(set_pool, hand=["Undermine"])
    obliterate = _spell_on_stack(game, set_pool, "Obliterate", controller=1)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    assert game.resolve_top_of_stack()

    assert _lives(game) == [20, 17]
    assert any(item is obliterate for item in game.stack)


@pytest.mark.cr("608.2b")
def test_undermine_does_nothing_once_its_spell_has_left(set_pool):
    """Every target illegal: the object leaves the stack unresolved, and no
    part of it happens to anybody."""
    game = _table(set_pool, hand=["Undermine"])
    bears = _spell_on_stack(game, set_pool, "Grizzly Bears", controller=1)

    assert game.queue_from_hand(0, "Undermine", target_stack_index=0).supported
    game.stack = [item for item in game.stack if item is not bears]
    _settle(game)

    assert _lives(game) == [20, 20]


# --- the same seat, asked by other sentences ---------------------------------

@pytest.mark.cr("112.2", "118.12a")
def test_divert_asks_the_controller_of_the_spell_it_is_aimed_at(set_pool):
    """"Change the target of target spell with a single target unless **that
    spell's controller** pays {2}." Aimed at the caster's own spell the toll
    was offered to the opponent."""
    for controller in (0, 1):
        game = _table(set_pool, hand=["Divert"], interactive=(0, 1))
        island = set_pool("LEA")["Island"]
        for seat in (0, 1):
            for _ in range(2):
                game._put_permanent_onto_battlefield(
                    seat, Permanent(card=island), None
                )
        spell = _spell_on_stack(game, set_pool, "Ancestral Recall", controller=controller)
        spell.target_player_index = 1 - controller

        assert game.queue_from_hand(0, "Divert", target_stack_index=0).supported
        game.resolve_top_of_stack(pause_for_choices=True)

        assert [(c.kind, c.player_index) for c in game.pending_choices] == [
            ("optional_pay", controller)
        ]


@pytest.mark.cr("112.2")
@pytest.mark.parametrize("phrase", [
    "its controller", "that spell's controller", "that player",
])
@pytest.mark.parametrize("controller", [0, 1])
def test_a_damage_rider_reaches_the_countered_spells_controller(
    set_pool, phrase, controller
):
    """The sentence no shipped card prints and several real ones do (Essence
    Backlash, Psychic Strike's kin): an invented card with the same words must
    work, because the seat is the announcement's and not one card's."""
    probe = _mk_card(
        "Probe Backlash", "{1}{U}", "Instant",
        f"Counter target spell. Probe Backlash deals 2 damage to {phrase}.",
    )
    game = _table(set_pool, hand=[probe])
    _spell_on_stack(game, set_pool, "Grizzly Bears", controller=controller)

    assert game.queue_from_hand(0, "Probe Backlash", target_stack_index=0).supported
    _settle(game)

    expected = [20, 20]
    expected[controller] = 18
    assert _lives(game) == expected


@pytest.mark.cr("112.2", "115.1")
def test_a_spell_that_also_targets_a_permanent_keeps_that_permanents_seat(set_pool):
    """Suffocating Blast names a spell *and* a creature. The creature's
    battlefield is the seat that announcement settled, and the spell beside it
    does not take it over."""
    game = _table(set_pool, hand=["Suffocating Blast"])
    bears = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    spell = _spell_on_stack(game, set_pool, "Lightning Bolt", controller=0)
    spell.target_player_index = 1

    item = StackItem(
        card=_lookup(set_pool, "Suffocating Blast"), caster_index=0,
        target_player_index=1, target_permanent_index=None,
        target_permanent_id=[None, bears.permanent_id], x_value=None,
        target_stack_item=spell,
    )
    assert game.stack_target_seat(item) is None
