"""Whether an AI seat entwines (CR 702.42a), through the policy and the real
executor (``ai_entwine.entwined_cast``).

Entwine is weighed as a cast of its own once every mode is built: every mode
named, the entwine offer paid on top of the mana cost, the combined cast
rehearsed. These boards are the decision's edges — the mana for it and not,
a mode worth casting only behind its sibling (Promise of Power's Demon), and
a sacrifice-of-lands price the seat keeps its land reserve against.
"""

from __future__ import annotations

from engine import ai_simulator
from engine.ai_entwine import ENTWINE_LANDS_KEPT
from engine.ai_policy import choose_cast_action
from engine.game import Game
from engine.models import Permanent, PlayerState


def _card(set_pool, name):
    mrd = set_pool("MRD")
    return mrd[name] if name in mrd else set_pool("LEA")[name]


def _board(set_pool, hand, own=(), opposing=()):
    card = lambda name: _card(set_pool, name)  # noqa: E731
    game = Game(players=[
        PlayerState(name="P1", hand=[card(n) for n in hand], library=[card("Forest")] * 20),
        PlayerState(name="P2", library=[card("Forest")] * 20),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for seat, names in ((0, own), (1, opposing)):
        for name in names:
            permanent = Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _entwined(action) -> bool:
    return (
        action is not None
        and action.mode_choices is not None
        and len(action.mode_choices) == 2
        and bool(action.optional_cost_payments)
    )


def test_it_entwines_with_the_mana_for_it_and_casts_one_mode_without(set_pool):
    rich = _board(set_pool, ["One Dozen Eyes"], own=["Forest"] * 9)
    action = choose_cast_action(rich, 0)
    assert _entwined(action), action
    assert action.optional_cost_payments == {"{G}{G}{G}": 1}
    assert len(action.land_tap_indices) == 9

    poor = _board(set_pool, ["One Dozen Eyes"], own=["Forest"] * 6)
    action = choose_cast_action(poor, 0)
    assert action is not None and not _entwined(action), action
    assert action.mode_index in (0, 1)


def test_the_simulator_casts_the_entwined_spell_and_both_modes_resolve(set_pool):
    game = _board(set_pool, ["One Dozen Eyes"], own=["Forest"] * 9)
    report = ai_simulator.SimulationReport(
        games_requested=1, games_completed=0, interaction_count=0,
    )
    assert ai_simulator._play_one_cast(game, 0, report, 1, 1) is True
    names = sorted(p.card.name for p in game.players[0].battlefield if p.card.name != "Forest")
    assert names == ["Beast Token"] + ["Insect Token"] * 5, (names, game.log)
    assert all(p.tapped for p in game.players[0].battlefield if p.card.name == "Forest")
    assert report.refused_casts == {} and report.issues == []


def test_a_mode_worth_casting_only_behind_its_sibling_is_entwined(set_pool):
    """Promise of Power's Demon is a 0/0 from an empty hand and a 5/5 after the
    draw (its 2004-12-01 ruling), so it is never built alone — and is still
    named in the entwined cast, which the rehearsal prices whole."""
    game = _board(set_pool, ["Promise of Power"], own=["Swamp"] * 9)
    action = choose_cast_action(game, 0)
    assert _entwined(action), action
    assert action.optional_cost_payments == {"{4}": 1}


def test_a_land_sacrifice_entwine_keeps_the_land_reserve(set_pool):
    """"Entwine—Sacrifice two lands.": taken only by a seat left with
    ``ENTWINE_LANDS_KEPT`` lands; below that, the single mode."""
    plenty = ENTWINE_LANDS_KEPT + 2 + 6
    rich = _board(
        set_pool, ["Solar Tide"], own=["Plains"] * plenty,
        opposing=["Grizzly Bears", "Hill Giant"],
    )
    action = choose_cast_action(rich, 0)
    assert _entwined(action), action
    assert action.optional_cost_payments == {"sacrifice two lands": 1}

    tight = _board(
        set_pool, ["Solar Tide"], own=["Plains"] * (ENTWINE_LANDS_KEPT + 1),
        opposing=["Grizzly Bears", "Hill Giant"],
    )
    action = choose_cast_action(tight, 0)
    assert action is not None and not _entwined(action), action
