from __future__ import annotations

from engine.ai_policy import (
    choose_activation_action,
    choose_cast_action,
    choose_combat_blockers,
    choose_combat_instant_cast_action,
    choose_search_library_index,
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


def test_ai_chooses_creature_target_when_casting_fear(all_cards):
    """Regression: the AI cast Fear (an Aura) without choosing a target.

    Aura spells require a target (Rule 115.1b) — the AI must pick a legal
    creature for Fear, not a land, and put the beneficial Aura on its own creature.
    """
    fear = _get(all_cards, "Fear")
    grizzly = _get(all_cards, "Grizzly Bears")
    swamp = _get(all_cards, "Swamp")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=swamp), Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Fear"
    assert action.target_player_index == 0
    assert action.target_permanent_index == 1, "AI must target its creature, not the Swamp"

    # The chosen action must actually be castable by the engine
    result = game.cast_from_hand(
        0,
        action.card_name,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
    )
    assert result.supported
    fear_perm = next(perm for perm in p1.battlefield if perm.card.name == "Fear")
    assert fear_perm.metadata.get("attached_to") is not None


def test_ai_skips_aura_with_no_legal_target(all_cards):
    """The AI must not try to cast an Aura when no legal enchant target exists."""
    fear = _get(all_cards, "Fear")
    swamp = _get(all_cards, "Swamp")

    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=swamp)])
    p2 = PlayerState(name="P2")  # no creatures anywhere
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    assert action is None or action.card_name != "Fear"


def test_ai_puts_harmful_aura_on_opponent_creature(all_cards):
    """A harmful Aura (Paralyze) goes on an opponent's creature, not the AI's own."""
    paralyze = _get(all_cards, "Paralyze")
    grizzly = _get(all_cards, "Grizzly Bears")

    p1 = PlayerState(name="P1", hand=[paralyze], battlefield=[Permanent(card=grizzly)])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=grizzly)])
    game = Game(players=[p1, p2])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Paralyze"
    assert action.target_player_index == 1
    assert action.target_permanent_index == 0


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


def test_tutor_picks_lethal_burn_when_opponent_low(all_cards):
    """Demonic Tutor AI: with the opponent at 3 life, find the kill spell."""
    bolt = _get(all_cards, "Lightning Bolt")
    grizzly = _get(all_cards, "Grizzly Bears")
    forest = _get(all_cards, "Forest")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", library=[forest, grizzly, bolt], battlefield=[Permanent(card=mountain)])
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2])

    index = choose_search_library_index(game, 0)

    assert index is not None
    assert p1.library[index].name == "Lightning Bolt"


def test_tutor_picks_land_when_mana_screwed(all_cards):
    """Demonic Tutor AI: with no lands in play or hand, dig for mana."""
    shivan = _get(all_cards, "Shivan Dragon")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", library=[shivan, mountain])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True

    index = choose_search_library_index(game, 0)

    assert index is not None
    assert p1.library[index].name == "Mountain"


def test_tutor_returns_none_on_empty_library(all_cards):
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    assert choose_search_library_index(game, 0) is None


def test_tutor_prefers_castable_spell(all_cards):
    """Demonic Tutor AI: with mana enforcement on, prefer a spell it can afford now."""
    bolt = _get(all_cards, "Lightning Bolt")
    shivan = _get(all_cards, "Shivan Dragon")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(name="P1", library=[shivan, bolt], battlefield=[Permanent(card=mountain)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True

    index = choose_search_library_index(game, 0)

    assert index is not None
    assert p1.library[index].name == "Lightning Bolt"


def test_ai_does_not_self_target_x_damage_spell(all_cards):
    """Regression: Disintegrate ("deals X damage to any target") parses to amount 'x',
    so the literal damage extractor read 0 and the target tie-break pointed the spell at
    the caster's own face. The AI must aim X-damage burn at the opponent."""
    disintegrate = _get(all_cards, "Disintegrate")
    mountain = _get(all_cards, "Mountain")

    p1 = PlayerState(
        name="P1",
        hand=[disintegrate],
        battlefield=[Permanent(card=mountain) for _ in range(3)],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True

    action = choose_cast_action(game, 0)

    assert action is not None
    assert action.card_name == "Disintegrate"
    assert action.target_player_index == 1, "AI must aim X-damage burn at the opponent, not itself"
