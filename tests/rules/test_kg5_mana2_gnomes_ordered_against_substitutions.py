"""Quarum Trench Gnomes' record is ordered against the other substitutions.

    106.12b A replacement effect that applies if a permanent "is tapped for
    mana" … modifies the mana production event while such an ability is
    resolving and producing mana …
    616.1e Any of the applicable replacement and/or prevention effects may be
    chosen.
    616.1f Once the chosen effect has been applied, this process is repeated …

"{T}: If target Plains is tapped for mana, it produces colorless mana instead
of white mana. (This effect lasts indefinitely.)" The "instead" makes it a
replacement effect (CR 614.1a) over the Plains' production, like Hall of
Gemstone's "lands tapped for mana produce mana of the chosen color instead of
any other color" — so on one tap the two are ordered by the land's controller.
Hall first, the white becomes the chosen {R} and the Gnomes have no white left
to replace ("The ability only replaces white mana produced by the Plains",
its ruling, 2008-08-01); the Gnomes first, the {C} is no colour for Hall to
change (Hall's ruling, 2016-08-23: "Any colorless mana that's produced isn't
affected"). Either {R} or {C}. Beside Pulse of Llanowar ("…mana of a color of
your choice instead of any other type") the Gnomes first then Pulse is any
colour, and Pulse's white then the Gnomes is {C}.

The record was applied inside ``Permanent.effective_produced_mana``, ahead of
every substitution: backwards on ``e245e624c`` the Gnomed Plains beside Hall's
{R} offered and made {C} alone (a Lightning Bolt stayed in hand), beside Pulse
{C} was never offered and a tap asking for it made {W}, and a Plains whose
white came from a granted mana ability (Overlaid Terrain) made {W}{W}.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.land_mana_swaps import payment_colors
from engine.mana_could_produce import lands_could_produce
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(names, *, hand=(), interactive=True, hall_colour=None):
    """Seat 0's turn: *names* on its battlefield, Hall of Gemstone's upkeep
    choice answered *hall_colour* by the seat itself (an interactive seat),
    then the Gnomes activated at the Plains — every step through the engine's
    own entry points."""
    game = Game(players=[
        PlayerState("A", hand=[_CARDS[name] for name in hand], library=[_CARDS["Plains"]] * 10),
        PlayerState("B", library=[_CARDS["Plains"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = {}
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.setdefault(name, permanent)
    game.interactive_seats = {0}
    game.start_turn(0)
    settle(game, answers={
        "color_choice": lambda g, c: g.confirm_color_choice(c.player_index, hall_colour),
    })
    land = placed.get("Plains") or placed.get("Tundra")
    activated = game.activate_permanent_ability(
        0, "Quarum Trench Gnomes", target_permanent_ids=[land.permanent_id],
    )
    assert activated.supported, activated.details
    settle(game)
    assert land.metadata.get("produced_mana_swaps"), game.log[-4:]
    for permanent in game.all_permanents():
        permanent.tapped = False
    for symbol in game.players[0].mana_pool:
        game.players[0].mana_pool[symbol] = 0
    game.interactive_seats = {0} if interactive else set()
    return game, land


def _tap(game, land, asked):
    for symbol in game.players[0].mana_pool:
        game.players[0].mana_pool[symbol] = 0
    land.tapped = False
    before = len(game.log)
    assert game.tap_land_for_mana(0, land.card.name, chosen_color=asked, permanent_id=land.permanent_id)
    made = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    return made, game.log[before:]


@pytest.mark.cr("616.1e", "616.1f", "106.12b")
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("asked,made", [("R", {"R": 1}), ("C", {"C": 1})])
def test_a_gnomed_plains_beside_hall_of_gemstone_makes_either(interactive, asked, made):
    """Both orders, for a tapper nobody asks and for a person — who is asked
    nothing mid-payment: the symbol the tap names is the choice (CR 601.2g)."""
    game, plains = _table(
        ["Plains", "Quarum Trench Gnomes", "Hall of Gemstone"],
        hall_colour="R", interactive=interactive,
    )
    assert set(payment_colors(game, plains)) == {"C", "R"}
    assert lands_could_produce(game)[plains.permanent_id] == {"C", "R"}, "CR 106.7: any possible order"
    pool, log = _tap(game, plains, asked)
    assert pool == made, log
    assert f"Plains produced {{{asked}}} instead" in log
    assert not [c for c in game.pending_choices if getattr(c, "kind", None) == "effect_order"]


@pytest.mark.cr("616.1e", "106.12b")
def test_hall_having_chosen_white_still_leaves_only_colourless():
    """Hall's white is the Plains' own white, which the Gnomes then replace —
    and the Gnomes' {C} is no colour Hall changes: {C} in either order."""
    game, plains = _table(
        ["Plains", "Quarum Trench Gnomes", "Hall of Gemstone"], hall_colour="W",
    )
    assert payment_colors(game, plains) == ("C",)
    for asked in ("W", "C"):
        pool, _log = _tap(game, plains, asked)
        assert pool == {"C": 1}


@pytest.mark.cr("616.1e", "601.2g")
def test_the_ai_pays_a_lightning_bolt_with_the_gnomed_plains_under_hall():
    """The real chooser and the real executor: the plan counts the Plains as
    {R}, asks the tap for it, and the order follows. On the base the plan read
    the Plains as {C} alone and the Bolt was never castable."""
    game, plains = _table(
        ["Plains", "Quarum Trench Gnomes", "Hall of Gemstone"],
        hand=["Lightning Bolt"], hall_colour="R", interactive=False,
    )
    game.enforce_mana_costs = True
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Lightning Bolt"
    action = tap_planned_lands(game, 0, action)
    assert game.players[0].mana_pool["R"] == 1, game.log[-4:]
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_graveyard_indices=action.target_graveyard_indices,
        target_permanent_ids=action.target_permanent_ids,
    )
    assert result.supported, result.details
    assert plains.tapped


@pytest.mark.cr("616.1e", "616.1f", "106.12b")
@pytest.mark.parametrize("asked", ["C", "W", "G"])
def test_a_gnomed_plains_under_pulse_of_llanowar_makes_any_of_six(asked):
    """The Gnomes first, then Pulse's colour of choice: any of the five. Pulse
    first naming white, then the Gnomes: {C}. Asked for {C} it made {W} on the
    base — Pulse named the land's own colour, the Gnomes had already run."""
    game, plains = _table(["Plains", "Quarum Trench Gnomes", "Pulse of Llanowar"])
    assert set(payment_colors(game, plains)) == {"W", "U", "B", "R", "G", "C"}
    pool, log = _tap(game, plains, asked)
    assert pool == {asked: 1}, log


@pytest.mark.cr("106.12b", "614.1a")
@pytest.mark.parametrize("asked,made", [("W", {"C": 2}), ("C", {"C": 2}), ("U", {"U": 2})])
def test_the_record_replaces_white_from_a_granted_mana_ability(asked, made):
    """"Lands you control have "{T}: Add two mana of any one color."" (Overlaid
    Terrain.) The Plains' white from that ability is still white mana the
    Plains produced, and the Gnomes replace it; its blue they leave alone
    (the ruling). The granted ability compiles and wrote into the pool past
    the summary the record was read from, so {W}{W} came out."""
    game = Game(players=[
        PlayerState("A", library=[_CARDS["Plains"]] * 10),
        PlayerState("B", library=[_CARDS["Plains"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    terrain = Permanent(card=_CARDS["Overlaid Terrain"])
    game._put_permanent_onto_battlefield(0, terrain, None)
    settle(game)
    placed = {}
    for name in ("Plains", "Quarum Trench Gnomes"):
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed[name] = permanent
    plains = placed["Plains"]
    game.start_turn(0)
    settle(game)
    assert game.activate_permanent_ability(
        0, "Quarum Trench Gnomes", target_permanent_ids=[plains.permanent_id],
    ).supported
    settle(game)
    assert set(payment_colors(game, plains)) == {"C", "U", "B", "R", "G"}
    pool, log = _tap(game, plains, asked)
    assert pool == made, log
