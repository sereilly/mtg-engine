"""Every CR number cited in brief files, checked against MagicCompRules.txt.

    check_brief_crs.py <repo-root> <brief files...>

Mirrodin's integrator sent a brief citing CR 722 for controlling a player (723;
722 is Preparation Cards) and Scourge's carried four wrong numbers: printing
each cited rule's opening words makes a wrong subject visible as well as a
missing number.

Prints each cited rule with the first words of its text (so a number that
exists but is about something else is visible), and every number the CR does
not have. Exit 1 if any is missing.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
cr = (root / "MagicCompRules.txt").read_text(encoding="utf-8").splitlines()
rules = {}
for line in cr:
    m = re.match(r"^(\d{3}(?:\.\d+[a-z]?)?)\.?\s+(.*)", line)
    if m and m.group(1) not in rules:
        rules[m.group(1)] = m.group(2)

cited = {}
for f in sys.argv[2:]:
    text = Path(f).read_text(encoding="utf-8")
    for m in re.finditer(r"\bCR\s+((?:\d{3}\.\d+[a-z]?(?:[–-]\d{3}\.\d+[a-z]?)?)(?:\s*(?:,|and|/)\s*\d{3}\.\d+[a-z]?)*)", text):
        for num in re.findall(r"\d{3}\.\d+[a-z]?", m.group(0)):
            cited.setdefault(num, set()).add(Path(f).parent.name + "/" + Path(f).name)
    for m in re.finditer(r"\b(\d{3}\.\d+[a-z]?)\b", text):
        num = m.group(1)
        if num.startswith(("7", "1", "2", "3", "4", "5", "6")) and "." in num:
            cited.setdefault(num, set()).add(Path(f).parent.name + "/" + Path(f).name)

missing = []
for num in sorted(cited, key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)]):
    body = rules.get(num)
    if body is None:
        missing.append(num)
        print(f"MISSING {num:8s} in {sorted(cited[num])}")
    else:
        print(f"ok      {num:8s} {body[:70]}")
sys.exit(1 if missing else 0)
