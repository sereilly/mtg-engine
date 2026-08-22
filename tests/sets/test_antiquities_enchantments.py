"""Per-card tests for Antiquities' enchantments.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Haunting Wind / Powerleech (round 6) — one ability, two trigger events
# ---------------------------------------------------------------------------


def test_haunting_wind_fires_when_an_artifact_becomes_tapped(set_pool):
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    thopter = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[thopter])
    game = Game(players=[p1, p2])

    game.become_tapped(thopter)

    # CR 603.3: the trigger goes on the stack. Nothing drives the stack in this
    # fixture, so that is the observable here — the activation tests below go
    # through a path that resolves, and assert on the damage instead.
    assert [item.card.name for item in game.stack] == ["Haunting Wind"]


def test_haunting_wind_fires_when_an_artifact_ability_is_activated_without_tapping(set_pool):
    """The half that had no dispatcher. A declaration in two front-end tables
    is not a trigger that fires — round 140's lesson — so this asserts the
    activation seam actually announces the event."""
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    # Dragon Engine's "{2}: This creature gets +1/+0 until end of turn" is an
    # artifact ability with no {T} in its cost, which is exactly the condition
    # the card names.
    engine_perm = Permanent(card=pool["Dragon Engine"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[engine_perm])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.activate_permanent_ability(1, "Dragon Engine")

    assert not engine_perm.tapped, "the fixture needs an ability with no {T} cost"
    assert p2.life == before - 1, game.log


def test_haunting_wind_does_not_fire_twice_for_a_tap_ability(set_pool):
    """An ability that *does* tap announces the condition once, through
    become_tapped. Emitting from the activation seam as well would fire the
    same printed ability twice for one activation."""
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    tome = Permanent(card=pool["Jalum Tome"])  # "{2}, {T}: Draw a card, then discard a card."
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[tome], library=[pool["Ornithopter"]] * 3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    before = p2.life
    game.activate_permanent_ability(1, "Jalum Tome")

    assert p2.life == before - 1, (
        f"one activation, one trigger — took {before - p2.life} damage: {game.log}"
    )


def test_haunting_wind_ignores_a_nonartifact_tapping(set_pool):
    pool = set_pool("ATQ")
    wind = Permanent(card=pool["Haunting Wind"])
    druid = Permanent(card=pool["Citanul Druid"])
    p1 = PlayerState(name="P1", battlefield=[wind])
    p2 = PlayerState(name="P2", battlefield=[druid])
    game = Game(players=[p1, p2])

    game.become_tapped(druid)

    assert game.stack == []


def test_powerleech_only_watches_its_opponents_artifacts(set_pool):
    """"an artifact **an opponent controls**" — the controller scope half."""
    pool = set_pool("ATQ")
    leech = Permanent(card=pool["Powerleech"])
    mine = Permanent(card=pool["Ornithopter"])
    p1 = PlayerState(name="P1", battlefield=[leech, mine])
    game = Game(players=[p1, PlayerState(name="P2")])

    game.become_tapped(mine)

    assert game.stack == [], "Powerleech watches an opponent's artifacts, not its own"
