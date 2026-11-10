"""Every CR number cited in brief files, checked against MagicCompRules.txt.

    check_brief_crs.py [--strict] <repo-root> <brief files...>

Mirrodin's integrator sent a brief citing CR 722 for controlling a player (723;
722 is Preparation Cards) and Scourge's carried four wrong numbers: printing
each cited rule's opening words makes a wrong subject visible as well as a
missing number.

Prints each cited rule with the first words of its text (so a number that
exists but is about something else is visible), and every number the CR does
not have. Exit 1 if any is missing.

**A number that exists can still be the wrong rule.** So each citation is
also compared with the sentence citing it: a ``SUBJECT?`` line names a
citation whose rule (the rule and its subrules) shares no content word with
that sentence, words compared by their first five letters so "controls" meets
"control". It catches a citation of the wrong section — "controls a player's
turn (CR 722.1)", Preparation Cards, flags — and not a neighbour that shares
the vocabulary: Mirrodin's CR 205.2a for "artifact creature card" (205.2b)
passes, because 205.2a lists the card types. Read the printed opening words
too. A prompt to read the rule, not a verdict; ``--strict`` makes it fail.
"""
import re
import sys
from pathlib import Path

#: Words too common to tell two rules apart.
STOPWORDS = frozenset("""
    a an and any are as at be been by can card cards cast does each effect
    effects for from game has have if in into is it its may not of on one or
    other player players rule rules see spell spells than that the their them
    then there these this those to under until when whenever which while who
    will with without would you your
""".split())

#: A citing sentence with fewer content words than this is a bare reference
#: and is not compared (Mirrodin's 21 briefs: 8 of 10 flags were such).
MIN_CLAIM_WORDS = 3

args = sys.argv[1:]
strict = "--strict" in args
args = [a for a in args if a != "--strict"]
root = Path(args[0])
cr = (root / "MagicCompRules.txt").read_text(encoding="utf-8").splitlines()
rules = {}
for line in cr:
    m = re.match(r"^(\d{3}(?:\.\d+[a-z]?)?)\.?\s+(.*)", line)
    if m and m.group(1) not in rules:
        rules[m.group(1)] = m.group(2)


def words(text: str) -> set[str]:
    return {
        w[:5] for w in re.findall(r"[a-z]+", text.lower())
        if len(w) >= 4 and w not in STOPWORDS
    }


def rule_words(num: str) -> set[str]:
    """The rule and its lettered subrules (702.41 reads 702.41a, 702.41b ...)."""
    own = re.compile(rf"^{re.escape(num)}[a-z]?$")
    return set().union(*(words(body) for key, body in rules.items() if own.match(key)))


#: Where a sentence ends in a hard-wrapped brief: a full stop before a space or
#: line break, a blank line, or the start of a bullet or heading. A bare line
#: break is the wrap, not an end.
_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(`*\"'])|\n\s*\n|\n\s*(?:[-*]|\d+\.|#+)\s")


def sentence_around(text: str, start: int, end: int) -> str:
    """The sentence holding text[start:end], across the brief's line wraps."""
    ends = [m.span() for m in _SENTENCE_END.finditer(text)]
    left = max((e for s, e in ends if e <= start), default=0)
    right = min((s for s, e in ends if s >= end), default=len(text))
    return " ".join(text[left:right].split())


cited = {}
sentences = {}   # num -> [(file, sentence)]
for f in args[1:]:
    text = Path(f).read_text(encoding="utf-8")
    label = Path(f).parent.name + "/" + Path(f).name
    for m in re.finditer(r"\bCR\s+((?:\d{3}\.\d+[a-z]?(?:[–-]\d{3}\.\d+[a-z]?)?)(?:\s*(?:,|and|/)\s*\d{3}\.\d+[a-z]?)*)", text):
        for num in re.findall(r"\d{3}\.\d+[a-z]?", m.group(0)):
            cited.setdefault(num, set()).add(label)
    for m in re.finditer(r"\b(\d{3}\.\d+[a-z]?)\b", text):
        num = m.group(1)
        if num.startswith(("7", "1", "2", "3", "4", "5", "6")) and "." in num:
            cited.setdefault(num, set()).add(label)
            sentences.setdefault(num, []).append((label, sentence_around(text, m.start(), m.end())))

missing = []
unsubjected = []
for num in sorted(cited, key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)]):
    body = rules.get(num)
    if body is None:
        missing.append(num)
        print(f"MISSING  {num:8s} in {sorted(cited[num])}")
        continue
    print(f"ok       {num:8s} {body[:70]}")
    subject = rule_words(num)
    for label, sentence in sentences.get(num, ()):
        claim = words(sentence.replace(num, " "))
        # "CR 707.5 — check", "CR 723 is the rule": nothing to compare against.
        if len(claim) < MIN_CLAIM_WORDS:
            continue
        if subject and not (claim & subject):
            unsubjected.append(num)
            print(f"SUBJECT? {num:8s} {label}: rule reads {body[:60]!r}")
            print(f"         {'':8s} cited in: {sentence[:110]!r}")
if unsubjected:
    print(f"{len(unsubjected)} citation(s) share no word with their rule - read each rule before sending")
sys.exit(1 if missing or (strict and unsubjected) else 0)
