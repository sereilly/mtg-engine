"""Guard: a CR citation in the 701 block names the keyword action it cites.

``scripts/rules_gaps.py`` already checks that a cited rule *number* exists, and
that a cited subrule *letter* exists under it. Neither question is the one that
was wrong here. A comment saying "the no-regeneration rider (CR 701.15c)" cites
a real number with a real letter — and CR 701.15 is **Goad**.

Visions' wave 4 audited every CR citation in ``engine/`` and ``web/`` against
``MagicCompRules.txt`` and rewrote **185** of them. Almost none was a typo. The
CR shipped in this repo is the April 17, 2026 edition, which inserted
``701.4 Behold`` and ``701.11 Triple`` into the alphabetical keyword-action
block; everything after them shifted, some by one and some by four, and the
comments were written against the older numbering. So ``701.7`` (then Destroy,
now **Create**) was cited nine times for destroying, ``701.13a`` (then Mill, now
**Exile**) six times for milling, ``701.19`` (then Search, now **Regenerate**)
seventeen times for searching and shuffling, and ``701.5a`` (then Counter, now
**Cast**) sixteen times for countering. Every one of those citations pointed at
a real rule about something else.

That is why this guard exists and why it is scoped to 701. The renumbering is
the *mechanism*, and it will happen again on the next CR bump; the 701 block is
also the one place in the rules where every top-level rule is headed by a single
keyword word (``701.19. Regenerate``), which makes "does the comment name what
it cites?" a question a test can actually ask. Outside 701 the headings are
prose and the same check would be noise.

**The heading map is read out of ``MagicCompRules.txt`` at test time**, not
copied here. Update the CR file to a later edition and every citation whose
keyword moved underneath it fails immediately — which is precisely the failure
that went unnoticed for as long as it did, and the reason the sweep alone would
not have held.

The check is deliberately weak in one direction: the keyword has to appear
*somewhere* within eight lines, not in a particular relation to the citation.
A weak question over every site beats a strong question over a list somebody
maintains — and the sites where even the weak question fails are the ones
listed below, each read by hand and each correct.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "MagicCompRules.txt"

#: How far from the citation the keyword may be. Eight lines is a paragraph of
#: this codebase's comments; a citation whose subject is further away than that
#: is not being explained by the words around it anyway.
WINDOW = 8

#: Heading words too common to be evidence of anything.
_STOPWORDS = frozenset({"a", "an", "and", "the", "in", "into", "to", "of",
                        "or", "on", "you", "your", "for", "it"})

#: Citations whose comment does not repeat the cited keyword, each read against
#: ``MagicCompRules.txt`` by hand and each **correct**. Keyed by the file and
#: the number, with the word the comment uses instead — which is the whole
#: reason the mechanical check cannot see it.
#:
#: :func:`test_every_reviewed_exception_is_still_there` fails on a stale entry,
#: so this list cannot outlive the sites it excuses.
REVIEWED = {
    # "finding fewer, none included, is a legal answer" — 701.23b is
    # fail-to-find, and neither comment prints the word "search".
    ("engine/grammar/ast/library.py", "701.23b"),
    ("engine/grammar/lowering/exile.py", "701.23b"),
    # "the look" / "a look" — 701.20e is the look, filed under Reveal.
    ("engine/grammar/ast/statements.py", "701.20e"),
    ("engine/handlers/control_flow.py", "701.20e"),
    # "regeneration" / "regenerated" — the noun, never the infinitive.
    ("engine/grammar/lowering/damage.py", "701.19c"),
    ("engine/grammar/lowering/prohibitions.py", "701.19"),
    # "doesn't untap during your next untap step" is what exerting *is*; the
    # three comments describe the effect and never name the keyword.
    ("engine/grammar/lowering/untap_restrictions.py", "701.43a"),
    ("engine/handlers/tapping.py", "701.43a"),
    ("engine/phases/untap_step.py", "701.43a"),
    # Timmerian Fiends exchanges ownership; the comment says "nowhere to be
    # found", which is 701.12a's "if the effect can't be performed".
    ("engine/handlers/zones.py", "701.12a"),
}

_CITATION = re.compile(r"\b(?:CR|rule)\s*(701\.(\d+)[a-z]?)\b")


def _keyword_headings() -> dict[str, str]:
    """``{"19": "Regenerate", ...}`` read out of the shipped CR text."""
    text = RULES.read_text(encoding="utf-8", errors="replace")
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^701\.(\d+)\.\s+([A-Z][A-Za-z' /-]+)\s*$", text, re.M)
    }


def _stems(heading: str) -> set[str]:
    """Word stems that count as naming *heading* in a comment."""
    words = [w for w in heading.lower().split() if w not in _STOPWORDS]
    return {w[:5] if len(w) > 3 else w for w in words}


def _prose_lines(path: Path) -> set[int]:
    """Line numbers of *path* that are comment or string tokens.

    A citation in executable code is not a claim about the rules, and there are
    none; tokenizing keeps the check to prose without having to say so.
    """
    src = path.read_bytes().decode("utf-8")
    out: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            out.update(range(tok.start[0], tok.end[0] + 1))
    return out


def _sites():
    """``(relpath, line, citation, rule number, lines)`` per 701 citation."""
    for base in ("engine", "web"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            lines = path.read_bytes().decode("utf-8").split("\n")
            prose = _prose_lines(path)
            for i, line in enumerate(lines, start=1):
                if i not in prose:
                    continue
                for m in _CITATION.finditer(line):
                    yield (
                        path.relative_to(ROOT).as_posix(), i, m.group(1),
                        m.group(2), lines,
                    )


def _names_its_keyword(number: str, index: int, lines, headings) -> bool:
    heading = headings.get(number)
    if heading is None:
        return False
    window = " ".join(lines[max(0, index - 1 - WINDOW): index + WINDOW]).lower()
    return any(stem in window for stem in _stems(heading))


def test_a_701_citation_names_the_keyword_action_it_cites():
    headings = _keyword_headings()
    assert len(headings) > 50, "the CR's keyword-action block did not parse"

    offenders = []
    for rel, line, citation, number, lines in _sites():
        if headings.get(number) is None:
            offenders.append(
                "%s:%d cites CR %s and rule 701.%s has no heading in the CR"
                % (rel, line, citation, number)
            )
            continue
        if (rel, citation) in REVIEWED:
            continue
        if not _names_its_keyword(number, line, lines, headings):
            offenders.append(
                "%s:%d cites CR %s, which is %r, and no word near it says so"
                % (rel, line, citation, headings[number])
            )
    assert not offenders, (
        "A CR 701 citation should be about the keyword action it names. The 701 "
        "block renumbers whenever a keyword action is added - the April 2026 "
        "edition inserted Behold and Triple and moved everything after them - so "
        "a citation that was right when it was written now points at a different "
        "action entirely. Check each against MagicCompRules.txt and fix the "
        "number; if the comment is right and simply does not print the keyword, "
        "add it to REVIEWED with the word it uses instead. Offenders:\n  "
        + "\n  ".join(offenders)
    )


def test_every_reviewed_exception_is_still_there():
    """No entry above outlives the citation it excuses."""
    present = {(rel, citation) for rel, _, citation, _, _ in _sites()}
    stale = sorted(REVIEWED - present)
    assert not stale, (
        "these REVIEWED entries no longer match any citation - the code moved "
        "and the exemption did not: %r" % (stale,)
    )


def test_the_shipped_rules_state_their_edition():
    """The heading map is derived, but the *edition* is worth asserting once.

    Not a version pin - a later CR is welcome, and the check above is what makes
    one safe. This is here so a reader chasing a failure has a date to compare.
    """
    head = RULES.read_text(encoding="utf-8", errors="replace")[:400]
    assert "effective as of" in head
