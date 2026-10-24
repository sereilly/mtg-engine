"""The AI uses a land's non-mana ability when a rehearsal says it is worth it
(``ai_abilities._abilities_weighed`` / ``_land_ability_worth``).

``choose_activation_action`` passed over every land, so Krosan Verge's
search, a manland's animation and the other 70 non-mana land abilities in the
pool (71 on 70 lands, measured at JUD's wave 2) were never activated by an AI
seat. A land's mana abilities stay the payment planner's; each other ability
is weighed by its own index and proposed only where carrying it out on a copy
of the game leaves the seat ahead once the turn is over — a mana not made is a
price the chooser's heuristic score does not see.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import _abilities_weighed, choose_activation_action
from engine.ai_policy import holds_an_ability_it_could_activate
from engine.ai_simulator import SimulationReport, _play_activations, run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.models import Permanent

ME, OPP = 0, 1


def _card(set_pool, name):
    for code in ("JUD", "LEA", "ICE", "ARN", "USG"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)


def _board(set_pool, lands, *, library=("Forest", "Plains", "Island") * 4, hand=()):
    """Seat 0's precombat main phase with *lands* (names) on its battlefield,
    mana costs enforced, an empty board across the table."""
    game = Game(players=[
        PlayerState("A", library=[_card(set_pool, n) for n in library],
                    hand=[_card(set_pool, n) for n in hand]),
        PlayerState("B", library=[_card(set_pool, "Island")] * 12),
    ], enforce_mana_costs=True)
    placed = []
    for name in lands:
        permanent = Permanent(card=_card(set_pool, name))
        game._put_permanent_onto_battlefield(ME, permanent, None)
        permanent.tapped = False
        placed.append(permanent)
    game.start_turn(ME)
    return game, placed


def test_krosan_verge_searches_for_its_two_lands(set_pool):
    """"{2}, {T}, Sacrifice this land: Search your library for a Forest card
    and a Plains card, put them onto the battlefield tapped." Two lands for
    one: the rehearsal reads it as the seat ahead, so the ability — the
    land's second, after its mana ability — is proposed by its index, paid for
    with the two other lands and never with the Verge's own mana, and carried
    out by the simulator's executor."""
    game, (_island, _swamp, verge) = _board(set_pool, ["Island", "Swamp", "Krosan Verge"])
    action = choose_activation_action(game, ME)
    assert action is not None and action.permanent_name == "Krosan Verge"
    assert action.ability_index == 1
    assert game.permanent_at(ME, action.permanent_index) is verge
    assert sorted(
        game.permanent_at(ME, slot).card.name for slot in action.land_tap_indices
    ) == ["Island", "Swamp"]

    report = SimulationReport(games_requested=1, games_completed=0, interaction_count=0)
    _play_activations(game, ME, report, 1, 1)
    assert not report.refused_activations, report.refused_activations
    names = sorted(p.card.name for p in game.controlled_by(ME))
    assert names == ["Forest", "Island", "Plains", "Swamp"]
    assert [card.name for card in game.players[ME].graveyard] == ["Krosan Verge"]


def test_bazaar_of_baghdad_is_not_tapped_to_lose_a_card(set_pool):
    """"{T}: Draw two cards, then discard three cards." A card down: the
    rehearsal reads the seat behind, so the land is left alone."""
    game, _ = _board(
        set_pool, ["Bazaar of Baghdad"], hand=("Grizzly Bears", "Giant Growth", "Lightning Bolt"),
    )
    assert choose_activation_action(game, ME) is None
    assert len(game.players[ME].hand) == 3


def test_a_painland_is_a_mana_ability_and_is_not_weighed(set_pool):
    """"{T}: Add {W} or {U}. This land deals 1 damage to you." A mana ability
    with a drawback (CR 605.1a — it could add mana, it does not target), so
    it is the payment planner's and never the activation chooser's — asked of
    the engine's own predicate, which reads the two-step effect whole."""
    game, (wastes,) = _board(set_pool, ["Adarkar Wastes"])
    assert _abilities_weighed(game, wastes) == []
    assert choose_activation_action(game, ME) is None
    assert not holds_an_ability_it_could_activate(game, ME)


def test_a_land_ability_is_something_to_activate_at_instant_speed(set_pool):
    """The instant-speed chooser's cheap question asks the same list: a land
    whose only non-mana ability is its second ("{2}{R}, {T}: Shivan Gorge
    deals 1 damage to each opponent") is something to look at."""
    game, _ = _board(set_pool, ["Shivan Gorge", "Mountain", "Mountain", "Mountain"])
    assert holds_an_ability_it_could_activate(game, ME)


@pytest.mark.slow
def test_a_seeded_run_activates_krosan_verge():
    """Krosan Verge pinned into both decks of a seeded Judgment run: a seat
    searches with it at least once (a floor of one — the path was reached),
    and nothing it proposed was refused."""
    report = run_ai_simulation(
        manifest_set_path("JUD", include_measured=True), games=2, seed=SEED,
        max_turns=12, required_cards=["Krosan Verge"],
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert not any("Krosan Verge" in reason for reason in report.refused_activations)
    assert any(
        "activate Krosan Verge -> resolved" in line for line in report.log_lines
    ), "no seat activated Krosan Verge; pick another seed"


SEED = 11
