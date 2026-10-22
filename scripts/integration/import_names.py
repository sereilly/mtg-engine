"""Every `from X import Y` in engine/, web/ and scripts/ resolves — function-level ones too.

    import_names.py            run from the root of the tree to check

A module split moves names, and a merge of two splits can move a name out
from under an import the other branch wrote. A module-level import that
broke fails at import time; a **function-level** one waits for its line to
run, and the missing-name scan cannot see it (the name *is* imported — from
a module that no longer has it). This imports every module an import
statement names and asks it for every name the statement pulls. Exit 1 on
any that does not resolve.
"""
import ast
import importlib
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def package_of(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    else:
        parts = parts[:-1]
    return ".".join(parts)


failures = []
checked = 0
for top in ("engine", "web", "scripts"):
    for path in sorted((ROOT / top).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # An import under `if TYPE_CHECKING:` is never executed; annotations
        # under `from __future__ import annotations` are never evaluated.
        type_only = {
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING")
            for inner in ast.walk(node)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module == "__future__":
                continue
            if id(node) in type_only:
                continue
            if node.level:
                base = package_of(path).split(".")
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            elif top == "scripts" and node.module and (ROOT / "scripts" / f"{node.module.split('.')[0]}.py").exists():
                target = node.module
            else:
                target = node.module
                if not (target.startswith(("engine", "web", "tests")) or top == "scripts"):
                    continue
            try:
                module = importlib.import_module(target)
            except ModuleNotFoundError:
                if top == "scripts" and not target.startswith(("engine", "web")):
                    continue  # a third-party module a script names
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno} no module {target}")
                continue
            except Exception as exc:  # noqa: BLE001 - report, never mask
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno} importing {target}: {exc!r}")
                continue
            for alias in node.names:
                checked += 1
                if alias.name == "*" or hasattr(module, alias.name):
                    continue
                try:
                    importlib.import_module(f"{target}.{alias.name}")
                except ModuleNotFoundError:
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} {target} has no {alias.name}"
                    )

print(f"checked {checked} imported names")
for line in failures:
    print("UNRESOLVED", line)
print(f"unresolved: {len(failures)}")
sys.exit(1 if failures else 0)
