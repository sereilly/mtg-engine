"""What a seat nobody asks does with a creature type it may *set* (ONS W1G5).

* ``ai_prompt_readers.resolution_creature_type_preference`` — a type set on the
  ability's own source or its Aura's host (the Mistforms, Mistform Mask) is
  side ``"join"``: the controller's commonest type among its *other*
  creatures; the replacement word of a creature-type text change (Artificial
  Evolution) is the controller's own commonest; a targeted or board-wide set
  (Trickery Charm, Unnatural Selection, Imagecrafter, Mistform Mutant,
  Standardize) keeps the hoser default.
* ``ai_abilities.choose_activation_action`` — a Mistform's type change is
  proposed only where a rehearsal says it leaves the seat ahead (the gate a
  land's ability takes). It scored a flat 2.5 like every other activation and
  was bought every main phase, naming no type when the seat had no other
  creature.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_prompt_readers import resolution_creature_type_preference
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.mark.parametrize(("name", "expected"), [
    ("Mistform Dreamer", ("join", "battlefield")),
    ("Mistform Skyreaver", ("join", "battlefield")),
    ("Mistform Stalker", ("join", "battlefield")),
    ("Mistform Wall", ("join", "battlefield")),
    ("Mistform Shrieker", ("join", "battlefield")),
    ("Mistform Mask", ("join", "battlefield")),
    ("Artificial Evolution", ("you", "battlefield")),
    ("Trickery Charm", None),
    ("Standardize", None),
    ("Imagecrafter", None),
    ("Mistform Mutant", None),
])
def test_whose_type_a_type_set_names(set_pool, name, expected):
    assert resolution_creature_type_preference(set_pool("ONS")[name]) == expected


def _w1g5_board(set_pool, catalog_by_name, mine, theirs=()):
    """Seat 0 in its precombat main phase with *mine* (ONS names first, then
    the catalog's) and three Islands, costs enforced; seat 1 with *theirs*."""
    ons = set_pool("ONS")

    def card(name):
        return ons[name] if name in ons else catalog_by_name[name]

    game = Game(players=[
        PlayerState(
            name="A",
            battlefield=[Permanent(card=card(n)) for n in (*mine, "Island", "Island", "Island")],
            library=[catalog_by_name["Island"]] * 8,
        ),
        PlayerState(
            name="B", battlefield=[Permanent(card=card(n)) for n in theirs],
            library=[catalog_by_name["Island"]] * 8,
        ),
    ])
    game.interactive_seats = set()
    game.start_turn(0)
    game._sync_control()
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def test_a_mistform_with_no_type_worth_joining_is_not_activated(set_pool, catalog_by_name):
    """Alone on its side, the Dreamer's default names nothing and the ability
    would change nothing: the seat keeps its mana."""
    game = _w1g5_board(set_pool, catalog_by_name, ["Mistform Dreamer"])
    assert choose_activation_action(game, 0) is None


def test_a_mistform_joins_a_lords_tribe_before_it_attacks(set_pool, catalog_by_name):
    """Beside Lord of Atlantis, with an empty board across the table, the
    Dreamer made a Merfolk attacks as a 3/2 rather than a 2/1 — what the
    rehearsal reads through the fight — so the activation is proposed, and
    carried out it makes the Dreamer a Merfolk."""
    game = _w1g5_board(
        set_pool, catalog_by_name, ["Mistform Dreamer", "Lord of Atlantis"],
    )
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Mistform Dreamer"
    dreamer = next(p for p in game.controlled_by(0) if p.card.name == "Mistform Dreamer")
    game.enforce_mana_costs = False
    assert game.activate_permanent_ability(
        0, action.permanent_name, permanent_index=action.permanent_index,
    ).supported
    resolve_stack(game)
    assert dreamer.has_type("merfolk") and not dreamer.has_type("illusion")
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)


@pytest.mark.full
def test_seeded_onslaught_games_use_the_type_changes():
    """Every W1G5 card pinned into every deck: the runs complete, nothing
    rehearsed raises, at least one Mistform changes its own type and one
    Artificial Evolution rewrites a text — floors, never counts — and no
    Mistform activation is one that changed nothing."""
    report = run_ai_simulation(
        manifest_set_path("ONS", include_measured=True), games=4, seed=5150,
        max_turns=14, required_cards=[
            "Mistform Dreamer", "Mistform Wall", "Mistform Mask",
            "Mistform Stalker", "Standardize", "Trickery Charm",
            "Artificial Evolution",
        ],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    lines = report.log_lines
    assert any(
        line.strip().startswith("Mistform") and "until end of turn (Mistform" in line
        for line in lines
    )
    assert any("Artificial Evolution changed" in line for line in lines)
    assert not any(
        line.strip().startswith("Mistform") and "so nothing changes" in line
        for line in lines
    )
