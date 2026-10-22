"""Generate each group's CARDS.md from the instruments' own output.

    gen_cards.py CODE <log-dir> <groups.json> <out-root>

Run from the root of a tree with the set ingested. <log-dir> holds the
instruments' output for the set: `<code>_refusals.log`
(`support_report.py --set CODE --refusals`), `<code>_hollow.log`
(`--hollow-lines`), `<code>_parse.log` (`parse_coverage.py --set CODE`) and
`<code>_picker.log` (`picker_sweep.py --set CODE`). <groups.json> is
`{group: {"title": ..., "cards": [...], "drive": [...]}}`; `drive` is the
supported-on-arrival cards a group is given to play rather than build.
Writes <out-root>/<group>/CARDS.md, and prints every flagged card no group
was given and every assigned card nothing flagged — both are planning errors.
"""
import io
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402

code, logs, groups_path, out_root = sys.argv[1:5]
low = code.lower()
GROUPS = json.load(io.open(groups_path, encoding="utf-8"))

set_path = next(p for p in manifest_set_paths(include_measured=True)
                if os.path.basename(str(p)).startswith(code))
cards = {c.name: c for c in load_cards([set_path])}


def read(name):
    return io.open(os.path.join(logs, name), encoding="utf-8", errors="replace").read()


refusals = {}
cur = None
for line in read(f"{low}_refusals.log").splitlines():
    if line.startswith("By refusal site"):
        break
    m = re.match(r"^(\S.*?) \[(\w+)\] ", line)
    if m and not line.startswith(("Pool:", "Unsupported", "(")):
        cur = refusals.setdefault(m.group(1), [])
    elif cur is not None and line.startswith("  "):
        cur.append(line.rstrip())

unclaimed = {}
cur = None
for line in read(f"{low}_parse.log").splitlines()[2:]:
    if line and not line.startswith(" "):
        cur = unclaimed.setdefault(line.strip(), [])
    elif cur is not None and line.strip():
        cur.append(line.strip())

hollow = {}
for line in read(f"{low}_hollow.log").splitlines():
    m = re.match(r"^  (.+?) \[(\w+)\]: (.+)$", line)
    if m:
        hollow.setdefault(m.group(1), []).append(m.group(3))

picker = {}
for line in read(f"{low}_picker.log").splitlines():
    m = re.match(r"^  (.+?): (.+)$", line)
    if m:
        picker[m.group(1)] = m.group(2)

assigned = [n for g in GROUPS.values() for n in g["cards"]]
assert len(assigned) == len(set(assigned)), "a card is in two groups: " + str(
    sorted({n for n in assigned if assigned.count(n) > 1}))
driven = [n for g in GROUPS.values() for n in g.get("drive", [])]
assert len(driven) == len(set(driven)), "a driven card is in two groups: " + str(
    sorted({n for n in driven if driven.count(n) > 1}))
missing = [n for n in assigned + driven if n not in cards]
assert not missing, missing
unsupported = {n for n, c in cards.items() if not compile_card_oracle(c).supported}
flagged = unsupported | set(unclaimed) | set(picker) | set(hollow)
print("unassigned but flagged:", sorted(flagged - set(assigned)))
print("assigned but neither unsupported nor flagged:", sorted(set(assigned) - flagged))
print("driven but flagged (should be in a card list):", sorted(set(driven) & flagged))
print("supported, unflagged, in nobody's drive list:",
      sorted(set(cards) - flagged - set(driven)))


def card_block(name, lines):
    card = cards[name]
    program = compile_card_oracle(card)
    lines.append(f"## {name}")
    cost = card.mana_cost or "(no cost)"
    pt = f" — {card.power}/{card.toughness}" if card.power is not None else ""
    lines.append(f"{cost} — {card.type_line}{pt} — layout `{card.layout}`")
    lines.append("")
    for row in (card.oracle_text or "(no text)").split("\n"):
        lines.append(f"> {row}")
    lines.append("")
    status = "supported" if program.supported else f"UNSUPPORTED — {program.reason}"
    lines.append(f"- Status at ingest: **{status}**")
    if name in refusals:
        lines.append("- Refused lines (grammar probe):")
        lines.append("")
        lines.append("```")
        lines.extend(refusals[name])
        lines.append("```")
    if name in unclaimed:
        lines.append("- `parse_coverage`: " + "; ".join(unclaimed[name]))
    if name in hollow:
        lines.append("- `--hollow-lines` (an ability part with no instruction): " + "; ".join(hollow[name]))
    if name in picker:
        lines.append("- `picker_sweep`: names a choice the derivation offers no picker for")
    lines.append("")


for group, spec in GROUPS.items():
    lines = [f"# {group.upper()} — {spec['title']}", "",
             f"Generated from the instruments on the day of the ingest "
             f"(`support_report.py --set {code} --refusals`, `--hollow-lines`, "
             f"`parse_coverage.py --set {code}`, `picker_sweep.py --set {code}`). "
             "A refusal site names where the parser stopped — a work-list entry, not a "
             "diagnosis. Re-run the instruments in your own worktree; do not trust this "
             "file over them.", ""]
    for name in spec["cards"]:
        card_block(name, lines)
    if spec.get("drive"):
        lines += ["---", "",
                  "# Supported on arrival — yours to *drive*, not to build", "",
                  "These compile supported with every instrument quiet. **That is not the "
                  "same as working** — none has been run. See your BRIEF.md for what "
                  "driving them means and how much time it gets.", ""]
        for name in spec["drive"]:
            card_block(name, lines)
    dest = os.path.join(out_root, group)
    os.makedirs(dest, exist_ok=True)
    io.open(os.path.join(dest, "CARDS.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(group, len(spec["cards"]), "cards +", len(spec.get("drive", [])), "driven ->",
          os.path.join(dest, "CARDS.md"))
