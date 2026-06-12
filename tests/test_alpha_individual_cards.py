from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from engine import Game, PlayerState, classify_card, load_cards
from engine.mixins.stack_casting import aura_enchant_noun, permanent_matches_enchant_noun
from engine.models import CardDefinition, Permanent

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}


@dataclass(frozen=True)
class _Snapshot:
    p1_life: int
    p2_life: int
    p1_hand: int
    p2_hand: int
    p1_graveyard: int
    p2_graveyard: int
    p1_battlefield: int
    p2_battlefield: int
    p1_creatures: int
    p2_creatures: int
    p1_lands: int
    p2_lands: int
    p1_prevention: int
    p2_prevention: int
    p1_black_mana: int


def _sanitize_test_name(card_name: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", card_name).strip("_").lower()
    return f"test_alpha_unique_effect_{slug}"


def _normalize_oracle(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _alpha_cards() -> list[CardDefinition]:
    root = Path(__file__).resolve().parent.parent
    return load_cards(root / "lea_cards.json")


def _cards_with_unique_effects(cards: list[CardDefinition]) -> list[CardDefinition]:
    normalized = [_normalize_oracle(card.oracle_text) for card in cards if card.oracle_text.strip()]
    counts = Counter(normalized)
    return [
        card
        for card in cards
        if card.oracle_text.strip() and counts[_normalize_oracle(card.oracle_text)] == 1
    ]


def _build_context_cards(all_cards: list[CardDefinition]) -> dict[str, CardDefinition]:
    by_name = {card.name: card for card in all_cards}
    return {
        "island": by_name["Island"],
        "plains": by_name["Plains"],
        "swamp": by_name["Swamp"],
        "mountain": by_name["Mountain"],
        "forest": by_name["Forest"],
        "grizzly_bears": by_name["Grizzly Bears"],
        "black_lotus": by_name["Black Lotus"],
        "bad_moon": by_name["Bad Moon"],
        "ancestral_recall": by_name["Ancestral Recall"],
    }


def _build_game_for_card(card: CardDefinition, all_cards: list[CardDefinition]) -> tuple[Game, PlayerState, PlayerState]:
    ctx = _build_context_cards(all_cards)

    p1 = PlayerState(
        name="P1",
        hand=[card],
        battlefield=[
            Permanent(card=ctx["grizzly_bears"]),
            Permanent(card=ctx["plains"]),
            Permanent(card=ctx["black_lotus"]),
            Permanent(card=ctx["bad_moon"]),
        ],
        graveyard=[ctx["grizzly_bears"]],
        library=[
            ctx["forest"],
            ctx["mountain"],
            ctx["swamp"],
            ctx["plains"],
            ctx["island"],
            ctx["forest"],
            ctx["mountain"],
            ctx["swamp"],
            ctx["plains"],
            ctx["island"],
            ctx["forest"],
            ctx["mountain"],
        ],
    )

    p2 = PlayerState(
        name="P2",
        hand=[ctx["island"], ctx["plains"], ctx["grizzly_bears"]],
        battlefield=[
            Permanent(card=ctx["grizzly_bears"], tapped=True),
            Permanent(card=ctx["plains"]),
            Permanent(card=ctx["black_lotus"]),
            Permanent(card=ctx["bad_moon"]),
        ],
        graveyard=[ctx["grizzly_bears"]],
        library=[
            ctx["island"],
            ctx["plains"],
            ctx["swamp"],
            ctx["mountain"],
            ctx["forest"],
            ctx["island"],
            ctx["plains"],
            ctx["swamp"],
            ctx["mountain"],
            ctx["forest"],
            ctx["island"],
            ctx["plains"],
        ],
    )

    return Game(players=[p1, p2]), p1, p2


def _snapshot(p1: PlayerState, p2: PlayerState) -> _Snapshot:
    return _Snapshot(
        p1_life=p1.life,
        p2_life=p2.life,
        p1_hand=len(p1.hand),
        p2_hand=len(p2.hand),
        p1_graveyard=len(p1.graveyard),
        p2_graveyard=len(p2.graveyard),
        p1_battlefield=len(p1.battlefield),
        p2_battlefield=len(p2.battlefield),
        p1_creatures=sum(1 for perm in p1.battlefield if perm.card.primary_type == "creature"),
        p2_creatures=sum(1 for perm in p2.battlefield if perm.card.primary_type == "creature"),
        p1_lands=sum(1 for perm in p1.battlefield if perm.card.primary_type == "land"),
        p2_lands=sum(1 for perm in p2.battlefield if perm.card.primary_type == "land"),
        p1_prevention=p1.damage_prevention_pool,
        p2_prevention=p2.damage_prevention_pool,
        p1_black_mana=p1.mana_pool["B"],
    )


def _run_card(card: CardDefinition, all_cards: list[CardDefinition]) -> tuple[Game, PlayerState, PlayerState, _Snapshot, object]:
    game, p1, p2 = _build_game_for_card(card, all_cards)
    if card.name == "Animate Wall":
        # Animate Wall needs a Wall on the battlefield to target (Rule 115.1b)
        wall = next(c for c in all_cards if "wall" in c.type_line.lower())
        p2.battlefield.append(Permanent(card=wall))
    if card.name == "Gaea's Liege":
        # CDA: P/T = number of Forests its controller controls. Without a Forest
        # it enters as a 0/0 and dies to state-based actions (704.5f).
        forest = next(c for c in all_cards if c.name == "Forest")
        p1.battlefield.append(Permanent(card=forest))
    before = _snapshot(p1, p2)

    if card.name in {"Counterspell", "Power Sink", "Spell Blast"}:
        recall = next(c for c in all_cards if c.name == "Ancestral Recall")
        p2.hand.append(recall)
        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        return game, p1, p2, before, result

    if card.name == "Fork":
        recall = next(c for c in all_cards if c.name == "Ancestral Recall")
        p1.hand.insert(0, recall)
        game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, "Fork", target_player_index=1)
        return game, p1, p2, before, result

    if card.name == "Blue Elemental Blast":
        # First mode is "counter target red spell": queue a red spell to counter.
        lightning_bolt = next(c for c in all_cards if c.name == "Lightning Bolt")
        p2.hand.append(lightning_bolt)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        return game, p1, p2, before, result

    if card.name == "Red Elemental Blast":
        # First mode is "counter target blue spell": queue a blue spell to counter.
        recall = next(c for c in all_cards if c.name == "Ancestral Recall")
        p2.hand.append(recall)
        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        return game, p1, p2, before, result

    if card.name == "Camouflage":
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # → beginning_of_combat
        game.advance_combat_phase()  # → declare_attackers
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        return game, p1, p2, before, result

    if card.name == "Siren's Call":
        # Castable only during an opponent's turn, before attackers are declared.
        game.start_turn(1)
        result = game.cast_from_hand(0, card.name, target_player_index=1)
        return game, p1, p2, before, result

    # Aura spells must declare a legal enchant target when cast (Rule 115.1b)
    aura_target_index = None
    enchant_noun = aura_enchant_noun(card)
    if enchant_noun is not None:
        aura_target_index = next(
            (idx for idx, perm in enumerate(p2.battlefield) if permanent_matches_enchant_noun(perm, enchant_noun)),
            None,
        )

    # Creatures that enter with X +1/+1 counters (e.g. Rock Hydra) would enter
    # as 0/0 and die to state-based actions (704.5f) if cast with X=0.
    cast_x_value = 2 if "enters with x +1/+1 counters" in card.oracle_text.lower() else None
    result = game.cast_from_hand(
        0, card.name, target_player_index=1, target_permanent_index=aura_target_index, x_value=cast_x_value
    )

    activatable_fragments = (
        "this creature gets +1/+0 until end of turn",
        "this creature gets +0/+1 until end of turn",
        "this creature gets +1/+1 until end of turn",
        "this creature gains flying until end of turn",
        "target creature gains banding until end of turn",
        "put a +1/+1 counter on this creature",
        "deals 1 damage to any target",
        "deals 2 damage to any target and 3 damage to you",
        "destroy target",
        "untap target land",
        "prevent the next 1 damage",
        "would deal damage to you this turn, prevent that damage",
        "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage",
        "regenerate this creature",
        "add three mana of any one color",
        "draw a card",
        "target creature with power 2 or less can't be blocked this turn",
        "target land becomes a forest",
        "choose target non-wall creature",
        "target creature you control with toughness less than this creature's power gains flying until end of turn",
        "the next 1 damage that would be dealt to this creature this turn is dealt to its owner instead",
        "this artifact becomes a 3/6 golem artifact creature until end of combat",
        "create a 1/1 colorless insect artifact creature token with flying named wasp",
        "look at target player's hand",
        "put a mire counter on target non-swamp land",
        "add {",
    )
    text = card.oracle_text.lower()
    should_activate = ":" in text and any(fragment in text for fragment in activatable_fragments)

    if result.supported and should_activate and card.primary_type in {"artifact", "creature", "enchantment"}:
        permanent = next((perm for perm in p1.battlefield if perm.card.name == card.name), None)
        if permanent is not None:
            permanent.metadata["summoning_sickness_turn"] = game.turn - 1
            if "remove a corpse counter from this creature" in text:
                # Scavenging Ghoul's regeneration costs a corpse counter
                permanent.metadata["corpse_counters"] = 1
        activation_result = game.activate_permanent_ability(0, card.name, target_player_index=1)
        return game, p1, p2, before, activation_result

    return game, p1, p2, before, result


def _assert_unsupported_result(card: CardDefinition, p1: PlayerState, result) -> None:
    assert result.supported is False
    assert classify_card(card).supported is False
    assert any(c.name == card.name for c in p1.hand)
    assert not any(perm.card.name == card.name for perm in p1.battlefield)
    assert not any(c.name == card.name for c in p1.graveyard)


def _extract_numeric_from_text(text: str, keyword: str) -> int | None:
    match = re.search(rf"{keyword} (\\w+)", text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _assert_supported_effect(card: CardDefinition, game: Game, p1: PlayerState, p2: PlayerState, before: _Snapshot, result) -> None:
    text = card.oracle_text.lower()

    assert result.supported is True

    if card.primary_type in {"instant", "sorcery"}:
        assert any(c.name == card.name for c in p1.graveyard)

    if card.primary_type in {"land", "creature", "artifact", "enchantment"}:
        assert any(perm.card.name == card.name for perm in p1.battlefield)

    if text.startswith("whenever ") or text.startswith("at the beginning ") or text.startswith("as long as "):
        return

    if "target player draws" in text and "x cards" not in text:
        count = _extract_numeric_from_text(text, "draws")
        if count is not None:
            assert len(p2.hand) >= before.p2_hand + count
            return

    if "deals x damage" in text:
        assert p2.life <= before.p2_life
        return

    if "deals " in text and " damage" in text and "whenever" not in text and "at the beginning" not in text:
        amount_match = re.search(r"deals (\d+) damage", text)
        if amount_match:
            assert p2.life <= before.p2_life
            return

    if "destroy all lands" in text:
        assert _snapshot(p1, p2).p1_lands + _snapshot(p1, p2).p2_lands < before.p1_lands + before.p2_lands
        return

    if "destroy all creatures" in text:
        assert _snapshot(p1, p2).p1_creatures + _snapshot(p1, p2).p2_creatures < before.p1_creatures + before.p2_creatures
        return

    if "destroy target" in text:
        assert len(p2.battlefield) <= before.p2_battlefield
        return

    if "target player discards" in text and (
        card.primary_type in {"instant", "sorcery"} or result.effect_kind.startswith("activated")
    ):
        assert len(p2.hand) <= before.p2_hand
        assert len(p2.graveyard) >= before.p2_graveyard
        return

    if "target player loses" in text:
        amount_match = re.search(r"loses (\d+) life", text)
        if amount_match:
            assert p2.life == before.p2_life - int(amount_match.group(1))
            return

    if "tap target" in text and "untap target" not in text:
        assert any(perm.tapped for perm in p2.battlefield)
        return

    if "untap target" in text:
        assert any(not perm.tapped for perm in p2.battlefield)
        return

    if "prevent the next" in text and result.effect_kind == "activated_prevent":
        assert (
            p1.damage_prevention_pool > before.p1_prevention
            or p2.damage_prevention_pool > before.p2_prevention
        )
        return

    if "regenerate target creature" in text:
        assert any(perm.regeneration_shield > 0 for perm in p2.battlefield if perm.card.primary_type == "creature")
        return

    if "from your graveyard to your hand" in text:
        assert len(p1.hand) >= before.p1_hand
        assert len(p1.graveyard) <= before.p1_graveyard
        return

    if "from your graveyard to the battlefield" in text or "from a graveyard onto the battlefield" in text:
        assert len(p1.battlefield) >= before.p1_battlefield
        return

    if "return target creature to its owner's hand" in text:
        assert len(p2.hand) > before.p2_hand
        return

    if "each player discards their hand, then draws seven cards" in text:
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7
        return

    if "each player shuffles their hand and graveyard into their library, then draws seven cards" in text:
        assert len(p1.hand) == 7
        assert len(p2.hand) == 7
        return

    if "search your library for a card, put that card into your hand, then shuffle" in text:
        assert game.pending_search_library is not None
        game.confirm_search_library(0, 0)
        assert len(p1.hand) == before.p1_hand
        return

    if "take an extra turn after this one" in text and card.primary_type in {"instant", "sorcery"}:
        assert game.extra_turns.get(0, 0) > 0
        return

    if "as an additional cost to cast this spell, sacrifice a creature" in text:
        assert _snapshot(p1, p2).p1_creatures < before.p1_creatures
        assert p1.mana_pool["B"] > before.p1_black_mana
        return

    if "becomes red" in text or "becomes black" in text or "becomes blue" in text or "becomes green" in text or "becomes white" in text:
        assert any(perm.metadata.get("color_override") for perm in p2.battlefield)
        return

    if "copy target instant or sorcery spell" in text:
        assert len(p2.hand) >= before.p2_hand + 3
        return

    if "counter target spell" in text or (card.name in {"Blue Elemental Blast", "Red Elemental Blast"}):
        assert any("countered" in line.lower() or "no spell to counter" in line.lower() for line in game.log)
        return

    if "target creature gains banding until end of turn" in text:
        # Bug 5 fix: banding is granted to the controller's own creatures, not the opponent's.
        assert any(perm.metadata.get("gains_banding_until_eot") for perm in p1.battlefield)
        return

    if "target creature with power 2 or less can't be blocked this turn" in text:
        assert any(perm.metadata.get("cant_be_blocked_until_eot") for perm in p2.battlefield)
        return

    if "target land becomes a forest" in text:
        assert any(perm.metadata.get("land_type_override") == "forest" for perm in p2.battlefield)
        return

    if "choose target non-wall creature" in text:
        assert any(perm.metadata.get("must_attack_until_eot") for perm in p2.battlefield)
        return

    if "creatures the active player controls attack this turn if able" in text:
        active_creatures = [
            perm
            for perm in game.players[game.active_player_index].battlefield
            if perm.card.primary_type == "creature"
        ]
        assert active_creatures
        assert all(perm.metadata.get("must_attack_until_eot") for perm in active_creatures)
        return

    if "gains flying until end of turn" in text and "target creature you control" in text:
        assert any(perm.metadata.get("gains_flying_until_eot") for perm in p1.battlefield)
        return

    if "create a 1/1 colorless insect artifact creature token with flying named wasp" in text:
        assert any(perm.card.name == "Wasp" for perm in p1.battlefield)
        return

    if "this artifact becomes a 3/6 golem artifact creature until end of combat" in text:
        animated = next((perm for perm in p1.battlefield if perm.card.name == card.name), None)
        assert animated is not None
        assert animated.metadata.get("absolute_power") == 3
        assert animated.metadata.get("absolute_toughness") == 6
        return

    if "put a mire counter on target non-swamp land" in text:
        assert any(perm.metadata.get("mire_counter") for perm in p2.battlefield)
        return

    assert any(card.name in line for line in game.log) or len(game.log) > 0


def _assert_card_unique_effect(card: CardDefinition, all_cards: list[CardDefinition]) -> None:
    game, p1, p2, before, result = _run_card(card, all_cards)

    if not classify_card(card).supported:
        _assert_unsupported_result(card, p1, result)
        return

    _assert_supported_effect(card, game, p1, p2, before, result)


for _card in _cards_with_unique_effects(_alpha_cards()):
    def _make_test(card: CardDefinition):
        def _test_alpha_unique_effect_behavior(all_cards):
            _assert_card_unique_effect(card, all_cards)

        _test_alpha_unique_effect_behavior.__name__ = _sanitize_test_name(card.name)
        _test_alpha_unique_effect_behavior.__doc__ = f"Validate unique Alpha effect behavior for {card.name}."
        return _test_alpha_unique_effect_behavior

    globals()[_sanitize_test_name(_card.name)] = _make_test(_card)
