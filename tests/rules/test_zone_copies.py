"""CR 613 layer 1 for a copy effect whose source is a **position in a zone**.

Every other copy in this pool is set at a moment — something enters, a trigger
fires — and ``engine/copies.py`` records the copied object's copiable values
then and there (CR 707.2b). Volrath's Shapeshifter has no such moment: its
static ability asks a standing question about the top card of a graveyard, and
the answer changes when a card is discarded, when a creature dies, when a spell
finishes resolving — with no trigger and no event for a fire site to hang off.

So the contribution is *derived*: what is stored on the permanent is only which
zone to read, and ``copiable_card`` resolves it every time layer 1 is folded.
This file is the behaviour that shape has to have.

Covers:
  109.5  — "your" on a static ability is the object's current controller
  121.1  — a draw takes the **top** card of a library
  205.2b — an object with several card types satisfies criteria for any of them
  401.2  — a library is one face-down pile whose order players can't change
  404.1  — an object put into a graveyard goes on **top** of it
  613.1a — layer 1: rules and effects that modify copiable values
  613.2a — layer 1a: copy effects
  613.2c — after layer 1, the object's characteristics *are* its copiable values
  613.6  — an effect that has started to apply keeps applying even if the
           ability generating it is removed
  613.7a — a static ability's continuous effect is stamped with its object
  707.2  — what the copiable values are
  707.2c — a static ability's copy effect grants copiable values determined when
           that effect first starts to apply
  707.9a — a copy effect may grant the copy an ability
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog, manifest_set_path, load_cards
from engine.copies import become_copy, copiable_card, copied_name, is_copy
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier
from engine.zone_positions import TOP_INDEX, top_card, top_index

SHIFTER = "Volrath's Shapeshifter"


@pytest.fixture(scope="module")
def catalog():
    return {card.name: card for card in load_catalog()}


@pytest.fixture(scope="module")
def sth():
    return {
        card.name: card
        for card in load_cards(manifest_set_path("STH", include_measured=True))
    }


def _rig(sth, graveyard=()):
    shifter = Permanent(card=sth[SHIFTER])
    shifter.metadata["summoning_sickness_turn"] = -99
    seats = [
        PlayerState(name="P1", battlefield=[shifter], graveyard=list(graveyard)),
        PlayerState(name="P2"),
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, seats, shifter


@pytest.mark.cr("404.1", "121.1", "401.2")
def test_the_top_of_a_graveyard_and_the_top_of_a_library_are_opposite_ends():
    """The hazard :mod:`engine.zone_positions` exists for.

    CR 404.1 puts an arriving object on **top** of a graveyard and this engine
    appends, so the graveyard's top is the last element. CR 121.1 has a draw take
    the **top** card of a library and ``PlayerState.draw`` pops index 0, so the
    library's top is the first. Both are ordinary Python and neither end
    announces itself, so a reader written for one zone and pointed at the other
    keeps working and silently names the wrong card.
    """
    assert TOP_INDEX["graveyard"] == -1
    assert TOP_INDEX["library"] == 0

    pile = ["oldest", "middle", "newest"]
    assert top_card("graveyard", pile) == "newest"
    assert top_card("library", pile) == "oldest"
    assert top_index("graveyard", pile) == 2
    assert top_index("library", pile) == 0

    # An empty zone has no top card, which is "the condition is false" and not
    # an error — a graveyard is empty for most of most games.
    assert top_card("graveyard", []) is None
    assert top_index("library", []) is None

    # A zone this module has no answer for raises rather than guessing: the two
    # candidate answers are each other's opposite.
    with pytest.raises(KeyError):
        top_card("exile", ["a"])


@pytest.mark.cr("613.1a", "613.2a", "707.2")
def test_the_derived_copy_replaces_the_copiable_values(sth, catalog):
    """Layer 1a, not a modification over the printed card.

    A 0/1 Shapeshifter with a Shivan Dragon on top of its graveyard is a 5/5
    Shivan Dragon — its own printed name, cost, types, text and P/T are gone
    rather than adjusted, because CR 613.2c makes layer 1's result the values
    every later layer starts from.
    """
    game, seats, shifter = _rig(sth, [catalog["Shivan Dragon"]])

    values = copiable_card(shifter)
    assert values.name == "Shivan Dragon"
    assert values.mana_cost == "{4}{R}{R}"
    assert (values.power, values.toughness) == ("5", "5")
    assert is_copy(shifter)
    assert copied_name(shifter) == "Shivan Dragon"


@pytest.mark.cr("613.2c")
def test_later_layers_apply_over_the_copied_values(sth, catalog):
    """CR 613.2c: after layer 1 the object's characteristics *are* its copiable
    values, so a layer-7c modifier adds to the **copied** P/T and not to the
    printed 0/1."""
    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    assert (shifter.effective_power, shifter.effective_toughness) == (2, 2)

    add_pt_modifier(shifter, 1, 1)
    assert (shifter.effective_power, shifter.effective_toughness) == (3, 3)

    # And the modifier is not copied away when the copy changes: layer 7 is
    # applied over whatever layer 1 leaves, each recompute.
    seats[0].graveyard.append(catalog["Shivan Dragon"])
    assert (shifter.effective_power, shifter.effective_toughness) == (6, 6)


@pytest.mark.cr("707.2c", "404.1")
def test_the_effect_stops_and_starts_again_as_the_condition_turns(sth, catalog):
    """CR 707.2c: a static ability's copy effect grants the copiable values
    determined when that effect **first starts to apply**.

    Which is why the answer has to be re-derived rather than recorded: the effect
    stops applying the moment the top card stops being a creature card, and
    starts applying anew — against whatever is on top *then* — the moment one is
    back. Nothing fires at either boundary.
    """
    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    assert shifter.effective_card.name == "Grizzly Bears"

    seats[0].graveyard.append(catalog["Lightning Bolt"])
    assert shifter.effective_card.name == SHIFTER
    assert not is_copy(shifter), "an armed effect whose condition is false"

    seats[0].graveyard.append(catalog["Shivan Dragon"])
    assert shifter.effective_card.name == "Shivan Dragon"


@pytest.mark.cr("707.9a")
def test_the_granted_ability_rides_the_copy_and_is_added_once(sth, catalog):
    """CR 707.9a: the granted ability becomes part of the copy's copiable values,
    *in addition to* what was copied.

    Appended once however many times the top card has changed — a second copy of
    the sentence would give the permanent the ability twice, and this is the one
    the Shapeshifter reloads itself with.
    """
    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    seats[0].graveyard.append(catalog["Shivan Dragon"])

    text = shifter.effective_card.oracle_text
    assert text.count("{2}: Discard a card.") == 1, text
    assert "Flying" in text, "the copied card's own text is still there"

    lines = [a.source_line for a in compile_card_oracle(shifter.effective_card).activated_abilities]
    assert "{2}: Discard a card." in lines
    assert "{R}: This creature gets +1/+0 until end of turn." in lines


@pytest.mark.cr("613.6")
def test_the_copy_keeps_applying_though_it_erases_its_own_ability(sth, catalog):
    """CR 613.6: an effect that has started to apply keeps applying "even if the
    ability generating the effect is removed during this process".

    The copy replaces the permanent's rules text, so the "as long as…" sentence
    that generated it is not in what the permanent now says. Reading the effect
    off the *effective* card would therefore drop it on the next recompute and
    the copy would flicker on and off one pass at a time; it is read off the
    recorded copiable values instead.
    """
    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    assert "As long as the top card" not in shifter.effective_card.oracle_text

    for _ in range(3):
        game._refresh_dynamic_creatures()
        assert shifter.effective_card.name == "Grizzly Bears"

    seats[0].graveyard.append(catalog["Shivan Dragon"])
    game._refresh_dynamic_creatures()
    assert shifter.effective_card.name == "Shivan Dragon"


@pytest.mark.cr("109.5")
def test_your_graveyard_is_the_current_controllers(sth, catalog):
    """CR 109.5: for a static ability, "your" is the **current** controller of the
    object it is on. A stolen Shapeshifter reads its new controller's graveyard,
    which is what makes the source a refresh rather than a one-time arming."""
    from engine.control import change_control, set_base_controller

    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    seats[1].graveyard.append(catalog["Shivan Dragon"])
    set_base_controller(shifter, 0)
    assert shifter.effective_card.name == "Grizzly Bears"

    change_control(shifter, 1, source=object())
    game._sync_control()
    game._refresh_dynamic_creatures()
    assert game.controller_index_of(shifter) == 1
    assert shifter.effective_card.name == "Shivan Dragon"


@pytest.mark.cr("613.7a")
def test_a_recorded_copy_applies_over_the_derived_one(sth, catalog):
    """CR 613.7a stamps a static ability's continuous effect with the object the
    ability is on, so it is always earlier than an effect that later copies
    something *onto* that object. Layer 1a is timestamp-ordered, so the recorded
    contribution is applied last and wins."""
    game, seats, shifter = _rig(sth, [catalog["Grizzly Bears"]])
    assert shifter.effective_card.name == "Grizzly Bears"

    wurm = Permanent(card=catalog["Craw Wurm"])
    seats[0].battlefield.append(wurm)
    become_copy(shifter, wurm)
    assert shifter.effective_card.name == "Craw Wurm"
    assert (shifter.effective_power, shifter.effective_toughness) == (6, 4)


@pytest.mark.cr("205.2b")
def test_a_card_type_test_over_a_zone_reads_every_printed_type(sth, catalog):
    """CR 205.2b: an object with more than one card type satisfies the criteria
    for any of them.

    ``CardDefinition.primary_type`` returns the **first** of a fixed list, so
    "Artifact Creature" answers "creature" and never "artifact" — the
    disagreement SET_PLAYBOOK's Known gaps records for 77 cards in this pool.
    The template's card type is payload, so both readings are reachable, and the
    condition is tested with ``search_filters.card_has_type`` — which is what
    makes "an artifact card" find Battering Ram rather than nothing.
    """
    from engine.zone_copies import ZoneTopCopy, copied_card_for

    ram = catalog["Battering Ram"]
    assert "artifact creature" in ram.type_line.lower()
    assert ram.primary_type == "creature", "the reader that only sees one type"

    as_creature = ZoneTopCopy("graveyard", "your", "creature")
    as_artifact = ZoneTopCopy("graveyard", "your", "artifact")
    assert copied_card_for([ram], as_creature) is ram
    assert copied_card_for([ram], as_artifact) is ram, (
        "primary_type would deny this one"
    )
    assert copied_card_for([catalog["Mountain"]], as_creature) is None

    # And the printed card, end to end.
    game, seats, shifter = _rig(sth, [ram])
    assert shifter.effective_card.name == "Battering Ram"
