"""Every card in the pool resolves without throwing.

Pool-wide, not per-set: it parametrizes over cards/manifest.json, so a
newly ingested set is swept the moment it is added. It lived in
tests/sets/test_lea_cards.py, which is why Arabian Nights went unswept
for as long as it did.
"""

from __future__ import annotations

from engine import Game, PlayerState, classify_card, load_cards
from engine.models import CardDefinition, Permanent
from tests.helpers import (
    _mk_card,
    _mk_creature_card,
    _pass_priority,
    _resolve_top_stack,
    client,
    _get,
)
from tests.sets.lea_helpers import (
    _forest,
    _grizzly,
    _island,
    _mountain,
    _plains,
    _start_session_with_p0_graveyard,
    _swamp,
)


# Cards excluded from the generic sweep below, with the reason each needs
# something the generic setup doesn't provide. Everything else in the catalog
# — new sets included — runs through the sweep automatically.
SWEEP_EXCLUSIONS: set[str] = set()


def pytest_generate_tests(metafunc):
    if "card_name" not in metafunc.fixturenames:
        return
    if metafunc.function is not test_every_catalog_card_resolves_without_exception:
        return
    # The whole manifest catalog, not just LEA. This used to read
    # cards/LEA_cards.json directly, so Arabian Nights — 78 cards, tracked as a
    # complete set — was never swept at all. Driving it from the manifest means
    # a new set is covered the moment it is ingested.
    from engine.card_loader import load_catalog

    names = [c.name for c in load_catalog() if c.name not in SWEEP_EXCLUSIONS]
    metafunc.parametrize("card_name", names)


def test_every_catalog_card_resolves_without_exception(all_cards, catalog_by_name, card_name):
    """Every card in the pool must resolve without throwing a Python exception.

    A smoke test: it does not check the effect in detail. The board it builds is
    LEA scaffolding (basics, a Grizzly Bears, a Black Lotus, a Bad Moon), which
    is deliberately generic — the card under test comes from the full catalog.
    """
    from engine.mixins.stack import aura_enchant_noun, permanent_matches_enchant_noun

    card = catalog_by_name[card_name]
    island = _island(all_cards)
    plains = _plains(all_cards)
    swamp = _swamp(all_cards)
    mountain = _mountain(all_cards)
    forest = _forest(all_cards)
    bear = _grizzly(all_cards)
    bad_moon = _get(all_cards, "Bad Moon")
    black_lotus = _get(all_cards, "Black Lotus")

    p1 = PlayerState(
        name="P1",
        hand=[card],
        library=[island, plains, swamp, mountain, forest] * 4,
        battlefield=[
            Permanent(card=bear),
            Permanent(card=plains),
            Permanent(card=black_lotus),
            Permanent(card=bad_moon),
        ],
        graveyard=[bear],
    )
    p2 = PlayerState(
        name="P2",
        hand=[island, plains, bear],
        library=[island, plains, swamp, mountain, forest] * 4,
        battlefield=[
            Permanent(card=bear, tapped=True),
            Permanent(card=island),
            Permanent(card=black_lotus),
            Permanent(card=bad_moon),
        ],
        graveyard=[bear],
        life=20,
    )

    game = Game(players=[p1, p2])

    # Determine target index for aura spells
    aura_target_idx = None
    enchant_noun = aura_enchant_noun(card)
    if enchant_noun is not None:
        aura_target_idx = next(
            (
                idx
                for idx, perm in enumerate(p2.battlefield)
                if permanent_matches_enchant_noun(perm, enchant_noun)
            ),
            None,
        )

    # Cards requiring special setup
    if card_name == "Camouflage":
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()  # â†’ beginning_of_combat
        game.advance_combat_phase()  # â†’ declare_attackers
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name in {"Counterspell", "Power Sink", "Spell Blast", "Blue Elemental Blast"}:
        bolt = _get(all_cards, "Lightning Bolt")
        p2.hand.append(bolt)
        game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name == "Red Elemental Blast":
        recall = _get(all_cards, "Ancestral Recall")
        p2.hand.append(recall)
        game.queue_from_hand(1, "Ancestral Recall", target_player_index=1)
        game.cast_from_hand(0, card_name, target_player_index=1)
        return

    if card_name == "Fork":
        recall = _get(all_cards, "Ancestral Recall")
        p1.hand.insert(0, recall)
        game.queue_from_hand(0, "Ancestral Recall", target_player_index=1)
        game.cast_from_hand(0, "Fork", target_player_index=1)
        return

    # General cast
    result = game.cast_from_hand(
        0,
        card_name,
        target_player_index=1,
        target_permanent_index=aura_target_idx,
        x_value=3,
    )
    # The call must not raise; result being unsupported is acceptable
    # (some cards may have unmet preconditions in this generic setup)
    assert result is not None
