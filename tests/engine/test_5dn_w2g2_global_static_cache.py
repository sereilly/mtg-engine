"""A board-wide static's text-keyed cache holds no compiled answer.

"Each creature you control is a Vampire in addition to its other creature
types and has "Whenever this creature deals damage to a creature, put a +1/+1
counter on this creature."" (Mephidross Vampire.) Whether that quote compiles
is ``granted_abilities.granted_ability_supported`` — a compilation cache,
cleared whenever a piece of the compiler is swapped. ``global_statics``
asked it inside ``_template_match``, an ``lru_cache`` keyed by the text alone,
so the match outlived the answer it was built on: once the grammar was stubbed
(``test_front_end_safety``'s hooks-only compile) the cache handed back the
Vampire's match, the quote no longer compiled, and building the static raised
``TypeError: cannot unpack non-iterable NoneType object`` — in whichever
process had read the line before the stub (Fifth Dawn's wave 2 met it running
``test_static_line_support`` before ``test_front_end_safety`` under
``MTG_PROMOTE=5DN``; the guard over compilation caches reads only the names a
cache's own body calls, and the call was two frames down).

The cache now holds every candidate the text allows and ``global_static_for``
asks the compile-dependent check on each call (``global_statics._compiles``).

Validated backwards: on the tree before the split the second read raises.
"""

from __future__ import annotations

import engine.front_ends as front_ends
from engine.global_statics import global_static_for
from engine.oracle_types import clear_compilation_caches
from tests.passes import rewarm_compile_cache

_VAMPIRE = (
    "Each creature you control is a Vampire in addition to its other creature "
    "types and has \"Whenever this creature deals damage to a creature, put a "
    "+1/+1 counter on this creature.\""
)


def test_a_stubbed_compiler_changes_the_answer_and_raises_nothing():
    live = global_static_for(_VAMPIRE)
    assert live is not None and live.adds_subtypes == ("vampire",)
    assert live.grants_ability.lower().startswith("whenever this creature deals damage")

    original = front_ends._grammar_instruction
    front_ends._grammar_instruction = lambda *args, **kwargs: None
    clear_compilation_caches()
    try:
        # The quote no longer compiles, so the line is no static — and the
        # cached match from the live read above must not be built regardless.
        assert global_static_for(_VAMPIRE) is None
    finally:
        front_ends._grammar_instruction = original
        clear_compilation_caches()
        rewarm_compile_cache()
    assert global_static_for(_VAMPIRE) == live
