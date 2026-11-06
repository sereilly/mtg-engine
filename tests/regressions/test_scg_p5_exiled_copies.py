"""Two copies of one card in one exile, from two exiling effects, are two
objects — and every record about one names that one (CR 400.7, 406.3).

A deck repeats one immutable ``CardDefinition`` per copy, so before
``Game.put_card_into_exile`` an exile could hold the same Python object twice,
and every reader of a record mapped the object back to the *first* position
holding it. Scourge's post-promotion browser session met it twice:

* **Repro A** (human vs AI). Dimensional Breach exiled a Temple of the False
  God, a Mountain, a Forest and a Goblin Warchief face up; Parallel Thoughts
  then exiled seven cards face down, a copy of each of those four among them.
  Both seats saw the four *pile* cards by name and the four *Breach* cards as
  ``<hidden>``, and taking the pile's top card (the Temple) took the Breach's
  Temple out of exile and left the pile's.
* **Repro B** (human vs human). Three Wishes exiled a Mountain face down;
  Mangara's Tome's pile then took a Mountain. The owner saw the Tome's
  Mountain face up and Three Wishes' hidden, ``castable_from_zones`` listed
  both under Three Wishes, and the Tome's was played from the exile viewer.

The pool-wide census is ``tests/engine/test_scg_p5_exiled_copies_census.py``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import permission_for, playable_from_zones
from engine.exiled_records import live_records
from engine.linked_exile import linked_entries
from engine.models import Permanent
from tests.helpers import resolve_stack
from web.serialization import _exile_payload


def _pool():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _game(library, *, interactive=()):
    game = Game(players=[
        PlayerState(name="Me", library=list(library)),
        PlayerState(name="Opp", library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _settle(game):
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _positions(pile, card):
    return [index for index, held in enumerate(pile) if held is card]


def test_no_exile_ever_holds_one_object_twice():
    """The seam's own guarantee: the second copy of an object to arrive is a
    new object, equal by value."""
    pool = _pool()
    mountain = pool["Mountain"]
    game = _game([])
    first = game.put_card_into_exile(0, mountain)
    second = game.put_card_into_exile(0, mountain)
    other_seat = game.put_card_into_exile(1, mountain)
    assert first is mountain
    assert second is not mountain and second == mountain
    assert other_seat is not mountain and other_seat is not second
    assert [len(_positions(p.exile, held)) for p in game.players for held in p.exile] == [1, 1, 1]


def _breach_then_parallel_thoughts(pool, *, interactive=()):
    """Repro A, in miniature: a Mountain exiled by Dimensional Breach (face
    up), then a Parallel Thoughts pile holding the same object's other copy."""
    mountain = pool["Mountain"]
    others = [pool[name] for name in (
        "Forest", "Island", "Swamp", "Plains", "Grizzly Bears", "Giant Growth",
    )]
    game = _game([mountain, *others, *([pool["Island"]] * 6)], interactive=interactive)
    game.start_turn(0)
    game._put_permanent_onto_battlefield(0, Permanent(card=mountain), None)
    breach = pool["Dimensional Breach"]
    game.players[0].hand.append(breach)
    assert game.cast_from_hand(0, "Dimensional Breach").supported
    _settle(game)
    (breach_mountain,) = [card for card in game.players[0].exile if card.name == "Mountain"]
    assert breach_mountain is mountain
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Parallel Thoughts"]), None,
    )
    _settle(game)
    return game, breach_mountain


def test_the_breach_card_shows_and_the_pile_card_is_hidden():
    pool = _pool()
    game, breach_mountain = _breach_then_parallel_thoughts(pool)
    exile = game.players[0].exile
    mountains = [index for index, held in enumerate(exile) if held.name == "Mountain"]
    assert len(mountains) == 2
    (pile_mountain,) = [exile[index] for index in mountains if exile[index] is not breach_mountain]
    thoughts = next(
        perm for perm in game.all_permanents() if perm.card.name == "Parallel Thoughts"
    )
    assert any(entry["card"] is pile_mountain for entry in linked_entries(thoughts))
    for viewer in (0, 1):
        shown = _exile_payload(game, game.players[0], viewer, 0)
        breach_slot = _positions(exile, breach_mountain)[0]
        pile_slot = _positions(exile, pile_mountain)[0]
        assert shown[breach_slot] != "<hidden>" and shown[breach_slot]["name"] == "Mountain"
        assert shown[pile_slot] == "<hidden>"
        assert shown.count("<hidden>") == 7


def test_taking_the_piles_top_card_takes_the_pile_card():
    pool = _pool()
    game, breach_mountain = _breach_then_parallel_thoughts(pool)
    thoughts = next(
        perm for perm in game.all_permanents() if perm.card.name == "Parallel Thoughts"
    )
    # Every card of the pile out through the draw replacement, the Mountain
    # among them; the Breach's Mountain never moves.
    for _ in range(7):
        game._draw_with_replacements(game.players[0], 1)
        game.auto_resolve_pending_choices()
        assert any(held is breach_mountain for held in game.players[0].exile)
    assert not linked_entries(thoughts)
    assert [card.name for card in game.players[0].exile if card is not breach_mountain
            and card.name == "Mountain"] == []
    # …and the Breach's "for as long as any of those cards remain exiled"
    # still has its card.
    assert any(record.card is breach_mountain for record in live_records(game))


def _three_wishes_then_mangaras_tome(pool):
    """Repro B: Three Wishes' face-down Mountain, then a Mangara's Tome pile
    holding the same object's other copy."""
    mountain = pool["Mountain"]
    library = [
        mountain, pool["Island"], pool["Swamp"],
        mountain, pool["Forest"], pool["Plains"], pool["Grizzly Bears"], pool["Giant Growth"],
    ]
    game = _game(library, interactive={0})
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].hand.append(pool["Three Wishes"])
    assert game.cast_from_hand(0, "Three Wishes").supported
    _settle(game)
    wishes = list(game.players[0].exile)
    assert [card.name for card in wishes] == ["Mountain", "Island", "Swamp"]
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Mangara's Tome"]), None)
    _settle(game)
    return game, wishes


def test_three_wishes_card_is_the_one_its_caster_sees_and_may_play():
    pool = _pool()
    game, wishes = _three_wishes_then_mangaras_tome(pool)
    exile = game.players[0].exile
    tome = next(perm for perm in game.all_permanents() if perm.card.name == "Mangara's Tome")
    piled = [entry["card"] for entry in linked_entries(tome)]
    assert len(piled) == 5
    (tome_mountain,) = [card for card in piled if card.name == "Mountain"]
    assert tome_mountain is not wishes[0]
    shown = _exile_payload(game, game.players[0], 0, 0)
    assert shown[_positions(exile, wishes[0])[0]]["name"] == "Mountain"
    assert shown[_positions(exile, tome_mountain)[0]] == "<hidden>"
    # Three Wishes' permission covers its three cards and nothing of the pile.
    entries = playable_from_zones(game, 0)
    offered = [exile[entry["index"]] for entry in entries if entry["zone"] == "exile"]
    assert len(offered) == 3
    assert all(any(card is held for held in wishes) for card in offered)
    assert not any(card is tome_mountain for card in offered)


def test_the_tomes_mountain_cannot_be_played_and_three_wishes_mountain_can():
    pool = _pool()
    game, wishes = _three_wishes_then_mangaras_tome(pool)
    exile = game.players[0].exile
    tome = next(perm for perm in game.all_permanents() if perm.card.name == "Mangara's Tome")
    (tome_mountain,) = [
        entry["card"] for entry in linked_entries(tome) if entry["card"].name == "Mountain"
    ]
    assert permission_for(game, 0, tome_mountain, "exile", as_land=True) is None
    assert permission_for(game, 0, wishes[0], "exile", as_land=True) is not None
    # The cast path finds a card by name and prefers the occurrence a
    # permission covers (``_spell_source``): the Wishes' Mountain leaves, the
    # Tome's stays face down in its pile.
    played = game.cast_from_hand(0, "Mountain", from_zone="exile")
    assert played.supported, played.details
    assert not any(held is wishes[0] for held in exile)
    assert any(held is tome_mountain for held in exile)
    assert any(entry["card"] is tome_mountain for entry in linked_entries(tome))
