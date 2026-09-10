"""One shared, cached read of the repo's source tree for the guard tests.

Around twenty-five files in ``tests/engine/`` are convention guards that sweep
``engine/`` (some also ``web/`` or ``scripts/``) with ``rglob`` + ``read_text``
+ ``ast.parse``. Each did its own sweep, so one suite run parsed the same ~200
files dozens of times — 35-45 seconds of pure repetition. These helpers are
that sweep, done once per process (``lru_cache``; per-worker under xdist,
which is the same safety story every module-level cache in the engine has).

Read-only by contract: callers walk the returned trees and slice the returned
text, never mutate them — a guard that edited a shared AST would corrupt every
guard after it. Nothing here changes what any guard checks; the file lists,
exemption tables and analyses all stay in their guard files.
"""

from __future__ import annotations

import ast
import io
import tokenize
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=None)
def python_files(*roots: str) -> tuple[Path, ...]:
    """Every ``*.py`` under the named repo-relative roots, sorted per root.

    ``python_files("engine", "web")`` matches the common guard sweep; a root
    may also be a subpackage path like ``"engine/grammar"``.
    """
    found: list[Path] = []
    for root in roots:
        found.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return tuple(found)


@lru_cache(maxsize=None)
def source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def source_tree(path: Path) -> ast.Module:
    """The parsed module. Walk it, never mutate it — the tree is shared."""
    return ast.parse(source_text(path))


@lru_cache(maxsize=None)
def code_only_lines(path: Path) -> tuple[str, ...]:
    """*path*'s lines with comments and string literals blanked out.

    The regex guards are about what a module *does*, and this repo explains
    itself in prose: a docstring naming ``permanent.card.oracle_text`` to say
    why a node is not normalized is a description of the rule, not a breach of
    it. Matching it would leave the only fix available being to stop writing
    the sentence down. Line numbers are preserved so a real hit still points at
    its line.

    Shared because two guards ask it of two roots — ``tests/engine`` of
    ``engine/`` and ``tests/ui`` of ``web/`` — and a second copy of a scanner
    is a second answer to "is this line code?".
    """
    source = source_text(path)
    lines = source.splitlines()
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return tuple(lines)  # unparseable: report everything rather than nothing
    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            head = line[:start_col] if row == start_row else ""
            tail = line[end_col:] if row == end_row else ""
            lines[row - 1] = head + " " * (len(line) - len(head) - len(tail)) + tail
    return tuple(lines)
