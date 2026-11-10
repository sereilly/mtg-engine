"""A copy is named what it copies wherever the engine names a permanent
(CR 707.2): in the lists it offers, in the refusals it gives, and in the lines
its own machinery logs about the permanent.

CR 707.2: "The copiable values are the values derived from the text printed
on the object (that text being name, mana cost, …)". A Clone copying
Prodigal Sorcerer *is* named Prodigal Sorcerer, and since kg5's ``client``
group the board's name plate says so. The engine went on calling it "Clone":
the target lists it built, "Clone has summoning sickness", "Clone ability
added to stack", "Clone died (704.5g: lethal damage)".

**Which name where** (the rule this file holds):

* a permanent — on the battlefield, or leaving it — is named by its name,
  ``effective_card.name``: a copy's is the copied object's (CR 707.2), and
  one that has left is named as it last existed (CR 608.2h, 113.7a; its
  copy effects outlive its leaving on the object, so ``effective_card`` still
  reads them). That is also what the legend rule's line already did;
* an ability is named by its source (``stack_targets.source_name``): "the
  object as it exists — or as it most recently existed — that does it"
  (CR 608.2h);
* a **card** outside the battlefield — in a graveyard, in a hand, in exile,
  the spell on the stack, the card about to be put onto the battlefield — is
  named by its card (CR 400.7: the copy effect does not follow it there).
  So "A put Clone onto battlefield" stays: the spell that resolved was a
  Clone, and it became a copy *as* it entered (CR 707.5).

Backwards: every test here fails on the round's base (the Seat of the Synod
refusal and tap line, the upkeep labels and the lists named "Clone" /
"Sculpting Steel"), except the ones marked as the direction that must not
move.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, settle


def _table(set_pool, *, hand0=(), board0=(), board1=(), interactive=()) -> Game:
    """Two seats with libraries, seat 0 in its first main phase; *board0* /
    *board1* placed and able to attack or tap."""
    island = set_pool("LEA")["Island"]
    game = Game(players=[
        PlayerState(name="P0", hand=list(hand0), library=[island] * 10),
        PlayerState(name="P1", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, board in ((0, board0), (1, board1)):
        for card in board:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _on(game: Game, seat: int, printed: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == printed)


def _copy(game: Game, copier: str, original: Permanent) -> Permanent:
    """Cast *copier* from seat 0's hand choosing *original* to copy."""
    result = game.cast_from_hand(
        0, copier,
        target_player_index=game.controller_index_of(original),
        target_permanent_index=game.battlefield_index_of(original),
    )
    assert result.supported, result.details
    settle(game)
    copy = _on(game, 0, copier)
    assert copy.effective_card.name == original.effective_card.name, game.log[-5:]
    return copy


def _clone_of(set_pool, original: str, *, original_set: str = "LEA", **table):
    pool = set_pool(original_set)
    game = _table(
        set_pool, hand0=[set_pool("LEA")["Clone"], *table.pop("hand0", ())],
        board0=[pool[original], *table.pop("board0", ())], **table,
    )
    clone = _copy(game, "Clone", _on(game, 0, original))
    return game, clone


# ---------------------------------------------------------------------------
# The lists the engine offers
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.2", "601.2c")
def test_a_spells_target_list_names_a_copy_by_what_it_copies(set_pool):
    game, clone = _clone_of(set_pool, "Grizzly Bears")
    bolt = set_pool("LEA")["Lightning Bolt"]
    spec = game.cast_target_spec(0, bolt)
    by_id = {
        game.permanent_at(t["seat"], t["index"]).permanent_id: t["name"]
        for t in spec["valid_targets"] if t.get("kind") == "permanent"
    }
    assert by_id[clone.permanent_id] == "Grizzly Bears"
    assert "Clone" not in by_id.values()


@pytest.mark.cr("707.2", "603.3d")
def test_a_triggers_target_prompt_names_a_copy_by_what_it_copies(set_pool):
    """Man-o'-War's "return target creature" asked of a person, over a board
    with a Clone of Grizzly Bears on it."""
    man_o_war = set_pool("VIS")["Man-o'-War"]
    game, clone = _clone_of(set_pool, "Grizzly Bears", hand0=[man_o_war], interactive=(0,))
    result = game.cast_from_hand(0, "Man-o'-War")
    assert result.supported, result.details
    prompt = settle(game, defaults=False)
    assert prompt is not None and prompt.kind == "trigger_target", prompt
    offered = {entry["permanent_id"]: entry["name"] for entry in prompt.data["targets"]}
    assert offered[clone.permanent_id] == "Grizzly Bears"
    assert "Clone" not in offered.values()


@pytest.mark.cr("707.2", "502.3")
def test_the_optional_untap_list_names_a_copy_by_what_it_copies(set_pool):
    game, clone = _clone_of(set_pool, "Phyrexian Gremlins", original_set="ATQ")
    clone.tapped = True
    listed = {entry["id"]: entry["name"] for entry in game.get_optional_untap_permanents(0)}
    assert listed == {clone.permanent_id: "Phyrexian Gremlins"}


@pytest.mark.cr("707.2", "118.12")
def test_an_upkeep_tolls_prompt_names_a_copy_by_what_it_copies(set_pool):
    """Force of Nature's "…unless you pay {G}{G}{G}{G}", printed on a Clone."""
    game, clone = _clone_of(set_pool, "Force of Nature")
    tolls = {entry["permanent_id"]: entry["card_name"] for entry in game.get_upkeep_pay_triggers(0)}
    assert tolls[clone.permanent_id] == "Force of Nature"


@pytest.mark.cr("707.2", "707.4")
def test_vesuvan_doppelgangers_recopy_prompt_names_both_copies(set_pool):
    """The Doppelganger copying Grizzly Bears is offered a Clone of Serra
    Angel: the prompt's source and its target are named as the board names
    them."""
    lea = set_pool("LEA")
    game = _table(
        set_pool, hand0=[lea["Vesuvan Doppelganger"], lea["Clone"]],
        board0=[lea["Grizzly Bears"], lea["Serra Angel"]],
    )
    vesuvan = _copy(game, "Vesuvan Doppelganger", _on(game, 0, "Grizzly Bears"))
    clone = _copy(game, "Clone", _on(game, 0, "Serra Angel"))
    (entry,) = [
        e for e in game.get_optional_upkeep_triggers(0)
        if e.get("permanent_id") == vesuvan.permanent_id
    ]
    assert entry["card_name"] == "Grizzly Bears"
    assert entry["prompt"] == "Have Grizzly Bears become a copy of a different creature?"
    targets = {t["id"]: t["name"] for t in entry["valid_targets"]}
    assert targets[clone.permanent_id] == "Serra Angel"
    # The headless shorthand answers to the name the prompt gave it as well
    # as to the printed one.
    for key in ("Grizzly Bears", "Vesuvan Doppelganger"):
        keyed = game._upkeep_answers_by_permanent({key: True})
        assert keyed.get(vesuvan.permanent_id) is True, key


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.2", "302.6")
def test_a_summoning_sick_copy_is_refused_by_its_name(set_pool):
    game, clone = _clone_of(set_pool, "Prodigal Sorcerer")
    result = game.activate_permanent_ability(
        0, "Clone", permanent_index=game.battlefield_index_of(clone), target_player_index=1,
    )
    assert not result.supported
    assert result.details == "Prodigal Sorcerer has summoning sickness"


@pytest.mark.cr("707.2", "508.1a")
def test_a_tapped_copy_is_refused_as_an_attacker_by_its_name(set_pool):
    game, clone = _clone_of(set_pool, "Grizzly Bears")
    clone.tapped = True
    clone.metadata["summoning_sickness_turn"] = -99
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(clone)], defending_player_index=1,
    )
    assert not ok and why == "Grizzly Bears is tapped"


@pytest.mark.cr("707.2", "106.12")
def test_a_copied_artifact_land_is_tapped_and_refused_by_its_name(set_pool):
    """Sculpting Steel copying Seat of the Synod is an artifact land named
    Seat of the Synod: tapped for mana as that, and refused as that."""
    mrd = set_pool("MRD")
    game = _table(set_pool, hand0=[mrd["Sculpting Steel"]], board0=[mrd["Seat of the Synod"]])
    steel = _copy(game, "Sculpting Steel", _on(game, 0, "Seat of the Synod"))
    index = game.battlefield_index_of(steel)
    assert game.tap_land_for_mana_or_refusal(0, "Sculpting Steel", "U", index) is None
    assert "P0 tapped Seat of the Synod for mana" in game.log
    assert not any("Sculpting Steel for mana" in str(line) for line in game.log)
    refusal = game.tap_land_for_mana_or_refusal(0, "Sculpting Steel", "U", index)
    assert refusal == "Seat of the Synod is already tapped"


# ---------------------------------------------------------------------------
# The lines the engine's machinery logs about a permanent
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.2", "608.2h")
def test_a_copys_ability_is_named_by_its_source_on_the_stack(set_pool):
    game, clone = _clone_of(set_pool, "Prodigal Sorcerer")
    clone.metadata["summoning_sickness_turn"] = -99
    mark = len(game.log)
    result = game.activate_permanent_ability(
        0, "Clone", permanent_index=game.battlefield_index_of(clone), target_player_index=1,
    )
    assert result.supported, result.details
    settle(game)
    lines = [str(line) for line in game.log[mark:]]
    assert "Prodigal Sorcerer ability added to stack" in lines
    assert "Prodigal Sorcerer ability resolved" in lines
    assert game.players[1].life == 19


@pytest.mark.cr("707.2", "704.5g", "608.2h")
def test_a_copy_that_dies_to_lethal_damage_is_named_as_it_last_was(set_pool):
    game, clone = _clone_of(set_pool, "Prodigal Sorcerer", hand0=[set_pool("LEA")["Lightning Bolt"]])
    result = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(clone),
    )
    assert result.supported, result.details
    settle(game)
    assert "Prodigal Sorcerer died (704.5g: lethal damage)" in game.log
    # The card that went to the graveyard is the Clone (CR 400.7).
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt", "Clone"]


@pytest.mark.cr("707.2", "603.2")
def test_a_copys_attack_trigger_is_announced_by_its_name(set_pool):
    """A Clone of Library Larcenist attacks: "Whenever this creature attacks,
    draw a card" is the copy's, and its announcement names it as the board
    does."""
    game, clone = _clone_of(set_pool, "Library Larcenist", original_set="M21")
    # Only the copy attacks.
    _on(game, 0, "Library Larcenist").tapped = True
    clone.metadata["summoning_sickness_turn"] = -99
    mark = len(game.log)
    hand_before = len(game.players[0].hand)
    declare_attack(game, 0)
    settle(game)
    lines = [str(line) for line in game.log[mark:]]
    assert "Library Larcenist triggered on attack (added to stack)" in lines, lines
    assert not any(line.startswith("Clone triggered") for line in lines), lines
    assert len(game.players[0].hand) == hand_before + 1


@pytest.mark.cr("707.2", "400.7")
def test_the_spell_put_onto_the_battlefield_is_named_by_its_card(set_pool):
    """The direction that must not move: the card the resolving spell was is
    a Clone (CR 707.5 makes it a copy *as* it enters)."""
    game, _clone = _clone_of(set_pool, "Grizzly Bears")
    assert "P0 put Clone onto battlefield" in game.log
