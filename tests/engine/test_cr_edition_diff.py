"""``scripts/cr_edition_diff.py`` — what a Comprehensive Rules bump moved.

A rules bump renumbers by inserting, and a citation left behind goes on naming
a rule that exists and says something else. The script finds those by *text*;
these hold the three verdicts it gives on editions small enough to read, and
that the rules file in the repo is in the convention ``--install`` writes, so
the next bump's diff is the rules that changed and not four thousand blank
lines.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import cr_edition_diff  # noqa: E402

_OLD = """\
506.5. A creature attacks alone if it is the only attacker.
506.6. Some abilities check whether a creature had to attack.
506.7. Some spells may be cast only before or after a point in combat.
506.7c Some spells may be cast only during combat, in addition to rule 506.7.
601.5. If a player is no longer allowed to cast a spell, the cast is illegal.
704.5y Each extra Role is put into its owner's graveyard.
704.5z A rule that is simply deleted in the next edition.
"""

_NEW = """\
506.5. A creature attacks alone if it is the only attacker, or says so.
506.6. A creature attacks a player alone if no other creature attacks them.
506.7. Some abilities check whether a creature had to attack.
506.8. Some spells may be cast only before or after a point in combat.
506.8c Some spells may be cast only during combat, in addition to rule 506.8.
601.5. If a player is no longer allowed to cast a spell, the cast is illegal.
704.5z Each extra Role is put into its owner's graveyard.
"""


def _verdicts():
    return cr_edition_diff.classify(
        cr_edition_diff.rules_of(_OLD), cr_edition_diff.rules_of(_NEW)
    )


def test_a_rule_whose_text_sits_under_another_number_has_moved():
    verdicts = _verdicts()

    assert verdicts["506.6"] == ("moved", "506.7")
    assert verdicts["506.7"] == ("moved", "506.8")
    assert verdicts["704.5y"] == ("moved", "704.5z")
    # Unchanged where it was: not reported at all.
    assert "601.5" not in verdicts


def test_a_cross_reference_renumbered_on_the_way_is_still_a_move():
    """506.7c's text changed by one digit - the rule it points at moved too.
    Read as "gone" it would send a reader looking for a deletion."""
    assert _verdicts()["506.7c"] == ("moved", "506.8c")


def test_an_edit_in_place_and_a_deletion_are_told_apart():
    verdicts = _verdicts()

    kind, ratio = verdicts["506.5"]
    assert kind == "changed" and 0.5 < float(ratio) < 1.0
    # Its number now holds another rule's text and nothing carries its own.
    assert verdicts["704.5z"][0] == "changed"
    only_old = cr_edition_diff.classify({"100.9": "A rule nobody kept."}, {"100.1": "Other."})
    assert only_old == {"100.9": ("gone", "")}


def test_a_download_is_read_in_one_convention():
    """Wizards' text has shipped with NO-BREAK SPACE on its blank lines and
    U+2028 for soft breaks, with a BOM and without, CRLF and LF."""
    raw = "﻿Title\r\n \r\n100.1. A rule.     Its second paragraph.  \r\n".encode("utf-8")

    assert cr_edition_diff.normalized(raw) == "Title\n\n100.1. A rule.\n    Its second paragraph.\n"


def test_the_rules_file_in_the_repo_is_already_in_that_convention():
    raw = (REPO / "MagicCompRules.txt").read_bytes()
    plain = raw.decode("utf-8-sig").replace("\r\n", "\n")

    assert cr_edition_diff.normalized(raw) == plain
    rules = cr_edition_diff.rules_of(plain)
    assert len(rules) > 3000
    # The edition the engine's mana-ability predicate is written against.
    assert "move any card to or from a library" in rules["605.1a"]
