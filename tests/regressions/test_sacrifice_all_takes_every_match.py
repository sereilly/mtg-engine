""""Sacrifice **all** creatures you control." — every one, not one.

Found at Prophecy wave 1 (W1G6) while reading Keldon Firebombers' "each player
sacrifices all lands they control except for three". The forced-sacrifice
lowering had no reading of the quantifier "all": the payload carried no count,
the handler's default of one applied, and two shipped cards sacrificed a single
creature where they print a sweep. Death Pit Offering (MIR) kept two of three
creatures and still got its anthem; Living Death (TMP) left each player with
all but one of their creatures and then returned the graveyards on top.
Reproduced before the fix with three creatures a side.
"""

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import _mk_card, resolve_stack


def _card(name):
    for path in manifest_set_paths():
        for card in load_cards(path):
            if card.name == name:
                return card
    raise LookupError(name)


def _cast_over_three_creatures_a_side(name):
    game = Game(players=[
        PlayerState(name="P0", hand=[_card(name)]), PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    for seat in (0, 1):
        for beast in ("Bear", "Wolf", "Elk"):
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=_mk_card(f"{beast}{seat}", "Creature — Beast")), None
            )
    assert game.cast_from_hand(0, name).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game


def _creatures(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


def test_death_pit_offering_sacrifices_every_creature_you_control():
    game = _cast_over_three_creatures_a_side("Death Pit Offering")
    assert _creatures(game, 0) == []
    assert _creatures(game, 1) == ["Bear1", "Elk1", "Wolf1"]
    assert len(game.players[0].graveyard) == 3


def test_living_death_sacrifices_every_creature_on_both_sides():
    game = _cast_over_three_creatures_a_side("Living Death")
    assert _creatures(game, 0) == [] and _creatures(game, 1) == []
    assert len(game.players[0].graveyard) == 4  # three creatures and the spell
    assert len(game.players[1].graveyard) == 3
