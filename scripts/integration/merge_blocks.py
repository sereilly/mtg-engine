"""Resolve append-append conflicts in per-set test files during a merge.

    merge_blocks.py <branch> [file ...]     (files default to every unmerged
                                             tests/sets/test_*.py)

For each file: read merge base, ours (HEAD) and theirs (the branch) as **bytes**
from git, assert both sides start with the base byte for byte (a side that
edited the shared prefix cannot be reconstructed and must be read by hand),
write base + ours-tail + theirs-tail, and `git add` it. Then the survival
sweep: every non-blank line of the branch's tail must be in the merged file.
"""
import subprocess
import sys


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


branch = sys.argv[1]
files = sys.argv[2:] or [
    f for f in git("diff", "--name-only", "--diff-filter=U").decode().split("\n")
    if f.startswith("tests/sets/test_") and f.endswith(".py")
]
base_rev = git("merge-base", "HEAD", branch).decode().strip()
crlf = git("config", "--get", "core.autocrlf").decode().strip().lower() == "true"
failed = False
for path in files:
    base = git("show", f"{base_rev}:{path}")
    ours = git("show", f"HEAD:{path}")
    theirs = git("show", f"{branch}:{path}")
    if not ours.startswith(base) or not theirs.startswith(base):
        who = "ours" if not ours.startswith(base) else "theirs"
        print(f"REFUSED {path}: {who} edited the shared prefix - resolve by hand")
        failed = True
        continue
    ours_tail, theirs_tail = ours[len(base):], theirs[len(base):]
    merged = base + ours_tail
    if theirs_tail.strip():
        if not merged.endswith(b"\n"):
            merged += b"\n"
        if ours_tail.strip() and not merged.endswith(b"\n\n\n"):
            merged += b"\n" * (3 - (len(merged) - len(merged.rstrip(b"\n"))))
        merged += theirs_tail.lstrip(b"\n")
    out = merged.replace(b"\r\n", b"\n")
    if crlf:
        out = out.replace(b"\n", b"\r\n")
    with open(path, "wb") as fh:
        fh.write(out)
    lines = set(merged.replace(b"\r\n", b"\n").split(b"\n"))
    lost = [l for l in theirs_tail.replace(b"\r\n", b"\n").split(b"\n") if l.strip() and l not in lines]
    lost += [l for l in ours_tail.replace(b"\r\n", b"\n").split(b"\n") if l.strip() and l not in lines]
    if lost:
        print(f"LOST {len(lost)} line(s) in {path}: {lost[:3]}")
        failed = True
        continue
    subprocess.run(["git", "add", path], check=True)
    print(f"ok {path}: base {len(base.splitlines())} + ours {len(ours_tail.splitlines())} + theirs {len(theirs_tail.splitlines())} lines")
sys.exit(1 if failed else 0)
