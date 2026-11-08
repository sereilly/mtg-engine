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

**The trees are most of a worker's memory, so they are held once.** The
engine's ~650 modules parse to about 400 MB of trees (2026-11-08), which a
worker keeps for every later sweep; :func:`source_tree` keeps each file's
under one key whatever the spelling of its path, and keeps none of
``tests/``'s. So a guard that sweeps ``engine/`` reads its trees here, never
through a parse of its own (that held a second copy for as long as the test
ran), and nothing parses at import time (a module-level sweep cost every
collecting process those 400 MB, IDE discoveries included). A sweep whose
question is a string skips each file whose text (:func:`source_text`) does not
contain it before asking for a tree.
"""

from __future__ import annotations

import ast
import io
import os
import tokenize
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: Whose trees are parsed for each asking and never kept (see :func:`source_tree`).
TESTS_ROOT = REPO_ROOT / "tests"


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


def source_tree(path: Path) -> ast.Module:
    """The parsed module. Walk it, never mutate it — the tree is shared.

    Kept once per file, however the path is spelled: a guard that asked by a
    relative path held a second copy of every tree it swept, 1.3 GB in the
    full pass (2026-11-08). A file under ``tests/`` is parsed afresh each time
    and not kept — two guards sweep that folder, each once, and keeping its
    trees cost the worker that ran them as much again as the engine's."""
    absolute = Path(os.path.abspath(path))
    if absolute.is_relative_to(TESTS_ROOT):
        return ast.parse(source_text(absolute))
    return _kept_tree(absolute)


@lru_cache(maxsize=None)
def _kept_tree(path: Path) -> ast.Module:
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


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The ids of the constants that are docstrings — prose, not code."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None) or []
            if (
                body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


@lru_cache(maxsize=None)
def string_key_uses(path: Path, keys: tuple[str, ...]) -> tuple[tuple[int, str], ...]:
    """Every place *path*'s **code** spells one of *keys* as a string:
    ``(line, key)`` pairs.

    The question a guard over a *storage key* asks, and one
    :func:`code_only_lines` cannot answer: that function blanks string literals
    along with the comments, so a pattern that is itself a quoted key matches
    nothing it returns, in any file — the guard reads green over a raw poke
    and over none alike. Two guards were written that way before this existed.

    Read off the AST instead. A whole constant equal to a key counts, and so
    does a constant piece of an f-string that *starts* with one
    (``f"color_override{suffix}"`` spelled two keys at once). Docstrings are
    skipped; a comment never reaches the AST at all.
    """
    tree = source_tree(path)
    prose = _docstring_nodes(tree)
    pieces = {
        id(value)
        for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
        for value in node.values if isinstance(value, ast.Constant)
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in prose:
            continue
        for key in keys:
            if node.value == key or (id(node) in pieces and node.value.startswith(key)):
                found.append((node.lineno, key))
    return tuple(sorted(found))
