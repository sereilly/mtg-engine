"""Guard: there is one keyword registry, and the gate reads it.

`engine/grammar/vocabulary.py`'s ``IMPLEMENTED_KEYWORDS`` is the list of keyword
abilities the engine actually implements. Two different questions consult it and
they have to agree:

* **may this printed line be admitted?** — `engine/oracle.py`'s keyword-line
  classifier, deciding whether a creature whose text is "Vigilance" is supported;
* **may this keyword be lowered?** — the grammar, refusing to compile a grant of
  a keyword whose behaviour does not exist.

Until this test existed the first question was answered by a *second* list
spelled out in `oracle.py` — seventeen Title Case strings beside seventeen
lowercase ones, held equal by hand and compared by nothing.

**Both ways of getting it wrong are silent**, which is why a behavioural guard
is the one worth having. Add a keyword to the grammar's list alone and nothing
happens at all: the card stays unsupported, naming the keyword line as too
complex, and the full suite stays green — that is exactly what a lifelink
experiment did, 4,458 tests passing over an edit that did nothing. Add it to
`oracle.py`'s list alone and the card is admitted while the behaviour behind it
is missing, which is the silent-wrongness invariant (a card may fail loudly; it
may never resolve as something other than what it says).

So the tests below do not compare two lists — comparing them is what a future
second copy would also pass. They check that the *behaviour* of the gate is
derived from the registry: every implemented keyword is admitted, and a real
Magic keyword that is not implemented is refused.
"""

from __future__ import annotations

import pytest

from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS, KEYWORD_ABILITIES
from engine.oracle import _is_supported_keyword_line, compile_card_oracle

from tests.helpers import _mk_creature_card


@pytest.mark.parametrize("keyword", sorted(IMPLEMENTED_KEYWORDS))
def test_every_implemented_keyword_is_admitted_as_a_printed_line(keyword):
    """The direction that fails silently by doing nothing.

    A keyword the engine implements but the line classifier refuses costs every
    creature printed with it, and costs it invisibly — the card reports
    "creature text too complex" naming a keyword the engine has, and no test
    anywhere disagrees.
    """
    assert _is_supported_keyword_line(keyword), (
        f"{keyword!r} is in IMPLEMENTED_KEYWORDS but the keyword-line gate "
        "refuses it; the gate must read the registry, not a copy of it"
    )


@pytest.mark.parametrize("keyword", sorted(IMPLEMENTED_KEYWORDS))
def test_a_creature_whose_whole_text_is_one_keyword_compiles_supported(keyword):
    """End to end, because the gate is only half the path.

    `_is_supported_keyword_line` admitting the line is not the same as the card
    compiling — this is the assertion that the registry buys a playable card
    rather than a passing predicate.
    """
    card = _mk_creature_card(f"Keyword Test {keyword}", 2, 2, oracle_text=keyword.title())
    assert compile_card_oracle(card).supported, (
        f"a 2/2 whose only printed text is {keyword.title()!r} compiles unsupported"
    )


def test_keyword_lines_combine():
    """Printed keyword lines are comma-joined ("Vigilance, trample")."""
    assert _is_supported_keyword_line("Flying, trample")
    assert _is_supported_keyword_line("first strike, vigilance, haste")


# Real keyword abilities in the Scryfall catalog that the engine does not
# implement. Named rather than derived so this test keeps meaning something as
# the registry grows: when one of these is implemented it moves out of here and
# into the parametrized tests above by itself. (menace/hexproof/prowess/flash
# graduated with the M21 keyword round.)
_NOT_IMPLEMENTED = ("ward", "cascade", "mutate", "scavenge")


@pytest.mark.parametrize("keyword", _NOT_IMPLEMENTED)
def test_an_unimplemented_keyword_is_refused(keyword):
    """The direction that fails silently by admitting a lie.

    A keyword whose behaviour is not built must not be admitted, however well
    the word parses — the card is meant to report unsupported and name the line.
    If one of these ever becomes implemented, this test is the reminder to move
    it: it fails, and the fix is to delete the entry, not to weaken the check.
    """
    if keyword in IMPLEMENTED_KEYWORDS:
        pytest.fail(
            f"{keyword!r} is now implemented — remove it from _NOT_IMPLEMENTED "
            "here so the parametrized tests above cover it instead"
        )
    assert not _is_supported_keyword_line(keyword)


def test_the_unimplemented_names_are_real_keywords():
    """Otherwise the test above passes on typos.

    `_NOT_IMPLEMENTED` is a list of words asserted to be *refused*, and a
    misspelling is refused for the wrong reason — it would keep passing after
    the keyword it meant to name was implemented.
    """
    catalog = {word.lower() for word in KEYWORD_ABILITIES}
    for keyword in _NOT_IMPLEMENTED:
        assert keyword in catalog, (
            f"{keyword!r} is not a keyword ability in data/vocabulary/; "
            "a typo here would make the refusal test vacuous"
        )
