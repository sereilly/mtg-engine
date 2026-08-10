"""Guard: a grammar production must never take a line over and say *less*.

`engine/oracle.py` reads a line through two front ends in order — the grammar,
then `card_hooks.CARD_LINE_INSTRUCTIONS` — and the first that claims it wins. So
a production that learns to read a hooked line *silently replaces* that hook.
`tests/engine/test_card_lines.py` catches the resulting dead entry; it does not
catch the case that matters more, where the production reads the line but reads
less of it than the hook's handler implemented. The card still compiles, still
reports `supported`, and quietly loses an effect.

This compiles the whole pool twice — once with `_grammar_instruction` stubbed,
leaving only the hooks — and fails on any card that loses an instruction kind
when the grammar is switched on.

**This file was `test_grammar_fallback_safety.py`, and the deletion of
`engine/parsing/` changed what it measures rather than emptying it.** The old
baseline was "the legacy rule registry alone", and the hazard was the compiler's
per-card fallback: one grammar production claiming one line suppressed the
legacy reading of *every* line. That fallback is gone with the registry — the
instruction list is assembled per line now, and there is no whole-text pass
underneath. What is left is the narrower hazard above, which is not gone and is
not prevented by anything in the parser: it has been avoided so far only by
authors being careful, which is not a mechanism.
"""

import pytest

import engine.oracle as oracle
from engine.card_loader import load_catalog


# Cards where a grammar production deliberately replaces a card hook's kind with
# a better one. Each entry is a real improvement, not a loss — verify before
# extending.
#
# Empty, and that is the expected steady state: a hook whose line the grammar
# has learned to read is a *dead* hook, and test_card_lines.py fails on those
# before this guard ever sees them. An entry here means a hook that is still
# load-bearing for one kind while the grammar claims the line for another, which
# is a shape worth a written reason.
#
# The five entries that stood here (Earthquake, Hurricane, Sandstorm,
# Pestilence, Cuombajj Witches, Ley Druid) were all the same thing: a legacy
# *category whose rules had been deleted* left behind a broad rule that still
# claimed the line and dropped most of its meaning, and the grammar routed it to
# the handler implementing the whole sentence. With the registry gone there is
# no broad rule left to improve on, so they are not divergences any more.
ACCEPTED_REPLACEMENTS: dict[str, str] = {}


# Payload keys under which engine/handlers/control_flow.py carries nested steps.
# A composed effect keeps its parts here, so a comparison that reads only the
# top level sees composition as deletion.
_NESTED_STEP_KEYS = ("steps", "then", "else", "action", "otherwise", "effect")


def _flatten(instructions):
    for instruction in instructions:
        yield instruction
        for key in _NESTED_STEP_KEYS:
            yield from _flatten(instruction.payload.get(key) or ())


def _kinds(program) -> set[str]:
    """Executable instruction kinds — `spell_pattern` is a whitelist marker, not
    behaviour, so it is excluded.

    Nested steps count. The grammar's whole point is that effects *compose*
    (ROADMAP "Effects could not compose"), so "you may pay {1}. If you do, you
    gain 1 life" lowers to `may` wrapping the `target_gains_life` a flat rule
    emitted bare and unconditional. Reading only the top level would score that
    wrapping as a deleted life gain — the guard reporting the migration's
    central mechanism as the bug class it exists to catch.
    """
    return {i.kind for i in _flatten(program.instructions) if i.kind != "spell_pattern"}


@pytest.fixture(scope="module")
def with_and_without_grammar():
    cards = load_catalog()
    live = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    original = oracle._grammar_instruction
    oracle._grammar_instruction = lambda *args, **kwargs: None
    oracle._compile_card_oracle.cache_clear()
    try:
        hooks_only = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    finally:
        oracle._grammar_instruction = original
        oracle._compile_card_oracle.cache_clear()
    return live, hooks_only


def test_no_card_silently_loses_an_instruction_to_the_grammar(with_and_without_grammar):
    """A card that compiles to fewer effects with the grammar on has lost one.
    It still reports supported, so only this catches it."""
    live, hooks_only = with_and_without_grammar
    unexpected = []
    for name, hook_kinds in hooks_only.items():
        missing = hook_kinds - live[name]
        if not missing:
            continue
        accepted = ACCEPTED_REPLACEMENTS.get(name)
        if accepted is not None and missing == {accepted}:
            continue
        unexpected.append((name, sorted(missing), sorted(live[name])))

    assert not unexpected, (
        "enabling the grammar dropped instructions these cards had from their "
        "card hooks. If the replacement is a deliberate improvement, add it to "
        f"ACCEPTED_REPLACEMENTS with the reason: {unexpected}"
    )


def test_accepted_replacements_are_all_still_happening(with_and_without_grammar):
    """A stale entry hides a card that has quietly stopped being improved."""
    live, hooks_only = with_and_without_grammar
    stale = [
        name for name, kind in ACCEPTED_REPLACEMENTS.items()
        if kind not in hooks_only.get(name, set()) - live.get(name, set())
    ]

    assert not stale, f"ACCEPTED_REPLACEMENTS entries that no longer occur: {stale}"


def test_the_grammar_is_what_reads_most_of_the_pool(with_and_without_grammar):
    """Without this the guard above could pass by the grammar doing nothing.

    Stubbing the front end that reads most of the pool's lines has to cost most
    of the pool its instructions; if it does not, `_grammar_instruction` is no
    longer the function being stubbed and the comparison is between two
    identical compiles.

    (This is what `test_grammar_differential.py`'s
    ``test_grammar_is_load_bearing_for_migrated_categories`` asserted, stated
    against the front end rather than against the migration's category list.)
    """
    live, hooks_only = with_and_without_grammar
    weakened = [name for name in live if hooks_only[name] < live[name]]
    assert len(weakened) > 100, (
        "stubbing the grammar barely changed the pool — this guard is comparing "
        f"a compile against itself (only {len(weakened)} cards weakened)"
    )


def test_every_card_in_the_pool_is_supported():
    """The pool's headline claim, asserted rather than reported.

    `scripts/support_report.py` prints it; nothing failed on it. A card that
    stops compiling is the loud failure the parser is designed to produce, and
    this is what makes it loud in CI rather than in a report somebody reads.
    """
    unsupported = [
        (card.name, oracle.compile_card_oracle(card).reason)
        for card in load_catalog()
        if not oracle.compile_card_oracle(card).supported
    ]
    assert not unsupported, f"cards no front end reads: {unsupported}"


def _compile_pool(cards):
    oracle._compile_card_oracle.cache_clear()
    programs = {card.name: oracle.compile_card_oracle(card) for card in cards}
    oracle._compile_card_oracle.cache_clear()
    return programs


# A spell carrying an ability line. Both front ends have a half of the gate that
# keeps such a line out of the list an instant or sorcery *resolves*, and no card
# in the pool has one — so the shape is written here rather than swept for.
#
# `test_grammar_differential.py` claimed this ground with a directional
# comparison of instruction *counts* between two compiles, and a pool sweep
# replacing it was no better. Both were verified by injection and neither fired:
# removing the gate makes the grammar side produce *more*, which a "the other
# side must not produce more" assertion is blind to, and the pool contains zero
# instants or sorceries with an ability line for a sweep to find.
_HOISTS = (
    # The grammar's half: the node is an ActivatedAbilityNode, not a
    # SpellEffectLine, and `spell_line_only` drops it.
    ("Hoist Test", "Draw a card.\n{2}: Target player mills two cards.",
     "draw_controller_cards", "mill_target_player"),
    # The card hooks' half, which asks the same question of the raw text
    # (`_is_ability_line`). Keyed on a real hooked (name, line) pair, because
    # that registry is a lookup and an invented one would never fire.
    ("Jandor's Saddlebags", "Draw a card.\n{3}, {T}: Untap target creature.",
     "draw_controller_cards", "untap_target_permanent"),
)


@pytest.mark.parametrize("name,text,spell_kind,ability_kind", _HOISTS)
def test_an_ability_effect_never_reaches_the_list_a_spell_resolves(
    name, text, spell_kind, ability_kind
):
    """Where a claimed line *lands*, not just whether it was claimed.

    A line the parser reads correctly can still end up in the wrong part of the
    program: an activated ability's effect reaching the instruction list an
    instant or sorcery **resolves**, which makes the spell perform the ability
    when it resolves. Every individual line still looks right, the card
    compiles, and nothing else notices.

    (A permanent's card-level list is a mirror rather than a program:
    `_resolve_card` returns before `_apply_spell_text`, so the same hoist is
    inert there — which is why the gate applies to instants and sorceries only,
    and why this test does too.)
    """
    from engine.models import CardDefinition

    card = CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Instant", oracle_text=text,
        colors=("U",), color_identity=("U",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Instant"},
    )
    program = oracle.compile_card_oracle(card)
    kinds = [i.kind for i in program.instructions]

    assert spell_kind in kinds, f"the plain effect line was dropped: {kinds}"
    assert ability_kind not in kinds, (
        "an ability line's instruction reached the list this spell resolves, so "
        f"casting it performs the ability: {kinds}"
    )
    # The ability itself is still compiled — it is kept out of the *spell's*
    # program, not thrown away.
    assert [a.instruction.kind for a in program.activated_abilities] == [ability_kind]


# `test_the_grammar_never_produces_less_than_the_card_hooks` stood here — the
# directional whole-program comparison inherited from the differential guard
# ("the weaker front end must never produce *more*"). **Retired deliberately: it
# could no longer fail.**
#
# It was written when the compiler had a per-card fallback that collapsed a
# card's whole text to one string, so switching the grammar off could genuinely
# produce a different *number* of instructions. The list is assembled per line
# now, and each line yields exactly one instruction whichever front end claims
# it — so the hooks-only compile can only ever have *fewer*, never more, and the
# assertion is structurally unreachable. Three injections were tried against it
# (a hook out-producing the grammar, the gate above removed, a production
# refusing a hooked line) and it stayed green for all three, while
# `test_no_card_silently_loses_an_instruction_to_the_grammar` caught the first
# and the parametrized test above catches the second.


@pytest.mark.parametrize("seed", [1, 7])
def test_grammar_compilation_is_deterministic(seed):
    """Compiling twice yields identical programs. Parsing must stay a pure
    function of the text — the AI-behavior regression tests depend on a given
    seed reproducing a run exactly."""
    cards = load_catalog()
    first = [oracle.compile_card_oracle(card) for card in cards]
    second = [oracle.compile_card_oracle(card) for card in cards]
    assert first == second
