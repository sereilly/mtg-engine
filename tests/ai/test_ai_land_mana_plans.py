"""What the AI's tap plan believes a land makes, against what the tap makes.

Planeshift wave 1, group 5 (lands and mana). Three defects in already-shipped
lands, each found by driving a Planeshift land and each the same shape: the
planner read Scryfall's ``produced_mana`` summary, or its own arithmetic over
it, where the engine's tap seam does something narrower — so a cost was planned
as payable, the taps came up short, and the cast was refused. Nothing crashes
and no rule is broken; the seat proposes the same spell again next turn.

* a land whose tap makes **two different symbols** ("{T}: Add {C}{U}.") was
  credited as two of whichever one symbol the plan asked for;
* a land whose **entry trigger would sacrifice it** was the chooser's first
  pick on turn one, because it adds more colours than a basic;
* a land whose colours **the board defines** (Reflecting Pool) was five
  colours to every planner — that one is pinned beside its card, in
  ``tests/sets/test_tmp_lands.py``.

Each test names how many lands it examined, because a census that examined
nothing passes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.ai_policy import _land_mixed_run, _plan_land_taps, choose_land_drop
from engine.ai_valuation import entry_sacrifice_is_unavoidable
from engine.card_loader import manifest_set_paths
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def pool() -> dict:
    return {card.name: card for card in load_cards(manifest_set_paths())}


def _board(pool, *, mine=(), hand=()):
    """Seat 0 with *mine* on the battlefield and *hand* in hand, costs enforced."""
    me = PlayerState(
        name="A",
        battlefield=[Permanent(card=pool[name]) for name in mine],
        hand=[pool[name] for name in hand],
    )
    game = Game(players=[me, PlayerState(name="B")])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    return game


def _floating(game) -> dict[str, int]:
    return {s: n for s, n in game.players[0].mana_pool.items() if n}


def _mixed_run_lands(pool) -> list[str]:
    """Every shipped land whose tap-alone mana ability makes a fixed run of two
    or more different symbols."""
    found = []
    for card in pool.values():
        if card.primary_type != "land":
            continue
        for ability in compile_card_oracle(card).activated_abilities:
            if ability.instruction is None or not is_tap_alone_mana_ability(ability):
                continue
            pips = (ability.instruction.payload or {}).get("pips")
            if pips and len({symbol for symbol, _count in pips}) >= 2:
                found.append(card.name)
    return sorted(found)


def test_a_mixed_run_is_planned_as_the_symbols_it_makes(pool):
    """Coral Atoll taps for {C}{U}. Alone it cannot pay {U}{U}, and the plan
    used to say it could (two mana, both credited as the {U} it was asked for):
    the tap made {C}{U} and the cast was refused "insufficient mana". With an
    Island beside it the same cost is payable, and {1}{U} is payable alone."""
    game = _board(pool, mine=["Coral Atoll"])
    assert _plan_land_taps(game, game.players[0], {"U": 2}) is None
    assert _plan_land_taps(game, game.players[0], {"U": 1, "generic": 1}) is not None

    game = _board(pool, mine=["Coral Atoll", "Island"])
    slots, _asked = _plan_land_taps(game, game.players[0], {"U": 2})
    assert sorted(slots) == [0, 1]


def test_every_mixed_run_land_is_planned_for_what_its_tap_makes(pool):
    """The census behind the fix, over the shipped pool: for each such land,
    the plan's belief about one tap (`_land_mixed_run`) is exactly what the
    tap seam puts in the pool — and a cost of two of either symbol is never
    planned on the land alone.

    Validated backwards when it was written: with `take` crediting `amount` of
    one symbol, the last assertion fails for all seven.
    """
    names = _mixed_run_lands(pool)
    assert len(names) >= 7, names

    for name in names:
        game = _board(pool, mine=[name])
        (land,) = list(game.controlled_by(0))
        believed = _land_mixed_run(game, land)
        assert believed is not None, name

        assert game.tap_land_for_mana(0, name, "G", permanent_id=land.permanent_id)
        assert _floating(game) == believed, name

        for symbol in believed:
            fresh = _board(pool, mine=[name])
            assert _plan_land_taps(fresh, fresh.players[0], {symbol: 2}) is None, (
                name, symbol,
            )


def _entry_sacrifice_lands(pool) -> list[str]:
    """Every shipped land its own entry trigger sacrifices on an empty board."""
    empty = _board(pool)
    return sorted(
        card.name for card in pool.values()
        if card.primary_type == "land"
        and entry_sacrifice_is_unavoidable(empty, 0, card)
    )


def test_the_ai_never_plays_a_land_into_its_own_sacrifice(pool):
    """"When this land enters, sacrifice it unless you return an untapped
    Plains you control to its owner's hand." (Karoo and its four siblings.)
    Read off the compiled entry trigger: with nothing to return, the land is
    not a land drop at all — the seat plays the basic beside it, or holds —
    and once the price can be met it is. An ordinary land is never held."""
    names = _entry_sacrifice_lands(pool)
    assert len(names) >= 5, names
    assert not entry_sacrifice_is_unavoidable(_board(pool), 0, pool["Forest"])
    assert not entry_sacrifice_is_unavoidable(_board(pool), 0, pool["Tundra"])

    for name in names:
        alone = _board(pool, hand=[name])
        assert choose_land_drop(alone, 0) is None, name

        with_basic = _board(pool, hand=[name, "Forest"])
        drop = choose_land_drop(with_basic, 0)
        assert drop is not None
        assert with_basic.players[0].hand[drop.hand_index].name == "Forest", name

    payable = _board(pool, mine=["Plains"], hand=["Karoo"])
    assert not entry_sacrifice_is_unavoidable(payable, 0, pool["Karoo"])
    drop = choose_land_drop(payable, 0)
    assert drop is not None and payable.players[0].hand[drop.hand_index].name == "Karoo"

    tapped = _board(pool, mine=["Plains"], hand=["Karoo"])
    next(iter(tapped.controlled_by(0))).tapped = True
    assert entry_sacrifice_is_unavoidable(tapped, 0, pool["Karoo"]), (
        "the price is an *untapped* Plains"
    )
