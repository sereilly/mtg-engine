from __future__ import annotations

from engine.ai_policy import choose_activation_action, choose_cast_action
from engine.game import Game
from engine.models import Permanent, PlayerState


def _get(all_cards, name: str):
    return next(card for card in all_cards if card.name == name)


def test_choose_cast_action_targets_self_for_ancestral_recall(all_cards):
    recall = _get(all_cards, "Ancestral Recall")
    p1 = PlayerState(name="P1", hand=[recall], mana_pool={"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 0})
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Ancestral Recall"
    assert action.target_player_index == 0


def test_choose_cast_action_finds_lethal_lightning_bolt(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    salve = _get(all_cards, "Healing Salve")
    mountain = _get(all_cards, "Mountain")
    plains = _get(all_cards, "Plains")

    p1 = PlayerState(
        name="P1",
        hand=[salve, bolt],
        battlefield=[Permanent(card=mountain), Permanent(card=plains)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Lightning Bolt"
    assert action.target_player_index == 1
    assert action.land_tap_indices


def test_choose_cast_action_skips_unsummon_without_target(all_cards):
    unsummon = _get(all_cards, "Unsummon")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[unsummon], battlefield=[Permanent(card=island)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_cast_action(game, 0)

    assert action is None


def test_choose_activation_action_prefers_prodigal_for_lethal(all_cards):
    prodigal = _get(all_cards, "Prodigal Sorcerer")
    tome = _get(all_cards, "Jayemdae Tome")

    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=tome), Permanent(card=prodigal)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 4},
        library=[_get(all_cards, "Island")],
    )
    p2 = PlayerState(name="P2", life=1)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    action = choose_activation_action(game, 0)

    assert action is not None
    assert action.permanent_name == "Prodigal Sorcerer"
    assert action.target_player_index == 1
