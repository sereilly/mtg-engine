"""How a script names the set it runs over.

``cards/manifest.json`` is the registry of which sets the engine ships, so a
script asks for one by **code** — ``--set ARN`` — and the registry answers with
the file. A filename spelled into a script is a second copy of that list, and
the copy is what goes stale: ``support_report.py`` spent four sets' worth of
ingestion printing Alpha's 290 cards, so "no unsupported cards" was a true
statement about a much smaller question than it appeared to answer.

What is guarded here is not the typo but **the typo that resolves to nothing**.
A ``--set`` that silently produced an empty pool would make
``support_report.py`` report perfect coverage over zero cards and
``simulate_ai_games.py`` report a clean run it never had — both true statements
about nothing, and neither one visible in the output. So an unrecognized code
exits naming the codes that do exist. That is the same reason
``tests/conftest.py``'s ``set_pool`` factory is not a dict lookup.

Every selection also carries a ``label``, and scripts print it. The original
bug was not only that ``support_report.py`` read one set — it was that its
output never said *which* pool the numbers described, so nothing about the
report looked wrong.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import (  # noqa: E402
    MANIFEST_PATH,
    manifest_measured_codes,
    manifest_set,
    manifest_set_paths,
    manifest_sets,
)


@dataclass(frozen=True)
class SetSelection:
    """The card files a run covers, and what to call them in its output."""

    paths: list[Path]
    label: str


def _shipped_codes() -> str:
    return ", ".join(entry["code"] for entry in manifest_sets())


def _known_codes() -> str:
    """Every code ``--set`` accepts, shipped first and measured marked as such.

    Measured sets are nameable here but are *not* in ``--all``: the aggregate
    describes the pool the guarantees are about, and quietly folding an
    unimplemented set into it is how "the pool is 100% supported" stops meaning
    anything. Naming one explicitly is the opposite — it is how you find out
    what the next set needs.
    """
    measured = manifest_measured_codes()
    if not measured:
        return _shipped_codes()
    return f"{_shipped_codes()}; measured (not shipped): {', '.join(measured)}"


def add_set_argument(
    parser: argparse.ArgumentParser,
    *,
    default: str | None,
    path_flags: tuple[str, ...] = ("--cards",),
) -> None:
    """Register ``--set CODE`` / ``--all`` / ``--cards PATH`` on ``parser``.

    ``default`` is the set code used when none is given, or ``None`` for the
    whole manifest pool. It is a *code*, never a filename: if a set leaves the
    manifest, the default stops resolving and says so, where a stale filename
    would simply keep pointing at a file nobody registered any more.

    ``path_flags`` exists for the one script whose historical flag was spelled
    differently (``retrieve_oracle.py --file``); an invocation somebody has in
    muscle memory should keep working.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--set",
        dest="set_code",
        metavar="CODE",
        default=default,
        help=(
            f"set to use, by its code in cards/manifest.json ({_known_codes()})"
            + ("" if default is None else f" [default: {default}]")
        ),
    )
    group.add_argument(
        "--all",
        dest="whole_pool",
        action="store_true",
        help=(
            "every set in the manifest"
            + (" [default]" if default is None else "")
        ),
    )
    group.add_argument(
        *path_flags,
        dest="cards_path",
        metavar="PATH",
        default=None,
        help="a card JSON by path, for a file the manifest does not list",
    )


def resolve_set(parser: argparse.ArgumentParser, args: argparse.Namespace) -> SetSelection:
    """Turn the parsed ``--set`` / ``--all`` / ``--cards`` into card files.

    Exits (code 2) rather than returning an empty selection, because an empty
    selection is the one outcome no caller here would notice.
    """
    if args.cards_path:
        path = Path(args.cards_path)
        if not path.exists():
            parser.error(
                f"no card file at {path}. Sets in cards/manifest.json are "
                f"reachable by code instead: --set {manifest_sets()[0]['code']}"
            )
        return SetSelection(paths=[path], label=str(path))

    if args.whole_pool or args.set_code is None:
        # `_shipped_codes`, never `_known_codes`: this selection *is* the shipped
        # pool, so naming the measured sets here would describe a pool the run
        # did not cover — the same failure the label exists to prevent, with the
        # error moved from which set to which list.
        return SetSelection(
            paths=manifest_set_paths(),
            label=f"the whole manifest pool ({_shipped_codes()})",
        )

    try:
        entry = manifest_set(args.set_code, include_measured=True)
    except KeyError as exc:
        parser.error(exc.args[0])
        raise  # unreachable; parser.error exits. Keeps the type checker honest.

    path = MANIFEST_PATH.parent / entry["file"]
    # A measured set says so in the label, because every one of these scripts
    # prints it and the numbers mean something different for a set nobody has
    # implemented — "104/285 supported" read as a shipped-pool figure is a
    # regression report rather than a to-do list. This is the same reason the
    # label exists at all: the original bug was not only that `support_report.py`
    # read one set, it was that the output never said which.
    suffix = " — measured, not shipped" if entry["code"] in manifest_measured_codes() else ""
    return SetSelection(paths=[path], label=f"{entry['name']} ({entry['code']}){suffix}")
