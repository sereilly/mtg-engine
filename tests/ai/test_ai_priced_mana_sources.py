"""An AI seat pays through a mana ability that itself costs mana.

"{1}, {T}: Add {U}{B}." (Darkwater Catacombs and the other four Odyssey filter
lands) is a land with no ``{T}: Add …`` of its own. The tap-for-mana seam runs
only an ability whose whole cost is {T}, the AI's planner asked the seam, and
so a filter land in an AI seat's hands was a land that made nothing: ten were
played in a ten-game seeded Odyssey run and none was ever activated (W1G2).

This is the cheap half of ROADMAP's "costed and sacrifice mana sources". A
price paid in **mana** moves nothing on the battlefield — the reason the
sacrifice sources are still out — but it needs an *input*, a unit from another
source in the pool before the source is activated, and that is an ordering
problem: `ai_policy._plan_through_a_priced_source` puts the tap that pays the
price immediately in front of the source.

Deliberately narrow (`ai_policy._priced_mana_source`): generic mana and {T},
nothing else, on a permanent with no other mana ability. The census below
counts what that admits and what it leaves, over both manifest roles.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, ai_policy, ai_simulator
from engine.ai_policy import (CastAction, _plan_land_taps, _priced_mana_source,
                              cast_announcement, choose_cast_action,
                              spell_being_cast, tap_planned_lands,
                              zone_being_cast_from)
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.faces import compilation_units
from engine.mana_payment import is_mana_ability
from engine.mixins.turn_management import is_tap_alone_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

ME = 0

POOL = load_cards(manifest_set_paths(include_measured=True))
BY_NAME: dict = {}
for _card in POOL:
    BY_NAME.setdefault(_card.name, _card)

FILTER_LANDS = (
    "Darkwater Catacombs", "Mossfire Valley", "Shadowblood Ridge",
    "Skycloud Expanse", "Sungrass Prairie",
)


def _duel(mine, hand=(), floating=None):
    me = PlayerState(
        name="AI", library=[BY_NAME["Forest"]] * 10,
        hand=[BY_NAME[name] for name in hand],
        battlefield=[_nosick(Permanent(card=BY_NAME[name])) for name in mine],
    )
    game = Game(players=[me, PlayerState(name="Opp", library=[BY_NAME["Forest"]] * 10)])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    me.mana_pool.update(floating or {})
    return game


def _cast(game, action):
    spell = spell_being_cast(zone_being_cast_from(game, ME, action), action)
    tap_planned_lands(game, ME, action)
    result = game.cast_from_hand(ME, spell.name, **cast_announcement(action))
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


def _floating(game) -> dict:
    return {s: n for s, n in game.players[ME].mana_pool.items() if n}


# --- the decisions ---------------------------------------------------------------

def test_a_filter_land_pays_for_a_spell_its_controller_could_not_otherwise_cast():
    """An Island and Darkwater Catacombs make {U}{B}: the Island's {U} pays the
    Catacombs' {1}. Drudge Skeletons ({1}{B}) is cast, with the Island tapped
    first and nothing left floating. The Catacombs alone pays for nothing."""
    game = _duel(["Island", "Darkwater Catacombs"], hand=["Drudge Skeletons"])

    action = choose_cast_action(game, ME)

    assert action is not None and action.card_name == "Drudge Skeletons"
    assert action.land_tap_indices == (0, 1), "the price, then the source"
    assert _cast(game, action).supported
    assert _floating(game) == {}
    assert "Darkwater Catacombs produced {B}{U}" in game.log
    assert choose_cast_action(
        _duel(["Darkwater Catacombs"], hand=["Drudge Skeletons"]), ME
    ) is None


def test_the_tap_that_pays_the_price_sits_directly_in_front_of_the_source():
    """Three Islands and the Catacombs for Phantom Monster ({3}{U}). The order
    is the plan: with the price tapped immediately before the source, the pool
    holds exactly that price when the source is activated, so the engine has
    no choice of which unit pays it."""
    game = _duel(["Island", "Island", "Island", "Darkwater Catacombs"],
                 hand=["Phantom Monster"])

    action = choose_cast_action(game, ME)

    taps = action.land_tap_indices
    assert sorted(taps) == [0, 1, 2, 3]
    assert taps.index(3) == 1, taps
    assert _cast(game, action).supported
    assert _floating(game) == {}


def test_a_board_the_free_sources_pay_for_is_planned_as_it_always_was():
    """The filter land is asked last. With an Island and a Swamp beside it,
    {1}{B} is two basics and the Catacombs stays untapped."""
    game = _duel(["Island", "Swamp", "Darkwater Catacombs"], hand=["Drudge Skeletons"])

    action = choose_cast_action(game, ME)

    assert action.land_tap_indices == (1, 0)
    assert _cast(game, action).supported
    assert not game.permanent_at(ME, 2).tapped


def test_no_plan_goes_through_a_priced_source_while_mana_is_floating():
    """Which floating unit a generic price would take is not the planner's to
    say, so with mana already in the pool the fallback is not taken — the seat
    plans with what it would without the land, as before."""
    game = _duel(["Island", "Darkwater Catacombs"], floating={"G": 1})

    assert _plan_land_taps(game, game.players[ME], {"B": 1, "generic": 1}) is None
    game.players[ME].mana_pool["G"] = 0
    assert _plan_land_taps(game, game.players[ME], {"B": 1, "generic": 1}) == (
        (0, 1), ("U", "B"),
    )


@pytest.mark.parametrize("name, why", [
    ("Fire Sprites", "a coloured price: {G}, {T}: Add {R}."),
    ("Bog Initiate", "no {T}: {1}: Add {B}. may be activated any number of times"),
    ("An-Havva Township", "it also taps for {C} on its own"),
    ("Black Lotus", "its price is itself"),
    ("Island", "it is a land the seam taps"),
])
def test_what_the_narrow_reading_leaves_out(name, why):
    game = _duel([name])
    assert _priced_mana_source(game, ME, game.permanent_at(ME, 0)) is None, why


def test_a_tapped_or_summoning_sick_source_is_not_counted():
    game = _duel(["Forest", "Helionaut"])
    helionaut = game.permanent_at(ME, 1)
    assert _priced_mana_source(game, ME, helionaut) is not None
    helionaut.tapped = True
    assert _priced_mana_source(game, ME, helionaut) is None
    helionaut.tapped = False
    helionaut.metadata["summoning_sickness_turn"] = game.turn
    assert _priced_mana_source(game, ME, helionaut) is None


# --- the census ------------------------------------------------------------------

def census() -> list[dict]:
    """Every mana ability in both manifest roles that the tap seam does not
    run, with whether the planner now counts its permanent — and, where it
    does, whether the plan it makes through that source is one the engine
    carries out."""
    rows = []
    for card in compilation_units(POOL):
        if card.primary_type in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        abilities = usable_activated_abilities(program)
        priced = [
            ability for ability in abilities
            if is_mana_ability(ability) and not is_tap_alone_mana_ability(ability)
        ]
        if not priced:
            continue
        game = _duel(["Forest", "Forest", "Forest", card.name])
        source = _priced_mana_source(game, ME, game.permanent_at(ME, 3))
        row = {
            "card": card.name, "land": card.primary_type == "land",
            "admitted": source is not None, "finding": None,
        }
        rows.append(row)
        if source is None:
            continue
        for asked, made in source.outputs():
            if set(made) == {"G"}:
                continue  # the three Forests pay that on their own
            trial = _duel(["Forest", "Forest", "Forest", card.name])
            plan = _plan_land_taps(trial, trial.players[ME], dict(made))
            if plan is None:
                row["finding"] = f"no plan for its own output {made}"
                break
            action = CastAction(
                card_name="probe", target_player_index=ME, x_value=None,
                land_tap_indices=plan[0], score=0.0, hand_index=0,
                land_tap_colors=plan[1],
            )
            tap_planned_lands(trial, ME, action)
            pool = trial.players[ME].mana_pool
            if any(pool.get(symbol, 0) < count for symbol, count in made.items()):
                row["finding"] = f"planned {made}, the pool holds {_floating(trial)}"
                break
            if len(plan[0]) != source.price + 1:
                row["finding"] = f"tapped {len(plan[0])} for a price of {source.price}"
                break
    return rows


@pytest.fixture(scope="module")
def rows() -> list:
    return census()


def test_the_census_examined_the_pool(rows):
    """The floor: over a hundred mana abilities carry a cost beyond {T}."""
    assert len(rows) >= 100
    assert sum(1 for row in rows if row["land"]) >= 40


def test_the_filter_lands_are_counted_and_every_admitted_source_pays_what_it_planned(rows):
    admitted = {row["card"] for row in rows if row["admitted"]}
    assert set(FILTER_LANDS) <= admitted
    assert {"Mana Cylix", "Helionaut", "Celestial Prism"} <= admitted
    assert [f"{row['card']}: {row['finding']}" for row in rows if row["finding"]] == []


def test_only_a_source_with_no_other_mana_ability_is_admitted(rows):
    """The lands of this kind are the five filter lands and nothing else: a
    land that also taps for mana on its own is the free planner's."""
    lands = sorted(row["card"] for row in rows if row["admitted"] and row["land"])
    for name in lands:
        abilities = usable_activated_abilities(compile_card_oracle(BY_NAME[name]))
        assert not any(is_tap_alone_mana_ability(ability) for ability in abilities), name
    assert set(FILTER_LANDS) <= set(lands)


def test_without_the_fallback_none_of_them_is_planned(rows, monkeypatch):
    """Backwards: take the priced arm away and every admitted source is a
    permanent no plan reaches, which is the tree before the change."""
    monkeypatch.setattr(
        ai_policy, "_plan_through_a_priced_source", lambda *args, **kwargs: None,
    )
    for row in rows:
        if not row["admitted"]:
            continue
        game = _duel(["Forest", "Forest", "Forest", row["card"]])
        source = _priced_mana_source(game, ME, game.permanent_at(ME, 3))
        _asked, made = source.outputs()[0]
        wanted = {
            symbol: count for symbol, count in made.items() if symbol != "G"
        } or {"generic": 4}
        assert _plan_land_taps(game, game.players[ME], wanted) is None, row["card"]


# --- a seeded game ---------------------------------------------------------------

@pytest.mark.slow
def test_a_simulated_odyssey_game_activates_a_filter_land():
    """With the five pinned, a seeded run activates one — a floor of one —
    and no cast is refused for the mana it was counted for."""
    report = ai_simulator.run_ai_simulation(
        manifest_set_path("ODY", include_measured=True), games=3, seed=2024,
        max_turns=14, required_cards=list(FILTER_LANDS),
    )

    activated = [
        line for line in report.log_lines
        if any(f"{name} produced" in line for name in FILTER_LANDS)
    ]
    assert len(activated) >= 1
    assert [why for why in report.refused_casts if "insufficient mana" in why] == []
    assert not any(
        name in what for what in report.steps_left_owing for name in FILTER_LANDS
    )
