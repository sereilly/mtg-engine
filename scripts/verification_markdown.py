"""Regenerate CARD_VERIFICATION.md from card_verification.json.

The tracker's markdown is a projection of the recorded results plus the
behaviour-class derivation (``web/verification_report.py``), and CI's
freshness step regenerates it and fails on a diff. Importing the web layer
loads the card catalog, which compiles the shipped pool, so this reads the
compiled-program store first (``engine/program_store.py``): run after every
merge by ``scripts/integration/regen.sh``, it compiled the pool each time. The
web layer reads the store as it loads too; a process reads it once, and the
call here is what the merge-path census in
``tests/engine/test_program_store.py`` looks for.

Usage:
    python scripts/verification_markdown.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import program_store  # noqa: E402


def main() -> int:
    program_store.warm()
    # Imported here, after the store is read: importing the web layer is what
    # compiles the pool (`web/runtime.py` loads the catalog as it loads).
    from web.verification_report import write_verification_markdown

    write_verification_markdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
