""""Add three mana in any combination of {R} and/or {G}": the split is the
producer's, announced with the activation (or the cast) as
``mana_combination`` — ``engine/mana_combination.py``.

``handlers/mana._split_mana_combination`` read the key and nothing wrote it,
so a mix (RRG) was unreachable on Goblin Clearcutter, Orcish Lumberjack and
Burnt Offering: every unit was one colour. Now the activation and cast paths
carry it, refuse a malformed split before anything is paid, and a seat that
names none gets units toward what its own hand asks for.
"""
from __future__ import annotations

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import _nosick, resolve_stack


def _board(set_pool, source: str, *, hand=()):
    """Seat 0 with *source* (unsick) and one Forest; costs unenforced."""
    lgn, ice, lea = set_pool("LGN"), set_pool("ICE"), set_pool("LEA")
    pool = {**lea, **ice, **lgn}
    maker = Permanent(card=pool[source])
    forest = Permanent(card=lea["Forest"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[maker, forest], hand=[pool[n] for n in hand]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    _nosick(maker)
    return game, maker, forest


def _made(game) -> dict:
    pool = game.players[0].mana_pool
    return {symbol: pool[symbol] for symbol in pool if pool[symbol]}


def test_goblin_clearcutter_makes_the_split_its_activator_names(set_pool):
    game, _maker, forest = _board(set_pool, "Goblin Clearcutter")

    result = game.activate_permanent_ability(
        0, "Goblin Clearcutter", mana_combination={"R": 2, "G": 1},
    )

    assert result.supported, result.details
    assert not game.is_on_battlefield(forest), "the Forest paid the cost"
    assert _made(game) == {"R": 2, "G": 1}


def test_a_split_the_ability_does_not_offer_is_refused_before_any_cost(set_pool):
    """An unlisted symbol, or the wrong total: refused whole, and nothing paid
    — the Forest is still there and the Clearcutter untapped (CR 602.2b
    routes the announcement through CR 601.2b, ahead of the costs)."""
    for split, reason in (
        ({"U": 3}, "may be only"),
        ({"R": 2, "G": 2}, "add up to 3"),
        ({"R": 4, "G": -1}, "negative"),
    ):
        game, maker, forest = _board(set_pool, "Goblin Clearcutter")
        result = game.activate_permanent_ability(
            0, "Goblin Clearcutter", mana_combination=split,
        )
        assert not result.supported, split
        assert reason in result.details, (split, result.details)
        assert game.is_on_battlefield(forest) and not maker.tapped
        assert _made(game) == {}


def test_a_seat_that_names_no_split_gets_what_its_hand_asks_for(set_pool):
    """No split, no colour named: one unit each to the {G} and the {R} the
    held Llanowar Elves and Lightning Bolt ask for, the third the first
    printed symbol. With nothing in hand it is every unit the first symbol, as
    before; a colour named is every unit that colour, as before."""
    game, _maker, _forest = _board(
        set_pool, "Orcish Lumberjack", hand=("Llanowar Elves", "Lightning Bolt"),
    )
    assert game.activate_permanent_ability(0, "Orcish Lumberjack").supported
    assert _made(game) == {"R": 2, "G": 1}

    game, _maker, _forest = _board(set_pool, "Orcish Lumberjack")
    assert game.activate_permanent_ability(0, "Orcish Lumberjack").supported
    assert _made(game) == {"R": 3}

    game, _maker, _forest = _board(
        set_pool, "Orcish Lumberjack", hand=("Llanowar Elves", "Lightning Bolt"),
    )
    assert game.activate_permanent_ability(0, "Orcish Lumberjack", mana_color="G").supported
    assert _made(game) == {"G": 3}


def test_burnt_offering_makes_the_split_its_caster_names(set_pool):
    """"Add X mana in any combination of {B} and/or {R}, where X is the
    sacrificed creature's mana value." A Hill Giant (mana value 4) gives four;
    the caster names one black and three red."""
    lea, ice = set_pool("LEA"), set_pool("ICE")
    giant = Permanent(card=lea["Hill Giant"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[giant], hand=[ice["Burnt Offering"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()

    refused = game.cast_from_hand(0, "Burnt Offering", mana_combination={"G": 4})
    assert not refused.supported and "may be only" in refused.details
    assert game.is_on_battlefield(giant), "refused before the creature was paid"

    result = game.cast_from_hand(0, "Burnt Offering", mana_combination={"B": 1, "R": 3})
    assert result.supported, result.details
    resolve_stack(game)
    assert not game.is_on_battlefield(giant)
    assert _made(game) == {"B": 1, "R": 3}
