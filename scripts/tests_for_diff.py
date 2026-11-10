"""Which tests does this diff owe, and what will they cost before they start?

    tests_for_diff.py                    the list, with each file's recorded time
    tests_for_diff.py --why              ... and why each file is on it
    tests_for_diff.py --run [-n N]       run them: the quick tests only (`pytest --quick`)
    tests_for_diff.py --run --full       ... with their `full` tests and whole censuses
    tests_for_diff.py --censuses --list  only the registry censuses, one path a line
                                         (what `scripts/integration/meeting.sh` adds)

The diff is the working tree against ``--base`` (default: the merge-base of
HEAD and ``main``), untracked files included. Three reasons put a test file
on the list:

1. **changed** — the diff added or edited it, or edited a test helper it imports.
2. **imports** — it imports a changed ``engine/``, ``web/`` or ``scripts/``
   module directly. A module more than ``--hub`` test files import is named,
   not listed: a change to ``engine/game.py`` owes the quick pass, not a list.
3. **census** — it reads a registry whose members the diff added or removed:
   the keys of a module-level dict, or the members of a set, list or tuple,
   named in capitals in ``engine/``. Both trees are imported — HEAD's working
   tree, and the base's ``engine/`` and ``data/`` from ``git archive`` (cached
   under ``.worktrees/scratch/_tests_for_diff/``) — and their registries
   compared. This is the class no meeting list named: Mirrodin's wave-close
   gate found eight reds, each a census "every member of registry R is
   classified" in a file no branch had edited, after a branch added to R
   from a module the census never imports.

The times are ``tests/passes.py``'s record (``.test_timings.json``: this tree's,
over the main checkout's), split into the quick tests and the ``full`` ones,
so an agent can choose before a run that would take an hour. A file with no
record is marked ``?``.

Named files run whole in pytest (their ``full`` tests too); ``--run`` passes
``--quick`` so the list costs what its quick tests cost, unless ``--full``.
"""

from __future__ import annotations

import argparse
import ast
import enum
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("engine", "web", "scripts")
HUB_DEFAULT = 60
CACHE_DIR_NAME = "_tests_for_diff"
DUMP_FLAG = "--dump-registries"


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        encoding="utf-8",
    ).stdout


def main_checkout() -> Path:
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common).parent


def resolve_base(base: str | None) -> str:
    if base:
        return git("rev-parse", base).strip()
    return git("merge-base", "HEAD", "main").strip()


def changed_files(base: str) -> list[str]:
    tracked = git("diff", "--name-only", "--diff-filter=AMR", base).split()
    untracked = git("ls-files", "--others", "--exclude-standard").split()
    return sorted({p for p in tracked + untracked if p.endswith(".py") and (ROOT / p).is_file()})


# ---------------------------------------------------------------------------
# registries: dumped by importing a tree's engine in a process of its own
# ---------------------------------------------------------------------------


def _member(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        return repr(value)
    if isinstance(value, enum.Enum):
        return f"{type(value).__name__}.{value.name}"
    if isinstance(value, tuple) and value and all(
        isinstance(v, (str, int)) and not isinstance(v, bool) for v in value
    ):
        return repr(value)
    return None


def _members(value) -> list[str] | None:
    if isinstance(value, Mapping):
        items = list(value.keys())
    elif isinstance(value, (set, frozenset, list, tuple)):
        items = list(value)
    else:
        return None
    out = sorted({m for m in map(_member, items) if m is not None})
    return out or None


def dump_registries() -> dict:
    """Every capitals-named container in the engine of the cwd's tree, keyed
    ``module:NAME`` by the module that assigns it, with every alias."""
    import importlib
    import pkgutil

    sys.path.insert(0, os.getcwd())
    import engine

    failed = []
    for info in pkgutil.walk_packages(engine.__path__, "engine."):
        try:
            importlib.import_module(info.name)
        except Exception as error:  # a module that cannot import holds no registry we can read
            failed.append(f"{info.name}: {type(error).__name__}")
    by_id: dict[int, dict] = {}
    for name, module in sorted(sys.modules.items()):
        if not (name == "engine" or name.startswith("engine.")) or module is None:
            continue
        for attr, value in vars(module).items():
            if not attr.lstrip("_") or not attr.isupper():
                continue
            members = _members(value)
            if members is None:
                continue
            entry = by_id.setdefault(id(value), {"aliases": [], "members": members})
            entry["aliases"].append([name, attr])
    registries = {}
    for entry in by_id.values():
        home = _assigning_alias(entry["aliases"]) or entry["aliases"][0]
        registries[f"{home[0]}:{home[1]}"] = entry
    return {"registries": registries, "failed": failed}


def _assigning_alias(aliases: list[list[str]]) -> list[str] | None:
    for module_name, attr in aliases:
        module = sys.modules.get(module_name)
        path = getattr(module, "__file__", None)
        if not path:
            continue
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        if re.search(rf"^{re.escape(attr)}\s*(:[^=\n]*)?=", text, re.M):
            return [module_name, attr]
    return None


def registries_of(tree: Path) -> dict:
    run = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), DUMP_FLAG],
        cwd=tree, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "MTG_NO_PROGRAM_STORE": "1"},
    )
    if run.returncode != 0:
        raise SystemExit(f"could not read the registries of {tree}:\n{run.stderr[-2000:]}")
    return json.loads(run.stdout)


def base_tree(sha: str) -> Path:
    """The base's ``engine/`` and ``data/``, extracted once per commit."""
    cache = main_checkout() / ".worktrees" / "scratch" / CACHE_DIR_NAME
    tree = cache / sha
    if (tree / ".complete").exists():
        return tree
    tree.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "archive", "--format=tar", sha, "engine", "data"],
        cwd=ROOT, check=True, capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(tree, filter="data")
    (tree / ".complete").write_text(sha, encoding="utf-8")
    _prune_bases(cache, keep=tree)
    return tree


#: Bases kept in the cache (~40 MB each; a round's meetings name one apiece).
KEEP_BASES = 8


def _prune_bases(cache: Path, keep: Path) -> None:
    """Drop all but the newest :data:`KEEP_BASES` extracted bases."""
    import shutil

    bases = sorted(
        (d for d in cache.iterdir() if d.is_dir() and d != keep),
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    for stale in bases[KEEP_BASES - 1:]:
        shutil.rmtree(stale, ignore_errors=True)


def base_registries(sha: str) -> dict:
    tree = base_tree(sha)
    cached = tree / "registries.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    dumped = registries_of(tree)
    cached.write_text(json.dumps(dumped), encoding="utf-8")
    return dumped


def moved_registries(before: dict, after: dict) -> dict[str, dict]:
    """Registries present in both trees whose members differ, keyed as in *after*."""
    by_name: dict[str, list[str]] = {}
    for key in before:
        by_name.setdefault(key.split(":", 1)[1], []).append(key)
    moved = {}
    for key, entry in after.items():
        old = before.get(key)
        if old is None:
            same_name = by_name.get(key.split(":", 1)[1], [])
            old = before[same_name[0]] if len(same_name) == 1 else None
        if old is None:
            continue
        added = sorted(set(entry["members"]) - set(old["members"]))
        removed = sorted(set(old["members"]) - set(entry["members"]))
        if added or removed:
            moved[key] = {"aliases": entry["aliases"], "added": added, "removed": removed}
    return moved


# ---------------------------------------------------------------------------
# the test side
# ---------------------------------------------------------------------------


def _test_modules() -> list[Path]:
    return sorted(
        p for p in (ROOT / "tests").rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_")


def _dotted(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


#: Calls that walk the container they are handed.
_WALKERS = frozenset({
    "sorted", "set", "list", "frozenset", "tuple", "dict", "len", "enumerate",
    "any", "all", "sum", "min", "max", "zip", "iter", "Counter",
})
_VIEWS = frozenset({"keys", "values", "items"})


class _Imports:
    """What one module imports — modules, and names from modules, resolved to
    absolute dotted names (relative imports inside ``tests/`` included) — and
    which imported names it *enumerates*: iterates, walks with ``sorted`` /
    ``set`` / ``len`` / ..., reads through ``.keys()`` / ``.items()``, or tests
    membership in (``key not in R``, a census over the pool's keys).

    Enumerating is what a census does ("every member of R is classified"); a
    test that looks one handler up in ``EFFECT_HANDLERS`` reads the registry
    without being owed a run when a member arrives (Mirrodin's replay: 314 of
    the 520 census rows a plain read listed were lookups)."""

    def __init__(self, path: Path, text: str):
        self.modules: dict[str, str] = {}      # local name -> module
        self.names: set[tuple[str, str]] = set()  # (module, name)
        self.enumerated: set[tuple[str, str]] = set()
        bound: dict[str, tuple[str, str]] = {}  # local name -> (module, name)
        package = _dotted(path).rsplit(".", 1)[0]
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    self.modules[local] = alias.name if alias.asname else alias.name.split(".")[0]
                    self.modules.setdefault(alias.name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".")
                    parts = parts[: len(parts) - node.level + 1]
                    base = ".".join(parts + ([base] if base else []))
                for alias in node.names:
                    self.names.add((base, alias.name))
                    bound[alias.asname or alias.name] = (base, alias.name)
                    # `from engine import oracle` binds a module.
                    self.modules[alias.asname or alias.name] = f"{base}.{alias.name}"

        def resolve(expr) -> tuple[str, str] | None:
            if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute)                     and expr.func.attr in _VIEWS:
                return resolve(expr.func.value)
            if isinstance(expr, ast.Name):
                return bound.get(expr.id)
            if isinstance(expr, ast.Attribute):
                chain, value = [], expr
                while isinstance(value, ast.Attribute):
                    chain.append(value.attr)
                    value = value.value
                if isinstance(value, ast.Name) and value.id in self.modules:
                    dotted = [self.modules[value.id], *reversed(chain)]
                    return ".".join(dotted[:-1]), dotted[-1]
            return None

        walked = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                walked.append(node.iter)
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                if name in _WALKERS:
                    walked.extend(node.args)
                if isinstance(func, ast.Attribute) and func.attr in _VIEWS:
                    walked.append(func.value)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.BitOr, ast.BitAnd, ast.BitXor)):
                walked.extend((node.left, node.right))
            elif isinstance(node, ast.Starred):
                walked.append(node.value)
            elif isinstance(node, ast.Compare):
                # `key not in R` over a pool's keys: membership is a census of R.
                walked.extend(
                    right for op, right in zip(node.ops, node.comparators)
                    if isinstance(op, (ast.In, ast.NotIn))
                )
        for expr in walked:
            found = resolve(expr)
            if found is not None:
                self.enumerated.add(found)

    def imports_module(self, module: str) -> bool:
        if module in self.modules.values():
            return True
        return any(m == module or f"{m}.{n}" == module for m, n in self.names)

    def enumerates(self, module: str, name: str) -> bool:
        return (module, name) in self.enumerated


_TEXTS: dict[Path, str] = {}
_PARSED: dict[Path, _Imports] = {}


def _text(path: Path) -> str:
    if path not in _TEXTS:
        _TEXTS[path] = path.read_text(encoding="utf-8", errors="replace")
    return _TEXTS[path]


def _scan(paths: list[Path], needles: set[str]) -> dict[Path, _Imports]:
    """Parse only the modules whose text holds one of *needles* (each once)."""
    found = {}
    for path in paths:
        text = _text(path)
        if any(n in text for n in needles):
            if path not in _PARSED:
                _PARSED[path] = _Imports(path, text)
            found[path] = _PARSED[path]
    return found


def _with_helper_importers(
    hits: dict[Path, str], modules: list[Path], hub: int, hubs: list[tuple[str, int]],
) -> dict[Path, str]:
    """Carry a hit in a test helper to the test files importing it, to a
    fixpoint — except a helper more than *hub* files import (``tests.helpers``,
    ``tests.passes``), which is named in *hubs* instead."""
    hits = dict(hits)
    pending = [p for p in hits if not _is_test_file(p)]
    seen: set[Path] = set()
    while pending:
        helper_path = pending.pop()
        if helper_path in seen:
            continue
        seen.add(helper_path)
        helper = _dotted(helper_path)
        importers = [
            path for path, imports in _scan(modules, {helper.rsplit(".", 1)[-1]}).items()
            if path != helper_path and imports.imports_module(helper)
        ]
        if len(importers) > hub:
            hubs.append((helper, len(importers)))
            continue
        for path in importers:
            if path not in hits:
                hits[path] = f"{hits[helper_path]} (via {helper})"
                if not _is_test_file(path):
                    pending.append(path)
    return hits


def pick(base: str, *, hub: int, censuses_only: bool = False) -> dict:
    changed = changed_files(base)
    modules = _test_modules()
    picked: dict[Path, tuple[str, str]] = {}   # path -> (reason, detail)
    hubs: list[tuple[str, int]] = []

    def take(hits: dict[Path, str], reason: str) -> None:
        for path, detail in _with_helper_importers(hits, modules, hub, hubs).items():
            if _is_test_file(path) and path not in picked:
                picked[path] = (reason, detail)

    if not censuses_only:
        tests_changed = {ROOT / p: "edited" for p in changed if p.startswith("tests/")}
        take(tests_changed, "changed")
        sources = [p for p in changed if p.split("/", 1)[0] in SOURCE_DIRS]
        for source in sources:
            module = _dotted(ROOT / source)
            stem = module.rsplit(".", 1)[-1]
            hits = {}
            for path, imports in _scan(modules, {stem}).items():
                if imports.imports_module(module):
                    hits[path] = module
            if source.startswith("scripts/"):
                pattern = re.compile(rf"scripts[/.]{re.escape(stem)}\b|^\s*(from|import) {re.escape(stem)}\b", re.M)
                for path in modules:
                    if path not in hits and pattern.search(_text(path)):
                        hits[path] = module
            if len(hits) > hub:
                hubs.append((module, len(hits)))
                continue
            take(hits, "imports")

    after = registries_of(ROOT)
    before = base_registries(base)
    moved = moved_registries(before["registries"], after["registries"])
    for key, entry in moved.items():
        names = {attr for _, attr in entry["aliases"]}
        hits = {}
        for path, imports in _scan(modules, names).items():
            if any(imports.enumerates(m, a) for m, a in entry["aliases"]):
                hits[path] = key
        take(hits, "census")
    return {
        "base": base, "changed": changed, "picked": picked, "hubs": hubs,
        "moved": moved, "unreadable": after["failed"],
    }


# ---------------------------------------------------------------------------
# times
# ---------------------------------------------------------------------------


def recorded_times() -> dict[str, list]:
    sys.path.insert(0, str(ROOT))
    try:
        from tests.passes import read_timings
    except ImportError:  # a tree from before the record (a replay of an old commit)
        return {}
    times = read_timings(main_checkout())
    times.update(read_timings(ROOT))
    return times


def file_times(times: dict[str, list]) -> dict[str, tuple[float, float]]:
    per_file: dict[str, list[float]] = {}
    for nodeid, (seconds, full) in times.items():
        quick_full = per_file.setdefault(nodeid.split("::", 1)[0], [0.0, 0.0])
        quick_full[1 if full else 0] += seconds
    return {path: (q, f) for path, (q, f) in per_file.items()}


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", help="the ref to diff against (default: merge-base of HEAD and main)")
    parser.add_argument("--why", action="store_true", help="say why each file is listed")
    parser.add_argument("--list", action="store_true", help="paths only, one a line")
    parser.add_argument("--censuses", action="store_true", help="only the registry censuses")
    parser.add_argument("--hub", type=int, default=HUB_DEFAULT,
                        help=f"name, not list, a module more test files import (default {HUB_DEFAULT})")
    parser.add_argument("--run", action="store_true", help="run the listed files")
    parser.add_argument("--full", action="store_true", help="with --run: their full tests too")
    parser.add_argument("-n", "--workers", type=int, default=2, help="with --run: xdist workers (default 2)")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == [DUMP_FLAG]:
        json.dump(dump_registries(), sys.stdout)
        return 0
    args = build_parser().parse_args(argv)
    os.chdir(ROOT)
    base = resolve_base(args.base)
    result = pick(base, hub=args.hub, censuses_only=args.censuses)
    picked = result["picked"]
    paths = sorted(p.relative_to(ROOT).as_posix() for p in picked)
    if args.list:
        print("\n".join(paths))
        return 0

    times = file_times(recorded_times())
    print(f"base {base[:10]}; {len(result['changed'])} changed .py file(s)")
    for key, entry in sorted(result["moved"].items()):
        print(f"registry moved: {key} (+{len(entry['added'])} -{len(entry['removed'])})"
              + (f"  e.g. {', '.join(entry['added'][:3])}" if entry["added"] else ""))
    for module, count in dict.fromkeys(result["hubs"]):
        print(f"hub, not listed: {module} ({count} test files import it) — it owes the quick pass")
    if result["unreadable"]:
        print(f"modules that would not import (their registries unread): {result['unreadable']}")
    quick_total = full_total = 0.0
    unknown = 0
    rows = []
    for path in paths:
        quick, full = times.get(path, (None, None))
        reason, detail = picked[ROOT / path]
        if quick is None:
            unknown += 1
        else:
            quick_total += quick
            full_total += full
        rows.append((quick if quick is not None else -1.0, full, path, reason, detail))
    if rows:
        print(f"{'quick s':>8} {'full s':>8}  {'why':<8} file")
    for quick, full, path, reason, detail in sorted(rows, reverse=True):
        q = "?" if quick < 0 else f"{quick:.1f}"
        f = "" if quick < 0 or not full else f"{full:.1f}"
        line = f"{q:>8} {f:>8}  {reason:<8} {path}"
        print(line + (f"   [{detail}]" if args.why else ""))
    print(
        f"{len(paths)} file(s): quick {quick_total:.0f} s serial "
        f"(~{quick_total / max(args.workers, 1):.0f} s at -n {args.workers}); "
        f"their full tests {full_total:.0f} s more"
        + (f"; {unknown} with no recorded time" if unknown else "")
    )
    if not args.run or not paths:
        return 0
    command = [sys.executable, "-m", "pytest", "-n", str(args.workers), "--dist", "worksteal",
               "-q", "-p", "no:cacheprovider", *([] if args.full else ["--quick"]), *paths]
    print("running:", " ".join(command[1:6]), "...", f"({len(paths)} files)", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
