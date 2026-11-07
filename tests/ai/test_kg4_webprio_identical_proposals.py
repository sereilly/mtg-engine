"""Identical permanents do not spend the instant-speed chooser's whole budget
(kg4 `webprio`, the Scourge re-check's unregenerated Krosan Warchief).

``ai_policy.choose_instant_speed_activation`` rehearses up to
``INSTANT_ACTIVATIONS_WEIGHED`` (three) of the main-phase chooser's proposals,
setting aside the permanent behind each one it turns down. Six Pemmin's Auras
on one attacking Prodigal Sorcerer are six permanents making one proposal
("{U}: Untap enchanted creature"): it was turned down three times and the
chooser passed, so the Krosan Warchief *behind them on the battlefield*,
blocked by Hill Giant with {1}{G} open, was never weighed and died. Where the
Warchief entered before the Auras (every rebuild of the board until this
round) it was proposed first, which is why nobody could reproduce it.

The board is the end-of-turn-9 state of the re-check's game
(``scratch/scg/p5c/redrive/itemA_after_regen2.json``), with the Warchief
entering last, as it did there (cast in turn 8, after the Auras of turns 4–7).
"""

from __future__ import annotations

import pytest

from engine.ai_policy import _making_the_same_proposal
from engine.ai_priority import act_at_priority
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, declare_attack, resolve_stack

_AI_CREATURES = ["Prodigal Sorcerer", "Charging Paladin", "Zealous Inquisitor"]
_AI_LANDS = ["Island"] * 9 + ["Plains", "Plains", "Forest", "Mountain"]
_PERSON = [
    "Goblin Warchief", "Goblin Brigand", "Edgewalker", "Hill Giant",
    "Mountain", "Mountain", "Temple of the False God", "Plains", "Island",
]


@pytest.fixture(scope="module")
def cards():
    return {card.name: card for card in load_catalog()}


def _board(cards, auras_on_sorcerer: int = 6):
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Player 1")])
    game.enforce_mana_costs = True
    game.interactive_seats = {1}
    ai, person = game.players
    for name in _AI_CREATURES + _AI_LANDS:
        ai.battlefield.append(_nosick(Permanent(card=cards[name])))
    for name in _PERSON:
        person.battlefield.append(_nosick(Permanent(card=cards[name])))
    ai.library = [cards["Island"]] * 10
    person.library = [cards["Plains"]] * 10
    game._sync_control()
    sorcerer = ai.battlefield[0]
    auras = []
    for _ in range(auras_on_sorcerer):
        aura = _nosick(Permanent(card=cards["Pemmin's Aura"]))
        ai.battlefield.append(aura)
        game._sync_control()
        attach_aura(aura, sorcerer)
        auras.append(aura)
    warchief = _nosick(Permanent(card=cards["Krosan Warchief"]))
    ai.battlefield.append(warchief)
    game._sync_control()
    game._recompute_continuous_effects()
    return game, sorcerer, auras, warchief


def test_the_warchief_behind_six_identical_auras_regenerates_and_lives(cards):
    """The AI attacks with all four; the person blocks Krosan Warchief with
    Hill Giant. The AI's answer to its CR 509.2 priority is the Warchief's
    regeneration, and the Warchief survives the 3 damage."""
    game, _sorcerer, _auras, warchief = _board(cards)
    giant_slot = next(
        slot for slot, p in enumerate(game.players[1].battlefield) if p.card.name == "Hill Giant"
    )
    warchief_slot = next(
        slot for slot, p in enumerate(game.players[0].battlefield) if p is warchief
    )
    declare_attack(game, 0, blocks={giant_slot: warchief_slot})

    act = act_at_priority(game, 0)

    assert act is not None and act.supported, game.log[-10:]
    assert act.kind == "activate" and act.action.permanent_name == "Krosan Warchief"
    resolve_stack(game)
    game.advance_combat_phase()
    assert "Krosan Warchief regenerated" in game.log, game.log[-12:]
    assert game.is_on_battlefield(warchief)
    assert all(card.name != "Krosan Warchief" for card in game.players[0].graveyard)


def test_one_turned_down_proposal_sets_aside_only_the_permanents_that_would_make_it_again(cards):
    """Six Auras on the Sorcerer are one proposal; a seventh on the Paladin
    untaps something else and is still weighed, as are the Sorcerer, the
    Warchief and the lands."""
    game, sorcerer, auras, warchief = _board(cards)
    paladin = next(p for p in game.players[0].battlefield if p.card.name == "Charging Paladin")
    elsewhere = _nosick(Permanent(card=cards["Pemmin's Aura"]))
    game.players[0].battlefield.append(elsewhere)
    game._sync_control()
    attach_aura(elsewhere, paladin)
    game._recompute_continuous_effects()

    aside = _making_the_same_proposal(game, 0, auras[0])

    assert aside == {aura.permanent_id for aura in auras}
    assert elsewhere.permanent_id not in aside
    assert warchief.permanent_id not in aside and sorcerer.permanent_id not in aside
    # A permanent with nothing identical beside it sets aside itself alone.
    assert _making_the_same_proposal(game, 0, warchief) == {warchief.permanent_id}
