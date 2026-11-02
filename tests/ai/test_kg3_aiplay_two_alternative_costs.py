"""Two alternative costs at once (kg3 `aiplay`, part 7).

Dream Halls ("Rather than pay the mana cost for a spell, its controller may
discard a card that shares a color with that spell") beside a morph card in
hand is two CR 118.9 alternative costs — the face-down {3} (CR 702.37c) and
the discard — and CR 118.9a applies one of them, which the cast names
(``alternative_cost_index``; ``client`` at kg3). ``ai_cast_gates`` accepted
exactly one applicable alternative, so an AI seat holding both took neither
and kept the card. Each payable alternative is now planned and the cast the
rehearsal measures more is made (``ai_casts._better_alternative``), naming
its index.

Both ways: with a white card to discard, the free face-up Daru Lancer beats
the face-down 2/2 for {3}; with nothing to discard, the morph is the only
one payable — still named, because two apply.
"""
from __future__ import annotations

from engine import ai_simulator
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _table(hand):
    players = [
        PlayerState(name="AI-A", hand=[_CARDS[name] for name in hand],
                    library=[_CARDS["Plains"]] * 8),
        PlayerState(name="AI-B", hand=[], library=[_CARDS["Plains"]] * 8),
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    game.turn = 3
    game.active_player_index = 0
    for name in ("Dream Halls", "Plains", "Plains", "Plains"):
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _cast(game, action):
    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result
    resolve_stack(game)


def test_with_a_card_to_discard_dream_halls_puts_the_lancer_face_up():
    game = _table(["Daru Lancer", "Savannah Lions"])
    applicable = game.applicable_alternative_costs(0, _CARDS["Daru Lancer"])
    assert len(applicable) == 2
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Daru Lancer", action
    assert action.alternative_cost and action.alternative_cost_index is not None
    _cast(game, action)
    lancer = next(p for p in game.controlled_by(0) if p.is_creature)
    assert not lancer.metadata.get("face_down") and lancer.card.name == "Daru Lancer"
    assert [card.name for card in game.players[0].graveyard] == ["Savannah Lions"]


def test_with_nothing_to_discard_the_morph_is_named_by_its_index():
    game = _table(["Daru Lancer"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Daru Lancer", action
    assert action.alternative_cost and action.alternative_cost_index is not None
    _cast(game, action)
    creature = next(p for p in game.controlled_by(0) if p.is_creature)
    assert creature.card.face_down_of is not None
    assert creature.card.face_down_of.name == "Daru Lancer"
    assert sum(1 for p in game.controlled_by(0) if p.has_type("land") and p.tapped) == 3
