"""Whose creature type a seat nobody asks names (ONS W1G4).

Two readers decide it, both off the compiled program and never off a name:

* ``ai_prompt_readers.resolution_creature_type_preference`` — for a type
  chosen while an effect resolves (CR 608.2d): a pump or an untap of the type
  is the chooser's own, a sweep that spares the types named is too, a
  graveyard return counts graveyards, a revealed-card test the chooser's
  library, and a board-wide steal behind "more … than each other player" the
  type the chooser leads in that the others hold most of. Everything else
  (destroy, tap, forced attack) keeps the hoser default.
* ``ai_prompt_readers.chosen_creature_type_side`` — for CR 614.1c's entry
  record: a keyword-only lord ("have fear", "have shroud") and a cost paid
  with a creature of the type are the controller's own. Both read the
  opponents' type at ingest: Cover of Darkness gave the opponents fear, Steely
  Resolve gave them shroud, and Doom Cannon named a type its controller could
  never sacrifice.
"""
from __future__ import annotations

import pytest

from engine.ai_prompt_readers import (chosen_creature_type_side,
                                      resolution_creature_type_preference)
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from tests.helpers import _mk_card


@pytest.mark.parametrize(("name", "expected"), [
    ("Defensive Maneuvers", ("you", "battlefield")),
    ("Tribal Unity", ("you", "battlefield")),
    ("Riptide Chronologist", ("you", "battlefield")),
    ("Harsh Mercy", ("you", "battlefield")),
    ("Patriarch's Bidding", ("you", "graveyard")),
    ("Bloodline Shaman", ("you", "library")),
    ("Peer Pressure", ("majority", "battlefield")),
    # A forced attack is a hoser: the reader says nothing and the sweep
    # default stands.
    ("Walking Desecration", None),
])
def test_what_the_rest_of_the_card_does_with_the_word_says_whose_it_is(
    set_pool, name, expected,
):
    assert resolution_creature_type_preference(set_pool("ONS")[name]) == expected


def test_a_shrinking_pump_of_the_chosen_type_keeps_the_hoser_default():
    """The sign of the pump is what is read: -1/-1 to the type (Outbreak's
    shape) is aimed at the opponents, so the reader stays silent."""
    shrink = _mk_card(
        "W1G4 Blight", "{B}", "Instant",
        "Creatures of the creature type of your choice get -1/-1 until end of turn.",
    )
    assert resolution_creature_type_preference(shrink) is None


@pytest.mark.parametrize("name", ["Cover of Darkness", "Steely Resolve", "Doom Cannon"])
def test_a_keyword_lord_and_a_sacrifice_cost_name_the_controllers_type(set_pool, name):
    assert chosen_creature_type_side(set_pool("ONS")[name]) == "you"


@pytest.mark.slow
def test_a_seeded_onslaught_game_asks_every_seat_for_a_creature_type():
    """Harsh Mercy and Patriarch's Bidding pinned into every deck: the runs
    complete, nothing rehearsed raises, and at least one "each player chooses"
    round reaches its last seat — a floor, never a count. Nothing is asserted
    about the rest of the set, which is still being built."""
    report = run_ai_simulation(
        manifest_set_path("ONS", include_measured=True), games=4, seed=4242,
        max_turns=14, required_cards=["Harsh Mercy", "Patriarch's Bidding"],
    )
    assert report.games_completed == 4
    assert not report.rehearsals_raised
    assert any(
        "creature types chosen this way" in line for line in report.log_lines
    )
