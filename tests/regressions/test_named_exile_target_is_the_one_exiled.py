"""Regressions: a permanent exile named by id exiles that permanent or nothing.

Found while driving Nemesis' Topple ("Exile target creature with the greatest
power among creatures on the battlefield") and measured on the shipped pool
with a census over the single-target "nonblack" removal: **Eradicate exiled a
creature nobody named**. Cast at a green creature that was then made black in
response, the named target was no longer legal (CR 608.2b), the resolver's id
check failed its predicate — and ``pick_target_permanent`` fell through to its
scan, which took the *other* creature on that battlefield.

That fall-through is ``pick_target_permanent``'s documented asymmetry ("an id
that resolves to a permanent this caller cannot use falls through to the index
behaviour"), and it is right for a caller that never recorded a choice. A spell
that recorded one has made its choice (CR 601.2c), so ``exile_target_permanent``
now reads the recorded id strictly: the permanent it names, if it still answers
the printed description, and otherwise nothing. A cast that named no id (the AI
seat-only announcement) keeps the scan.

Twenty-seven cards in both manifest roles compile to this kind; the shapes
below are the two the census and the Topple round reproduced.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent
from engine.pt import add_pt_modifier
from tests.helpers import resolve_stack

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=line, oracle_text="",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _table(spell: str, *theirs: Permanent, mine=()) -> Game:
    game = Game(players=[
        PlayerState(name="P0", hand=[_POOL[spell]], battlefield=list(mine)),
        PlayerState(name="P1", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_eradicate_whose_target_turned_black_exiles_no_bystander():
    """The census row, as a test: the named creature turned black in response,
    so nothing is exiled — least of all the creature beside it."""
    named = Permanent(card=_creature("Named"))
    bystander = Permanent(card=_creature("Bystander"))
    game = _table("Eradicate", named, bystander)

    queued = game.queue_from_hand(
        0, "Eradicate", target_player_index=1, target_permanent_ids=[named.permanent_id],
    )
    assert queued.supported, queued
    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert game.is_on_battlefield(named)
    assert game.is_on_battlefield(bystander), "a creature nobody named was exiled"
    assert game.players[1].exile == []


def test_topple_whose_target_was_overtaken_exiles_nothing_on_its_board():
    """Topple's own shape: the target's controller pumps *another* creature of
    theirs past it in response. The target is illegal (CR 608.2b) — and the
    scan would have found the newly greatest creature right beside it."""
    target = Permanent(card=_creature("Target 4/4", 4, 4))
    other = Permanent(card=_creature("Other 3/3", 3, 3))
    game = _table("Topple", target, other)

    queued = game.queue_from_hand(
        0, "Topple", target_player_index=1, target_permanent_ids=[target.permanent_id],
    )
    assert queued.supported, queued
    add_pt_modifier(other, 2, 0)
    resolve_stack(game)

    assert game.is_on_battlefield(target) and game.is_on_battlefield(other)
    assert game.players[1].exile == []


def test_a_named_legal_target_is_still_exiled():
    """The fix narrows the fall-through and nothing else: a target that still
    answers its description is exiled exactly as before."""
    named = Permanent(card=_creature("Named"))
    bystander = Permanent(card=_creature("Bystander"))
    game = _table("Eradicate", named, bystander)

    game.cast_from_hand(
        0, "Eradicate", target_player_index=1, target_permanent_ids=[named.permanent_id],
    )

    assert not game.is_on_battlefield(named)
    assert game.is_on_battlefield(bystander)
    assert [card.name for card in game.players[1].exile] == ["Named"]
