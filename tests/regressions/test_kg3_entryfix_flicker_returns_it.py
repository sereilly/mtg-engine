"""Flicker returns the permanent it exiled, as a new object.

"Exile target nontoken permanent, then return it to the battlefield under its
owner's control." Its rulings: "This spell effectively 'resets' the permanent
to being just like it was freshly cast. All counters, Auras, effects, and so
on are removed when it is exiled. Then it comes back onto the battlefield like
new." (2005-08-01) and "It will trigger 'enters' abilities and 'leaves the
battlefield' abilities." (2004-10-04).

The second sentence compiled to ``return_source_card_to_battlefield``: the
bare "it" read as the spell's own card (the reading Anurid Brushhopper's
"Exile this creature. Return it …" needs), so every Flicker exiled its target
for good and logged "Flicker was no longer in a graveyard". Behind a step that
exiled something other than the source, "it" names that card now
(``lowering/_bound_returns``, the "that card" back-reference Liberate already
had: ``put_exiled_cards_into_zone``). And an Aura it returns is put back by an
effect that names no host, so its owner chooses one as it enters (CR 303.4f;
``_return_pile_with_aura_hosts``, Worldgorger Dragon's plan) — returned bare it
sat on the battlefield attached to nothing.

Found driving the blink road of ``test_kg3_entryfix_choice_then_trigger.py``.
Backwards: on the tree before the fix every row fails on the permanent's
absence; with the lowering fixed and the handler not, the Aura rows fail on
their host (``attached_to`` None — an Aura entered with no host never had the
key, so CR 704.5m's sweep skips it as "manually placed").
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.control import change_control
from engine.models import Permanent
from tests.helpers import resolve_stack, settle

_C = {card.name: card for card in load_catalog()}


def _table(person: bool) -> Game:
    game = Game(players=[
        PlayerState(name="P0", library=[_C["Plains"]] * 10),
        PlayerState(name="P1", library=[_C["Plains"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0} if person else set()
    game._sync_control()
    return game


def _place(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_C[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    settle(game)
    return permanent


def _flicker(game: Game, permanent: Permanent) -> None:
    game.players[0].hand = [_C["Flicker"]]
    result = game.queue_from_hand(0, "Flicker", target_permanent_ids=[permanent.permanent_id])
    assert result.supported, result.details
    settle(game)


def _named(game: Game, seat: int, name: str) -> list[Permanent]:
    return [p for p in game.controlled_by(seat) if p.card.name == name]


@pytest.mark.parametrize("person", [False, True], ids=["nobody_asked", "a_person"])
@pytest.mark.parametrize("name", ["Grizzly Bears", "Sol Ring", "Forest", "Brass Herald"])
def test_flicker_returns_what_it_exiled_as_a_new_object(name, person):
    game = _table(person)
    target = _place(game, 0, name)
    target.metadata["plus_counters"] = 1
    old_id = target.permanent_id

    _flicker(game, target)

    back = _named(game, 0, name)
    assert len(back) == 1, game.log[-6:]
    assert back[0].permanent_id != old_id  # CR 400.7: a new object
    assert not back[0].metadata.get("plus_counters")
    assert [card.name for card in game.players[0].exile] == []
    assert [card.name for card in game.players[0].graveyard] == ["Flicker"]
    assert not any("no longer in a graveyard" in line for line in game.log)


@pytest.mark.parametrize("person", [False, True], ids=["nobody_asked", "a_person"])
def test_flicker_returns_a_permanent_under_its_owners_control(person):
    """An opponent's permanent comes back on its side; one the caster had
    stolen goes home — "under its owner's control"."""
    game = _table(person)
    theirs = _place(game, 1, "Grizzly Bears")
    stolen = _place(game, 1, "Hill Giant")
    change_control(stolen, 0, source="test")
    game._sync_control()
    assert game.controller_index_of(stolen) == 0

    _flicker(game, theirs)
    _flicker(game, stolen)

    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Grizzly Bears", "Hill Giant"]
    assert list(game.controlled_by(0)) == []


@pytest.mark.parametrize("person", [False, True], ids=["nobody_asked", "a_person"])
def test_flicker_returns_an_aura_to_a_host_its_owner_chooses(person):
    """CR 303.4f: an Aura an effect puts onto the battlefield without naming
    what it enchants is attached to a legal object its controller chooses as
    it enters. Its old host's counters and the Aura's own effects are gone;
    it enchants again, and what it grants applies."""
    game = _table(person)
    bears = _place(game, 0, "Grizzly Bears")
    game.players[0].hand = [_C["Holy Strength"]]
    assert game.queue_from_hand(0, "Holy Strength", target_permanent_ids=[bears.permanent_id]).supported
    settle(game)
    aura = _named(game, 0, "Holy Strength")[0]
    assert aura.metadata.get("attached_to") is bears

    _flicker(game, aura)

    back = _named(game, 0, "Holy Strength")
    assert len(back) == 1, game.log[-6:]
    assert back[0] is not aura
    assert back[0].metadata.get("attached_to") is bears
    assert bears.effective_power == 3 and bears.effective_toughness == 4
    resolve_stack(game)
    assert [card.name for card in game.players[0].graveyard] == ["Flicker"]
