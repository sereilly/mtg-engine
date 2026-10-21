"""An AI seat answers the madness offer (CR 702.35a) by weighing the cast.

The offer is ``engine/madness.py``'s ``madness_cast`` prompt, which a seat
nobody asks answers as it is armed — inside the trigger's resolution, where no
copy of the table can be taken as it stands — with
``ai_policy.choose_madness_cast``: the candidate builder every cast out of a
zone a permission opens goes through, rehearsed on a copy that owes nothing.
So the seat casts a madness spell that helps it and declines one that does not,
where a fixed default would have done one or the other every time.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.models import Permanent
from tests.helpers import _nosick


def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


_CARDS = _pool()


def _haze_board(own: tuple[str, ...], theirs: tuple[str, ...]) -> Game:
    game = Game(players=[
        PlayerState(
            name="AI",
            battlefield=[_nosick(Permanent(card=_CARDS["Aquamoeba"]))]
            + [Permanent(card=_CARDS["Swamp"]) for _ in range(2)]
            + [_nosick(Permanent(card=_CARDS[name])) for name in own],
            hand=[_CARDS["Psychotic Haze"]],
        ),
        PlayerState(
            name="Other",
            battlefield=[_nosick(Permanent(card=_CARDS[name])) for name in theirs],
        ),
    ])
    game.enforce_mana_costs = True
    return game


def test_the_ai_casts_a_madness_sweep_that_kills_only_the_other_side():
    """Psychotic Haze for {1}{B}: 1 damage to each creature and each player.
    Over two of the opponent's Llanowar Elves and none of its own x/1s, it is
    cast."""
    game = _haze_board(own=(), theirs=("Llanowar Elves", "Llanowar Elves"))
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert any("cast Psychotic Haze for its madness cost" in line for line in game.log)
    assert [c.name for c in game.players[1].graveyard] == ["Llanowar Elves"] * 2


def test_the_ai_declines_a_madness_sweep_that_kills_only_its_own_creatures():
    """The same spell over the seat's own two Elves and nothing of the
    opponent's is declined — the card goes to the graveyard and the Elves
    live. A default that always cast would have killed them."""
    game = _haze_board(own=("Llanowar Elves", "Llanowar Elves"), theirs=())
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert any(
        "did not cast Psychotic Haze for its madness cost" in line for line in game.log
    )
    assert [c.name for c in game.players[0].graveyard] == ["Psychotic Haze"]
    assert sum(
        1 for p in game.players[0].battlefield if p.card.name == "Llanowar Elves"
    ) == 2


@pytest.mark.slow
def test_a_seeded_torment_game_casts_a_card_for_its_madness_cost():
    """A whole game reaches the offer and takes it: the madness cards and an
    outlet pinned into every deck, the run completes, and the log holds at
    least one madness cast — a floor, never a count. Nothing is asserted about
    the run's refusals or what it left owing: those are statements about
    every other Torment card, and the set is still being built."""
    report = run_ai_simulation(
        manifest_set_path("TOR", include_measured=True), games=4, seed=1337,
        required_cards=[
            "Aquamoeba", "Fiery Temper", "Obsessive Search", "Arrogant Wurm",
            "Basking Rootwalla", "Psychotic Haze", "Compulsion",
        ],
    )
    assert report.games_completed == 4
    assert not any(
        "madness" in str(entry).lower() for entry in report.rehearsals_raised
    )
    assert any("for its madness cost" in line and " cast " in line
               for line in report.log_lines)


def _compulsion_board(hand: tuple[str, ...], islands: int) -> Game:
    game = Game(players=[
        PlayerState(
            name="AI",
            battlefield=[Permanent(card=_CARDS["Compulsion"])]
            + [Permanent(card=_CARDS["Island"]) for _ in range(islands)],
            hand=[_CARDS[name] for name in hand],
            library=[_CARDS["Forest"]] * 5,
        ),
        PlayerState(name="Other"),
    ])
    game.enforce_mana_costs = True
    return game


def test_the_ai_discards_a_madness_card_to_its_own_outlet_and_only_one_it_can_cast():
    """A discard cost is a trade the activation chooser does not price, so it
    activated no "{1}{U}, Discard a card: Draw a card" at all. A card with
    madness is the exception: discarding it offers it for its madness cost,
    so with Obsessive Search ({U}) in hand and {1}{U}{U} to spend, Compulsion
    is activated **naming the Search** rather than the Island before it — and
    with only {1}{U} (the Search's cast unpayable beside the ability) it is
    not, any more than with no madness card at all."""
    from engine.ai_policy import choose_activation_action

    game = _compulsion_board(("Island", "Obsessive Search"), islands=3)
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Compulsion"
    assert action.cost_hand_index == 1
    assert choose_activation_action(
        _compulsion_board(("Island", "Obsessive Search"), islands=2), 0,
    ) is None
    assert choose_activation_action(
        _compulsion_board(("Island", "Island"), islands=3), 0,
    ) is None
