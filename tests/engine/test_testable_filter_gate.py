"""Guard: "can this be tested?" is asked in one place, and it recurses.

``TESTABLE_SUBJECT_FILTER_KEYS`` is what a compiler admits a narrowed line on.
A key outside it is a narrowing the matcher cannot answer, so a payload
carrying one is a restriction the dispatcher silently ignores — and an ignored
restriction is not a card doing less, it is an effect reaching a strictly
larger set than the card prints. That is the one thing this engine must never
do, which is why the check exists at all.

The check was **copied**, forty times. ``set(payload) -
TESTABLE_SUBJECT_FILTER_KEYS`` is a flat difference; the matcher is not flat.
``attached_to_filter`` and ``controller_controls`` each carry a whole noun
phrase inside a key, so "Auras attached to permanents you control" answers
"testable" to the flat form whatever the inner phrase says — one testable
outer key, the seat dropped, and a destroy sweep that takes every Aura on the
table. ``subject_filters.untestable_filter_keys`` was written one round earlier
to close exactly that hole, in modules that then kept the flat spelling.

Wave 2 of Visions folded the four copies in ``lowering/prevention.py`` and
found that two of them had already drifted. Wave 4 folded the remaining
**forty sites across twenty-one files** — eighteen ``lowering/`` modules plus
``engine/oracle.py`` (twice), ``engine/cost_modifiers.py`` and
``engine/enter_tapped_statics.py``, which the standing note had not counted
because it looked only at ``lowering/``. None of them changed an answer on
today's pool: 1,431 calls over 4,085 printings, zero disagreements between the
flat form and the recursive one. The debt was latent, not live, which is the
only reason forty copies could stay correct for as long as they did — and
exactly why a swept-once fix would not hold.

So the sweep is replaced by an invariant. The key set is **named in code** in
the two modules that own the question and nowhere else: it is defined in
``engine/subject_filters.py`` beside the matcher that answers it, and it is
read in ``engine/grammar/lowering/_filters.py`` as the default *allowed* set of
the two helpers every caller now goes through. A forty-first flat spelling
fails here rather than waiting for the set that prints the nested phrase.

Prose is not code: this file tokenizes, so a comment or a docstring naming the
constant — and there are a dozen, each explaining why its lowering gates on it
-- is untouched. What fails is *using* the name outside its two homes.
"""

from __future__ import annotations

import io
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

KEYS = "TESTABLE_SUBJECT_FILTER_KEYS"

#: The two modules that may name the key set in code, and what each does with
#: it. Not a list of exceptions that grew — it is the whole ownership of the
#: question, and :func:`test_both_owners_really_own_it` below fails if either
#: stops holding up its end, so the pair cannot quietly become a list.
OWNERS = {
    # Defines it, next to ``subject_matches``, the matcher whose answers it is
    # the set of.
    "engine/subject_filters.py",
    # Reads it as the default *allowed* set of ``testable_filter_payload`` and
    # ``refuse_untestable`` — the two helpers every lowering asks.
    "engine/grammar/lowering/_filters.py",
}


def _source_files() -> list[Path]:
    return sorted(
        p
        for base in ("engine", "web")
        for p in (ROOT / base).rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _names_in_code(path: Path) -> list[int]:
    """Line numbers where *path* uses :data:`KEYS` as a code token.

    Tokenizing rather than grepping is the whole point: the constant is
    discussed in a dozen comments and docstrings that should stay, and a
    substring scan cannot tell those from a use.
    """
    src = path.read_bytes().decode("utf-8")
    return [
        tok.start[0]
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type == tokenize.NAME and tok.string == KEYS
    ]


def test_the_testable_key_set_is_named_in_code_in_two_places():
    """No third module asks "are all these keys testable?" for itself."""
    offenders = {}
    for path in _source_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in OWNERS:
            continue
        lines = _names_in_code(path)
        if lines:
            offenders[rel] = lines
    assert not offenders, (
        "these modules name %s in code instead of going through "
        "lowering/_filters.testable_filter_payload (build a payload from a "
        "noun phrase and check it) or refuse_untestable (check a payload you "
        "built yourself). A hand-written set difference is flat, and the "
        "matcher is not: a nested noun phrase under attached_to_filter or "
        "controller_controls answers 'testable' whatever it says, and the "
        "dropped narrowing widens the effect. Offenders: %r" % (KEYS, offenders)
    )


def test_both_owners_really_own_it():
    """The two allowed modules hold the halves this guard claims they hold."""
    from engine import subject_filters
    from engine.grammar.lowering import _filters

    assert isinstance(subject_filters.TESTABLE_SUBJECT_FILTER_KEYS, frozenset)
    assert callable(subject_filters.untestable_filter_keys)
    assert callable(_filters.testable_filter_payload)
    assert callable(_filters.refuse_untestable)
    for rel in OWNERS:
        assert _names_in_code(ROOT / rel), (
            "%s is allowed to name %s and does not — the allow-list has "
            "outlived one of its entries" % (rel, KEYS)
        )


def test_the_shared_question_recurses_where_a_flat_difference_cannot():
    """The reason the fold was worth doing, asserted rather than described.

    A flat ``set(payload) - TESTABLE_SUBJECT_FILTER_KEYS`` sees one key here and
    calls the phrase testable. The real question looks inside.
    """
    from engine.subject_filters import (TESTABLE_SUBJECT_FILTER_KEYS,
                                        untestable_filter_keys)

    inner_key = "no_matcher_answers_this"
    assert inner_key not in TESTABLE_SUBJECT_FILTER_KEYS
    nested = {"type_filter": "enchantment", "attached_to_filter": {inner_key: True}}

    assert set(nested) - TESTABLE_SUBJECT_FILTER_KEYS == set()
    assert untestable_filter_keys(nested) == {"attached_to_filter"}


def test_the_shared_refusal_names_the_key_that_caused_it():
    """A refusal that names the missing piece is a mechanism, not an absence."""
    from engine.grammar.errors import LoweringError
    from engine.grammar.lowering._filters import refuse_untestable

    payload = {"attached_to_filter": {"no_matcher_answers_this": True}}
    with pytest.raises(LoweringError) as excinfo:
        refuse_untestable(payload, refusal="the sweep cannot narrow by")
    assert "the sweep cannot narrow by" in str(excinfo.value)
    assert "attached_to_filter" in str(excinfo.value)
