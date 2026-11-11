"""CR 616.1e for two substitutions on one land: the tapper picks which wins.

    616.1. If two or more replacement and/or prevention effects are attempting
    to modify the way an event affects an object or player, the affected
    object's controller … chooses one to apply …
    616.1e Any of the applicable replacement and/or prevention effects may be
    chosen.
    616.1f Once the chosen effect has been applied, this process is repeated
    (taking into account only replacement or prevention effects that would now
    be applicable) until there are no more left to apply.

"If a land is tapped for mana, it produces {B} instead of any other type"
(Infernal Darkness) and Deep Water's record ("…if you tap a land you control
for mana, it produces {U} instead of any other type") both apply to one tap of
a Forest (CR 106.12b). Applied one after the other, the one applied **last**
is what the Forest makes — so the order is a choice of {B} or {U}, and it is
the land's controller's. ``land_mana_swaps.swapped_production`` picked by
timestamp: the newer record always won, and a seat holding a {B} spell could
not pay it off that Forest. The same choice is Naked Singularity's ruling for a
land of two types: "the player tapping the land for mana can choose to produce
mana of either color. But if it produces more than one mana, all mana is of
the same color." (2013-04-15.)

A land is tapped part-way through paying a cost (CR 601.2g), where no prompt
can be answered and nothing resumes, so the choice is made **before the tap**:
the symbol the tapper asks the land for picks the order
(``land_mana_swaps.ordered_substitutions``), the registration stands for one
CR 616.1 candidate per substitution (``instances``), what every order could
make is what the planner and the wire offer (``payment_colors``), and the AI's
planner asks for the symbol its plan counted.

Backwards on the base (59f133e63): the Forest asked for {B} makes {U}, the
planner finds no way to pay {B}, and the Tundra makes {R} whatever is asked.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_payment import _plan_land_taps, tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.land_mana_swaps import payment_colors
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(lands, statics=(), *, deep_water=False, hand=(), interactive=False):
    """Seat 0's main phase: *lands* untapped, Deep Water's record armed when
    asked (by activating it), then the *statics* put onto the battlefield."""
    game = Game(players=[
        PlayerState("A", hand=[_CARDS[name] for name in hand], library=[_CARDS["Forest"]] * 10),
        PlayerState("B", library=[_CARDS["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False

    def put(name):
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        return permanent

    placed = [put(name) for name in lands]
    if deep_water:
        put("Deep Water")
    game.start_turn(0)
    settle(game)
    if deep_water:
        activated = game.activate_permanent_ability(0, "Deep Water")
        assert activated.supported, activated.details
        settle(game)
    for name in statics:
        put(name)
    for permanent in placed:
        permanent.tapped = False
    for symbol in game.players[0].mana_pool:
        game.players[0].mana_pool[symbol] = 0
    game.interactive_seats = {0} if interactive else set()
    return game, placed


def _tap(game, land, asked):
    before = len(game.log)
    assert game.tap_land_for_mana(0, land.card.name, chosen_color=asked, permanent_id=land.permanent_id)
    made = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    for bucket in (getattr(game.players[0], "restricted_mana", None) or {}).values():
        for symbol, n in bucket.items():
            if n:
                made[f"restricted {symbol}"] = n
    return made, game.log[before:]


@pytest.mark.cr("616.1e", "616.1f", "106.12b")
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("asked,made", [("B", {"B": 1}), ("U", {"U": 1})])
def test_infernal_darkness_beside_a_deep_water_record_makes_what_is_asked(interactive, asked, made):
    """Both directions, for a seat nobody asks and for a person — who is asked
    nothing mid-payment: the request is the choice, and no ``effect_order``
    prompt is armed."""
    game, (forest,) = _table(["Forest"], ["Infernal Darkness"], deep_water=True, interactive=interactive)
    assert set(payment_colors(game, forest)) == {"B", "U"}
    pool, log = _tap(game, forest, asked)
    assert pool == made, log
    assert f"Forest produced {{{asked}}} instead" in log
    assert not [c for c in game.pending_choices if getattr(c, "kind", None) == "effect_order"]


@pytest.mark.cr("616.1e")
def test_a_request_no_order_makes_takes_the_default_the_newest_record():
    """Asked for the {G} neither order makes — the tap seam's own default
    request — the record armed by a resolution still wins, as it always did."""
    game, (forest,) = _table(["Forest"], ["Infernal Darkness"], deep_water=True)
    assert payment_colors(game, forest)[0] == "U", "the default order's symbol is offered first"
    pool, _log = _tap(game, forest, "G")
    assert pool == {"U": 1}


@pytest.mark.cr("616.1f", "106.12b")
@pytest.mark.parametrize("static,asked,made", [
    # "…instead of any other type" leaves the amount alone (Infernal
    # Darkness's ruling, 2008-10-01): {C}{C} becomes two of the one chosen.
    ("Infernal Darkness", "B", {"B": 2}),
    ("Infernal Darkness", "U", {"U": 2}),
    # "…and amount" (Contamination) makes it one mana in either order.
    ("Contamination", "B", {"B": 1}),
    ("Contamination", "U", {"U": 1}),
])
def test_a_two_mana_land_under_two_substitutions(static, asked, made):
    game, (tomb,) = _table(["Ancient Tomb"], [static], deep_water=True)
    pool, log = _tap(game, tomb, asked)
    assert pool == made, log


@pytest.mark.cr("616.1f", "106.6")
@pytest.mark.parametrize("asked", ["B", "U"])
def test_a_restricted_production_keeps_its_bucket_whichever_wins(asked):
    """Mishra's Workshop's {C}{C}{C} "spend this mana only to cast artifact
    spells" stays restricted (CR 106.6a's reasoning), all of it the chosen
    symbol."""
    game, (workshop,) = _table(["Mishra's Workshop"], ["Infernal Darkness"], deep_water=True)
    pool, log = _tap(game, workshop, asked)
    assert pool == {f"restricted {asked}": 3}, log


@pytest.mark.cr("616.1e")
@pytest.mark.parametrize("asked,made", [("R", {"R": 1}), ("G", {"G": 1})])
def test_a_tundra_under_naked_singularity_makes_either_colour(asked, made):
    """A Plains and an Island at once: "Plains produce {R}, Islands produce
    {G}" are two effects on one tap, and the tapper chooses (the card's
    ruling, 2013-04-15). It made {R} — the first in printed order — whatever
    was asked."""
    game, (tundra,) = _table(["Tundra"], ["Naked Singularity"])
    assert set(payment_colors(game, tundra)) == {"R", "G"}
    pool, log = _tap(game, tundra, asked)
    assert pool == made, log


@pytest.mark.cr("616.1e", "601.2g")
@pytest.mark.parametrize("required,asked", [({"B": 1}, "B"), ({"U": 1}, "U")])
def test_the_ai_planner_asks_for_the_symbol_its_plan_counted(required, asked):
    game, (forest,) = _table(["Forest"], ["Infernal Darkness"], deep_water=True)
    game.enforce_mana_costs = True
    plan = _plan_land_taps(game, game.players[0], required)
    assert plan is not None, "the Forest pays either symbol"
    slots, colours = plan
    assert colours == (asked,)
    assert game.permanent_at(0, slots[0]) is forest


@pytest.mark.cr("616.1e", "601.2g")
@pytest.mark.parametrize("spell,symbol", [("Dark Ritual", "B"), ("Unsummon", "U")])
def test_the_ai_casts_a_spell_of_either_symbol_off_that_forest(spell, symbol):
    """The real chooser and the real executor: the plan's colour is asked of
    the tap, the order follows it, and the spell is paid and cast. Dark Ritual
    was dark on the base — the plan read the Forest as {U} alone."""
    game, (forest,) = _table(["Forest"], ["Infernal Darkness"], deep_water=True, hand=[spell])
    target = Permanent(card=_CARDS["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, target, None)
    game.enforce_mana_costs = True
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == spell
    action = tap_planned_lands(game, 0, action)
    assert game.players[0].mana_pool[symbol] == 1
    result = game.cast_from_hand(
        0, action.card_name,
        target_player_index=action.target_player_index,
        target_graveyard_indices=action.target_graveyard_indices,
        target_permanent_ids=action.target_permanent_ids,
    )
    assert result.supported, result.details
    assert forest.tapped
