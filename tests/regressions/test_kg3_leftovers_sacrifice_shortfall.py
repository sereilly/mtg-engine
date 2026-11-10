"""Census: every printed "sacrifice … If you can't, …" reaches its
consequence, and none through the forced sacrifice's prompt.

``SacrificeChoicesMixin.arm_forced_sacrifice`` carried an ``on_short``
consequence ("lose", or "damage N") applied by ``_apply_sacrifice_shortfall``
when a player owed more sacrifices than they could make — and no caller ever
passed one (measured at round ``kg3``'s base: no ``on_short=`` anywhere in
``engine/`` outside the mixin itself), so its two branches were dead. The
sentences it was written for are carried out elsewhere, by the step that
knows them:

* Lich — "sacrifice that many nontoken permanents. If you can't, you lose the
  game": the sacrifice handler records whether the payer could pay
  (``sacrificed_this_way``) and the compiled branch behind it reads that;
* Infernal Denizen — "sacrifice two Swamps. If you can't, tap this creature,
  and an opponent may gain control …": the same record;
* Lord of the Pit — "sacrifice a creature other than this creature. If you
  can't, this creature deals 7 damage to you": its upkeep arms the sacrifice
  only when a creature can be given up, and deals the damage otherwise.

So the branch and its parameter went. The census reads every compilation
unit's text for the shape and holds the set to the boards driven here, so a
new card printing it is driven before it ships.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}

#: Both manifest roles: the census holds a card printing the shape to a board
#: *before* it ships ("a new card printing it is driven before it ships"), so
#: it reads a set under ``measured`` too, and a board may name that set's cards
#: (Rust Elemental, Mirrodin, at its promotion rehearsal). A name the shipped
#: pool holds resolves as it always did.
_POOL = load_cards(manifest_set_paths(include_measured=True))
_MEASURED = {card.name: card for card in _POOL if card.name not in _CARDS}


#: "Sacrifice <something>. If you can't, <consequence>." — the sacrifice owed
#: first, its failure after.
_SHAPE = re.compile(r"\bsacrifices? [^.]*\.\s*if (?:you|they|that player) can't,")

DRIVEN = {"Lich", "Lord of the Pit", "Infernal Denizen", "Rust Elemental"}


def test_every_printed_sacrifice_shortfall_is_driven_here():
    printed = {
        card.name
        for card in compilation_units(_POOL)
        if _SHAPE.search((card.oracle_text or "").lower())
    }
    assert len(printed) >= 3, printed
    assert printed == DRIVEN, sorted(printed ^ DRIVEN)


def test_the_forced_sacrifice_carries_no_consequence_of_its_own():
    import inspect

    from engine.mixins.stack.choices.sacrifice import SacrificeChoicesMixin

    assert "on_short" not in inspect.signature(
        SacrificeChoicesMixin.arm_forced_sacrifice
    ).parameters
    assert not hasattr(SacrificeChoicesMixin, "_apply_sacrifice_shortfall")


def _perm(name: str) -> Permanent:
    permanent = Permanent(card=_CARDS.get(name) or _MEASURED[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _game(mine, theirs=(), *, interactive=()) -> Game:
    game = Game(players=[
        PlayerState(name="P0", library=[_CARDS["Swamp"]] * 10,
                    battlefield=[_perm(name) for name in mine]),
        PlayerState(name="P1", library=[_CARDS["Island"]] * 10,
                    battlefield=[_perm(name) for name in theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game._recompute_continuous_effects()
    return game


def _damage(game: Game, amount: int) -> None:
    source = _CARDS["Lightning Bolt"]
    game._deal_damage_to_player(game.players[0], amount, source=source)
    settle(game)


def test_lich_that_cannot_sacrifice_enough_loses_the_game():
    game = _game(["Lich", "Grizzly Bears"])
    _damage(game, 3)
    assert game.players[0].lost, game.log


def test_lich_that_can_sacrifice_enough_does_and_stays():
    game = _game(["Lich", "Grizzly Bears", "Hill Giant", "Swamp", "Swamp"])
    _damage(game, 2)
    assert not game.players[0].lost, game.log
    assert len(game.players[0].graveyard) == 2, game.log


@pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_lord_of_the_pit_with_nothing_to_sacrifice_deals_seven(interactive):
    game = _game(["Lord of the Pit", "Swamp"], interactive=interactive)
    game.resolve_upkeep(0)
    settle(game)
    assert game.players[0].life == 13, game.log
    assert game.is_on_battlefield(game.players[0].battlefield[0])


@pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_infernal_denizen_that_cannot_sacrifice_two_swamps_is_tapped(interactive):
    game = _game(["Infernal Denizen", "Swamp", "Grizzly Bears"], interactive=interactive)
    denizen = game.players[0].battlefield[0]
    game.resolve_upkeep(0)
    settle(game)
    # One Swamp cannot pay "two Swamps", so neither goes (the count is
    # indivisible) and the "If you can't" branch happens instead.
    assert any(p.card.name == "Swamp" for p in game.controlled_by(0)), game.log
    assert denizen.tapped, game.log


@pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_rust_elemental_sacrifices_another_artifact_when_it_can(interactive):
    """"At the beginning of your upkeep, sacrifice another artifact. If you
    can't, tap this creature and you lose 4 life." (Rust Elemental.) The
    2004-12-01 ruling: "Sacrificing an artifact isn't optional. If you control
    an artifact other than Rust Elemental, you must sacrifice it." — so the
    Sol Ring goes, the Elemental (itself an artifact) stays untapped and no
    life is lost."""
    game = _game(["Rust Elemental", "Sol Ring", "Swamp"], interactive=interactive)
    elemental = game.players[0].battlefield[0]
    game.resolve_upkeep(0)
    settle(game)
    assert [card.name for card in game.players[0].graveyard] == ["Sol Ring"], game.log
    assert game.is_on_battlefield(elemental) and not elemental.tapped, game.log
    assert game.players[0].life == 20, game.log


@pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_rust_elemental_with_no_other_artifact_is_tapped_and_costs_four(interactive):
    """"Otherwise, you must tap Rust Elemental and lose 4 life" (the same
    ruling): the Elemental is the only artifact, so nothing is sacrificed —
    not the Elemental itself, which "another" excludes."""
    game = _game(["Rust Elemental", "Swamp"], interactive=interactive)
    elemental = game.players[0].battlefield[0]
    game.resolve_upkeep(0)
    settle(game)
    assert game.is_on_battlefield(elemental), game.log
    assert elemental.tapped, game.log
    assert game.players[0].life == 16, game.log
    assert game.players[0].graveyard == [], game.log
