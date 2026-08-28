"""Every card in the pool resolves without throwing.

Pool-wide, not per-set: it parametrizes over cards/manifest.json, so a
newly ingested set is swept the moment it is added. It lived in
tests/sets/test_lea_cards.py, which is why Arabian Nights went unswept
for as long as it did.

**Both manifest roles**, and that is the whole point of the sweep. It read
``load_catalog()`` — the seam that decides what a player may deck, and so
shipped-only — which meant a set under ``measured`` was swept the moment it was
*promoted*, i.e. after every card in it had already been implemented. The
docstring above promised the opposite and nothing checked the promise, so The
Dark's ingest ran the whole suite green over 119 cards none of it had loaded.
That defeats SET_PLAYBOOK Phase 1's yield step, which is the cheapest
bug-finding moment a set has: a new set's text reaches code the old pool never
executed, and the crashes are worth more before the text work than after.
Reading a card file is not shipping it (CLAUDE.md, "the manifest has two
roles"), and a smoke test that only asks "does this throw" makes no support
claim — so this is the one pool-wide guard that opts in, the same way
``tests/conftest.py``'s ``set_cards`` factory does and for the same reason.
``test_the_sweep_covers_every_measured_set`` below holds it there.
"""

from __future__ import annotations

import pytest

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
    names = [c.name for c in _sweep_pool() if c.name not in SWEEP_EXCLUSIONS]
    metafunc.parametrize("card_name", names)


def _sweep_pool():
    """Every card file the manifest lists, both roles, deduped as usual.

    Not ``load_catalog()``: see the module docstring. A measured set's cards
    must reach this sweep while the set is still being implemented, which is
    the only time the crashes it finds are cheap.
    """
    from engine.card_loader import load_cards, manifest_set_paths

    return load_cards(manifest_set_paths(include_measured=True))


@pytest.fixture(scope="module")
def sweep_by_name():
    """The sweep's pool keyed by name — both manifest roles.

    ``catalog_by_name`` is shipped-only on purpose and is read by guards that
    are making a claim about what ships; this sweep is not one of them.
    """
    return {card.name: card for card in _sweep_pool()}


def test_the_sweep_covers_every_measured_set(sweep_by_name):
    """The sweep's pool includes the measured sets, not just the shipped ones.

    The guard for the bug in the module docstring. Asserting a card count or a
    named card would go stale the moment the pool moved — a set promotes and
    the assertion starts passing for the wrong reason — so this asks the
    manifest what it expects and compares against what the sweep actually
    parametrized over.
    """
    from engine.card_loader import load_cards, manifest_measured_sets, manifest_set_path

    for entry in manifest_measured_sets():
        code = entry["code"]
        cards = load_cards(manifest_set_path(code, include_measured=True))
        missing = [
            c.name for c in cards
            if c.name not in sweep_by_name and c.name not in SWEEP_EXCLUSIONS
        ]
        assert not missing, (
            f"{code} is in the manifest under 'measured' but {len(missing)} of its "
            f"cards never reach the sweep, e.g. {missing[:5]} — Phase 1's yield "
            f"step is running over a pool that does not contain the new set"
        )


def test_every_catalog_card_resolves_without_exception(all_cards, sweep_by_name, card_name):
    """Every card in the pool must resolve without throwing a Python exception.

    A smoke test: it does not check the effect in detail. The board it builds is
    LEA scaffolding (basics, a Grizzly Bears, a Black Lotus, a Bad Moon), which
    is deliberately generic — the card under test comes from the full catalog.
    """
    from engine.mixins.stack import aura_enchant_noun, permanent_matches_enchant_noun

    card = sweep_by_name[card_name]
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
