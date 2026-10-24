"""Census: a cost is a state change, and the state is checked before anybody
receives priority after it.

The playbook's Known gap: "The state-based check after a non-resolution is
audited for special actions only … cost payments have not been audited."
Judgment's costs move graveyard cards — Battlefield Scrounger puts three on
the bottom of its library, Flash of Insight's flashback exiles X blue cards,
Lost in Thought's special action exiles three — and each can switch a
threshold static off before the ability resolves. CR 704.3 checks state
whenever a player would receive priority, and CR 117.3c gives it back to the
activator the moment the object is on the stack; CR 601.2c / 602.2b put the
triggers a cost fires on the stack *after* the object (they wait for the
announcement to finish).

One row per road a cost is paid on, each with a cost that leaves something
due:

* activating from the battlefield (Scrounger), casting (Flash of Insight's
  flashback, and Wonder exiled by it), the special action (Lost in Thought) —
  Anurid Barkripper loses threshold's +2/+2 with 3 damage marked and dies
  before priority. These three already held on the base; pinned here;
* activating from a **hand** (cycling) and from a **graveyard** (Whiteout,
  Necrosavant) — neither swept nor deferred on the base: a Maro cycled down
  to 0/0 lived on, a Wild Growth stayed on the battlefield with no land under
  it (CR 704.5m), and Megrim's and Havoc Jester's triggers off the cost went
  on the stack *under* the ability that paid it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.special_actions import take_permanent_special_action


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()

_TABLES = [pytest.param((0, 1), id="interactive"), pytest.param((), id="headless")]


def _table(interactive) -> Game:
    game = Game(players=[
        PlayerState("P0", library=[_POOL["Island"]] * 10),
        PlayerState("P1", library=[_POOL["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game.stack.clear()
    return game


def _put(game, seat, name) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game.stack.clear()
    return permanent


def _barkripper(game, seat) -> Permanent:
    """A threshold +2/+2 creature at 4/4 with 3 damage marked."""
    ripper = _put(game, seat, "Anurid Barkripper")
    game._recompute_continuous_effects()
    assert (ripper.effective_power, ripper.effective_toughness) == (4, 4)
    ripper.damage_marked = 3
    return ripper


@pytest.mark.parametrize("interactive", _TABLES)
def test_an_activation_cost_on_the_battlefield(interactive):
    game = _table(interactive)
    game.players[0].graveyard.extend([_POOL["Forest"]] * 7)
    ripper = _barkripper(game, 0)
    _put(game, 0, "Battlefield Scrounger")

    assert game.queue_permanent_ability(0, "Battlefield Scrounger").supported
    assert [item.card.name for item in game.stack] == ["Battlefield Scrounger"]
    assert not game.is_on_battlefield(ripper), "704.5g before priority"


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_flashback_cost(interactive):
    game = _table(interactive)
    game.players[0].graveyard.extend(
        [_POOL["Flash of Insight"]] + [_POOL["Counterspell"]] * 3 + [_POOL["Forest"]] * 3
    )
    ripper = _barkripper(game, 0)

    assert game.queue_from_hand(
        0, "Flash of Insight", from_zone="graveyard", x_value=2,
        cost_graveyard_indices=[1, 2],
    ).supported
    assert [item.card.name for item in game.stack] == ["Flash of Insight"]
    assert not game.is_on_battlefield(ripper)


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_flashback_cost_that_exiles_an_incarnation(interactive):
    """Wonder grants flying from the graveyard; exiled to pay for the
    flashback, it grants nothing by the time anybody has priority."""
    game = _table(interactive)
    game.players[0].graveyard.extend(
        [_POOL["Flash of Insight"], _POOL["Wonder"], _POOL["Counterspell"]]
    )
    _put(game, 0, "Island")
    bears = _put(game, 0, "Grizzly Bears")
    game._recompute_continuous_effects()
    assert bears.has_keyword("flying")

    assert game.queue_from_hand(
        0, "Flash of Insight", from_zone="graveyard", x_value=1,
        cost_graveyard_indices=[1],
    ).supported
    assert [card.name for card in game.players[0].exile] == ["Wonder"]
    assert not bears.has_keyword("flying")


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_special_action_cost(interactive):
    game = _table(interactive)
    them = game.players[1]
    them.graveyard.extend([_POOL["Forest"]] * 7)
    ripper = _barkripper(game, 1)
    sorcerer = _put(game, 1, "Prodigal Sorcerer")
    aura = _put(game, 0, "Lost in Thought")
    attach_aura(aura, sorcerer)
    game.priority_player_index = 1

    assert take_permanent_special_action(
        game, 1, aura, "ignore_attached_static_until_eot", exiled_slots=[0, 1, 2],
    ) is None
    assert len(them.exile) == 3
    assert not game.is_on_battlefield(ripper)


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_cycling_cost_from_hand(interactive):
    """Cycling the last card in hand: Maro is 0/0 (CR 704.5f) before anybody
    has priority, with the cycling ability on the stack."""
    game = _table(interactive)
    game.players[0].hand = [_POOL["Rescind"]]
    maro = _put(game, 0, "Maro")
    game._recompute_continuous_effects()
    assert maro.effective_toughness == 1

    assert game.activate_from_hand(0, "Rescind").supported
    assert [item.card.name for item in game.stack] == ["Rescind"]
    assert not game.is_on_battlefield(maro)


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_trigger_off_a_cycling_cost_goes_above_the_ability(interactive):
    """Megrim triggers on the discard the cost makes; CR 602.2b / 601.2c: it
    waits for the announcement and goes on the stack above the ability, so it
    resolves first."""
    game = _table(interactive)
    _put(game, 1, "Megrim")
    game.players[0].hand = [_POOL["Rescind"]]

    assert game.activate_from_hand(0, "Rescind").supported
    assert [item.card.name for item in game.stack] == ["Rescind", "Megrim"]


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_sacrifice_cost_from_a_graveyard_takes_the_aura_with_it(interactive):
    """Whiteout's "Sacrifice a snow land" with Wild Growth on the land: the
    Aura is put into its owner's graveyard (CR 704.5m) before priority."""
    game = _table(interactive)
    land = _put(game, 0, "Snow-Covered Forest")
    growth = _put(game, 0, "Wild Growth")
    attach_aura(growth, land)
    game.players[0].graveyard.append(_POOL["Whiteout"])

    assert game.activate_from_graveyard(
        0, "Whiteout", cost_permanent_id=land.permanent_id,
    ).supported
    assert [item.card.name for item in game.stack] == ["Whiteout"]
    assert not game.is_on_battlefield(growth)
    assert "Wild Growth" in [card.name for card in game.players[0].graveyard]


@pytest.mark.parametrize("interactive", _TABLES)
def test_a_trigger_off_a_graveyard_sacrifice_goes_above_the_ability(interactive):
    """Necrosavant's "Sacrifice a creature" beside Havoc Jester ("whenever you
    sacrifice a permanent"): the Jester's ping goes above the ability."""
    game = _table(interactive)
    _put(game, 0, "Havoc Jester")
    bears = _put(game, 0, "Grizzly Bears")
    game.players[0].graveyard.append(_POOL["Necrosavant"])
    game.current_phase, game.current_step = "beginning", "upkeep"

    assert game.activate_from_graveyard(
        0, "Necrosavant", cost_permanent_id=bears.permanent_id,
    ).supported
    assert [item.card.name for item in game.stack] == ["Necrosavant", "Havoc Jester"]
