"""CR 106.7 for "that land could produce": the fixpoint, not the land's summary.

    106.7. Some abilities produce mana based on the type of mana another
    permanent or permanents "could produce." The type of mana a permanent could
    produce at any time includes any type of mana that an ability of that
    permanent would produce if the ability were to resolve at that time,
    taking into account any applicable replacement effects in any possible
    order. Ignore whether any costs of the ability could or could not be paid.
    If that permanent wouldn't produce any mana under these conditions, or no
    type of mana can be defined this way, there's no type of mana it could
    produce.

Three printed phrases name **one** land's "could produce": "Add one mana of
any type that land could produce" (Benthic Explorers, the land its cost
untapped), "…the sacrificed land could produce" (Squandered Resources) and
Mana Web's "…that could produce any type of mana that land could produce".
All three read the land's ``effective_produced_mana`` — Scryfall's summary —
while the board-wide phrases (Reflecting Pool, Fellwar Stone) read the
fixpoint. So an opponent's Reflecting Pool untapped by Benthic Explorers
offered all five colours, a lone one (which could produce nothing) made
whatever was asked, and a land already sacrificed answered the same way.

The fixpoint itself took no replacement effect into account: "When determining
what types of mana an opponent's land could produce, take into account any
applicable replacement effects that would apply to that land's mana abilities
(such as Contamination's effect, for example). If there is more than one,
consider them in any possible order." (Benthic Explorers and Fellwar Stone,
2009-10-01.) A Forest under Ritual of Subdual offered a Fellwar Stone {G}.

Now one reader (``mana_could_produce.types_that_land_could_produce``) answers
the handler, the wire's ``symbols_by_cost`` and Mana Web from the fixpoint,
which applies each land's substitutions in every order
(``land_mana_swaps.could_produce_under_substitutions``); a sacrificed land is
answered beside the board it left (CR 608.2h's last known information).

Backwards on the base (59f133e63): every board below but the plain Forest
fails — five colours on the wire, {B} or {W} or {U} made from a Pool that
could produce {G} or nothing, {G} from a Forest under Infernal Darkness, and
Mana Web leaving the Swamp untapped.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle
from web.offers import _decided_ability_mana

_CARDS = {card.name: card for card in load_catalog()}


def _table(mine=(), theirs=(), *, tapped_theirs=False):
    game = Game(players=[
        PlayerState("A", library=[_CARDS["Forest"]] * 10),
        PlayerState("B", library=[_CARDS["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed: dict[int, list[Permanent]] = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game.start_turn(0)
    settle(game)
    for permanent in placed[1]:
        permanent.tapped = tapped_theirs and permanent.has_type("land")
    return game, placed[0], placed[1]


def _floating(game, seat=0) -> dict:
    return {symbol: n for symbol, n in game.players[seat].mana_pool.items() if n}


def _wire_for_cost(game, source, land) -> "list | None":
    ability = game.usable_abilities_of(source)[0]
    entry = _decided_ability_mana(game, source, ability.instruction)
    return entry["symbols_by_cost"].get(str(land.permanent_id))


def _explore(theirs, asked):
    """Benthic Explorers untapping the first of *theirs* (all tapped)."""
    game, mine, their = _table(["Benthic Explorers"], theirs, tapped_theirs=True)
    explorers, land = mine[0], their[0]
    wire = _wire_for_cost(game, explorers, land)
    result = game.activate_permanent_ability(
        0, "Benthic Explorers", permanent_index=0,
        cost_permanent_ids=[land.permanent_id], mana_color=asked,
    )
    assert result.supported, result.details
    assert land.tapped is False, "the cost untapped the opponent's land"
    return game, wire


@pytest.mark.cr("106.7")
@pytest.mark.parametrize("theirs,asked,offered,made", [
    # The plain land: what it makes is what it could produce.
    (("Forest",), "G", ["G"], {"G": 1}),
    # The opponent's Reflecting Pool could produce what that opponent's other
    # lands could — {G} — however many colours its summary lists, and a
    # colour asked outside that set is not one (CR 608.2d).
    (("Reflecting Pool", "Forest"), "B", ["G"], {"G": 1}),
    # Two Pools reading each other and an Island: {U}, and nothing else.
    (("Reflecting Pool", "Reflecting Pool", "Island"), "G", ["U"], {"U": 1}),
    # "…taking into account any applicable replacement effects": a Forest
    # under Infernal Darkness could produce {B} only.
    (("Forest", "Infernal Darkness"), "G", ["B"], {"B": 1}),
])
def test_benthic_explorers_makes_what_the_untapped_land_could_produce(theirs, asked, offered, made):
    game, wire = _explore(theirs, asked)
    assert wire == offered, "the wire offers the land's CR 106.7 types"
    assert _floating(game) == made, game.log[-4:]


@pytest.mark.cr("106.7")
def test_a_lone_reflecting_pool_untapped_by_benthic_explorers_makes_nothing():
    """"If that permanent wouldn't produce any mana under these conditions …
    there's no type of mana it could produce": a Pool whose controller has no
    other land reads only itself. The wire leaves it out of the cost's lands
    with something to offer, and the activation adds nothing."""
    game, wire = _explore(("Reflecting Pool",), "W")
    assert wire is None
    assert _floating(game) == {}
    assert "Benthic Explorers: that land produces no mana" in game.log


def _squander(mine, asked):
    game, placed, _ = _table(["Squandered Resources", *mine])
    resources, land = placed[0], placed[1]
    wire = _wire_for_cost(game, resources, land)
    result = game.activate_permanent_ability(
        0, "Squandered Resources", cost_permanent_ids=[land.permanent_id], mana_color=asked,
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(land), "the cost sacrificed the land"
    return game, wire


@pytest.mark.cr("106.7", "608.2h")
@pytest.mark.parametrize("mine,asked,offered,made", [
    # The sacrificed Pool is answered beside the board it left: its
    # controller's Forest could produce {G}, so the Pool could.
    (("Reflecting Pool", "Forest"), "U", ["G"], {"G": 1}),
    # …and alone it could produce nothing, gone or not.
    (("Reflecting Pool",), "U", None, {}),
    # A Forest sacrificed under Infernal Darkness could produce {B} only.
    (("Forest", "Infernal Darkness"), "G", ["B"], {"B": 1}),
])
def test_squandered_resources_reads_the_sacrificed_land_as_the_board_last_stood(
    mine, asked, offered, made,
):
    game, wire = _squander(mine, asked)
    assert wire == offered
    assert _floating(game) == made, game.log[-4:]


@pytest.mark.cr("106.7")
@pytest.mark.parametrize("static,offered", [
    # "…such as Contamination's effect, for example" (Fellwar Stone's ruling).
    ("Contamination", ["B"]),
    # A Forest under Ritual of Subdual could produce {C} only, and colourless
    # is no colour (CR 105.1): the Stone has nothing to copy.
    ("Ritual of Subdual", []),
])
def test_fellwar_stone_reads_an_opponent_s_land_after_its_substitution(static, offered):
    game, mine, _theirs = _table(["Fellwar Stone"], ["Forest", static])
    stone = mine[0]
    ability = game.usable_abilities_of(stone)[0]
    assert _decided_ability_mana(game, stone, ability.instruction)["symbols"] == offered
    result = game.activate_permanent_ability(0, "Fellwar Stone", mana_color="G")
    assert result.supported, result.details
    assert _floating(game) == ({offered[0]: 1} if offered else {}), game.log[-3:]


@pytest.mark.cr("106.7", "106.12a")
def test_mana_web_compares_what_the_lands_could_produce():
    """"Whenever a land an opponent controls is tapped for mana, tap all lands
    that player controls that could produce any type of mana that land could
    produce." Under Infernal Darkness the opponent's Forest could produce {B}
    and so could their Swamp: the Swamp is tapped. Read off the summaries, {G}
    and {B} shared nothing, and the Swamp stayed untapped."""
    game, _mine, theirs = _table(["Mana Web"], ["Forest", "Swamp", "Infernal Darkness"])
    forest, swamp = theirs[0], theirs[1]
    assert game.tap_land_for_mana(1, "Forest", chosen_color="G", permanent_id=forest.permanent_id)
    settle(game)
    assert _floating(game, 1) == {"B": 1}
    assert swamp.tapped is True, game.log[-4:]
    assert "Mana Web tapped Swamp" in game.log
