"""CR 701.23d for the exile search (``search_exile_cards``).

    701.23d If a player is searching a hidden zone simply for a quantity of
    cards, such as "a card" or "three cards," that player must find that many
    cards (or as many as possible, if the zone doesn't contain enough cards).
    701.23b If a player is searching a hidden zone for cards with a stated
    quality, such as a card with a certain card type or color, that player
    isn't required to find some or all of those cards even if they're present
    in that zone.

Four cards print the bare quantity into an exile pile — Foresight and
Manipulate Fate ("Search your library for three cards, exile them, then
shuffle"), Mangara's Tome ("…for five cards, exile them in a face-down pile")
and Parallel Thoughts ("…for seven cards") — and every one of them took
nothing: the resolver had no floor, the client offered "Take Nothing", and a
seat nobody asked exiled nothing wherever the pile never came back (Foresight,
Manipulate Fate). The floor is the one ``search_library`` already reads
(``Game._search_floor``); the "any number of <quality>" cards (Mana Severance,
Skyship Weatherlight, Chandra, Heart of Fire) keep their fail-to-find.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_QUANTITY = {"Foresight": 3, "Manipulate Fate": 3, "Mangara's Tome": 5, "Parallel Thoughts": 7}
_ANY_NUMBER = ("Mana Severance", "Skyship Weatherlight", "Chandra, Heart of Fire")


@pytest.fixture(scope="module")
def pool():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _exile_step(card):
    program = compile_card_oracle(card)
    roots = [*program.instructions]
    roots += [ability.instruction for ability in program.activated_abilities]
    roots += [trigger.instruction for trigger in program.triggered_abilities]
    return next(
        step for root in roots for step in _walk(root)
        if step.kind == "search_and_exile_matching"
    )


def _library(pool, size):
    names = ["Forest", "Grizzly Bears", "Sol Ring", "Lightning Bolt", "Island",
             "Disenchant", "Hill Giant", "Swamp", "Shock", "Plains"]
    return [pool[names[i % len(names)]] for i in range(size)]


def _search(pool, name, *, library_size=10, interactive=True):
    """Run *name*'s exile search for seat 0 over a library of *library_size*,
    returning the game, the seat and the prompt (None once answered)."""
    card = pool[name]
    me = PlayerState(name="P0", life=20, library=_library(pool, library_size))
    you = PlayerState(name="P1", life=20, library=_library(pool, 10))
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    source = None
    type_line = (card.type_line or "").lower()
    if "instant" not in type_line and "sorcery" not in type_line:
        source = Permanent(card=card)
        me.battlefield.append(source)
    game._execute_oracle_instruction(_exile_step(card), OracleExecutionContext(
        caster=me, target=you, card=card, source_permanent=source, trigger_context={},
    ))
    return game, me, game.pending_choice_of("search_exile_cards", 0)


def _picks(count):
    return [{"zone": "library", "index": index} for index in range(count)]


@pytest.mark.cr("701.23d")
@pytest.mark.parametrize("name", sorted(_QUANTITY))
def test_701_23d_a_person_cannot_find_fewer_than_the_number_printed(pool, name):
    """Nothing, or one short, is refused whole with the prompt kept and the
    library untouched; exactly the number printed is taken."""
    wanted = _QUANTITY[name]
    game, me, prompt = _search(pool, name)
    assert prompt is not None and game._search_floor(prompt) == wanted
    assert game.confirm_search_exile(0, []) is False
    assert game.confirm_search_exile(0, _picks(wanted - 1)) is False
    assert game.pending_choice_of("search_exile_cards", 0) is prompt
    assert len(me.library) == 10 and me.exile == []
    assert game.confirm_search_exile(0, _picks(wanted))
    assert len(me.exile) == wanted and len(me.library) == 10 - wanted


@pytest.mark.cr("701.23d")
@pytest.mark.parametrize("name", sorted(_QUANTITY))
def test_701_23d_a_seat_nobody_asks_finds_that_many(pool, name):
    """Foresight's and Manipulate Fate's pile never comes back, and the
    default that took nothing for them takes the floor; the Tome's and
    Parallel Thoughts' pile does, and the default takes the maximum — the same
    number here."""
    game, me, _prompt = _search(pool, name, interactive=False)
    game.auto_resolve_pending_choices()
    assert game.pending_choice_of("search_exile_cards", 0) is None
    assert len(me.exile) == _QUANTITY[name], game.log


@pytest.mark.cr("701.23d")
@pytest.mark.parametrize("name", sorted(_QUANTITY))
def test_701_23d_as_many_as_possible_from_a_short_library(pool, name):
    """"…or as many as possible": two cards are all a two-card library holds,
    so two is the floor — one is refused, the default takes both."""
    game, me, prompt = _search(pool, name, library_size=2)
    assert game._search_floor(prompt) == 2
    assert game.confirm_search_exile(0, _picks(1)) is False
    assert game.confirm_search_exile(0, _picks(2))
    assert len(me.exile) == 2 and me.library == []

    game, me, _prompt = _search(pool, name, library_size=2, interactive=False)
    game.auto_resolve_pending_choices()
    assert len(me.exile) == 2 and me.library == []


@pytest.mark.cr("701.23b")
@pytest.mark.parametrize("name", _ANY_NUMBER)
def test_701_23b_any_number_of_cards_with_a_quality_may_find_none(pool, name):
    game, me, prompt = _search(pool, name)
    assert prompt is not None and game._search_floor(prompt) == 0
    assert game.confirm_search_exile(0, [])
    assert me.exile == [] and len(me.library) == 10
