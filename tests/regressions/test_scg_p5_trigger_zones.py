"""A trigger that functions from a graveyard does not fire from the
battlefield (CR 113.6m) — Scourge's post-promotion browser session.

Dragon Wings attached to a Shivan Dragon offered "return this card from your
graveyard to the battlefield attached to that creature" (Yes/No) when
Bladewing the Risen entered, and again when Eternal Dragon entered; Yes
resolved as "Dragon Wings was no longer in the graveyard". The lowering stamps
the zone (``functions_from: "graveyard"``) and the graveyard scan asked it;
the battlefield scans never did. The pool-wide census is
``tests/engine/test_scg_p5_trigger_zone_census.py``.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _pool():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _game(pool, *, interactive=()):
    forests = [pool["Forest"]] * 10
    game = Game(players=[
        PlayerState(name="Me", library=list(forests)),
        PlayerState(name="Opp", library=list(forests)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def test_dragon_wings_on_the_battlefield_offers_nothing_when_a_six_drop_enters():
    pool = _pool()
    game = _game(pool, interactive={0})
    game.start_turn(0)
    shivan = Permanent(card=pool["Shivan Dragon"])
    game._put_permanent_onto_battlefield(0, shivan, None)
    wings = Permanent(card=pool["Dragon Wings"])
    game._put_permanent_onto_battlefield(0, wings, None)
    attach_aura(wings, shivan)
    game._recompute_continuous_effects()
    resolve_stack(game)
    for entering in ("Bladewing the Risen", "Eternal Dragon"):
        game._put_permanent_onto_battlefield(0, Permanent(card=pool[entering]), None)
        assert not any(
            item.card.name == "Dragon Wings" for item in game.stack
        ), f"Dragon Wings fired from the battlefield as {entering} entered"
        game.stack.clear()
        game.pending_choices.clear()
    assert wings.metadata.get("attached_to") is shivan


def test_dragon_wings_in_the_graveyard_still_returns_attached_to_the_six_drop():
    pool = _pool()
    game = _game(pool)
    game.players[0].graveyard.append(pool["Dragon Wings"])
    game.start_turn(0)
    eternal = Permanent(card=pool["Eternal Dragon"])
    game._put_permanent_onto_battlefield(0, eternal, None)
    assert [item.card.name for item in game.stack] == ["Dragon Wings"]
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    wings = [perm for perm in game.all_permanents() if perm.card.name == "Dragon Wings"]
    assert len(wings) == 1 and wings[0].metadata.get("attached_to") is eternal


def test_squee_on_the_battlefield_fires_nothing_at_its_upkeep():
    """Squee's upkeep trigger compiles the same way ("return this card from
    your graveyard to your hand"), and on the battlefield it fired and
    resolved — "Squee, Goblin Nabob ability resolved" — doing nothing."""
    pool = _pool()
    game = _game(pool)
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Squee, Goblin Nabob"]), None)
    before = len(game.log)
    game.start_turn(0)
    assert not game.stack
    assert not any("Squee" in line for line in game.log[before:]), game.log[before:]
