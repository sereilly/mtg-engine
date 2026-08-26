"""Tests for Magic: The Gathering Comprehensive Rules Sections 613/707.

Covers:
  613.2a — layer 1a: copy effects are applied
  613.2c — after layer 1, the object's characteristics *are* its copiable values
  707.2  — what the copiable values are, and what is **not** copied
  707.2a — colour comes from the mana cost, abilities from the rules text
  707.2b — changing the original later does not change the copy
  707.3  — the copy's copiable values become the copied information, and an
           object copying *it* uses those new values
  707.4  — a permanent may copy something else without leaving the battlefield
  707.9a — a copy effect may grant the copy an ability
  707.9b — a copy effect may modify a characteristic ("in addition to its
           other types")
  707.9c — a copy effect may decline a characteristic, which the object then
           retains

CR 707.2's last sentence is the whole point of this file::

    Other effects (including type-changing and text-changing effects), status,
    counters, and stickers are not copied.

A model that stamps the *results* of copying onto the copy cannot hold that
line, because a stamp records an answer while the rule is a question about
where the answer came from. ``engine/copies.py`` records the copied object's
copiable values instead, and every characteristic is read back through the
layer system from there.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.copies import (
    ALL_VALUES,
    COLOR,
    EXCEPT_COLOR,
    RECOPY_EACH_UPKEEP,
    become_copy,
    copiable_card,
    copy_effects,
    copy_exceptions,
    end_copy,
    grants_ability,
    is_copy,
)
from engine.keywords import remove_keyword
from engine.models import Permanent
from engine.pt import add_pt_modifier, set_base_pt
from engine.text_changes import change_color_word


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _board(catalog, *names):
    perms = [Permanent(card=catalog[n]) for n in names]
    player = PlayerState(name="P1", battlefield=perms)
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, perms


# ---------------------------------------------------------------------------
# 613.2a / 613.2c — layer 1 produces the copiable values everything else reads
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.2c", "707.2")
def test_613_2c_a_permanent_that_copies_nothing_is_its_own_printed_card(catalog):
    """The fast path, and the contract: no copy effect means the card object
    itself, not a rebuilt equal one. ``effective_card`` sits under nearly every
    rules query, so an allocation here is an allocation everywhere."""
    _, (bears,) = _board(catalog, "Grizzly Bears")
    assert not is_copy(bears)
    assert copiable_card(bears) is bears.card
    assert bears.effective_card is bears.card


@pytest.mark.cr("613.2a", "707.2", "707.2a")
def test_707_2_a_copy_takes_name_types_text_colour_and_pt(catalog):
    """Clone copies every copiable value. Colour and abilities are included
    because 707.2a derives them from the mana cost and the rules text."""
    _, (clone, knight) = _board(catalog, "Clone", "Black Knight")
    become_copy(clone, knight)

    assert clone.effective_card.name == "Black Knight"
    assert clone.has_type("creature") and clone.has_type("knight")
    assert clone.effective_colors == {"B"}
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)
    assert clone.has_keyword("first strike")
    # The permanent's own card is untouched: it is still a Clone, so leaving
    # the battlefield takes the copy with it.
    assert clone.card.name == "Clone"


@pytest.mark.cr("707.2")
def test_707_2_counters_and_boosts_on_the_source_are_not_copied(catalog):
    """Layer 7c lives above layer 1, so it is not part of what is copied."""
    _, (clone, bears) = _board(catalog, "Clone", "Grizzly Bears")
    add_pt_modifier(bears, 3, 3)
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    become_copy(clone, bears)
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)


@pytest.mark.cr("707.2")
def test_707_2_a_base_pt_setting_effect_on_the_source_is_not_copied(catalog):
    """The bug the stamped model had by construction: a copy read its P/T out
    of ``absolute_power``, which is **layer 7b's** channel. Whatever a non-copy
    effect had set on the source was copied along with the printed value,
    because by then the two were the same number in the same place."""
    _, (clone, bears) = _board(catalog, "Clone", "Grizzly Bears")
    set_base_pt(bears, 0, 5)
    assert (bears.effective_power, bears.effective_toughness) == (0, 5)

    become_copy(clone, bears)
    assert (clone.effective_power, clone.effective_toughness) == (2, 2)


@pytest.mark.cr("707.2")
def test_707_2_a_text_change_on_the_source_is_not_copied(catalog):
    """"Other effects (including … text-changing effects) … are not copied."
    Copy Artifact used to read the source's ``effective_card``, which has
    layer 3 already folded into it."""
    _, (clone, knight) = _board(catalog, "Clone", "Black Knight")
    change_color_word(knight, "W", "R", label="Sleight of Mind")
    assert "protection from red" in knight.effective_card.oracle_text.lower()

    become_copy(clone, knight)
    text = clone.effective_card.oracle_text.lower()
    assert "protection from white" in text and "protection from red" not in text


@pytest.mark.cr("707.2")
def test_707_2_an_ability_removed_from_the_source_is_still_copied(catalog):
    """Layer 6 is above layer 1 too, so a removal on the source is not part of
    what the copy takes — and the copy's own printed abilities can then be
    removed independently."""
    _, (clone, knight) = _board(catalog, "Clone", "Black Knight")
    remove_keyword(knight, "first strike")
    assert not knight.has_keyword("first strike")

    become_copy(clone, knight)
    assert clone.has_keyword("first strike")

    remove_keyword(clone, "first strike")
    assert not clone.has_keyword("first strike")


@pytest.mark.cr("707.2b")
def test_707_2b_changing_the_original_afterwards_does_not_change_the_copy(catalog):
    """The contribution records the values as they were when it was created."""
    _, (clone, bears) = _board(catalog, "Clone", "Grizzly Bears")
    become_copy(clone, bears)
    add_pt_modifier(bears, 4, 4)
    set_base_pt(bears, 9, 9)

    assert (clone.effective_power, clone.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# 707.9 — the exceptions, each named positively
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.9c", "707.2a")
def test_707_9c_vesuvan_doppelganger_copies_everything_but_colour(catalog):
    """The exception is a *set of characteristics the effect takes* — colour is
    not in it — rather than a stamp that was never written. The two are
    distinguishable now, which is what the next test checks."""
    _, (dop, wurm) = _board(catalog, "Vesuvan Doppelganger", "Craw Wurm")
    become_copy(dop, wurm, copies=EXCEPT_COLOR)

    entry = copy_effects(dop)[-1]
    assert COLOR not in entry["copies"]
    assert entry["copies"] == EXCEPT_COLOR

    assert dop.effective_card.name == "Craw Wurm"
    assert (dop.effective_power, dop.effective_toughness) == (6, 4)
    assert dop.has_type("wurm")
    assert dop.effective_colors == {"U"}      # its own printed blue, retained


@pytest.mark.cr("707.9c", "707.2a")
def test_707_9c_declining_colour_differs_from_copying_a_colourless_object(catalog):
    """Under the stamped model these were the same state — no ``copied_colors``
    record — so Copy Artifact copying a colourless Sol Ring came out blue."""
    _, (dop, wurm, sol) = _board(catalog, "Vesuvan Doppelganger", "Craw Wurm", "Sol Ring")

    declined = Permanent(card=dop.card)
    become_copy(declined, wurm, copies=EXCEPT_COLOR)
    assert declined.effective_colors == {"U"}

    colourless = Permanent(card=dop.card)
    become_copy(colourless, sol)
    assert colourless.effective_colors == set()


@pytest.mark.cr("707.9b")
def test_707_9b_copy_artifact_is_an_enchantment_in_addition_to_its_types(catalog):
    """707.9b: the exception modifies a characteristic, and the modified value
    becomes part of the copy's copiable values."""
    _, (copier, sol) = _board(catalog, "Copy Artifact", "Sol Ring")
    become_copy(copier, sol, adds_types=("Enchantment",))

    assert copier.has_type("artifact") and copier.has_type("enchantment")
    assert copier.effective_card.name == "Sol Ring"
    assert copier.effective_produced_mana == sol.card.produced_mana


@pytest.mark.cr("707.9a")
def test_707_9a_a_granted_ability_is_part_of_the_copy(catalog):
    """Vesuvan Doppelganger's "and it has …" clause. Recorded on the copy
    effect, so it arrives with the copy and leaves with it."""
    _, (dop, wurm) = _board(catalog, "Vesuvan Doppelganger", "Craw Wurm")
    assert not grants_ability(dop, RECOPY_EACH_UPKEEP)

    become_copy(dop, wurm, copies=EXCEPT_COLOR, grants=(RECOPY_EACH_UPKEEP,))
    assert grants_ability(dop, RECOPY_EACH_UPKEEP)


@pytest.mark.cr("707.9a", "707.9b", "707.9c")
def test_707_9_the_exceptions_are_read_off_the_copiers_own_text(catalog):
    """Text-keyed, not name-keyed: the three templates in the pool are read off
    the printed exception clause, so a later card printed with one needs no
    entry anywhere."""
    from engine.oracle import compile_card_oracle

    def exceptions(name):
        return copy_exceptions(compile_card_oracle(catalog[name]).normalized_text)

    assert exceptions("Clone") == {
        "copies": ALL_VALUES, "adds_types": (), "grants": (),
    }
    assert exceptions("Vesuvan Doppelganger") == {
        "copies": EXCEPT_COLOR, "adds_types": (), "grants": (RECOPY_EACH_UPKEEP,),
    }
    assert exceptions("Copy Artifact") == {
        "copies": ALL_VALUES, "adds_types": ("Enchantment",), "grants": (),
    }


# ---------------------------------------------------------------------------
# 707.3 / 707.4 — copies of copies, and re-copying
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.2", "707.3")
def test_707_3_copying_a_copy_takes_what_the_first_copy_became(catalog):
    """"as modified by other copy effects". The stamped model recorded the
    source permanent's own ``card``, so a Clone of a Clone was a 0/0 blue
    Shapeshifter named Clone."""
    _, (first, second, wurm) = _board(catalog, "Clone", "Clone", "Craw Wurm")
    become_copy(first, wurm)
    become_copy(second, first)

    assert second.effective_card.name == "Craw Wurm"
    assert second.has_type("wurm")
    assert second.effective_colors == {"G"}
    assert (second.effective_power, second.effective_toughness) == (6, 4)


@pytest.mark.cr("707.3", "707.9c")
def test_707_3_a_copy_of_a_doppelganger_takes_its_retained_colour(catalog):
    """707.3: the Doppelganger's copiable values are the Wurm's *with blue
    retained*, and an object copying it uses those new values — so the Clone is
    a blue Craw Wurm even though Clone declines nothing."""
    _, (dop, clone, wurm) = _board(catalog, "Vesuvan Doppelganger", "Clone", "Craw Wurm")
    become_copy(dop, wurm, copies=EXCEPT_COLOR)
    become_copy(clone, dop)

    assert clone.effective_card.name == "Craw Wurm"
    assert clone.effective_colors == {"U"}
    assert (clone.effective_power, clone.effective_toughness) == (6, 4)


@pytest.mark.cr("707.4")
def test_707_4_re_copying_replaces_the_contribution_rather_than_stacking(catalog):
    """Vesuvan's upkeep ability copies something else without leaving the
    battlefield. One contribution per source, re-recorded with a fresh
    timestamp — otherwise a once-per-upkeep ability grows the fold by an entry
    every turn."""
    _, (dop, wurm, knight) = _board(catalog, "Vesuvan Doppelganger", "Craw Wurm", "Black Knight")
    become_copy(dop, wurm, copies=EXCEPT_COLOR)
    become_copy(dop, knight, copies=EXCEPT_COLOR)

    assert len(copy_effects(dop)) == 1
    assert dop.effective_card.name == "Black Knight"
    assert (dop.effective_power, dop.effective_toughness) == (2, 2)
    assert dop.effective_colors == {"U"}


@pytest.mark.cr("707.4", "613.2c")
def test_707_4_a_noncopy_effect_survives_the_re_copy(catalog):
    """"This also doesn't change any noncopy effects presently affecting the
    permanent." A +1/+1 counter is in layer 7c, above layer 1, so re-copying
    cannot disturb it — and does not have to remember it either."""
    _, (dop, wurm, knight) = _board(catalog, "Vesuvan Doppelganger", "Craw Wurm", "Black Knight")
    become_copy(dop, wurm, copies=EXCEPT_COLOR)
    add_pt_modifier(dop, 1, 1)
    assert (dop.effective_power, dop.effective_toughness) == (7, 5)

    become_copy(dop, knight, copies=EXCEPT_COLOR)
    assert (dop.effective_power, dop.effective_toughness) == (3, 3)


@pytest.mark.cr("613.2c")
def test_613_2c_ending_a_copy_effect_is_dropping_a_contribution(catalog):
    """Nothing in this pool ends one, but removal is the *absence* of a
    contribution here as it is in every other layer — not a stamp somebody has
    to remember to un-stamp."""
    _, (clone, wurm) = _board(catalog, "Clone", "Craw Wurm")
    become_copy(clone, wurm)
    assert clone.effective_card.name == "Craw Wurm"

    assert end_copy(clone, source=clone) is True
    assert end_copy(clone, source=clone) is False
    assert clone.effective_card is clone.card
    assert clone.copied_from is None


# ---------------------------------------------------------------------------
# The cards, end to end
# ---------------------------------------------------------------------------


@pytest.mark.cr("707.5", "707.9c")
def test_707_5_vesuvan_doppelganger_enters_as_a_blue_copy(catalog):
    """The card, cast: it enters as a copy (707.5) of the Wurm, with the colour
    exception applied."""
    wurm = Permanent(card=catalog["Craw Wurm"])
    p1 = PlayerState(name="P1", hand=[catalog["Vesuvan Doppelganger"]], battlefield=[wurm])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Vesuvan Doppelganger", target_player_index=0, target_permanent_index=0)

    dop = p1.battlefield[-1]
    assert dop.copied_from == "Craw Wurm"
    assert (dop.effective_power, dop.effective_toughness) == (6, 4)
    assert dop.effective_colors == {"U"}
    assert grants_ability(dop, RECOPY_EACH_UPKEEP)


@pytest.mark.cr("707.5", "707.9b")
def test_707_5_copy_artifact_enters_as_a_colourless_sol_ring(catalog):
    """Copy Artifact is blue; Sol Ring is colourless. The copy is colourless,
    which the stamped model got wrong because "copied no colours" and "copied a
    colourless object" were the same absent record."""
    sol = Permanent(card=catalog["Sol Ring"])
    p1 = PlayerState(name="P1", hand=[catalog["Copy Artifact"]], battlefield=[sol])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Copy Artifact", target_player_index=0, target_permanent_index=0)

    copy = p1.battlefield[-1]
    assert copy.copied_from == "Sol Ring"
    assert copy.effective_colors == set()
    assert copy.has_type("artifact") and copy.has_type("enchantment")


@pytest.mark.cr("707.2", "613.1b")
def test_707_2_control_is_not_a_copiable_value(catalog):
    """Layer 1 and layer 2 answer different questions about the same permanent.

    A copy of a creature an opponent controls is controlled by the copier's
    controller — control is not in CR 707.2's list — and taking control of the
    copy afterwards changes nothing about what it copies. The two are separate
    contributions on separate layers, so neither can be read off the other.
    """
    theirs = Permanent(card=catalog["Craw Wurm"])
    mine = PlayerState(name="P1", hand=[catalog["Clone"]])
    yours = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[mine, yours])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Clone", target_player_index=1, target_permanent_index=0)

    clone = mine.battlefield[-1]
    assert clone.copied_from == "Craw Wurm"
    assert game.controller_index_of(clone) == 0
    assert game.controller_index_of(theirs) == 1

    thief = Permanent(card=catalog["Control Magic"])
    game.take_control(clone, 1, source=thief)
    assert game.controller_index_of(clone) == 1
    assert clone.effective_card.name == "Craw Wurm"
    assert (clone.effective_power, clone.effective_toughness) == (6, 4)


@pytest.mark.cr("707.9b")
def test_707_9b_the_added_type_is_a_card_type_not_a_subtype(catalog):
    """"In addition to its other types" adds a *card type*. Appending it to a
    type line that has a subtype dash would file it as a subtype instead."""
    sol = catalog["Sol Ring"]
    dashed = dataclasses.replace(sol, type_line="Artifact — Equipment")
    copier = Permanent(card=catalog["Copy Artifact"])
    become_copy(copier, Permanent(card=dashed), adds_types=("Enchantment",))

    assert copier.effective_card.type_line == "Artifact Enchantment — Equipment"
    assert copier.has_type("enchantment") and copier.has_type("equipment")


# ---------------------------------------------------------------------------
# 707.10 — copying a spell or ability on the stack
#
# A different act from copying a permanent, which is everything above: the copy
# is *put onto the stack*, it was never cast, and it ceases to exist instead of
# going to a graveyard. Fork is the pool's copier ("Copy target instant or
# sorcery spell…"); Double Vision is M21's triggered form.
# ---------------------------------------------------------------------------

@pytest.mark.cr("707.10")
def test_707_10_the_copy_is_put_onto_the_stack_and_was_never_cast():
    """To copy a spell means to put a copy of it onto the stack.

    The copy is marked as one and is not a cast spell: it appears above the
    original without passing through anyone's hand.
    """
    catalog = {card.name: card for card in load_catalog()}
    p1 = PlayerState(name="P1", hand=[catalog["Lightning Bolt"], catalog["Fork"]])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.queue_from_hand(0, "Fork", target_player_index=1, target_stack_index=0)
    game.resolve_top_of_stack()  # Fork resolves and makes the copy

    copy = game.stack[-1]
    assert copy.is_copy is True
    assert copy.card.name == "Lightning Bolt"
    assert [c.name for c in p1.spells_cast_this_turn] == ["Lightning Bolt", "Fork"]


@pytest.mark.cr("707.10a")
def test_707_10a_the_copy_ceases_to_exist_instead_of_reaching_a_graveyard():
    """A copy of a spell in any zone other than the stack ceases to exist.

    So after both resolve, the damage landed twice but exactly one Lightning
    Bolt card is in a graveyard — the copy left no card behind.
    """
    catalog = {card.name: card for card in load_catalog()}
    p1 = PlayerState(name="P1", hand=[catalog["Lightning Bolt"], catalog["Fork"]])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.queue_from_hand(0, "Fork", target_player_index=1, target_stack_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    assert p2.life == 14  # 3 from the original, 3 from the copy
    bolts = [c for player in game.players for c in player.graveyard
             if c.name == "Lightning Bolt"]
    assert len(bolts) == 1


@pytest.mark.cr("707.10c")
def test_707_10c_the_controller_may_choose_new_targets_for_the_copy():
    """"You may choose new targets for the copy" — the copy resolves against a
    target the original never had."""
    catalog = {card.name: card for card in load_catalog()}
    bears_a = Permanent(card=catalog["Grizzly Bears"])
    bears_b = Permanent(card=catalog["Grizzly Bears"])
    p1 = PlayerState(name="P1", hand=[catalog["Giant Growth"], catalog["Fork"]],
                     battlefield=[bears_a, bears_b])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.queue_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)
    game.queue_from_hand(0, "Fork", target_stack_index=0,
                         target_player_index=0, target_permanent_index=1)
    while game.stack:
        game.resolve_top_of_stack()

    assert bears_a.effective_power == 5
    assert bears_b.effective_power == 5


@pytest.mark.cr("707.10c")
def test_707_10c_leaving_the_targets_unchanged_is_equally_legal():
    """The player *may* change targets; declining leaves the copy pointed where
    the original was, and both resolve at the same object."""
    catalog = {card.name: card for card in load_catalog()}
    bears = Permanent(card=catalog["Grizzly Bears"])
    p1 = PlayerState(name="P1", hand=[catalog["Giant Growth"], catalog["Fork"]],
                     battlefield=[bears])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.queue_from_hand(0, "Giant Growth", target_player_index=0, target_permanent_index=0)
    game.queue_from_hand(0, "Fork", target_stack_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    assert bears.effective_power == 8  # 2 + 3 + 3, both buffs on one creature


@pytest.mark.cr("707.10")
def test_707_10_a_copy_is_controlled_by_whoever_it_was_put_on_the_stack_under(
    set_pool,
):
    """"A copy of a spell is controlled by the player under whose control it was
    put on the stack."

    Fork's copy is the caster's, which makes the caster and the copy's
    controller the same seat and hides the rule. Chain Lightning's is not: the
    copy is offered to whoever the damage landed on, so the copy is put on the
    stack under an *opponent's* control and resolves as their spell.
    """
    catalog = {card.name: card for card in load_catalog()}
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Chain Lightning"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=catalog["Mountain"]) for _ in range(2)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}

    game.cast_from_hand(0, "Chain Lightning", target_player_index=1)
    game.confirm_optional_pay(1, accept=True)   # the {R}{R}
    game.confirm_optional_pay(1, accept=True)   # "they may copy this spell"

    copy = game.stack[-1]
    assert copy.is_copy is True
    assert copy.caster_index == 1
    assert [c.name for c in p2.spells_cast_this_turn] == []


@pytest.mark.cr("707.10c")
def test_707_10c_the_new_target_may_be_a_player_rather_than_a_permanent(set_pool):
    """The copy's controller re-aims an "any target" spell at a player face.

    CR 115.4 makes a player a legal answer, so a picker that could only offer
    permanents would leave half the rule unreachable — and for Chain Lightning
    it is the half the card is played for.
    """
    catalog = {card.name: card for card in load_catalog()}
    p1 = PlayerState(name="P1", hand=[set_pool("LEG")["Chain Lightning"]])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=catalog["Mountain"]) for _ in range(2)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {1}

    game.cast_from_hand(0, "Chain Lightning", target_player_index=1)
    game.confirm_optional_pay(1, accept=True)
    game.confirm_optional_pay(1, accept=True)
    assert game.confirm_copy_spell_target(1, target_seat=0) is True
    game.resolve_top_of_stack()

    assert p2.life == 17   # the original
    assert p1.life == 17   # the copy, sent back
