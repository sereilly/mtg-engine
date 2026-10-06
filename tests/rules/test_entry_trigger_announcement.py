"""The target a permanent spell names for its entry trigger is one the trigger
could have chosen (CR 603.3d, CR 702.16b).

This engine names an entry trigger's target as the permanent is cast. The rule
chooses it as the trigger is put on the stack, so the cast's announcement is a
pre-answer to that choice — and it was never held to what the choice would
accept. Both ends read the trigger's own list now: the cast picker
(``legality.entry_trigger_cast_targets``) and the push
(``Game.cast_announcement_fault``).

The pool-wide statement is ``tests/engine/
test_entry_trigger_announcement_census.py``. These are the shapes it counts,
each driven to the board: an announcement that is set aside is only right if
the creature it named is still there afterwards and the trigger then did what a
trigger nobody announced for would have done.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.game import Game
from engine.models import Permanent

from tests.helpers import resolve_stack


def _table(pool, hand, *, board=(), opp_board=(), opp_hand=(), interactive=()):
    game = Game(players=[
        PlayerState("P0", library=[pool["Forest"]] * 10, hand=[pool[name] for name in hand]),
        PlayerState("P1", library=[pool["Forest"]] * 10, hand=[pool[name] for name in opp_hand]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, names in ((0, board), (1, opp_board)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    return game


def _named(game, seat, name):
    return next(perm for perm in game.controlled_by(seat) if perm.card.name == name)


def _picker_names(game, card_name):
    card = next(card for card in game.players[0].hand if card.name == card_name)
    return sorted(
        game.players[entry["seat"]].battlefield[entry["index"]].card.name
        for entry in game.cast_target_spec(0, card)["valid_targets"]
        if entry["kind"] == "permanent"
    )


@pytest.mark.cr("603.3d", "702.16b")
def test_the_cast_picker_does_not_offer_a_creature_protected_from_the_permanent(catalog_by_name):
    """Nekrataal is black; White Knight has protection from black. CR 702.16b:
    it can't be the target of abilities from black sources — and the cast
    picker, which names the target for Nekrataal's trigger, offered it."""
    game = _table(
        catalog_by_name, ["Nekrataal"], opp_board=["White Knight", "Grizzly Bears"],
    )

    assert _picker_names(game, "Nekrataal") == ["Grizzly Bears"]


@pytest.mark.cr("603.3d", "702.16b")
def test_a_protected_creature_named_at_the_cast_is_not_destroyed(catalog_by_name):
    """The announcement is set aside as the trigger is put on the stack, and
    the trigger chooses for itself — here, with nobody to ask, the picker's
    default out of the one creature it may legally target."""
    game = _table(
        catalog_by_name, ["Nekrataal"], opp_board=["White Knight", "Grizzly Bears"],
    )
    knight, bears = _named(game, 1, "White Knight"), _named(game, 1, "Grizzly Bears")

    cast = game.cast_from_hand(0, "Nekrataal", target_permanent_ids=[knight.permanent_id])
    resolve_stack(game)

    assert cast.supported, "a permanent spell does not target: the cast stands"
    assert game.is_on_battlefield(knight), "protection from black"
    assert not game.is_on_battlefield(bears), "the trigger's own legal choice"
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert any("chooses again (603.3d)" in line for line in game.log)


@pytest.mark.cr("603.3d", "702.16b")
def test_with_no_legal_target_the_trigger_is_removed_and_nothing_dies(catalog_by_name):
    game = _table(catalog_by_name, ["Nekrataal"], opp_board=["White Knight"])
    knight = _named(game, 1, "White Knight")

    game.cast_from_hand(0, "Nekrataal", target_permanent_ids=[knight.permanent_id])
    resolve_stack(game)

    assert game.is_on_battlefield(knight)
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Nekrataal"]
    assert game.stack == [] and not game.pending_choices
    assert any("no legal target" in line for line in game.log)


@pytest.mark.cr("603.3d", "702.16b")
def test_a_seat_that_can_be_asked_is_asked_and_its_answer_is_what_resolves(catalog_by_name):
    """For a player the set-aside announcement becomes the trigger's own
    prompt, on the cast road — which never asked before this."""
    game = _table(
        catalog_by_name, ["Nekrataal"],
        opp_board=["White Knight", "Grizzly Bears", "Hill Giant"], interactive={0, 1},
    )
    knight, giant = _named(game, 1, "White Knight"), _named(game, 1, "Hill Giant")

    game.queue_from_hand(0, "Nekrataal", target_permanent_ids=[knight.permanent_id])
    game.resolve_top_of_stack(pause_for_choices=True)

    prompt = game.pending_choice_of("trigger_target")
    assert prompt is not None and prompt.player_index == 0
    assert sorted(entry["name"] for entry in prompt.data["targets"]) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert not game.confirm_trigger_target(0, permanent_id=knight.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id)
    resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(knight)
    assert game.is_on_battlefield(_named(game, 1, "Grizzly Bears"))


@pytest.mark.cr("603.3d")
def test_the_triggers_own_printed_narrowing_is_asked_of_the_announcement(catalog_by_name):
    """Hunting Drake: "put target **red or green** creature on top of its
    owner's library." The narrowing rides the trigger's instruction, which the
    cast picker never read: it offered every creature, and a Serra Angel named
    at the cast went to the top of its owner's library."""
    game = _table(
        catalog_by_name, ["Hunting Drake"], opp_board=["Serra Angel", "Grizzly Bears"],
    )
    angel, bears = _named(game, 1, "Serra Angel"), _named(game, 1, "Grizzly Bears")

    assert _picker_names(game, "Hunting Drake") == ["Grizzly Bears"]
    game.cast_from_hand(0, "Hunting Drake", target_permanent_ids=[angel.permanent_id])
    resolve_stack(game)

    assert game.is_on_battlefield(angel)
    assert not game.is_on_battlefield(bears)
    assert game.players[1].library[0].name == "Grizzly Bears"


@pytest.mark.cr("603.3d")
def test_a_target_that_left_before_the_permanent_resolved_is_chosen_again(catalog_by_name):
    """The trigger does not exist until the permanent enters, so a creature
    killed in response to the *spell* was never its target: the trigger chooses
    when it is put on the stack, among what is there then."""
    game = _table(
        catalog_by_name, ["Man-o'-War"], opp_board=["Grizzly Bears", "Hill Giant"],
    )
    bears, giant = _named(game, 1, "Grizzly Bears"), _named(game, 1, "Hill Giant")

    game.queue_from_hand(0, "Man-o'-War", target_permanent_ids=[bears.permanent_id])
    game.remove_from_battlefield(bears)
    game._permanent_to_graveyard(game.players[1], bears)
    resolve_stack(game)

    assert not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[1].hand] == ["Hill Giant"]


@pytest.mark.cr("603.3d", "702.18a")
def test_a_player_who_gained_shroud_before_the_permanent_resolved_is_not_hit(catalog_by_name):
    """Ravenous Rats: "When this creature enters, target opponent discards a
    card." With an Ivory Mask arriving in response to the spell, the trigger
    has no opponent it may target and is removed (CR 603.3d)."""
    game = _table(catalog_by_name, ["Ravenous Rats"], opp_hand=["Giant Growth"])

    game.queue_from_hand(0, "Ravenous Rats", target_player_index=1)
    game._put_permanent_onto_battlefield(
        1, Permanent(card=catalog_by_name["Ivory Mask"]), None
    )
    resolve_stack(game)

    assert [card.name for card in game.players[1].hand] == ["Giant Growth"]
    assert game.players[1].graveyard == []
    assert game.stack == []


@pytest.mark.cr("603.3d", "102.2")
def test_an_entry_triggers_target_opponent_cannot_be_its_controller(catalog_by_name):
    game = _table(
        catalog_by_name, ["Ravenous Rats", "Giant Growth"], opp_hand=["Hill Giant"],
    )

    game.cast_from_hand(0, "Ravenous Rats", target_player_index=0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].hand] == ["Giant Growth"]
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]


@pytest.mark.cr("603.3d")
def test_a_seat_named_alone_does_not_stand_in_for_an_object_target(catalog_by_name):
    """What the web route sends for a cast no picker ran in front of: a seat
    and no object. The trigger chooses — and Man-o'-War, alone on the table,
    is its own only legal target (it must return *a* creature)."""
    game = _table(catalog_by_name, ["Man-o'-War"])

    game.cast_from_hand(0, "Man-o'-War", target_player_index=1)
    resolve_stack(game)

    assert [card.name for card in game.players[0].hand] == ["Man-o'-War"]
    assert list(game.controlled_by(0)) == []


@pytest.mark.cr("603.3d")
def test_a_legal_announcement_is_honoured_and_asked_of_nobody(catalog_by_name):
    """The control: a target the trigger could choose rides the object as it
    always has — no prompt even for a seat that could be asked, and the named
    creature, not the picker's first, is the one that dies."""
    game = _table(
        catalog_by_name, ["Nekrataal"],
        opp_board=["Grizzly Bears", "Hill Giant"], interactive={0, 1},
    )
    giant = _named(game, 1, "Hill Giant")

    game.queue_from_hand(0, "Nekrataal", target_permanent_ids=[giant.permanent_id])
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.pending_choice_of("trigger_target") is None
    resolve_stack(game)
    assert not game.is_on_battlefield(giant)
    assert game.is_on_battlefield(_named(game, 1, "Grizzly Bears"))
    assert not any("chooses again" in line for line in game.log)
