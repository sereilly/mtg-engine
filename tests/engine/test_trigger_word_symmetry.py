"""CR 603.1: "when", "whenever" and "at" are one trigger word.

The rule writes a triggered ability as "[When/Whenever/At] [trigger condition],
[effect]" and says nothing else about the choice — the difference is how often
the ability triggers while it exists, never *what* triggers it, and no fire site
in this engine reads the word. `engine/oracle.py`'s regex table already acts on
that: a "when" line its own table misses is asked of the whenever table with the
word swapped, rather than by copying rows between the two.

The grammar did not, and the asymmetry was invisible from either side alone. Its
whole condition reader lived inside the `whenever` branch and the `when` branch
fell back to the *fixed phrase table* — so every clause carrying a **noun
phrase** was unreachable from one printed word: a narrowed cast, a subject-led
entry, a quantified tap. Two Weatherlight cards found it (Timid Drake's "When
another creature enters", Straw Golem's "When an opponent casts a creature
spell"), and what the two front ends disagreed about was not the condition but
which cards have one at all.

A guard rather than a note, because the failure is silent in the direction that
costs cards their support, and because the next reader to add a production
inside one branch will not think about the other.
"""

from __future__ import annotations

import pytest

from engine.grammar import parse_line
from engine.grammar.errors import GrammarError
from engine.grammar.trigger_tables import _WHENEVER_EVENTS
from engine.oracle import trigger_condition_of_line


def _event(word: str, clause: str):
    """The `TriggerEvent` the grammar reads out of "<word> <clause>, draw a card."

    None when the line refuses. The effect is the simplest sentence in the
    language, so anything that fails is the condition half.
    """
    try:
        node = parse_line(f"{word} {clause}, draw a card.")
    except GrammarError:
        return None
    return getattr(node, "event", None)


def _clause(phrase: tuple[str, ...]) -> str:
    """A phrase-table entry rendered back into the words a card prints."""
    return " ".join(phrase).replace(" 's", "'s")


@pytest.mark.parametrize(
    "phrase", [phrase for _kind, phrase in _WHENEVER_EVENTS], ids=_clause
)
def test_every_phrase_table_condition_reads_under_both_printed_words(phrase):
    """The fixed-phrase half, complete by construction rather than by a list."""
    clause = _clause(phrase)
    whenever, when = _event("whenever", clause), _event("when", clause)
    assert whenever is not None, "the table's own entry must parse under 'whenever'"
    assert when is not None, f"'when {clause}' refuses while 'whenever' reads it"
    assert when.kind == whenever.kind
    assert when.subject == whenever.subject


#: The clauses whose subject is a **noun phrase** rather than fixed words —
#: exactly the readings the `when` branch could not reach, one per production
#: that lives past the phrase table. Hand-written because a noun phrase has no
#: table to enumerate; each entry names the card that prints it.
_SUBJECT_CARRYING_CLAUSES = (
    "another creature enters",                      # Timid Drake
    "a Djinn or Efreet enters",                     # Suleiman's Legacy
    "an opponent casts a creature spell",           # Straw Golem
    "a player casts a blue spell",                  # the Rod/Cup/Sphere cycle
    "you cast a noncreature spell",                 # Spellgorger Weird
    "a creature you control dies",                  # Basri's Lieutenant
    "an artifact is put into a graveyard from the battlefield",  # Tablet of Epityr
)


@pytest.mark.parametrize("clause", _SUBJECT_CARRYING_CLAUSES)
def test_every_narrowed_condition_reads_under_both_printed_words(clause):
    whenever, when = _event("whenever", clause), _event("when", clause)
    assert whenever is not None
    assert when is not None, f"'when {clause}' refuses while 'whenever' reads it"
    assert when.kind == whenever.kind
    assert when.subject == whenever.subject, (
        "the narrowing has to survive the printed word too: a condition read "
        "on one front end and dropped on the other fires on the wrong event"
    )


def test_the_long_dies_spelling_reads_any_permanent_noun_and_either_article():
    """CR 700.4: "dies" *means* "is put into a graveyard from the battlefield".

    Both front ends had the long wording fixed to "this **creature**" and
    "**your** graveyard", so Lich — "When this enchantment is put into a
    graveyard from the battlefield, you lose the game" — had no condition at
    all on the dispatching side and its whole downside never happened. CR 404.1
    sends a permanent to its owner's graveyard, so "a" and "your" name one pile
    for a card its controller owns, and the noun is the source either way.
    """
    for noun in ("creature", "artifact", "enchantment", "land", "permanent"):
        for article in ("a", "your"):
            line = (
                f"When this {noun} is put into {article} graveyard from the "
                "battlefield, you lose the game."
            )
            condition, _ = trigger_condition_of_line(line, None)
            assert condition is not None, line
            assert condition.kind == "dies", line
            assert _event("when", line.split(", ")[0][len("When "):]).kind == "dies"
