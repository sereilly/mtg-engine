"""Resolve conflicted table rows by a word-level three-way merge against the base.

Mirrodin's chain met engine/ARCHITECTURE.md's module table at three merges,
each time two branches inserting phrases into the same rows.

    python wordmerge_rows.py <file> <theirs-branch-label>     (run in the merge tree)

For each conflict region, every line of ours is matched to the line of theirs
and of the base (stage 1) that begins with the same table key ("| `module` |");
each triple is merged word by word with `git merge-file`; a word-level
conflict aborts. Lines only theirs has (new rows) are appended after the
region's merged lines; lines only ours has are kept. Line endings preserved.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

path, label = Path(sys.argv[1]), sys.argv[2]
raw = path.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
base_text = subprocess.run(["git", "show", f":1:{path.as_posix()}"], capture_output=True,
                           check=True).stdout.decode("utf-8")
base_rows = {}
for line in base_text.splitlines():
    m = re.match(r"^(\| `[^`]+` \|)", line)
    if m:
        base_rows.setdefault(m.group(1), line)

pat = re.compile(r"<<<<<<< HEAD\r?\n(.*?)=======\r?\n(.*?)>>>>>>> " + re.escape(label) + r"\r?\n", re.S)


def key(line):
    m = re.match(r"^(\| `[^`]+` \|)", line)
    return m.group(1) if m else None


def word_merge(base, ours, theirs):
    with tempfile.TemporaryDirectory() as d:
        files = []
        for name, text in (("o", ours), ("b", base), ("t", theirs)):
            p = Path(d) / name
            p.write_text("\n".join(re.split(r"(?<= )", text)) + "\n", encoding="utf-8")
            files.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", *files], capture_output=True)
        out = r.stdout.decode("utf-8")
        if r.returncode != 0:
            raise SystemExit(f"word conflict in row {key(ours)}:\n{out[:2000]}")
        return "".join(out.splitlines())


out, pos, n = [], 0, 0
for r in pat.finditer(raw):
    out.append(raw[pos:r.start()])
    ours = r.group(1).splitlines()
    theirs = r.group(2).splitlines()
    theirs_by_key = {key(l): l for l in theirs}
    merged = []
    for line in ours:
        k = key(line)
        assert k, line[:80]
        if k in theirs_by_key and k in base_rows:
            merged.append(word_merge(base_rows[k], line, theirs_by_key[k]))
        elif k in theirs_by_key:
            assert line == theirs_by_key[k], k
            merged.append(line)
        else:
            merged.append(line)
    ours_keys = {key(l) for l in ours}
    merged += [l for l in theirs if key(l) not in ours_keys]
    out.append(nl.join(merged) + nl)
    pos = r.end()
    n += 1
out.append(raw[pos:])
path.write_bytes("".join(out).encode("utf-8"))
print(f"{path}: {n} region(s) merged")
