"""Census: does an AI seat announce, for a permanent's entry trigger, a seat
**that trigger may name**?

This engine names an entry trigger's target as the permanent is cast, and
holds the announcement to what the trigger could choose for itself as it is
put on the stack (CR 603.3d, ``Game.entry_trigger_cast_targets``): a seat it
could not choose is set aside there and chosen again. So a wrong announcement
is not a wrong game — it is a log line saying the cast named something the
trigger refused, and a decision the policy did not make.

``ai_scoring._choose_target_for_spell`` read the seat off what the trigger
*does* (``entry_trigger_seat_side``: a denial is aimed across the table) and
otherwise gave a permanent's seat to its caster. "When this creature enters,
**target opponent** gains control of it" (Sleeper Agent) does nothing that
reads as a denial, so the caster named itself.

**How it is built.** The population is every supported permanent in the
shipped pool and the measured sets whose cast's picker — the trigger's own
list — offers a player. Each is put alone in seat 0's hand on an empty table
and ``choose_cast_action`` asked; the seat its announcement names must be one
that list offers.

Validated backwards on the tree before the fix: 20 permanents examined, and
seven of them named the caster for a trigger that may name only an opponent
(``NAMED_ITS_OWN_SEAT``) — the seven Torment's W1G3 saw in its drive list.
"""
from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_cards, manifest_set_paths
from engine.oracle import compile_card_oracle

ME, OPP = 0, 1

#: The seven the census named on the tree before the fix.
NAMED_ITS_OWN_SEAT = frozenset({
    "Honorable Scout", "Hypnox", "Kitesail Freebooter", "Lord of Tresserhorn",
    "Mesmeric Fiend", "Sleeper Agent", "Telepathic Spies",
})


def _pool() -> dict:
    cards: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


POOL = _pool()


def _table(card) -> Game:
    forest = POOL["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[card], library=[forest] * 10),
        PlayerState(name="Opp", hand=[forest], library=[forest] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _trigger_seats(game: Game, card) -> list[int]:
    legal = game.entry_trigger_cast_targets(ME, card) or []
    return sorted({
        entry["seat"] for entry in legal
        if entry.get("kind") == "player" and isinstance(entry.get("seat"), int)
    })


def population() -> list:
    found = []
    for name in sorted(POOL):
        card = POOL[name]
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        if not compile_card_oracle(card).supported:
            continue
        if _trigger_seats(_table(card), card):
            found.append(card)
    return found


POPULATION = population()


def test_the_census_examines_what_it_says():
    names = {card.name for card in POPULATION}
    assert len(POPULATION) >= 20, len(POPULATION)
    assert NAMED_ITS_OWN_SEAT <= names, sorted(NAMED_ITS_OWN_SEAT - names)


@pytest.mark.parametrize("card", POPULATION, ids=lambda card: card.name)
def test_the_announced_seat_is_one_the_trigger_may_name(card):
    game = _table(card)
    legal = _trigger_seats(game, card)
    random.seed(1337)
    action = choose_cast_action(game, ME)
    if action is None:
        return  # not proposed at all: nothing announced, nothing to hold
    assert action.target_player_index in legal, (
        f"{card.name} announced seat {action.target_player_index}; "
        f"its entry trigger may name {legal}"
    )


def test_sleeper_agent_is_cast_at_the_opponent_and_nothing_is_set_aside():
    """The behaviour behind the census: the announcement is the trigger's
    target as it goes on the stack, so nothing is re-chosen and the creature
    goes to the seat the cast named."""
    from tests.helpers import resolve_stack

    card = POOL["Sleeper Agent"]
    game = _table(card)
    random.seed(1337)
    action = choose_cast_action(game, ME)
    assert action is not None and action.target_player_index == OPP
    logged = len(game.log)
    game.cast_from_hand(ME, card.name, target_player_index=action.target_player_index)
    resolve_stack(game)
    lines = game.log[logged:]
    # The line `_stack_push` writes when it sets the cast's announcement aside.
    assert not any("chooses again (603.3d)" in line for line in lines), lines
    assert any(perm.card.name == "Sleeper Agent" for perm in game.controlled_by(OPP)), lines
