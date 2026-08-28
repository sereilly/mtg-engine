"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# --- G3: upkeep and land denial (The Dark) ---


def _leviathan_board(set_pool, island_count: int = 2):
    """Leviathan untapped on the battlefield with *island_count* Islands."""
    lea = set_pool("LEA")
    leviathan = Permanent(card=set_pool("DRK")["Leviathan"])
    islands = [Permanent(card=lea["Island"]) for _ in range(island_count)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[leviathan, *islands]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    return game, leviathan


def test_leviathan_enters_tapped_and_stays_tapped(set_pool):
    """"This creature enters tapped and doesn't untap during your untap step."

    One printed line making two claims. The entry half was already applied
    (`enter_effects.ENTERS_TAPPED` is a substring probe); the untap half was
    **not** — `self_untap_line` is anchored on the whole line and had no row
    for this spelling, so Leviathan entered tapped and then untapped every
    turn with nothing failing.
    """
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("DRK")["Leviathan"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Leviathan").supported
    leviathan = next(p for p in game.all_permanents() if p.card.name == "Leviathan")
    assert leviathan.tapped

    game.resolve_untap_step(0)
    assert leviathan.tapped


def test_leviathan_untaps_when_two_islands_are_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice two Islands. If you
    do, untap this creature." This line produced no instruction at all."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)
    game.become_tapped(leviathan)
    game.current_turn_phase = "beginning"

    game.resolve_upkeep(0)
    while game.stack:
        game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, card_name="Leviathan", accept=True)

    assert not leviathan.tapped
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_cannot_attack_without_two_islands_to_sacrifice(set_pool):
    """"This creature can't attack unless you sacrifice two Islands. (This cost
    is paid as attackers are declared.)" CR 508.1g — a cost, not a target.

    With one Island the cost is unpayable, so the declaration is illegal. The
    Island stays: a refused declaration charges nothing.
    """
    game, _leviathan = _leviathan_board(set_pool, island_count=1)

    ok, _message = game.declare_attackers(0, [0])

    assert not ok
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1


def test_leviathan_pays_two_islands_as_attackers_are_declared(set_pool):
    """The other half: with the cost payable the attack happens **and** the
    Islands are gone. A restriction nothing charges is a card that attacks for
    free, which is the direction a missing enforcement always fails in."""
    game, leviathan = _leviathan_board(set_pool, island_count=3)

    ok, _message = game.declare_attackers(0, [0])

    assert ok
    assert leviathan.attacking
    assert sum(1 for p in game.controlled_by(0) if p.has_type("island")) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Island", "Island"]
