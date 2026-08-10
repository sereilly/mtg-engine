"""CR 611.3 / 613 — "All <land type>s are P/T creatures that are still lands".

Kormus Bell and Living Lands are one printed template with three parameters:
the land type (layer 4, CR 613.1d), the power/toughness the lands take (layer 7,
CR 613.1g) and — optionally — a colour (layer 5, CR 613.1e).

``engine/land_animation.py`` derives all three from the printed sentence. Before
it, the *gate* was two ``in text`` literals and the *dispatch* was two
``perm.card.name ==`` comparisons, so both failure modes this repo keeps finding
were live at once:

* a card printed "All Mountains are …" compiled **unsupported**, and
* a differently-named card with Kormus Bell's exact text compiled **supported**
  and animated nothing.

Every property below is therefore pinned with an **invented** card. A test
naming only Kormus Bell passes against the broken version, which is exactly how
the sibling combat-restriction bug survived.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _card(name: str, type_line: str, oracle_text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line},
    )


def _land(name: str, subtype: str) -> CardDefinition:
    return _card(name, f"Basic Land — {subtype.title()}")


def _game(*battlefields) -> tuple[Game, list[PlayerState]]:
    players = [
        PlayerState(name=f"P{index + 1}", battlefield=list(perms), life=20)
        for index, perms in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    return game, players


# Invented animators. None of these names has ever been printed, and the second
# one's land type, P/T and colour all differ from anything in the pool — so
# nothing below can pass by matching one card's literals.
BOG_CHIME = _card(
    "Bog Chime", "Artifact",
    "All Swamps are 1/1 black creatures that are still lands.",
)
PEAK_CHIME = _card(
    "Peak Chime", "Enchantment",
    "All Mountains are 3/2 red creatures that are still lands.",
)
TIDE_CHIME = _card(
    "Tide Chime", "Artifact",
    "All Islands are 2/2 creatures that are still lands.",
)


# ---------------------------------------------------------------------------
# The template, on cards the engine has never seen
# ---------------------------------------------------------------------------

@pytest.mark.cr("613.1d", "613.1g", "611.3a")
def test_animation_is_keyed_on_the_printed_line_not_the_card_name():
    """An invented card with Kormus Bell's exact text animates Swamps.

    This is the whole point of the table: the dispatch used to read
    ``perm.card.name == "Kormus Bell"``, so this card compiled *supported* and
    then did nothing at all.
    """
    swamp = Permanent(card=_land("Swamp", "swamp"))
    _game([Permanent(card=BOG_CHIME), swamp])

    assert swamp.is_creature is True
    assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)
    assert swamp.has_type("land") is True


@pytest.mark.cr("613.1d", "613.1e", "613.1g")
def test_land_type_power_toughness_and_colour_are_all_payload():
    """A third land type, a non-1/1 body and a different colour need no code.

    The instruction kinds this replaced spelled the land type out
    (``animate_all_swamps`` / ``animate_all_forests``) and the refresh hardcoded
    1/1 and black, so each of these three parameters was a separate way for the
    template to be unimplementable.
    """
    mountain = Permanent(card=_land("Mountain", "mountain"))
    swamp = Permanent(card=_land("Swamp", "swamp"))
    _game([Permanent(card=PEAK_CHIME), mountain, swamp])

    assert mountain.is_creature is True
    assert (mountain.effective_power, mountain.effective_toughness) == (3, 2)
    assert mountain.effective_colors == {"R"}
    # The other land type is untouched — the animation reads its own payload,
    # not "every basic land".
    assert swamp.is_creature is False


@pytest.mark.cr("613.1e")
def test_a_line_naming_no_colour_leaves_the_lands_their_own():
    """Living Lands' form. The colour is optional in the template, so it has to
    be optional in the payload — animating an Island as black would be reading a
    word the card does not print."""
    island = Permanent(card=_land("Island", "island"))
    _game([Permanent(card=TIDE_CHIME), island])

    assert island.is_creature is True
    assert (island.effective_power, island.effective_toughness) == (2, 2)
    assert "B" not in island.effective_colors


@pytest.mark.cr("611.3b")
def test_animation_ends_when_the_source_leaves_the_battlefield():
    """CR 611.3b: the continuous effect applies only while its source is on the
    battlefield, so the land stops being a creature the moment the source goes."""
    chime = Permanent(card=PEAK_CHIME)
    mountain = Permanent(card=_land("Mountain", "mountain"))
    game, players = _game([chime, mountain])
    assert mountain.is_creature is True

    players[0].battlefield.remove(chime)
    game._refresh_dynamic_creatures()

    assert mountain.is_creature is False
    assert mountain.effective_colors != {"R"}


@pytest.mark.cr("611.3a")
def test_two_animators_each_reach_their_own_land_type():
    """Nothing in the refresh is single-source: each land takes the animation
    whose land type it has."""
    mountain = Permanent(card=_land("Mountain", "mountain"))
    swamp = Permanent(card=_land("Swamp", "swamp"))
    _game([Permanent(card=PEAK_CHIME), Permanent(card=BOG_CHIME), mountain, swamp])

    assert (mountain.effective_power, mountain.effective_toughness) == (3, 2)
    assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)


# ---------------------------------------------------------------------------
# The gate reads the same table as the dispatch
# ---------------------------------------------------------------------------

@pytest.mark.cr("613.1d")
def test_an_unreadable_rider_makes_the_card_unsupported_not_silent():
    """A loose gate over a strict dispatch is how a restriction goes missing.

    "All Swamps are 1/1 black creatures that are still lands *and can't block*"
    is not this template. The table refuses it, so the card is reported
    unsupported and loud rather than admitted and half-applied.
    """
    program = compile_card_oracle(_card(
        "Warped Chime", "Artifact",
        "All Swamps are 1/1 black creatures that are still lands and can't block.",
    ))
    assert program.supported is False


@pytest.mark.cr("613.1d")
def test_an_unknown_land_type_is_refused_rather_than_guessed():
    program = compile_card_oracle(_card(
        "Hollow Chime", "Artifact",
        "All Bogs are 1/1 black creatures that are still lands.",
    ))
    assert program.supported is False


# ---------------------------------------------------------------------------
# The printed cards, for the CR anchor
# ---------------------------------------------------------------------------

@pytest.mark.cr("613.1d", "613.1e", "613.1g")
def test_kormus_bell_animates_swamps_black_one_one(cards):
    swamp = Permanent(card=_land("Swamp", "swamp"))
    _game([Permanent(card=cards["Kormus Bell"]), swamp])

    assert swamp.is_creature is True
    assert (swamp.effective_power, swamp.effective_toughness) == (1, 1)
    assert swamp.effective_colors == {"B"}


@pytest.mark.cr("613.1d", "613.1g")
def test_living_lands_animates_forests(cards):
    forest = Permanent(card=_land("Forest", "forest"))
    _game([Permanent(card=cards["Living Lands"]), forest])

    assert forest.is_creature is True
    assert (forest.effective_power, forest.effective_toughness) == (1, 1)
