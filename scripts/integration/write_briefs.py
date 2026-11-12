"""Write a set's wave-1 common brief (and each group's brief skeleton) from the census.

    write_briefs.py CODE --groups <groups.json> --census <census-dir> --out <scratch>
                    [--base-branch <round>/base] [--yield <YIELD.md>] [--memory "<sentence>"]

Run from the root of a tree with CODE ingested (the wave's base). Fills
``brief_templates/common_w1.md`` — Darksteel's hand-written brief with every
set-specific passage made a ``{{PLACEHOLDER}}`` — and writes
``<out>/BRIEF_COMMON_W1.md``, plus ``<out>/<group>/BRIEF.md`` skeletons for any
group that has none (its cards, drive list, worktree, test sections, and a
TODO where the integrator writes the shapes and boundaries). It never
overwrites a group brief.

Why: the common brief is ~500 lines and was rewritten for every set from the
last one, so a rule the last set corrected (a subagent cannot write a report
file; both differentials' snapshots before the first edit; never ``sed -i``;
the base's known reds) was lost unless the integrator re-typed it. The rules
live in the template once; what changes per set is computed here:

- the counts (``<code>_support.log``), the hollow and unclaimed cards
  (``_hollow.log``, ``_parse.log``), new-to-pool and the origin trap
  (``_new.log``), the picker findings (``_picker.log``);
- the keywords the set prints that ``IMPLEMENTED_KEYWORDS`` lacks, each
  classified by asking ``line_rewrites.expand_ability_lines`` whether it
  rewrites a printed line (a rewrite keyword ships by design) — the rest are
  the set's candidate new keywords;
- the group list (``groups.json``); the base's commits (``git log``); the size
  band and the near-cap modules (line counts, as ``headroom.py`` reads them);
  the per-set test files' sections (their markers); the yield table;
- free commit memory (Windows ``GlobalMemoryStatusEx``) unless ``--memory``.

Every judgment the census cannot make is left as a ``TODO:`` line in the
output; the integrator reads the file before sending it.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

TEMPLATE = Path(__file__).with_name("brief_templates") / "common_w1.md"
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen"}
REPO_PATH = Path(os.getcwd())


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _number(n: int) -> str:
    return NUMBER_WORDS.get(n, str(n))


# --- the census logs --------------------------------------------------------------


def support_counts(census: Path, low: str) -> dict:
    text = _read(census / f"{low}_support.log")
    grab = lambda label: int(re.search(rf"{label}:\s*(\d+)", text).group(1)) if re.search(rf"{label}:\s*(\d+)", text) else None
    return {"total": grab("Total cards"), "supported": grab("Supported cards"),
            "unsupported": grab("Unsupported cards")}


def hollow_cards(census: Path, low: str) -> list[str]:
    names = []
    for line in _read(census / f"{low}_hollow.log").splitlines():
        m = re.match(r"\s{2}(.+?) \[(activated|triggered|static|spell)\]:", line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def unclaimed_cards(census: Path, low: str) -> list[str]:
    names, current = [], None
    for line in _read(census / f"{low}_parse.log").splitlines():
        if line and not line.startswith(" ") and not line.startswith(("Pool:", "exit=")) and "cards analysed" not in line:
            current = line.strip()
        elif current and line.strip().startswith("unclaimed:") and current not in names:
            names.append(current)
    return names


def new_to_pool(census: Path, low: str) -> tuple[int | None, list[str]]:
    text = _read(census / f"{low}_new.log")
    m = re.search(r"new to the pool \((\d+)\)", text)
    trap = re.search(r"reprints whose only other printings are LATER than \w+ \((\d+)\): (\[.*?\])", text)
    later = json.loads(trap.group(2).replace("'", '"')) if trap else []
    return (int(m.group(1)) if m else None), later


def picker_findings(census: Path, low: str) -> int | None:
    m = re.search(r"Picker findings:\s*(\d+)", _read(census / f"{low}_picker.log"))
    return int(m.group(1)) if m else None


# --- the engine's own answers ---------------------------------------------------


def set_cards(code: str):
    from engine.card_loader import load_cards, manifest_set_path
    return load_cards(manifest_set_path(code, include_measured=True))


def set_name(code: str) -> str:
    from engine.card_loader import manifest_measured_sets, manifest_sets
    for entry in manifest_measured_sets() + manifest_sets():
        if entry["code"].upper() == code:
            return entry.get("name", code)
    return code


def refused_lines(census: Path, low: str) -> list[str]:
    """Every line the census's refusal log names as refused or unlowered."""
    lines = []
    for line in _read(census / f"{low}_refusals.log").splitlines():
        m = re.match(r"^\s{2}(?:refused|unlowered): (.+)$", line)
        if m:
            lines.append(m.group(1).strip())
    return lines


def keyword_reading(code: str, census: Path, low: str) -> tuple[list[str], list[str], list[str]]:
    """(rewrites, keywords with a reader of their own, keywords nothing reads)
    — the last the set's candidate new keywords. Of the keywords the set's
    cards print (their ingested ``keywords`` field) that
    ``IMPLEMENTED_KEYWORDS`` lacks, a keyword *action* (Scryfall's catalog,
    ``data/vocabulary/keyword_actions.json``: scry, regenerate) is not a
    keyword line and is left out, and so is an ability word (CR 207.2c,
    ``ability_words.json``: imprint, threshold), which has no rules meaning.
    Each keyword is judged by **its own line**, never by the card's other
    lines: it is a rewrite when ``expand_ability_lines`` changes a printed line
    that starts with it (Fifth Dawn's Opaline Bracers once made Sunburst read
    as a rewrite through its Equip line); it is read by nothing when the
    census refused a line that starts with it; otherwise it has a reader of
    its own (Enchant, the Aura code — even on a card whose *other* line is
    refused, as Dawn's Reflection's is)."""
    from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS
    from engine.line_rewrites import expand_ability_lines
    vocab = REPO_PATH / "data" / "vocabulary"
    skipped = set()
    for name in ("keyword_actions.json", "ability_words.json"):
        if (vocab / name).exists():
            skipped |= {a.lower() for a in json.loads((vocab / name).read_text(encoding="utf-8"))}
    implemented = {k.lower() for k in IMPLEMENTED_KEYWORDS}
    refused = [line.lower() for line in refused_lines(census, low)]
    by_keyword: dict[str, list] = {}
    for card in set_cards(code):
        for keyword in getattr(card, "keywords", ()) or ():
            if keyword.lower() not in implemented and keyword.lower() not in skipped:
                by_keyword.setdefault(keyword, []).append(card)
    rewrites, own_reader, missing = [], [], []
    for keyword, cards in sorted(by_keyword.items()):
        word = keyword.lower()
        rewritten = False
        for card in cards:
            printed = [l for l in (card.oracle_text or "").splitlines() if l.lower().startswith(word)]
            expanded = set(expand_ability_lines(card.oracle_text or "", card_name=card.name).splitlines())
            if any(l not in expanded for l in printed):
                rewritten = True
        label = f"{keyword} ({len(cards)})"
        if rewritten:
            rewrites.append(label)
        elif any(line.startswith(word) for line in refused):
            missing.append(label)
        else:
            own_reader.append(label)
    return rewrites, own_reader, missing


# --- the tree -----------------------------------------------------------------------


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def module_sizes(floor: int) -> list[tuple[int, str]]:
    sizes = []
    for top in ("engine", "web", "scripts"):
        for path in (REPO_PATH / top).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            n = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
            if n >= floor:
                sizes.append((n, path.relative_to(REPO_PATH).as_posix()))
    return sorted(sizes, reverse=True)


def per_set_sections(low: str) -> dict[str, list[str]]:
    files = {}
    for path in sorted((REPO_PATH / "tests" / "sets").glob(f"test_{low}_*.py")):
        groups = re.findall(r"^# ==== (?!end )(\S+) =", path.read_text(encoding="utf-8"), re.M)
        files[path.name] = groups
    return files


def free_commit_gb() -> float | None:
    if os.name != "nt":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullAvailPageFile / 2**30


# --- the sections -------------------------------------------------------------------


def state_of_the_set(code, low, name, groups, census, scratch) -> str:
    counts = support_counts(census, low)
    hollow = sorted(set(hollow_cards(census, low)) | set(unclaimed_cards(census, low)))
    new, trap = new_to_pool(census, low)
    picker = picker_findings(census, low)
    rewrites, own_reader, missing = keyword_reading(code, census, low)
    total, supported, unsupported = counts["total"], counts["supported"], counts["unsupported"]
    todo = (unsupported or 0) + len(hollow)
    reprints = (total or 0) - (new or 0)
    trap_sentence = ("no origin trap" if not trap else
                     f"**the origin trap names {', '.join(trap)}** — its insert position decides their origin")
    lines = [
        f"{name} is ingested under the manifest's `measured` role: **{total} cards, {new}",
        f"new to the pool** ({_number(reprints)} reprint(s) whose first printing already ships; "
        f"{trap_sentence}). `set_pool(\"{code}\")` / `set_cards(\"{code}\")` resolve it in tests. "
        f"`scripts/support_report.py --set {code}` (with `--refusals`, `--hollow-lines`, "
        f"`--fragments`), `scripts/parse_coverage.py --set {code} --workers 2` and "
        f"`scripts/picker_sweep.py --set {code}` all work on it.",
    ]
    picker_words = "names no card" if not picker else f"names {picker} card{'s' if picker != 1 else ''}"
    lines += [
        "",
        f"**{supported} report supported on arrival, and {_number(len(hollow))} of those carry a "
        f"sentence nothing implements** (`parse_coverage` and `--hollow-lines` see them; the "
        f"support count does not): {', '.join(hollow) or 'none'}. So the real work list is "
        f"**{todo} cards** ({unsupported} unsupported + {len(hollow)}), and every one has exactly one "
        f"owner below. The census outputs are in `{census}` (`{low}_refusals.log`, `{low}_fragments.log`, "
        f"`{low}_parse.log`, `{low}_hollow.log`, `{low}_picker.log`, `{low}_table.txt`). The picker "
        f"sweep {picker_words}.",
        "",
        f"**Keywords the set prints that `IMPLEMENTED_KEYWORDS` lacks:** rewrites that ship "
        f"(absent by design): {', '.join(rewrites) or 'none'}; read by a reader of their own: "
        f"{', '.join(own_reader) or 'none'}; **read by nothing yet**: "
        f"{', '.join(missing) or 'none'}.",
        "TODO: one sentence on the set's new mechanics and which group owns each.",
        "",
        "Each shape has one owner:",
        "",
    ]
    for group, spec in groups.items():
        lines.append(f"- **{group.upper()} — {spec['title']}** ({len(spec['cards'])}).")
    lines += [
        "",
        f"**A card that compiles is not a card that works.** Your `CARDS.md` ends with a second "
        f"list: {name} cards that are *supported on arrival*, in your family. Nobody has run one. "
        f"After your own cards, give each a headless game: fix what is local, measure and report "
        f"what is not.",
        "",
        "TODO: the 'Reuse before you invent' list below is the engine map Darksteel's brief "
        "carried; cut or add the names this set's families reach.",
    ]
    return "\n".join(lines)


def base_holds(base_branch: str) -> str:
    main = git("rev-parse", "--short=9", "main")
    log = git("log", "--reverse", "--format=%h %s", f"main..{base_branch}")
    items = [f"{i}. `{line.split(' ', 1)[0]}` {line.split(' ', 1)[1]}" for i, line in
             enumerate(log.splitlines(), 1)] or ["(no commits beyond main)"]
    return "\n".join([f"Your base is `main` (`{main}`) plus these commits on `{base_branch}`:", "", *items])


def size_cap() -> str:
    band = [(n, p) for n, p in module_sizes(1800)]
    near = [(n, p) for n, p in module_sizes(1700) if n < 1800]
    out = ["**The size cap.** No module in `engine/`, `web/` or `scripts/` may pass 2,000 lines."]
    if band:
        out.append("Inside the 200-line band (a group that adds to one must keep it under the "
                   "cap; a module two groups will reach was Phase 0's to split): "
                   + ", ".join(f"`{p}` (**{n:,}, {2000 - n} left**)" for n, p in band) + ".")
    else:
        out.append("No module is inside the 200-line band.")
    if near:
        out.append("Within 300 lines — **add to them sparingly; a new subject belongs in a module "
                   "of its own beside them**: " + ", ".join(f"`{p}` ({n:,})" for n, p in near) + ".")
    out.append("Everything else is unowned; a group that crosses 2,000 splits it in round (code "
               "motion: `oracle_diff` 0 for the move, then your change).")
    return " ".join(out)


def per_set_files(code: str, low: str) -> str:
    files = per_set_sections(low)
    if not files:
        return ("TODO: no per-set test files yet — open them on the base with "
                "`open_test_files.py CODE <groups> [--later creatures,artifacts]` before the fan-out.")
    rows = "\n".join(f"- `tests/sets/{f}`: {', '.join(g) or '(no sections)'}" for f, g in files.items())
    return (f"The per-set test files exist on your base with one marked section per group "
            f"(`# ==== W1G3 ====` … `# ==== end W1G3 ====`):\n\n{rows}\n\n"
            "**Artifact creatures and Equipment are artifacts** (the printed type starts "
            "\"Artifact\"). **Write only between your own markers**, in the file for the printed "
            "type of the card each test names, put your imports at the top of your own section, "
            "and prefix every module-level helper, constant and import alias with `_w1gN_`.")


def yield_section(yield_md: Path | None) -> str:
    if yield_md and yield_md.exists():
        return ("These reds are on your base — **the base's, not yours, unless your group is their "
                "owner**; report any other red you meet the day you see it:\n\n"
                + yield_md.read_text(encoding="utf-8").strip())
    return ("The **full pass** over the ingested tree is being read as you start; the integrator "
            "will message you if a red names one of your cards. **Report any red on your base** "
            "that you meet — that list is the earliest gate there is.")


def group_skeleton(code: str, low: str, round_: str, group: str, spec: dict) -> str:
    # open_test_files.py writes each marker as the group was named on its command
    # line (`w1g1` or `W1G1`), so the section is found whichever case was used.
    sections = [f for f, groups in per_set_sections(low).items()
                if group.upper() in {g.upper() for g in groups}]
    return "\n".join([
        f"# {group.upper()} — {spec['title']}",
        "",
        f"Your cards ({len(spec['cards'])}): {', '.join(spec['cards'])}. Your drive list "
        f"(supported on arrival, nobody has run them) is at the foot of `CARDS.md`. Worktree "
        f"`.worktrees/{round_}-{group}`, branch `{round_}/{group}`, scratch "
        f"`.worktrees/scratch/{round_}/{group}`. Your sections: "
        f"{', '.join('`tests/sets/' + s + '`' for s in sections) or 'TODO'}.",
        "",
        "## Shapes",
        "",
        "TODO: one paragraph per shape — the sentence, the refusal site probe_line names, the "
        "nearest shipped card and module to reuse, the CR rule (checked), the rulings to read.",
        "",
        "## Boundaries",
        "",
        "TODO: what sibling groups own that your cards touch.",
        "",
        f"Rulings: every card above, in `.worktrees/scratch/{round_}/rulings/{low}_rulings.txt`.",
        "",
    ])


def write_wave_two(code: str, low: str, name: str, args) -> int:
    """The wave-2 common brief: wave 1's rules hold, with the changes the
    template states; the base link and its reds are filled, the summary of
    what wave 1 left is the integrator's (a TODO)."""
    template = TEMPLATE.with_name("common_w2.md").read_text(encoding="utf-8")
    template = re.sub(r"\A<!--.*?-->\s*", "", template, flags=re.S)
    reds = []
    if args.base_reds and args.base_reds.exists():
        reds = [l.strip() for l in args.base_reds.read_text(encoding="utf-8").splitlines() if l.strip()]
    fills = {
        "{{SET_NAME}}": name, "{{CODE}}": code, "{{code}}": low,
        "{{W2_BASE}}": args.w2_base or "TODO: the gated link",
        "{{BASE_REDS}}": "\n".join(f"  - {r}" for r in reds) or "  - none known",
        "{{W1_SUMMARY}}": ("TODO: what wave 1 landed and declined, and what wave 2 takes "
                           "(the pile, by subject); how many groups run at once."),
    }
    for key, value in fills.items():
        template = template.replace(key, value)
    leftover = sorted(set(re.findall(r"\{\{[A-Za-z0-9_]+\}\}", template)))
    assert not leftover, f"unfilled placeholders: {leftover}"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "BRIEF_COMMON_W2.md").write_text(template, encoding="utf-8")
    print(f"wrote {args.out / 'BRIEF_COMMON_W2.md'} ({template.count('TODO')} TODO)")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("code")
    ap.add_argument("--groups", required=True, type=Path)
    ap.add_argument("--census", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base-branch")
    ap.add_argument("--round")
    ap.add_argument("--yield", dest="yield_md", type=Path)
    ap.add_argument("--memory")
    ap.add_argument("--wave", type=int, default=1, help="2 writes BRIEF_COMMON_W2.md instead")
    ap.add_argument("--w2-base", help="wave 2: the gated chain link the groups start from")
    ap.add_argument("--base-reds", type=Path,
                    help="wave 2: the reds on that link, one per line ('test-id — card — owner')")
    args = ap.parse_args(argv)
    code = args.code.upper()
    low = code.lower()
    round_ = args.round or low
    base_branch = args.base_branch or f"{round_}/base"
    groups = json.loads(args.groups.read_text(encoding="utf-8"))
    name = set_name(code)
    if args.wave == 2:
        return write_wave_two(code, low, name, args)
    memory = args.memory
    if not memory:
        gb = free_commit_gb()
        memory = (f"About **{gb:.0f} GB of commit is free** as this brief is written" if gb else
                  "TODO: free commit memory (GB)")
    base_commit = git("rev-parse", "--short=9", base_branch) or "TODO"
    fills = {
        "{{SET_NAME}}": name, "{{CODE}}": code, "{{code}}": low,
        "{{N_GROUPS_WORD}}": _number(len(groups)),
        "{{BASE_COMMIT}}": base_commit, "{{BASE_BRANCH}}": base_branch,
        "{{MEMORY}}": memory,
        "{{STATE_OF_THE_SET}}": state_of_the_set(code, low, name, groups, args.census, args.out),
        "{{BASE_HOLDS}}": base_holds(base_branch),
        "{{SIZE_CAP}}": size_cap(),
        "{{PER_SET_FILES}}": per_set_files(code, low),
        "{{YIELD}}": yield_section(args.yield_md),
        "{{HOLLOW_RULE}}": (f"**{name}'s hollow-on-arrival cards are exactly this failure** — do not "
                            f"add another."),
    }
    text = TEMPLATE.read_text(encoding="utf-8")
    text = re.sub(r"\A<!--.*?-->\s*", "", text, flags=re.S)
    for key, value in fills.items():
        text = text.replace(key, value)
    leftover = sorted(set(re.findall(r"\{\{[A-Za-z_]+\}\}", text)))
    assert not leftover, f"unfilled placeholders: {leftover}"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "BRIEF_COMMON_W1.md").write_text(text, encoding="utf-8")
    written = []
    for group, spec in groups.items():
        brief = args.out / group / "BRIEF.md"
        if not brief.exists():
            brief.parent.mkdir(parents=True, exist_ok=True)
            brief.write_text(group_skeleton(code, low, round_, group, spec), encoding="utf-8")
            written.append(group)
    todos = text.count("TODO")
    print(f"wrote {args.out / 'BRIEF_COMMON_W1.md'} ({len(text.splitlines())} lines, {todos} TODO); "
          f"group skeletons: {', '.join(written) or 'none (all exist)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
