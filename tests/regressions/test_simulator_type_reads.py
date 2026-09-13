"""The AI simulator's honesty checks ask CR 205.2b, not ``primary_type``.

Found at Mercadian Masques' Phase 5, by the one step that finds this class:
`simulate_ai_games.py --set MMQ` reported

    Game 9, Turn 15: Disenchant did not destroy one target artifact or
    enchantment

on a game whose own log read ``Destroyed Toymaker`` one line earlier. Toymaker
is an **Artifact Creature -- Spellshaper**, and ``CardDefinition.primary_type``
returns the *first* of ``land, creature, artifact, ...`` in the type line -- so
the destroyed permanent was in neither the before count nor the after count,
the total looked unchanged, and the check fired.

**The engine was right and the instrument was lying**, which is the expensive
direction: a false issue costs an investigation, and an honesty check nobody
trusts is an honesty check nobody reads. CLAUDE.md records this class from
Weatherlight ("77 artifact creatures answer 'creature' to a reader asking
'artifact'... every 'creature' reader was right by accident and every 'artifact'
reader was wrong") and the sweep that closed it did not reach
``engine/ai_simulator.py``. The population is now 114 and grows with the pool.

Both checks are pinned, not just the broken one: Unsummon's twin was correct
only because no land creature exists in this pool.
"""

from engine.card_loader import load_cards, manifest_set_paths
from engine.search_filters import card_has_type


def _artifact_or_enchantment(card) -> bool:
    return card_has_type(card, "artifact") or card_has_type(card, "enchantment")


def test_an_artifact_creature_counts_as_an_artifact_for_the_disenchant_check(catalog):
    """The card the finding was made on, by name."""
    toymaker = next(c for c in catalog if c.name == "Toymaker")
    assert "artifact creature" in toymaker.type_line.lower()
    assert _artifact_or_enchantment(toymaker), (
        "Toymaker is a legal Disenchant target; a check that misses it reports "
        "a destruction that happened as one that did not"
    )
    # The read that was wrong, asserted as wrong so the fix cannot be reverted
    # to it quietly.
    assert toymaker.primary_type == "creature"


def test_every_artifact_creature_in_the_pool_reads_as_an_artifact(catalog):
    """The population, so the guard fails on the class rather than on one card."""
    both = [
        c for c in catalog
        if card_has_type(c, "artifact") and card_has_type(c, "creature")
    ]
    assert len(both) >= 100, (
        f"only {len(both)} artifact creatures found — the sweep examined too "
        "little to mean anything"
    )
    missed = [c.name for c in both if c.primary_type == "artifact"]
    assert not missed, (
        "these read 'artifact' from primary_type, so the accident this guard "
        f"documents does not hold for them and its reasoning needs re-reading: {missed}"
    )
    assert all(_artifact_or_enchantment(c) for c in both)


def test_the_simulator_does_not_ask_primary_type_about_a_card_type():
    """The site, not just the answer.

    A count rebuilt from ``primary_type`` would pass both tests above while
    reintroducing the defect, because those ask the accessor rather than the
    caller.

    Tokenized rather than grepped, for the reason
    ``test_testable_filter_gate.py`` gives one guard over: the comments
    explaining *why* this read is wrong name the field repeatedly, and a guard
    that failed on its own explanation would be deleted rather than obeyed.
    What fails is **using** the name.
    """
    import inspect
    import io as _io
    import tokenize

    from engine import ai_simulator

    source = inspect.getsource(ai_simulator._assert_expected)
    used = [
        token
        for token in tokenize.generate_tokens(_io.StringIO(source).readline)
        if token.type == tokenize.NAME and token.string == "primary_type"
    ]
    assert not used, (
        "the simulator's honesty checks read a card type through primary_type "
        f"again, at line(s) {[t.start[0] for t in used]} of _assert_expected — "
        "CR 205.2b says a card has every type its line names, and "
        "search_filters.card_has_type is the one reader of that question"
    )
