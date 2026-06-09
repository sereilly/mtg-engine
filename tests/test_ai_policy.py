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


def test_ancestral_recall_not_cast_on_self_with_empty_library(all_cards):
    """Regression: AI must not self-target Ancestral Recall when library has < 3 cards.

    Before the fix, the AI would cast Ancestral Recall on itself even with an empty
    library, immediately losing the game via rule 704.5b (drew from empty library).
    """
    ancestral = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[ancestral])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # P1's library is empty — self-casting Ancestral Recall would lose the game.
    assert len(p1.library) == 0

    action = choose_cast_action(game, 0)

    # The AI should either skip Ancestral Recall entirely or target the opponent.
    if action is not None and action.card_name == "Ancestral Recall":
        assert action.target_player_index == 1, (
            "AI must not self-target Ancestral Recall with 0 library cards"
        )


def test_ancestral_recall_not_cast_on_self_with_two_library_cards(all_cards):
    """Regression: AI must not self-target Ancestral Recall when library has exactly 2 cards.

    Drawing from an empty library after the 2nd card causes an immediate loss.
    """
    ancestral = _get(all_cards, "Ancestral Recall")
    island = _get(all_cards, "Island")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[ancestral], library=[island, grizzly])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    if action is not None and action.card_name == "Ancestral Recall":
        assert action.target_player_index == 1, (
            "AI must not self-target Ancestral Recall when only 2 library cards remain"
        )


def test_healing_salve_not_cast_at_full_life(all_cards):
    """Regression: AI must not prefer Healing Salve when the caster is at full (20) life.

    Before the fix, life-gain cards received a flat +2.0 score bonus regardless of
    the caster's current life, causing the AI to waste its turn gaining life it didn't need.
    """
    salve = _get(all_cards, "Healing Salve")
    bolt = _get(all_cards, "Lightning Bolt")

    p1 = PlayerState(name="P1", hand=[salve, bolt], life=20)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    # Lightning Bolt should score higher than Healing Salve when at full life.
    assert action is not None
    assert action.card_name == "Lightning Bolt", (
        "AI should prefer Lightning Bolt over Healing Salve when at 20 life"
    )


def test_healing_salve_preferred_when_low_on_life(all_cards):
    """Healing Salve should be valued when the caster is under serious life pressure."""
    salve = _get(all_cards, "Healing Salve")
    island = _get(all_cards, "Island")

    p1 = PlayerState(name="P1", hand=[salve, island], life=5)
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    # Healing Salve (life-gain with pressure) should score above just playing a land.
    assert action is not None
    assert action.card_name == "Healing Salve", (
        "AI should prefer Healing Salve over a land when at 5 life"
    )


def test_black_lotus_not_preferred_when_mana_free(all_cards):
    """Regression: AI must not prefer Black Lotus over useful spells when mana costs are free.

    When enforce_mana_costs=False, Black Lotus provides zero benefit. Before the fix
    it still received a score bonus and could displace actually useful cards.
    """
    lotus = _get(all_cards, "Black Lotus")
    bolt = _get(all_cards, "Lightning Bolt")

    p1 = PlayerState(name="P1", hand=[lotus, bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    assert not game.enforce_mana_costs  # confirm default

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Lightning Bolt", (
        "AI should prefer Lightning Bolt over Black Lotus when mana costs are not enforced"
    )
