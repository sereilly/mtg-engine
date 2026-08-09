"""Differential guard: the grammar must agree with the legacy parse rules.

For every line where the grammar's output is *used* and the legacy registry
still has a rule for it, the two are compared instruction for instruction.
Anything that differs must be listed in :data:`ACCEPTED_DIFFS` with a reason
and a named behavioral test pinning the new semantics — divergence has to be a
deliberate, reviewed act rather than an accident.

**The comparison has a shelf life per category.** Once a category's legacy
rules are deleted, whatever broader rule is left behind claims those lines and
drops most of their meaning, so comparing against it measures nothing. Those
categories are listed in :data:`MIGRATED_CATEGORIES` and skipped here; what
guards them instead is the directional whole-program test below (the grammar
may never produce *less* than the legacy engine), the parse-coverage guard with
its deletion probe, and the per-card behavioral tests.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards
from engine.grammar import compile_line
from engine.grammar import behavioural_payload
from engine.oracle import (
    _extract_if_condition,
    _parse_trigger_condition,
    normalize_creature_line,
)
from engine.parsing import parse_primary_instruction

# Categories whose legacy @parse_rule functions have been deleted. Lines the
# grammar claims in these categories are no longer comparable — see the module
# docstring.
MIGRATED_CATEGORIES = frozenset({"damage", "pump", "destruction", "tapping"})

# (card name, oracle line) -> why the grammar deliberately differs.
#
# Every entry names the behavioral test that proves the new lowering is
# correct; without one, a divergence is indistinguishable from a regression.
# Entries retire when their category migrates, since the comparison stops.
_OPTIONAL_KEPT = (
    "The grammar keeps the optionality the legacy rule dropped: it reads "
    '"you may pay {N}. If you do, …" as one decision with a consequence, where '
    "the rule matched only the consequence and made it unconditional. These "
    "cards worked before because a name-keyed hook overrode the compiled "
    "instruction; that hook is now deleted. Behavior pinned by the per-card "
    "tests in tests/regressions/ and tests/sets/test_lea_cards.py."
)

_MANA_PIPS = (
    "The grammar emits the mana as structured pips instead of handing the "
    "handler the clause text to re-read. Same mana produced; one fewer "
    "oracle-text probe inside a handler. Behavior pinned by the per-card mana "
    "tests in tests/sets/test_lea_cards.py."
)

ACCEPTED_DIFFS: dict[tuple[str, str], str] = {
    **{
        (name, line): _MANA_PIPS
        for name, line in (
            ("Basalt Monolith", "{T}: Add {C}{C}{C}."),
            ("Dark Ritual", "Add {B}{B}{B}."),
            ("Llanowar Elves", "{T}: Add {G}."),
            ("Mana Vault", "{T}: Add {C}{C}{C}."),
            ("Mox Emerald", "{T}: Add {G}."),
            ("Mox Jet", "{T}: Add {B}."),
            ("Mox Pearl", "{T}: Add {W}."),
            ("Mox Ruby", "{T}: Add {R}."),
            ("Mox Sapphire", "{T}: Add {U}."),
            ("Sol Ring", "{T}: Add {C}{C}."),
            ("Desert", "{T}: Add {C}."),
            ("Elephant Graveyard", "{T}: Add {C}."),
            ("Library of Alexandria", "{T}: Add {C}."),
        )
    },
    **{
    (name, line): _OPTIONAL_KEPT
    for name, line in (
        ("Crystal Rod", "Whenever a player casts a blue spell, you may pay {1}. If you do, you gain 1 life."),
        ("Iron Star", "Whenever a player casts a red spell, you may pay {1}. If you do, you gain 1 life."),
        ("Ivory Cup", "Whenever a player casts a white spell, you may pay {1}. If you do, you gain 1 life."),
        ("Throne of Bone", "Whenever a player casts a black spell, you may pay {1}. If you do, you gain 1 life."),
        ("Wooden Sphere", "Whenever a player casts a green spell, you may pay {1}. If you do, you gain 1 life."),
        ("Soul Net", "Whenever a creature dies, you may pay {1}. If you do, you gain 1 life."),
        ("Verduran Enchantress", "Whenever you cast an enchantment spell, you may draw a card."),
    )
    },
}


def _legacy_instruction(line: str):
    """What the legacy rule registry produces for one line.

    Mirrors the three classification paths in engine/oracle.py: activated
    ability (text right of the colon), triggered ability (remainder after the
    trigger clause), or a plain effect line.
    """
    normalized = normalize_creature_line(line)
    if ":" in normalized:
        effect = normalized.split(":", 1)[1].strip()
        return parse_primary_instruction(effect, activated=True)[0]
    condition, remainder = _parse_trigger_condition(normalized)
    if condition is not None:
        _, clean = _extract_if_condition(remainder.lstrip(": "))
        return parse_primary_instruction(clean, activated=False)[0]
    return parse_primary_instruction(normalized, activated=False)[0]


def _pool(all_set_paths):
    return load_cards([str(path) for path in all_set_paths])


def _grammar_lines(all_set_paths):
    """Every (card, line, instructions) still comparable against legacy rules.

    Lines whose categories have all migrated are skipped: their legacy rules
    are gone, so there is nothing meaningful left to compare against.
    """
    for card in _pool(all_set_paths):
        for raw in (card.oracle_text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            result = compile_line(line, card_name=card.name)
            if not result.usable or result.categories <= MIGRATED_CATEGORIES:
                continue
            yield card.name, line, result.instructions


def test_grammar_agrees_with_legacy_rules(all_set_paths):
    """Every executed line either matches the legacy instruction exactly or is
    an accepted, documented divergence."""
    unexplained: list[str] = []
    for name, line, instructions in _grammar_lines(all_set_paths):
        legacy = _legacy_instruction(line)
        if legacy is None:
            continue  # newly supported: nothing to disagree with
        matches = (
            len(instructions) == 1
            and instructions[0].kind == legacy.kind
            and behavioural_payload(instructions[0].payload)
            == behavioural_payload(legacy.payload)
        )
        if matches or (name, line) in ACCEPTED_DIFFS:
            continue
        rendered = ", ".join(f"{i.kind}{i.payload}" for i in instructions)
        unexplained.append(
            f"{name}: {line}\n    legacy : {legacy.kind}{legacy.payload}\n    grammar: {rendered}"
        )

    assert not unexplained, (
        "grammar diverged from the legacy rules without an ACCEPTED_DIFFS entry:\n"
        + "\n".join(unexplained)
    )


def test_accepted_diffs_are_all_still_diverging(all_set_paths):
    """A stale entry means the divergence was resolved and the exemption should
    be deleted — the ratchet only tightens."""
    live = set()
    for name, line, instructions in _grammar_lines(all_set_paths):
        legacy = _legacy_instruction(line)
        if legacy is None:
            continue
        matches = (
            len(instructions) == 1
            and instructions[0].kind == legacy.kind
            and behavioural_payload(instructions[0].payload)
            == behavioural_payload(legacy.payload)
        )
        if not matches:
            live.add((name, line))

    stale = set(ACCEPTED_DIFFS) - live
    assert not stale, f"stale ACCEPTED_DIFFS entries, delete them: {sorted(stale)}"


def test_every_accepted_diff_explains_itself():
    for key, reason in ACCEPTED_DIFFS.items():
        assert len(reason) > 40, f"{key} needs a real explanation"
        assert "test" in reason.lower(), f"{key} must name the test pinning the new behavior"


def test_grammar_never_silently_drops_a_supported_card(all_set_paths):
    """Turning the grammar on must not make any card unsupported: a grammar
    failure falls back to the legacy rules, never to nothing."""
    from engine.oracle import compile_card_oracle

    unsupported = [
        card.name for card in _pool(all_set_paths) if not compile_card_oracle(card).supported
    ]
    assert not unsupported, f"cards became unsupported: {unsupported}"


def _compile_pool(cards):
    from engine.oracle import _compile_card_oracle, compile_card_oracle

    _compile_card_oracle.cache_clear()
    programs = {card.name: compile_card_oracle(card) for card in cards}
    _compile_card_oracle.cache_clear()
    return programs


def test_turning_the_grammar_off_only_ever_loses_capability(all_set_paths, monkeypatch):
    """Whole-program guard: compile the pool with the grammar gate on and off.

    Catches a bug class the per-line comparison cannot: a line the grammar
    parses correctly can still land in the wrong part of the program. Hoisting
    an activated ability's effect into the card-level instruction list, for
    instance, would make casting an Aura immediately perform its activated
    ability, and every individual line would still look right.

    The assertion is directional rather than an equality, because legacy rules
    are being deleted as categories migrate. Once a rule is gone the legacy-only
    engine is strictly weaker there, so a difference is expected — what must
    never happen is the reverse: legacy alone producing *more* than the grammar,
    which would mean the grammar had taken over a line and dropped part of it.
    """
    import engine.grammar as grammar

    cards = _pool(all_set_paths)
    with_grammar = _compile_pool(cards)
    monkeypatch.setattr(grammar, "GRAMMAR_CATEGORIES", frozenset())
    without_grammar = _compile_pool(cards)

    accepted = {name for name, _ in ACCEPTED_DIFFS}
    regressions: list[str] = []
    for name, program in with_grammar.items():
        legacy = without_grammar[name]
        if program == legacy or name in accepted:
            continue
        if legacy.supported and not program.supported:
            regressions.append(f"{name}: supported only without the grammar")
        elif len(legacy.instructions) > len(program.instructions):
            regressions.append(
                f"{name}: legacy produced {len(legacy.instructions)} instructions, "
                f"grammar {len(program.instructions)}"
            )

    assert not regressions, "the grammar lost capability the legacy rules had:\n" + "\n".join(
        regressions
    )


def test_grammar_is_load_bearing_for_migrated_categories(all_set_paths, monkeypatch):
    """Deleting a category's legacy rules must actually have happened.

    With the grammar switched off, cards whose rules were removed can no longer
    compile the same way. If this finds nothing, either no rules were deleted or
    the grammar is not being used — both of which would make the ratchet a
    fiction.
    """
    import engine.grammar as grammar

    cards = _pool(all_set_paths)
    with_grammar = _compile_pool(cards)
    monkeypatch.setattr(grammar, "GRAMMAR_CATEGORIES", frozenset())
    without_grammar = _compile_pool(cards)

    depend_on_grammar = [
        name for name, program in with_grammar.items()
        if program != without_grammar[name]
    ]
    assert len(depend_on_grammar) > len(ACCEPTED_DIFFS), (
        "no card depends on the grammar beyond the accepted divergences — "
        "the migration is not actually live"
    )


@pytest.mark.parametrize("seed", [1, 7])
def test_grammar_compilation_is_deterministic(all_set_paths, seed):
    """Compiling twice yields identical programs. Parsing must stay a pure
    function of the text — the AI-behavior regression tests depend on a given
    seed reproducing a run exactly."""
    from engine.oracle import compile_card_oracle

    cards = _pool(all_set_paths)
    first = [compile_card_oracle(card) for card in cards]
    second = [compile_card_oracle(card) for card in cards]
    assert first == second
