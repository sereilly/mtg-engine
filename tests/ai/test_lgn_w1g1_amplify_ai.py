"""The AI and amplify (CR 702.38): what it reveals, and the abilities sized by
the counters amplify put there.

* A seat nobody asks reveals every card that shares a creature type — the
  stated default (``EntryChoicesMixin._default_entry_reveal``).
* An ability sized by its own source's counters is not proposed while the
  source carries none: Kilnmouth Dragon tapped to deal 0 damage instead of
  attacking as a 5/5 flier, and Canopy Crawler gave a creature +0/+0, in the
  first seeded Legions games run (``ai_valuation.sized_by_its_own_empty_counters``).
* Seeded AI-vs-AI games over Legions reveal for amplify (a floor of one).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_abilities import choose_activation_action
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_cards, load_catalog, manifest_set_path
from engine.models import Permanent

_CATALOG = {card.name: card for card in load_catalog()}
_LGN = {card.name: card for card in load_cards(manifest_set_path("LGN", include_measured=True))}


def _game(mine, theirs=()):
    p1 = PlayerState(name="A", battlefield=list(mine), library=[_CATALOG["Island"]] * 5)
    p2 = PlayerState(name="B", battlefield=list(theirs), library=[_CATALOG["Island"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game._recompute_continuous_effects()
    return game


def _ready(card):
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


@pytest.mark.parametrize("name", ["Kilnmouth Dragon", "Canopy Crawler"])
def test_an_ability_sized_by_no_counters_is_not_proposed(name):
    permanent = _ready(_LGN[name])
    game = _game([permanent], [_ready(_CATALOG["Grizzly Bears"])])
    assert choose_activation_action(game, 0) is None


def test_the_same_ability_with_counters_on_its_source_is():
    dragon = _ready(_LGN["Kilnmouth Dragon"])
    game = _game([dragon])
    game.place_plus1_counters(dragon, 3)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Kilnmouth Dragon"


def test_seeded_legions_games_reveal_for_amplify():
    """A floor of one: across a few seeds some AI seat enters an amplifier with
    a card sharing its creature type in hand and reveals it, the counters
    arrive, and no step is left owing an amplify prompt. Several seeds rather
    than one, because the games change whenever another Legions card becomes
    castable; the first seed that reveals ends the search."""
    revealed: list[str] = []
    for seed in (7, 2, 4, 9, 10, 11):
        report = run_ai_simulation(
            manifest_set_path("LGN", include_measured=True), games=2, seed=seed,
            max_turns=12,
            required_cards=["Glowering Rogon", "Canopy Crawler", "Feral Throwback",
                            "Kilnmouth Dragon", "Embalmed Brawler", "Zombie Brute",
                            "Ghastly Remains"],
        )
        assert not any("entry_reveal" in key for key in report.steps_left_owing), seed
        assert not report.rehearsals_raised, seed
        lines = [str(line) for line in report.log_lines]
        revealed = [line for line in lines if "+1/+1 counter(s) (amplify" in line]
        if revealed:
            break
    assert revealed, "no amplify reveal in any seeded game"
