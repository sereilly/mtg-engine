"""Tests for Magic: The Gathering Comprehensive Rules Section 604.

Covers:
  604.3 — Characteristic-defining abilities

Every one of these was a literal containing the card's own name, in two places:
a whitelist entry gating support and an `elif` emitting a per-card instruction
kind. They are one template with a parameter, so these tests use invented cards
throughout — a test naming only Nightmare, Keldon Warlord, Plague Rats and
Gaea's Liege would pass against the version that hardcoded exactly those four.
"""

import pytest

from engine import Game, PlayerState
from engine.characteristic_defining import dynamic_pt_for
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line


def _cda_card(name: str, text: str, type_line: str = "Creature — Horror") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{2}{B}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "*", "toughness": "*"},
    )


@pytest.mark.cr("604.3")
def test_604_3_land_count_pt_is_recognized_whatever_the_card_is_called():
    """"<name>'s power and toughness are each equal to the number of Swamps you
    control" was whitelisted as a literal *including the card's own name*, which
    `normalize_creature_line` does not replace. Every reprint and every
    functionally identical card would have needed its own whitelist line, and
    until it got one the card compiled as unsupported."""
    from engine.characteristic_defining import dynamic_pt_for

    for name, land in (("nightmare", "swamp"), ("volcano horror", "mountain"),
                       ("some other creature", "forest")):
        line = (f"{name}'s power and toughness are each equal to "
                f"the number of {land}s you control")
        found = dynamic_pt_for(line)

        assert found is not None, line
        assert found.kind == "dynamic_pt_count"
        assert found.payload == {"count": "land", "land_type": land, "scope": "you"}


@pytest.mark.cr("604.3")
def test_604_3_the_counted_land_type_comes_from_the_text():
    """The type is data, not part of the instruction kind. One kind and one
    counter serve every basic type, so a card printed with a new one needs no
    code at all — where before it needed a whitelist line, an `elif` branch and
    a counter-registry entry."""
    from engine.card_loader import load_catalog
    from engine.models import CardDefinition

    catalog = {c.name: c for c in load_catalog()}
    variant = CardDefinition(
        name="Volcano Horror", mana_cost="{5}{R}", cmc=6.0,
        type_line="Creature — Horror",
        oracle_text=("Flying\nVolcano Horror's power and toughness are each equal "
                     "to the number of Mountains you control."),
        colors=("R",), color_identity=("R",), keywords=("Flying",), produced_mana=(),
        raw={"name": "Volcano Horror", "type_line": "Creature — Horror",
             "power": "*", "toughness": "*"},
    )
    horror = Permanent(card=variant)
    player = PlayerState(
        name="P1",
        battlefield=[horror] + [Permanent(card=catalog["Mountain"]) for _ in range(4)],
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game._refresh_dynamic_creatures()

    assert (horror.effective_power, horror.effective_toughness) == (4, 4)


@pytest.mark.cr("604.3")
def test_604_3_creature_count_with_a_type_exclusion_is_name_agnostic():
    """Keldon Warlord's "number of non-Wall creatures you control"."""
    line = normalize_creature_line(
        "Some Other Warlord's power and toughness are each equal to "
        "the number of non-Wall creatures you control."
    )
    found = dynamic_pt_for(line)
    assert found is not None
    assert found.payload == {"count": "creature", "scope": "you", "exclude_type": "wall"}


@pytest.mark.cr("604.3")
def test_604_3_the_excluded_creature_type_is_read_from_the_text():
    """"non-Wall" is data. The old branch matched the literal string
    "non-wall creatures", so the same template excluding any other type
    produced no instruction."""
    for excluded in ("wall", "goblin", "djinn"):
        line = normalize_creature_line(
            f"Probe's power and toughness are each equal to "
            f"the number of non-{excluded} creatures you control."
        )
        found = dynamic_pt_for(line)
        assert found is not None, excluded
        assert found.payload["exclude_type"] == excluded


@pytest.mark.cr("604.3")
def test_604_3_creature_count_excludes_by_layer_4_type_not_the_printed_line():
    """An animated land is a creature (CR 613.1d), so it counts toward "the
    number of non-Wall creatures you control". The replaced counter tested
    `card.primary_type == "creature"` against the printed line, which no
    animation ever updates — it would have counted 1 here, not 2."""
    from engine.card_loader import load_catalog

    catalog = {c.name: c for c in load_catalog()}
    warlord = Permanent(card=_cda_card(
        "Probe Warlord",
        "Probe Warlord's power and toughness are each equal to "
        "the number of non-Wall creatures you control.",
    ))
    swamp = Permanent(card=catalog["Swamp"])
    player = PlayerState(name="P1", battlefield=[warlord, swamp])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game._refresh_dynamic_creatures()
    assert swamp.is_creature is False
    assert warlord.effective_power == 1          # only itself

    # Kormus Bell: "All Swamps are 1/1 black creatures that are still lands."
    player.battlefield.append(Permanent(card=catalog["Kormus Bell"]))
    game._refresh_dynamic_creatures()
    assert swamp.is_creature is True
    assert warlord.effective_power == 2          # itself + the animated Swamp


@pytest.mark.cr("604.3")
def test_604_3_same_name_count_uses_the_cards_own_name():
    """Plague Rats. The old branch matched the literal "creatures named plague
    rats", so any other card with this template — the whole Relentless Rats
    family — produced nothing."""
    for name in ("Plague Rats", "Relentless Rats", "Rat Colony"):
        line = normalize_creature_line(
            f"{name}'s power and toughness are each equal to the number of "
            f"creatures named {name} on the battlefield."
        )
        found = dynamic_pt_for(line)
        assert found is not None, name
        assert found.payload == {"count": "same_name", "scope": "all"}


@pytest.mark.cr("604.3")
def test_604_3_counting_a_different_cards_name_is_refused():
    """"Creatures named X" only means "named like me" when X is the subject.
    The counter works from the permanent it refreshes, so a card counting some
    *other* name would silently count the wrong creatures — it must be reported
    unsupported instead."""
    line = normalize_creature_line(
        "Impostor Rats's power and toughness are each equal to the number of "
        "creatures named Plague Rats on the battlefield."
    )
    assert dynamic_pt_for(line) is None


@pytest.mark.cr("604.3")
def test_604_3_same_name_counts_across_both_battlefields():
    card = _cda_card(
        "Probe Rats",
        "Probe Rats's power and toughness are each equal to the number of "
        "creatures named Probe Rats on the battlefield.",
    )
    mine, theirs = Permanent(card=card), Permanent(card=card)
    p1 = PlayerState(name="P1", battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()

    assert (mine.effective_power, mine.effective_toughness) == (2, 2)


@pytest.mark.cr("604.3")
def test_604_3_attacking_split_land_count_is_name_and_type_agnostic():
    """Gaea's Liege: two clauses on one line, the second counting the
    *defending* player's lands. Gated by a `startswith` on the card's name."""
    line = normalize_creature_line(
        "As long as Probe Liege isn't attacking, its power and toughness are each "
        "equal to the number of Islands you control. As long as Probe Liege is "
        "attacking, its power and toughness are each equal to the number of "
        "Islands defending player controls."
    )
    found = dynamic_pt_for(line)
    assert found is not None
    assert found.payload == {
        "count": "land", "land_type": "island", "scope": "defender_when_attacking",
    }


@pytest.mark.cr("604.3")
def test_604_3_the_attacking_split_counts_the_right_players_lands():
    from engine.card_loader import load_catalog

    catalog = {c.name: c for c in load_catalog()}
    liege = Permanent(card=_cda_card(
        "Probe Liege",
        "As long as Probe Liege isn't attacking, its power and toughness are each "
        "equal to the number of Islands you control. As long as Probe Liege is "
        "attacking, its power and toughness are each equal to the number of "
        "Islands defending player controls.",
    ))
    p1 = PlayerState(name="P1", battlefield=[liege] + [Permanent(card=catalog["Island"])])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Island"]) for _ in range(3)])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game._refresh_dynamic_creatures()
    assert liege.effective_power == 1          # its controller's one Island

    liege.attacking = True
    liege.defending_player_index = 1
    game._refresh_dynamic_creatures()
    assert liege.effective_power == 3          # the defender's three Islands
