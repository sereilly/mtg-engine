"""The "whenever" table's rationale stays attached to its rows.

``engine/whenever_triggers.py`` is one ordered, first-match-wins table, which
is not split across modules because its order is behaviour. Its rationale —
the comment block above each row, four lines in five of the module — moved to
``engine/whenever_trigger_notes.py`` so the table can stay whole under the
2,000-line cap. A note that has left its row is a note that can come to
describe a row it was never about, or one that no longer exists, so each is
held here: it names exactly one row of its kind, no two name the same row,
and they run in the table's order (the order "the row below" and "the rows
above" in a note are written in).
"""

from engine.whenever_trigger_notes import WHENEVER_TRIGGER_NOTES
from engine.whenever_triggers import WHENEVER_TRIGGER_PATTERNS


def _row_named(kind: str, phrase: str) -> list[int]:
    """The rows a note's (kind, phrase) names: the row whose pattern *is* the
    phrase, else every row of the kind containing it."""
    exact = [
        index for index, (row_kind, pattern) in enumerate(WHENEVER_TRIGGER_PATTERNS)
        if row_kind == kind and pattern == phrase
    ]
    return exact or [
        index for index, (row_kind, pattern) in enumerate(WHENEVER_TRIGGER_PATTERNS)
        if row_kind == kind and phrase in pattern
    ]


def test_every_note_names_one_row_of_its_kind():
    assert len(WHENEVER_TRIGGER_NOTES) >= 100, "the notes did not load"
    for kind, phrase, text in WHENEVER_TRIGGER_NOTES:
        assert text.strip(), (kind, phrase)
        named = _row_named(kind, phrase)
        assert len(named) == 1, (
            f"the note headed {phrase!r} names {len(named)} {kind!r} rows; "
            "give it a phrase of its row's pattern no other row of that kind has"
        )


def test_the_notes_run_in_the_tables_order_one_per_row():
    rows = [_row_named(kind, phrase)[0] for kind, phrase, _text in WHENEVER_TRIGGER_NOTES]
    assert len(set(rows)) == len(rows), "two notes name one row"
    assert rows == sorted(rows), (
        "a note out of the table's order: \"the row below\" in it now means "
        "another row — move it to where its row is"
    )


def test_a_note_that_lost_its_row_is_caught():
    """Validated backwards: a phrase from no row, and a pair swapped out of
    order, are what the two tests above refuse."""
    (kind, phrase, _), (kind2, phrase2, _) = WHENEVER_TRIGGER_NOTES[:2]
    assert _row_named(kind, phrase + " that no row prints") == []
    first, second = _row_named(kind, phrase)[0], _row_named(kind2, phrase2)[0]
    assert [second, first] != sorted([second, first])
