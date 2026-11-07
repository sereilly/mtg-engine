"""Two defaults a seat nobody asks gives, read off the compiled program.

* **A pick that takes the permanent from somebody else** — "When this
  creature enters, an opponent chooses a permanent you control other than this
  creature and exiles it." (Wormfang Crab.) The opponent's default was the
  first candidate in board order: the Crab's controller's first land. It is
  the dearest now (``ai_prompt_readers.pick_is_taken_from_its_controller``,
  ``ai_standing.permanent_worth``), and only where the chooser controls none
  of the candidates.
* **A toggle** — "Whenever a player discards a card, you may pay {1}{U}. If
  you do, you may tap or untap target permanent." (Telekinetic Bonds.) No seat
  describes which way a toggle cuts, so the trigger's default target was the
  first permanent offered — the Bonds itself, tapped for {1}{U}. It is an
  opponent's untapped creature now, then one's own tapped one
  (``ai_target_sides.toggle_target_order``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_prompt_readers import pick_is_taken_from_its_controller
from engine.ai_target_sides import toggle_target_order, toggles_its_target
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


def _put(game, seat, card, *, tapped=False):
    permanent = _nosick(Permanent(card=card))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    permanent.tapped = tapped
    return permanent


def _settle(game) -> None:
    for _ in range(6):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
    resolve_stack(game)


def test_an_opponents_take_away_pick_is_the_dearest_permanent(set_pool):
    """Wormfang Crab enters under Alice; Bob, asked nothing, chooses which of
    her permanents it exiles — the Craw Wurm, not the first Island."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    crab = jud["Wormfang Crab"]
    assert pick_is_taken_from_its_controller(crab, "attach_host")
    game = Game(players=[
        PlayerState(name="Alice", hand=[crab], library=[lea["Island"]] * 5),
        PlayerState(name="Bob", library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    for card in (lea["Island"], lea["Island"], lea["Craw Wurm"], lea["Grizzly Bears"]):
        _put(game, 0, card)
    assert game.cast_from_hand(0, "Wormfang Crab").supported
    _settle(game)
    assert [card.name for card in game.players[0].exile] == ["Craw Wurm"]
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Grizzly Bears", "Island", "Island", "Wormfang Crab",
    ]


def test_a_pick_that_is_only_read_is_not_taken_away(set_pool):
    """The reader's other side: Guard Dogs' pick ("Choose a permanent you
    control. Prevent all combat damage target creature would deal this turn
    if it shares a color with that permanent.") is tested for a colour and
    stays where it is, so its default is not the dearest permanent."""
    assert not pick_is_taken_from_its_controller(
        set_pool("PLS")["Guard Dogs"], "attach_host",
    )


def _bonds_table(set_pool):
    """Alice: Telekinetic Bonds, two Islands and a Plains, Mind Twist in hand;
    Bob: one card to discard, an untapped Grizzly Bears and Forest. Alice's
    turn, nobody asked."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = Game(players=[
        PlayerState(name="Alice", hand=[lea["Mind Twist"]], library=[lea["Island"]] * 5),
        PlayerState(name="Bob", hand=[lea["Lightning Bolt"]], library=[lea["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    bonds = _put(game, 0, jud["Telekinetic Bonds"])
    for card in (lea["Island"], lea["Island"], lea["Plains"]):
        _put(game, 0, card)
    forest = _put(game, 1, lea["Forest"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    return game, bonds, forest, bears


def test_telekinetic_bonds_taps_the_opponents_creature_not_itself(set_pool):
    """Bob discards; Alice's trigger is aimed, its {1}{U} paid and the toggle
    made with nobody asked: Bob's untapped Bears is tapped — the default was
    the first permanent offered, the Bonds itself."""
    game, bonds, forest, bears = _bonds_table(set_pool)
    program = compile_card_oracle(set_pool("JUD")["Telekinetic Bonds"])
    assert toggles_its_target(program.triggered_abilities[0].instruction)
    result = game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=1)
    assert result.supported, result.details
    _settle(game)
    assert bears.tapped
    assert not bonds.tapped and not forest.tapped


def test_a_toggle_is_aimed_by_the_state_it_changes(set_pool):
    """The order itself: an opponent's untapped creature (the largest first),
    then one's own tapped creature, then an opponent's untapped land, then
    one's own tapped land; tapping one's own untapped permanent or untapping
    an opponent's tapped one is last."""
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="Alice", library=[lea["Island"]] * 5),
        PlayerState(name="Bob", library=[lea["Island"]] * 5),
    ])
    game.start_turn(0)
    my_tapped_land = _put(game, 0, lea["Island"], tapped=True)
    my_untapped_bear = _put(game, 0, lea["Grizzly Bears"])
    my_tapped_wurm = _put(game, 0, lea["Craw Wurm"], tapped=True)
    their_tapped_bear = _put(game, 1, lea["Grizzly Bears"], tapped=True)
    their_land = _put(game, 1, lea["Forest"])
    their_bear = _put(game, 1, lea["Grizzly Bears"])
    their_wurm = _put(game, 1, lea["Craw Wurm"])
    offered = [
        my_tapped_land, my_untapped_bear, my_tapped_wurm, their_tapped_bear,
        their_land, their_bear, their_wurm,
    ]
    assert toggle_target_order(game, 0, offered) == [
        their_wurm, their_bear, my_tapped_wurm, their_land, my_tapped_land,
        my_untapped_bear, their_tapped_bear,
    ]
