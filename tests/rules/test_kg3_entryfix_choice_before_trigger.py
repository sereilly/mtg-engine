"""The "as it enters" choice, then the entry, then the entry trigger.

CR 614.12a: the choice a replacement modifying how a permanent enters requires
"is made before the permanent enters the battlefield". CR 603.6a: an
enters-the-battlefield ability triggers when the permanent enters, and CR
603.3 puts it on the stack as an object of its own. So a person casting Brass
Herald answers its creature type with the Herald on its way, and only then
does the Herald enter and its reveal go on the stack — to resolve with the
type the person chose. Traveler's Cloak likewise: its land type, then the
Cloak, then "draw a card".

These are the boards ``tests/engine/test_entry_trigger_stack_census.py``
named as unexplained when it read the table before the answer
(``kg3/entryfix``): driven here to the end, through the real cast and answer
entry points, with the answer the person gives.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import entering_or_present, resolve_stack

_C = {card.name: card for card in load_catalog()}


def _table(hand, library) -> Game:
    game = Game(players=[
        PlayerState(name="Human", hand=[_C[name] for name in hand],
                    library=[_C[name] for name in library]),
        PlayerState(name="AI", library=[_C["Plains"]] * 10,
                    battlefield=[Permanent(card=_C["Soul Warden"])]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0}
    game._sync_control()
    return game


def _entry_triggers_of(game, permanent) -> list:
    return [
        item for item in game.stack
        if item.source_permanent is permanent and item.ability_instruction is not None
    ]


@pytest.mark.cr("614.12a", "603.6a", "603.3")
def test_brass_herald_reveals_for_the_creature_type_the_person_chose():
    game = _table(
        ["Brass Herald"],
        ["Obsianus Golem", "Forest", "Obsianus Golem", "Island", "Plains", "Plains"],
    )
    assert game.queue_from_hand(0, "Brass Herald").supported
    game.resolve_top_of_stack(pause_for_choices=True)

    herald = entering_or_present(game, 0, "Brass Herald")
    owed = game.waiting_prompt()
    assert owed is not None and owed.kind == "enter_choice"
    # On its way: on no battlefield, nothing triggered, nothing revealed, and
    # Soul Warden has not seen a creature enter.
    assert not game.is_on_battlefield(herald)
    assert not _entry_triggers_of(game, herald)
    assert [card.name for card in game.players[0].hand] == []
    assert game.players[1].life == 20

    assert game.resolve_pending_choice("enter_choice", 0, creature_type="Golem")
    assert game.is_on_battlefield(herald)
    assert herald.metadata.get("chosen_creature_type") == "golem"
    # Entered, and its reveal is a stack object of its own, not yet resolved.
    assert len(_entry_triggers_of(game, herald)) == 1
    assert [card.name for card in game.players[0].hand] == []

    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert sorted(card.name for card in game.players[0].hand) == ["Obsianus Golem"] * 2
    assert [card.name for card in game.players[0].library[-2:]] in (
        ["Forest", "Island"], ["Island", "Forest"],
    )
    assert game.players[1].life == 21


@pytest.mark.cr("614.12a", "603.6a", "603.3")
def test_travelers_cloak_draws_after_the_land_type_is_chosen():
    game = _table(["Traveler's Cloak"], ["Island", "Plains", "Plains"])
    bears = Permanent(card=_C["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    resolve_stack(game)
    assert game.queue_from_hand(
        0, "Traveler's Cloak", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    cloak = entering_or_present(game, 0, "Traveler's Cloak")
    assert not game.is_on_battlefield(cloak)
    assert not _entry_triggers_of(game, cloak)
    assert game.players[0].hand == []

    assert game.resolve_pending_choice("enter_choice", 0, land_type="swamp")
    assert game.is_on_battlefield(cloak)
    assert cloak.metadata.get("chosen_land_type") == "swamp"
    assert len(_entry_triggers_of(game, cloak)) == 1
    assert game.players[0].hand == []

    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Island"]
    assert game._has_keyword(bears, "swampwalk")


@pytest.mark.cr("614.12a", "603.6a", "303.4f")
def test_travelers_cloak_put_from_a_graveyard_chooses_then_draws():
    """The put road: Iridescent Drake puts the Cloak from a graveyard onto the
    battlefield attached to itself (CR 303.4f's host is named by the effect);
    the person chooses the land type with the Cloak on its way, and its draw
    triggers once it is there."""
    game = _table(["Iridescent Drake"], ["Island", "Plains", "Plains"])
    game.players[0].graveyard = [_C["Traveler's Cloak"]]
    assert game.queue_from_hand(0, "Iridescent Drake").supported
    for _ in range(10):
        if game.pending_choice_of("enter_choice", 0) is not None:
            break
        owed = game.waiting_prompt()
        if owed is not None:
            game.take_choice_default(owed)
        else:
            game.resolve_top_of_stack(pause_for_choices=True)
    cloak = entering_or_present(game, 0, "Traveler's Cloak")
    assert not game.is_on_battlefield(cloak)
    assert not _entry_triggers_of(game, cloak)

    assert game.resolve_pending_choice("enter_choice", 0, land_type="island")
    assert game.is_on_battlefield(cloak)
    assert len(_entry_triggers_of(game, cloak)) == 1
    hand_before = len(game.players[0].hand)

    resolve_stack(game)
    assert len(game.players[0].hand) == hand_before + 1
    drake = next(p for p in game.controlled_by(0) if p.card.name == "Iridescent Drake")
    assert cloak.metadata.get("attached_to") is drake
    assert game._has_keyword(drake, "islandwalk")
