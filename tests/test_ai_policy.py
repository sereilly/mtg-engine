from __future__ import annotations

from engine.ai_policy import (
    choose_activation_action,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
)
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


def test_choose_combat_blockers_tries_to_prevent_lethal(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly), Permanent(card=grizzly)], life=7)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0, 1], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)

    assert blockers
    assert len(blockers) == 2


def test_choose_combat_blockers_returns_empty_when_no_legal_blockers(all_cards):
    craw_wurm = _get(all_cards, "Craw Wurm")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=craw_wurm)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mountain)], life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    game.current_phase = "combat"

    ok, _ = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok
    game.current_step = "declare_blockers"

    blockers = choose_combat_blockers(game, 1)
    assert blockers == {}


def test_choose_combat_instant_cast_action_prefers_interaction_in_block_step(all_cards):
    bolt = _get(all_cards, "Lightning Bolt")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", life=5)
    p2 = PlayerState(
        name="P2",
        hand=[bolt],
        battlefield=[Permanent(card=mountain)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0},
    )
    game = Game(players=[p1, p2], enforce_mana_costs=True)
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_blockers"
    game.current_phase = "combat"

    action = choose_combat_instant_cast_action(game, 1)

    assert action is not None
    assert action.card_name == "Lightning Bolt"
    assert action.target_player_index == 0
