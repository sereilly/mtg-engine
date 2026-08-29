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
from engine.models import CardDefinition
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


@pytest.mark.parametrize("keyword", sorted(IMPLEMENTED_KEYWORDS))
def test_an_implemented_keyword_is_not_also_on_the_blocklist(keyword):
    """The third place a keyword's name can live, and the one that outranks
    everything else.

    ``oracle.UNSUPPORTED_KEYWORDS`` names keyword *mechanics* the engine does
    not model, matched against the **ingested** ``keywords`` field before any
    line is classified. It is not the negation of the registry — "Enchant" and
    "Landwalk" are Scryfall tags whose behaviour lives elsewhere — so it cannot
    be derived, and a word left in it after the mechanic is built costs every
    card printed with that keyword its support with the behaviour sitting right
    there. Rampage did exactly that: the declare-blockers step resolved it, three
    CR-cited tests passed over it, and every card that printed it compiled
    unsupported.

    Asserted behaviourally rather than by comparing the two sets, because the
    field is what the gate actually reads — a card whose ingested keywords name
    an implemented keyword must compile.
    """
    card = CardDefinition(
        name=f"Blocklist Probe {keyword}",
        mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=keyword.title(),
        colors=(), color_identity=(),
        keywords=(keyword.title(),), produced_mana=(),
        raw={"name": f"Blocklist Probe {keyword}", "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )
    assert compile_card_oracle(card).supported, (
        f"{keyword!r} is implemented but a card carrying it in its ingested "
        "keywords field compiles unsupported — check oracle.UNSUPPORTED_KEYWORDS"
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


def test_every_granted_ability_duration_the_grammar_emits_has_a_sweep():
    """A printed duration is implemented by *having a sweep*, not by having a
    word — so the lowering's table of printed durations may only name channels
    `engine/keywords.py` actually ends.

    Two tables, because the two sides answer different questions: one maps a
    printed phrase to a channel, the other says which channels are swept. What
    must not happen is the first naming a channel the second does not have,
    which is a grant that is recorded and then never taken away.
    """
    from engine.grammar.lowering.keywords import _GRANT_DURATIONS
    from engine.keywords import GRANTED_ABILITY_DURATIONS

    assert set(_GRANT_DURATIONS.values()) <= GRANTED_ABILITY_DURATIONS


def test_granting_an_ability_for_a_duration_nothing_sweeps_is_refused():
    """The other direction of the same rule, asked of the write API itself: a
    caller reaching past the grammar cannot record a duration no sweep ends."""
    import pytest

    from engine.keywords import grant_ability_line
    from engine.models import CardDefinition, Permanent

    card = CardDefinition(
        name="Probe", mana_cost="", cmc=0.0, type_line="Creature",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )
    with pytest.raises(ValueError):
        grant_ability_line(Permanent(card=card), "Flying", duration="until_i_say_so")


def test_the_aura_grant_vocabulary_is_the_keyword_registry():
    """``engine/auras.py`` used to keep its own tuple of grantable keywords, and
    it had drifted in both directions — which is what a second copy of one fact
    always does, and both directions are wrong in a way nothing catches.

    It listed ``shadow``, which this engine does not implement anywhere: an Aura
    granting it would have been *admitted*, entered play, and given its host an
    evasion ability that does nothing. And it omitted menace, lifelink,
    deathtouch, indestructible, flash, hexproof, prowess and rampage, so an Aura
    granting any of those was reported unsupported for a mechanic the engine
    has.

    The exclusions are the family words whose printed form carries a quality —
    "protection from red", "swampwalk" under "landwalk", "bands with other
    legendary creatures" — which the comma/"and" splitting would cut in half.
    They are the same three ``lord_buffs.grantable_keywords`` excludes, and this
    asserts the two agree rather than re-listing them.
    """
    from engine.auras import _grantable_keywords
    from engine.lord_buffs import grantable_keywords

    assert set(_grantable_keywords()) == set(grantable_keywords())
