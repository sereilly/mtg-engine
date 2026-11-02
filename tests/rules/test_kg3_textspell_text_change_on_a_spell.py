"""CR 612 on a **spell**: "Change the text of target spell or permanent".

Five shipped cards print the union — Sleight of Mind, Magical Hack, Crystal
Spray, Alter Reality and Artificial Evolution — and until kg3 they offered a
permanent alone: a stack object had no text channel, so the picker left the
stack out and a named spell was refused at announcement. Their rulings
(2004-10-04, all five) say what a text change on a spell does:

* "Changing the text of a spell will not allow you to change the targets of
  the spell because the targets were chosen when the spell was cast. The text
  change will (probably) cause it to be countered since the targets will be
  illegal." — CR 608.2b re-asks the targets by the *changed* text;
* "If you change the text of a spell which is to become a permanent, the
  permanent will retain the text change until the effect wears off." — CR
  400.7a.

And CR 707.2: "Other effects (including type-changing and text-changing
effects) … are not copied."

Each test drives a ``Game`` through the real cast and resolution entry points
and reads the board, the zones and the log.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.text_changes import TEXT_CHANGE_EFFECTS, spell_text_card
from tests.helpers import resolve_stack


def _duel(*, interactive=()):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _put(game, seat, card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    game._recompute_continuous_effects()
    return permanent


def _cast_at_the_spell(game, seat, card, **choices):
    """*seat* casts the text-changer *card* at the spell on top of the stack."""
    game.players[seat].hand.append(card)
    spec = game.cast_target_spec(seat, card)
    assert spec["kind"] == "spell_or_permanent"
    offered = [(entry["kind"], entry["name"]) for entry in spec["valid_targets"]]
    assert ("stack", game.stack[-1].card.name) in offered, offered
    result = game.queue_from_hand(
        seat, card.name, target_stack_index=len(game.stack) - 1, **choices,
    )
    assert result.supported, result.details
    return game.stack[-1]


@pytest.mark.cr("612.1", "608.2b")
def test_sleight_of_mind_on_terror_makes_its_chosen_target_illegal(catalog_by_name):
    """Terror ("Destroy target nonartifact, **nonblack** creature") is cast at
    Savannah Lions; Sleight of Mind rewrites black to white on the Terror. The
    Lions are white, so Terror's one target is illegal by its own changed text
    and it is countered by the rules — and the card that goes to the graveyard
    is the printed Terror."""
    game = _duel()
    lions = _put(game, 0, catalog_by_name["Savannah Lions"])
    terror_card = catalog_by_name["Terror"]
    game.players[1].hand = [terror_card]
    assert game.queue_from_hand(
        1, "Terror", target_permanent_ids=[lions.permanent_id],
    ).supported
    terror = game.stack[-1]

    _cast_at_the_spell(
        game, 0, catalog_by_name["Sleight of Mind"], old_color="B", new_color="W",
    )
    assert game.resolve_top_of_stack()
    assert "Sleight of Mind changed B text to W on Terror (on the stack)" in game.log
    assert "nonwhite" in spell_text_card(terror).oracle_text
    assert terror.card is terror_card, "the stack object's card stays the printed one"

    resolve_stack(game)

    assert game.is_on_battlefield(lions)
    assert "Terror was removed from the stack: every target is illegal (608.2b)" in game.log
    assert game.players[1].graveyard == [terror_card]
    assert game.players[1].graveyard[0].oracle_text == terror_card.oracle_text


@pytest.mark.cr("612.1", "608.2c")
def test_magical_hack_on_tsunami_destroys_the_other_land_type(catalog_by_name):
    """"Destroy all Islands" with island rewritten to swamp is "Destroy all
    Swamps" as it resolves: the Swamp goes and the Island stays."""
    game = _duel()
    island = _put(game, 1, catalog_by_name["Island"])
    swamp = _put(game, 1, catalog_by_name["Swamp"])
    game.players[0].hand = [catalog_by_name["Tsunami"]]
    assert game.queue_from_hand(0, "Tsunami").supported

    _cast_at_the_spell(
        game, 1, catalog_by_name["Magical Hack"], old_color="U", new_color="B",
    )
    resolve_stack(game)

    assert "Magical Hack changed island to swamp in Tsunami's text (on the stack)" in game.log
    assert game.is_on_battlefield(island)
    assert not game.is_on_battlefield(swamp)
    assert [card.name for card in game.players[0].graveyard] == ["Tsunami"]


@pytest.mark.cr("612.1", "205.3m")
def test_artificial_evolution_on_tivadars_crusade_asked_of_an_interactive_seat(
    catalog_by_name, set_pool,
):
    """"Destroy all Goblins" made "Destroy all Elves" by an interactive seat
    naming both words as Artificial Evolution resolves (its ruling: "You choose
    the words to change on resolution"). The word offered first is the one
    written on the targeted **spell**."""
    game = _duel(interactive=(0,))
    goblin = _put(game, 0, catalog_by_name["Raging Goblin"])
    elves = _put(game, 1, catalog_by_name["Llanowar Elves"])
    game.players[1].hand = [catalog_by_name["Tivadar's Crusade"]]
    assert game.queue_from_hand(1, "Tivadar's Crusade").supported

    _cast_at_the_spell(game, 0, set_pool("ONS")["Artificial Evolution"])
    game.resolve_top_of_stack(pause_for_choices=True)
    (first,) = game.pending_choices
    assert first.kind == "creature_type_choice"
    assert first.data["default_creature_type"] == "goblin", "written on the spell"
    assert game.confirm_creature_type_choice(0, "goblin")
    assert game.confirm_creature_type_choice(0, "elf")
    resolve_stack(game)

    assert (
        "Artificial Evolution changed goblin to elf in Tivadar's Crusade's text "
        "(on the stack)" in game.log
    )
    assert game.is_on_battlefield(goblin)
    assert not game.is_on_battlefield(elves)


@pytest.mark.cr("612.1", "205.3m")
def test_artificial_evolution_on_a_spell_for_a_seat_nobody_asks(catalog_by_name, set_pool):
    """The same cast by a seat nobody asks: the word replaced is the one
    written on the targeted spell (its type line first, then its rules text),
    so the change does something — Tivadar's Crusade no longer says Goblins.
    (Which word replaces it is the chooser's policy, not this rule's.)"""
    game = _duel()
    _put(game, 0, catalog_by_name["Raging Goblin"])
    game.players[1].hand = [catalog_by_name["Tivadar's Crusade"]]
    assert game.queue_from_hand(1, "Tivadar's Crusade").supported

    crusade = game.stack[-1]
    _cast_at_the_spell(game, 0, set_pool("ONS")["Artificial Evolution"])
    assert game.resolve_top_of_stack()

    assert "Artificial Evolution: chose goblin" in game.log
    (change,) = crusade.text_change_effects
    assert change["from"] == "goblin" and change["to"] != "goblin"
    assert "Goblins" not in spell_text_card(crusade).oracle_text
    resolve_stack(game)
    assert [card.name for card in game.players[1].graveyard] == ["Tivadar's Crusade"]


@pytest.mark.cr("400.7a", "612.1")
def test_magical_hack_on_a_creature_spell_stays_on_the_permanent(catalog_by_name):
    """Bog Wraith ("Swampwalk") hacked on the stack enters with islandwalk —
    the change is carried with the timestamp it was created at (CR 613.7b),
    and the permanent's card is still the printed Bog Wraith."""
    game = _duel()
    wraith_card = catalog_by_name["Bog Wraith"]
    game.players[0].hand = [wraith_card]
    assert game.queue_from_hand(0, "Bog Wraith").supported
    spell = game.stack[-1]

    _cast_at_the_spell(
        game, 1, catalog_by_name["Magical Hack"], old_color="B", new_color="U",
    )
    assert game.resolve_top_of_stack()
    (record,) = spell.text_change_effects
    resolve_stack(game)

    (wraith,) = game.players[0].battlefield
    assert wraith.card is wraith_card
    assert game._has_keyword(wraith, "islandwalk")
    assert not game._has_keyword(wraith, "swampwalk")
    (carried,) = wraith.metadata[TEXT_CHANGE_EFFECTS]
    assert carried["timestamp"] == record["timestamp"]
    assert carried["label"] == "Magical Hack"


@pytest.mark.cr("400.7a", "514.2")
def test_crystal_spray_on_a_creature_spell_wears_off_the_permanent_at_cleanup(
    catalog_by_name,
):
    """Crystal Spray's change lasts "until end of turn": carried onto the
    permanent the spell becomes, it is swept by that turn's cleanup like any
    other turn-long text change."""
    game = _duel()
    game.players[0].hand = [catalog_by_name["Bog Wraith"]]
    assert game.queue_from_hand(0, "Bog Wraith").supported

    _cast_at_the_spell(
        game, 1, catalog_by_name["Crystal Spray"], old_color="B", new_color="G",
    )
    resolve_stack(game)

    (wraith,) = game.players[0].battlefield
    assert game._has_keyword(wraith, "forestwalk")
    game.resolve_cleanup_step(0)
    assert game._has_keyword(wraith, "swampwalk")
    assert not game._has_keyword(wraith, "forestwalk")


@pytest.mark.cr("707.2", "707.10")
def test_a_copy_of_a_text_changed_spell_reads_its_printed_text(catalog_by_name):
    """Terror at Savannah Lions, Sleighted to "nonwhite", then Forked: the copy
    has the original's target and its *printed* text (CR 707.2 — a
    text-changing effect is not copied), so the copy destroys the Lions the
    original no longer may."""
    game = _duel()
    lions = _put(game, 0, catalog_by_name["Savannah Lions"])
    game.players[1].hand = [catalog_by_name["Terror"], catalog_by_name["Fork"]]
    assert game.queue_from_hand(
        1, "Terror", target_permanent_ids=[lions.permanent_id],
    ).supported
    terror = game.stack[-1]
    _cast_at_the_spell(
        game, 0, catalog_by_name["Sleight of Mind"], old_color="B", new_color="W",
    )
    assert game.resolve_top_of_stack()
    assert terror.text_change_effects

    assert game.queue_from_hand(1, "Fork", target_stack_index=0).supported
    assert game.resolve_top_of_stack()
    copy = game.stack[-1]
    assert copy.is_copy
    assert copy.text_change_effects == []
    assert spell_text_card(copy) is copy.card

    resolve_stack(game)
    assert not game.is_on_battlefield(lions)
    assert "Terror was removed from the stack: every target is illegal (608.2b)" in game.log


@pytest.mark.cr("612.1", "115.1")
def test_the_five_offer_a_spell_and_a_permanent_and_never_an_ability(catalog_by_name, set_pool):
    """The union is one target in one of two zones: every permanent and every
    spell on the stack, never an ability (CR 113.3: an ability is not a
    spell)."""
    game = _duel()
    _put(game, 0, catalog_by_name["Grizzly Bears"])
    game.players[1].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    for card in (
        catalog_by_name["Sleight of Mind"], catalog_by_name["Magical Hack"],
        catalog_by_name["Crystal Spray"], catalog_by_name["Alter Reality"],
        set_pool("ONS")["Artificial Evolution"],
    ):
        spec = game.cast_target_spec(0, card)
        assert spec["kind"] == "spell_or_permanent", card.name
        assert sorted((e["kind"], e["name"]) for e in spec["valid_targets"]) == [
            ("permanent", "Grizzly Bears"), ("stack", "Lightning Bolt"),
        ], card.name


@pytest.mark.cr("612.1", "400.7a")
def test_crystal_spray_asks_which_vocabulary_of_an_interactive_seat_for_a_spell(
    catalog_by_name,
):
    """Sol'kanar the Swamp King prints "black" and "Swamp": Crystal Spray
    naming B to U on the creature spell asks its interactive caster which word
    it rewrites (CR 612.1: the card offers either vocabulary). The prompt is
    held on the spell, and the answer — the land type — is what the permanent
    enters with, until end of turn."""
    game = _duel(interactive=(1,))
    game.players[0].hand = [catalog_by_name["Sol'kanar the Swamp King"]]
    assert game.queue_from_hand(0, "Sol'kanar the Swamp King").supported
    spell = game.stack[-1]

    _cast_at_the_spell(
        game, 1, catalog_by_name["Crystal Spray"], old_color="B", new_color="U",
    )
    game.resolve_top_of_stack(pause_for_choices=True)
    (prompt,) = game.pending_choices_of("text_change_vocabulary")
    assert prompt.data["options"] == ["color_word", "land_type"]
    assert prompt.data["_spell"] is spell and "_permanent" not in prompt.data
    assert game.confirm_text_change_vocabulary(1, "land_type")
    resolve_stack(game)

    assert (
        "Crystal Spray changed swamp to island in Sol'kanar the Swamp King's text "
        "(on the stack)" in game.log
    )
    (solkanar,) = game.players[0].battlefield
    assert game._has_keyword(solkanar, "islandwalk")
    assert "black spell" in solkanar.effective_card.oracle_text, "the colour word stood"
    game.resolve_cleanup_step(0)
    assert game._has_keyword(solkanar, "swampwalk")
