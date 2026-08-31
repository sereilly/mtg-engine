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
from engine.oracle_types import clear_compilation_caches


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
    """Both readings of the pool, and the swap put back exactly as it was.

    ``clear_compilation_caches`` rather than ``_compile_card_oracle.cache_clear``:
    three more caches hold answers the compiler produced, and with the grammar
    stubbed out they cache what the *hooks alone* said. The one that collected
    was ``granted_abilities.granted_ability_supported``, which compiles a
    granted ability's quoted text on a probe card — stubbed, it answered False
    for every grant in the pool and kept that answer afterwards, so Dread Wight
    and Musician reported their granted lines unreadable for the rest of the
    process. The failure surfaced in ``test_parse_coverage.py``, a different
    file entirely: a stale cache does not fail where it is written, which is why
    the reversibility is asserted below rather than trusted.
    """
    cards = load_catalog()
    live = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    original = oracle._grammar_instruction
    oracle._grammar_instruction = lambda *args, **kwargs: None
    clear_compilation_caches()
    try:
        hooks_only = {c.name: _kinds(oracle.compile_card_oracle(c)) for c in cards}
    finally:
        oracle._grammar_instruction = original
        clear_compilation_caches()
    return live, hooks_only


#: The compiler entry points a cache's body names when its values are compiled
#: answers. Not a list of caches — a list of the *functions a compiled answer
#: comes out of*, which is what makes the sweep below derive its expectation
#: instead of restating it.
_COMPILER_ENTRY_POINTS = frozenset({
    "compile_card_oracle", "_compile_card_oracle", "expand_ability_lines",
    "_parse_triggered_ability", "compile_line", "parse_line",
})


def _reaches_the_compiler(func) -> bool:
    """Whether *func*'s body (nested code objects included) names one."""
    code = getattr(func, "__code__", None)
    if code is None:
        return False
    names: set[str] = set()
    stack = [code]
    while stack:
        current = stack.pop()
        names |= set(current.co_names)
        stack += [c for c in current.co_consts if hasattr(c, "co_names")]
    return bool(names & _COMPILER_ENTRY_POINTS)


def _engine_lru_caches():
    """Every ``lru_cache``d function reachable from ``engine``, once each."""
    import importlib
    import pkgutil

    import engine

    modules = [engine]
    for found in pkgutil.walk_packages(engine.__path__, "engine."):
        try:
            modules.append(importlib.import_module(found.name))
        except Exception:  # a module that needs a game to import is not a cache
            continue
    seen = {}
    for module in modules:
        for name, obj in vars(module).items():
            wrapped = getattr(obj, "__wrapped__", None)
            if wrapped is None or not hasattr(obj, "cache_clear"):
                continue
            seen.setdefault((wrapped.__module__, wrapped.__qualname__), obj)
    return seen


def test_every_cache_holding_a_compiled_answer_is_registered_for_clearing():
    """The completeness half of ``clear_compilation_caches`` (engine/oracle_types.py).

    The fixture above stubs the grammar out and puts it back, and that is only
    reversible if every cache holding a *compiled* answer is emptied on both
    edges. ``granted_abilities.granted_ability_supported`` was not, and the way
    it failed is why this guard derives its expectation rather than listing the
    caches: with the stub in, the pool's compile asked it two questions the live
    pool had never asked — the lowercased, period-stripped forms of Dread
    Wight's and Musician's granted lines — and cached **False** for both. The
    live answers were still cached under their own keys, so every compiled
    program came back identical and nothing looked wrong; the two poisoned keys
    were the ones ``scripts/parse_coverage.py`` asks, and the failure surfaced
    hundreds of tests later in a different file as two unclaimed sentences.

    So a guard comparing programs across the swap cannot see this — verified by
    writing one first and watching it pass. What is checkable is the property
    the fix rests on: a cache whose body reaches the compiler must be
    registered. Derived by scanning the bytecode of every ``lru_cache``d
    function in ``engine/``, so the *fifth* such cache is caught by whoever
    writes it rather than by whoever remembers this comment.
    """
    from engine.oracle_types import _COMPILATION_CACHES

    # The walk imports modules, and importing one is what runs its
    # ``@compilation_cache``. So the sweep runs *first* and the registry is read
    # after it — the other order reads a registry the walk is about to add to,
    # and reports every not-yet-imported cache as unregistered.
    caches = _engine_lru_caches()
    registered = {
        (f.__wrapped__.__module__, f.__wrapped__.__qualname__)
        for f in _COMPILATION_CACHES
    }
    unregistered = sorted(
        key for key, cached in caches.items()
        if _reaches_the_compiler(cached.__wrapped__) and key not in registered
    )

    assert not unregistered, (
        "these caches hold answers the compiler produced but are not registered "
        "with @compilation_cache, so `clear_compilation_caches()` leaves them "
        f"holding whatever a stubbed compiler said: {unregistered}"
    )


def test_the_registered_caches_are_all_still_compiler_caches():
    """The other direction, so a cache that stops calling the compiler does not
    keep the decorator forever — the stale-acknowledgement shape this repo
    fails on everywhere else."""
    from engine.oracle_types import _COMPILATION_CACHES

    assert _COMPILATION_CACHES, "an empty registry clears nothing"
    stale = sorted(
        f"{f.__wrapped__.__module__}.{f.__wrapped__.__qualname__}"
        for f in _COMPILATION_CACHES
        if not _reaches_the_compiler(f.__wrapped__)
    )

    assert not stale, f"registered but no longer compiler-derived: {stale}"


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
    clear_compilation_caches()
    programs = {card.name: oracle.compile_card_oracle(card) for card in cards}
    clear_compilation_caches()
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
