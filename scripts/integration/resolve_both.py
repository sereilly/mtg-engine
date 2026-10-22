"""Resolve every conflict in a file by keeping both sides, ours first.

Asserts the number of conflicts it expected, so a file with a second, unread
conflict is refused rather than resolved blind.
"""
import sys
from pathlib import Path

path, expected = Path(sys.argv[1]), int(sys.argv[2])
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
out, state, seen = [], "plain", 0
for line in lines:
    if line.startswith("<<<<<<< "):
        assert state == "plain"; state = "ours"; seen += 1; continue
    if line.startswith("=======") and line.rstrip("\r\n") == "=======" and state == "ours":
        state = "theirs"; continue
    if line.startswith(">>>>>>> "):
        assert state == "theirs"; state = "plain"; continue
    out.append(line)
assert state == "plain", "unterminated conflict"
assert seen == expected, f"expected {expected} conflicts, found {seen}"
path.write_text("".join(out), encoding="utf-8", newline="")
print(f"resolved {seen} conflict(s) in {path}")
