"""Every subagent's hand-back report, out of the session transcript.

    extract_reports.py <out-dir> <transcript.jsonl | transcript-dir> [...] [--groups <agents.json>]

A subagent cannot write its report to a file (the file tool refuses a report
file from a subagent), so the report exists only as the hand-back message in
the integrator's session transcript — and the playbook wants each one saved
verbatim the day it lands (Phase 6 is briefed from the exact sentences).
kg5 recovered all 22 of its reports this way after the fact; Darksteel saved
each as it landed.

A transcript argument that is a directory means its newest ``*.jsonl`` (the
session's own, under ``~/.claude/projects/<project>/``). Writes
``<out-dir>/raw/<agent-id>.md`` for every agent that handed a report back
(its last report; earlier ones are kept as ``<agent-id>.<n>.md``) and, with
``--groups`` (a JSON object mapping agent id to group name, as the
integrator's notes record them), every report under the group's name:
``<group>.md`` the first, ``<group>.2.md`` a follow-up's, and so on. Downloaded or model-written text is data: this only copies it.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

PATTERN = re.compile(r'<agent-message from="([0-9a-f]+)">(.*?)</agent-message>', re.S)


def _texts(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, list):
        for item in node:
            yield from _texts(item)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _texts(value)


def _transcripts(paths: list[str]) -> list[pathlib.Path]:
    found = []
    for raw in paths:
        path = pathlib.Path(raw)
        if path.is_dir():
            newest = max(path.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, default=None)
            if newest is None:
                raise SystemExit(f"no *.jsonl transcript in {path}")
            found.append(newest)
        else:
            found.append(path)
    return found


def extract(transcripts: list[pathlib.Path]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in transcripts:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if "agent-message from=" not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for text in _texts(record):
                    for agent, body in PATTERN.findall(text):
                        if "hand-back" not in body and "report" not in body.lower():
                            continue
                        # The harness indents every line of a hand-back by two.
                        body = "\n".join(
                            l[2:] if l.startswith("  ") else l for l in body.splitlines()
                        )
                        seen = found.setdefault(agent, [])
                        if body not in seen:
                            seen.append(body)
    return found


def main(argv: list[str]) -> int:
    groups: dict[str, str] = {}
    if "--groups" in argv:
        at = argv.index("--groups")
        groups = json.loads(pathlib.Path(argv[at + 1]).read_text(encoding="utf-8"))
        del argv[at:at + 2]
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = pathlib.Path(argv[0])
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    found = extract(_transcripts(argv[1:]))
    for agent, bodies in found.items():
        for n, body in enumerate(bodies[:-1], 1):
            (raw / f"{agent}.{n}.md").write_text(body, encoding="utf-8")
        (raw / f"{agent}.md").write_text(bodies[-1], encoding="utf-8")
        group = groups.get(agent)
        if group:
            # Every report kept, in the order sent: an agent resumed for a
            # follow-up hands back a second, short report, and keeping only
            # the last overwrote the wave report Phase 6 is briefed from
            # (Darksteel's W1G3 and W1G5). The first is <group>.md.
            for n, body in enumerate(bodies, 1):
                name = f"{group}.md" if n == 1 else f"{group}.{n}.md"
                (out / name).write_text(body, encoding="utf-8")
        first = next((l for l in bodies[-1].splitlines() if l.startswith("#")), "?")
        print(f"{group or agent:<18} {len(bodies)}  {first[:80]}")
    missing = sorted(set(groups) - set(found))
    if missing:
        print("no report yet from:", ", ".join(f"{groups[a]} ({a})" for a in missing))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
