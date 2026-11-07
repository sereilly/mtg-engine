"""Guard: a CR citation names a rule that exists, and the rules most often
borrowed for something else are cited only for what they say.

``scripts/rules_gaps.py`` checks the numbers in ``engine/`` and ``web/`` that
follow the letters "CR", and only those: the later members of a list ("CR
608.2h, 113.7a", "CR 113.1c/113.8") and everything in ``tests/`` and
``scripts/`` went unread, which is where ``603.8b``, ``701.21b`` and two
``701.19d`` citations survived — letters no edition here has. And
``tests/engine/test_cr_citation_subjects.py`` holds the 701 block to its
headings, because a renumbering is mechanical; nothing held a citation to its
*subject* anywhere else.

The kg4 round found the commonest such borrowing. **CR 113.7a** says one thing:
once activated or triggered, an ability exists on the stack independently of
its source, removing the source does not affect it, and the source's last known
information is used. Over a hundred comments cited it, and most of them for a
neighbouring rule:

* "an ability on the stack is not a spell" — CR 113.9;
* "an ability on the stack has no card" — CR 405.1 ("without any card
  associated with it"), and for a triggered one CR 603.3;
* "no type line, no colour, no other characteristics" — CR 405.4;
* "an ability on the stack is an object" — CR 113.1c;
* "an Aura's ability is the Aura's, controlled by its controller, not a
  granted ability of its host" — CR 303.4e (an Equipment's, CR 301.5d), and
  the controller of an ability on the stack is CR 113.8.

So :data:`RULE_SUBJECTS` is a phrase list per cited rule: a sentence that cites
the rule and says one of the listed things must also cite a rule that says it.
The question is deliberately weak in one direction — a phrase in the same
sentence, not in a particular relation to the citation — and the sentences that
cite the right rule beside the borrowed one pass. A strong question over a list
somebody keeps would miss the next comment; a weak one over every comment
catches the borrowing as it is written.

**CR 112.2** is in the table for the other half of the same report: it was said
to be a spell's owner and not its controller. Its text gives both ("A spell's
controller is, by default, the player who put it on the stack"), so every
spell-controller citation of it is right, and what the row refuses is the
reading that would be wrong — 112.2 for an *ability's* controller, which is
CR 113.8.

Each check asserts a floor on what it read, and
:func:`test_the_subject_check_refuses_each_borrowing` plants every borrowing in
a sentence of its own, so a phrase list that stopped matching anything is a red
test rather than a quiet green one.
"""

from __future__ import annotations

import io
import re
import tokenize
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "MagicCompRules.txt"

#: Where citations are read. ``tests/`` and ``scripts/`` are in it because a
#: wrong number in a test's docstring is read by the next person exactly as one
#: in the engine is — and it was where the phantom letters were.
SCANNED = ("engine", "web", "scripts", "tests")

_NUMBER = r"\d{3}\.\d+[a-z]?"
_SEPARATOR = r"\s*(?:,|/|;|\band\b|\bor\b)\s*(?:CR\s+)?"
#: "CR 113.7a", and every number of a list it heads: "CR 608.2h, 113.7a",
#: "CR 113.1c/113.8", "CR 702.6a and 113.7a", "CR 608.2h, CR 120.7".
CITATION_LIST = re.compile(rf"\bCR\s+({_NUMBER}(?:{_SEPARATOR}{_NUMBER})*)")
_ONE_NUMBER = re.compile(r"(\d{3}\.\d+)([a-z])?")
#: ``@pytest.mark.cr("113.7a", "608.2h")`` — read outside ``tests/rules`` too,
#: where ``tests/engine/test_rules_progress.py`` does not look.
MARKER = re.compile(r"pytest\.mark\.cr\(([^)]*)\)")
_MARKER_NUMBER = re.compile(r"[\"'](\d{3}\.\d+[a-z]?)[\"']")

#: A sentence ends at a full stop, a question or an exclamation mark followed
#: by whitespace and a capital (or an opening quote or bracket). A rule number's
#: own dot is followed by a digit, so "113.7a" is never an end.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)*_`]*\s+(?=[A-Z\"“'(*`_])")

#: Per cited rule: ``(phrase, the rules that say it, what the phrase claims)``.
#: A sentence citing the rule whose text matches the phrase must also cite one
#: of those rules. Each rule number was read in ``MagicCompRules.txt``.
RULE_SUBJECTS: dict[str, tuple[tuple[re.Pattern, frozenset, str], ...]] = {
    "113.7a": (
        (re.compile(r"\bnot an? spells?\b|\baren't spells\b|\bnot an ability\b", re.I),
         frozenset({"113.9", "112.1"}),
         "an ability on the stack is not a spell"),
        (re.compile(
            r"\bno card\b|\bcards? of its own\b|\bno-card\b|\bnot a card\b"
            r"|\bwithout (?:a|any) card\b", re.I),
         frozenset({"405.1", "603.3", "707.10"}),
         "an ability on the stack has no card"),
        (re.compile(
            r"\bno type line\b|\bno other characteristics\b"
            r"|\bno card(?:,| and) no colou?r\b", re.I),
         frozenset({"405.4", "603.3"}),
         "an ability on the stack has no other characteristics"),
        (re.compile(
            r"\bis an object\b|\bare objects\b|\ban object with\b|\bstack object\b"
            r"|\bis an ability on the stack\b", re.I),
         frozenset({"113.1c", "109.1"}),
         "an ability on the stack is an object"),
        (re.compile(
            r"\bkeeps (?:them|the two) apart\b"
            r"|\b(?:whole|entire) (?:of the )?difference\b", re.I),
         frozenset({"113.9", "405.1", "112.1"}),
         "what tells a spell from an ability"),
        (re.compile(r"\bcontroll(?:ed|er|ers|s)\b|\bcontrols it\b", re.I),
         frozenset({"113.8", "303.4e", "301.5d", "405.4", "603.3"}),
         "who controls an ability"),
        (re.compile(
            r"\bis the Aura's\b|\bthe ability the Aura's\b|\bstays the Aura's\b"
            r"|\bnot a granted ability\b|\bnot the creature's\b", re.I),
         frozenset({"113.7", "303.4e", "301.5d"}),
         "whose ability it is"),
    ),
    "112.2": (
        (re.compile(
            r"\bability's controller\b"
            r"|\bcontroller of an? (?:activated |triggered )?ability\b", re.I),
         frozenset({"113.8", "405.4", "603.3"}),
         "an ability's controller"),
    ),
}

#: Citations of a rule that does not exist, each deliberate: a script's
#: docstring showing the *spelling* it reads, with a number chosen to be no
#: rule. Keyed by file and number; :func:`test_every_reviewed_phantom_is_still_there`
#: fails on a stale entry.
REVIEWED_PHANTOMS = {
    # The citation *style* its regex reads ("614.7c"), and "603.8b" as the
    # example of a letter a rule-level fold would hide — the module's subject.
    ("scripts/rules_gaps.py", "614.7c"),
    ("scripts/rules_gaps.py", "603.8b"),
    # The two spellings it reads, dotted and a marker's, shown on "506.7c".
    ("scripts/cr_edition_diff.py", "506.7c"),
}


@lru_cache(maxsize=1)
def _known_rules() -> frozenset[str]:
    """Every rule and subrule number in the shipped CR text."""
    text = RULES.read_text(encoding="utf-8", errors="replace")
    return frozenset(
        m.group(1) + (m.group(2) or "")
        for m in re.finditer(r"^(\d{3}\.\d+)([a-z])?[.\s]", text, re.M)
    )


def _python_files() -> Iterator[tuple[str, str]]:
    for base in SCANNED:
        for path in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path.relative_to(ROOT).as_posix(), path.read_bytes().decode("utf-8")


_PROSE_TOKENS = {tokenize.STRING} | (
    {tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set()
)


def prose_passages(source: str) -> Iterator[tuple[int, str]]:
    """``(first line, text)`` for each comment paragraph and each string.

    Consecutive comment lines are one passage, so a sentence wrapped over
    several lines is read whole; whitespace is folded to single spaces.
    """
    paragraph: list[str] = []
    first = last = 0
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            line = tok.start[0]
            text = re.sub(r"^#+:?", "", tok.string)
            if paragraph and line == last + 1:
                paragraph.append(text)
            else:
                if paragraph:
                    yield first, " ".join(" ".join(paragraph).split())
                paragraph, first = [text], line
            last = line
        elif tok.type in _PROSE_TOKENS:
            yield tok.start[0], " ".join(tok.string.split())
    if paragraph:
        yield first, " ".join(" ".join(paragraph).split())


def _sentence_around(text: str, start: int, end: int) -> str:
    begin, finish = 0, len(text)
    for m in _SENTENCE_END.finditer(text):
        if m.end() <= start:
            begin = m.end()
        elif m.start() >= end:
            finish = m.start() + 1
            break
    return text[begin:finish]


def citations(text: str) -> Iterator[tuple[int, int, list[str]]]:
    """``(start, end, numbers)`` for each "CR ..." list in *text*."""
    for m in CITATION_LIST.finditer(text):
        numbers = [n.group(1) + (n.group(2) or "") for n in _ONE_NUMBER.finditer(m.group(1))]
        yield m.start(), m.end(), numbers


def borrowings(text: str) -> list[tuple[str, str, str]]:
    """``(cited rule, what the sentence claims, the sentence)`` for every
    sentence in *text* that cites a rule of :data:`RULE_SUBJECTS` for a claim
    one of the rules that say it is not cited beside."""
    found = []
    for start, end, numbers in citations(text):
        for rule in RULE_SUBJECTS.keys() & set(numbers):
            sentence = _sentence_around(text, start, end)
            cited = {n for _, _, ns in citations(sentence) for n in ns}
            for phrase, sayers, claim in RULE_SUBJECTS[rule]:
                if phrase.search(sentence) and not (sayers & cited):
                    found.append((rule, claim, sentence))
    return found


def subject_offenders(files: Iterable[tuple[str, str]]) -> tuple[list[str], dict[str, int]]:
    """Every borrowing in *files*, and how many citations of each table rule
    were read."""
    offenders: list[str] = []
    read = {rule: 0 for rule in RULE_SUBJECTS}
    for rel, source in files:
        if not any(rule in source for rule in RULE_SUBJECTS):
            continue
        for line, text in prose_passages(source):
            for _, _, numbers in citations(text):
                for rule in RULE_SUBJECTS.keys() & set(numbers):
                    read[rule] += 1
            for rule, claim, sentence in borrowings(text):
                offenders.append(
                    f"{rel}:{line} cites CR {rule} for {claim!r}: {sentence[:160]}"
                )
    return offenders, read


def phantom_offenders(files: Iterable[tuple[str, str]]) -> tuple[list[tuple[str, int, str]], int]:
    """``(file, line, number)`` for every cited number the CR does not have,
    and how many numbers were read (prose citations and ``cr`` markers)."""
    known = _known_rules()
    offenders: list[tuple[str, int, str]] = []
    read = 0
    for rel, source in files:
        for line, text in prose_passages(source):
            for _, _, numbers in citations(text):
                for number in numbers:
                    read += 1
                    if number not in known:
                        offenders.append((rel, line, number))
        for m in MARKER.finditer(source):
            line = source.count("\n", 0, m.start()) + 1
            for n in _MARKER_NUMBER.finditer(m.group(1)):
                read += 1
                if n.group(1) not in known:
                    offenders.append((rel, line, n.group(1)))
    return offenders, read


def _cite(rule: str) -> str:
    """A citation built at run time, so the planted sentences below are not
    themselves read as citations by the scan."""
    return "(" + "CR " + rule + ")"


def test_the_subject_check_refuses_each_borrowing():
    """Backwards: every row fires on a sentence that borrows the rule, and is
    quiet once the right rule is cited beside it — so a phrase that stopped
    matching is a failure here rather than an empty list above."""
    borrowed = "113." + "7a"
    planted = {
        "an ability on the stack is not a spell": "An ability is not a spell " + _cite(borrowed) + ".",
        "an ability on the stack has no card": "An ability on the stack has no card " + _cite(borrowed) + ".",
        "an ability on the stack has no other characteristics": "It has no type line " + _cite(borrowed) + ".",
        "an ability on the stack is an object": "An ability on the stack is an object " + _cite(borrowed) + ".",
        "what tells a spell from an ability": "The rule keeps the two apart " + _cite(borrowed) + ".",
        "who controls an ability": "The life goes to its controller " + _cite(borrowed) + ".",
        "whose ability it is": "An Aura's ability is the Aura's " + _cite(borrowed) + ".",
    }
    for claim, sentence in planted.items():
        assert [c for _, c, _ in borrowings(sentence)] == [claim], sentence
    assert borrowings(
        "An ability is not a spell " + _cite("113.9") + " and outlives its source "
        + _cite(borrowed) + "."
    ) == []
    assert borrowings(
        "The ability outlives its source " + _cite(borrowed) + ". It is not a spell."
    ) == [], "a claim in the next sentence is not this citation's"
    assert [c for _, c, _ in borrowings(
        "Countered, the ability's controller pays " + _cite("112." + "2") + "."
    )] == ["an ability's controller"]
    assert borrowings(
        "A spell's controller is the player who cast it " + _cite("112." + "2") + "."
    ) == []


def test_a_borrowed_rule_is_cited_only_for_what_it_says():
    offenders, read = subject_offenders(_python_files())
    assert read["113.7a"] >= 20, f"too few CR 113.7a citations read: {read}"
    assert read["112.2"] >= 5, f"too few CR 112.2 citations read: {read}"
    assert not offenders, (
        "These sentences cite a rule for something a neighbouring rule says "
        "(see RULE_SUBJECTS for which). Cite the rule that says it - beside "
        "the borrowed one if the sentence also makes the borrowed rule's own "
        "claim. Offenders:\n  " + "\n  ".join(offenders)
    )


def test_every_cited_rule_is_in_the_shipped_rules():
    """A cited number, letter included, names a rule in ``MagicCompRules.txt`` —
    including the later members of a list and a ``cr`` marker anywhere in
    ``tests/``. After a CR bump, ``scripts/cr_edition_diff.py`` says what moved;
    this says what is now no rule at all."""
    offenders, read = phantom_offenders(_python_files())
    assert len(_known_rules()) > 2500, "the CR text did not parse"
    assert read > 20000, f"only {read} citations read"
    unexplained = sorted(
        f"{rel}:{line} cites {number}"
        for rel, line, number in offenders
        if (rel, number) not in REVIEWED_PHANTOMS
    )
    assert not unexplained, (
        "These citations name no rule in MagicCompRules.txt (a subrule letter "
        "the rule does not have, or a number that is gone). Find the rule the "
        "sentence means; if the number is a deliberate example, add it to "
        "REVIEWED_PHANTOMS. Offenders:\n  " + "\n  ".join(unexplained)
    )


def test_every_reviewed_phantom_is_still_there():
    offenders, _ = phantom_offenders(
        (rel, source) for rel, source in _python_files()
        if rel in {r for r, _ in REVIEWED_PHANTOMS}
    )
    present = {(rel, number) for rel, _, number in offenders}
    stale = sorted(REVIEWED_PHANTOMS - present)
    assert not stale, f"REVIEWED_PHANTOMS entries that match nothing: {stale}"
