"""Whole-pool compiled-program differential — "what else did this touch?"

The instrument SET_PLAYBOOK.md Phase 3 requires before believing a change is
local: build the map of every card's compiled program before the change and
once after, and read every card that moved. It was rebuilt by hand each round,
and on Homelands two of five groups and the integrator each wrote a lossy
version independently — keyed on kinds or counts — and each version hid a real
defect. This script stores the programs **in full, with their payloads**, so
the narrowing class (a trigger narrowed, a `type_filter` dropped) is visible.

Usage, from a round's point of view::

    python scripts/oracle_diff.py snapshot            # before the change
    ... edit ...
    python scripts/oracle_diff.py compare             # exit 1 if anything moved

There is deliberately no ``--set`` argument: the question this answers is what
the change touched *beyond* the card it was for, so the pool is always both
manifest roles (``manifest_set_paths(include_measured=True)``), deduped by name
with the earliest printing winning — the same pool ``parse_coverage.py`` reads.

**What the map cannot see** (printed on every compare): a text-keyed table —
``combat_restrictions``, ``untap_restrictions`` / ``draw_step_modifiers``,
``cast_restrictions`` / ``activation_restrictions``, ``cost_modifiers``,
``REPLACEMENT_LINES`` — never reaches the compiled program, so a round that
edits one owes a second differential over that table.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = REPO_ROOT / ".oracle_diff" / "baseline.json"

#: The components stored per card. Full reprs, never kinds and never counts:
#: both abbreviations are natural and both are blind to exactly the narrowing
#: class this instrument exists to catch, because a narrowing changes neither
#: how many of a thing there are nor what the thing is called.
COMPONENTS = (
    "supported",
    "reason",
    "effect_kind",
    "instructions",
    "activated_abilities",
    "triggered_abilities",
    "static_lines",
    "modes",
)

BLIND_SPOT = (
    "note: text-keyed tables (combat_restrictions, untap/draw-step modifiers,\n"
    "cast/activation_restrictions, cost_modifiers, REPLACEMENT_LINES) never\n"
    "reach the compiled program — a round editing one owes a second\n"
    "differential over that table."
)


def load_pool() -> list:
    """Both manifest roles, deduped by name, earliest printing winning."""
    pool: dict[str, object] = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return [pool[name] for name in sorted(pool)]


def snapshot_card(card) -> dict[str, str]:
    program = compile_card_oracle(card)
    return {
        "supported": repr(program.supported),
        "reason": repr(program.reason),
        "effect_kind": repr(program.effect_kind),
        "instructions": repr(program.instructions),
        "activated_abilities": repr(program.activated_abilities),
        "triggered_abilities": repr(program.triggered_abilities),
        "static_lines": repr(program.static_lines),
        "modes": repr((program.modes, program.modes_at_least)),
    }


def snapshot_pool() -> dict[str, dict[str, str]]:
    return {card.name: snapshot_card(card) for card in load_pool()}


def write_snapshot(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cards": len(snapshot),
        },
        "cards": snapshot,
    }
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def read_snapshot(path: Path) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))["cards"]


def compare_snapshots(old: dict, new: dict):
    """Returns (added, removed, changed): names in/out of the pool, and
    ``{name: [(component, old_repr, new_repr), ...]}`` for every card whose
    program moved."""
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed: dict[str, list[tuple[str, str, str]]] = {}
    for name in sorted(set(old) & set(new)):
        moved = [
            (component, old[name][component], new[name][component])
            for component in COMPONENTS
            if old[name].get(component) != new[name].get(component)
        ]
        if moved:
            changed[name] = moved
    return added, removed, changed


# A program repr is one long line; diffing it whole hides *where* it moved.
# Splitting after each `), ` puts one instruction/ability per segment, which is
# the granularity a reader compares at.
_SEGMENT = re.compile(r"(?<=\)), ")


def _segments(text: str) -> list[str]:
    return _SEGMENT.split(text)


def render_compare(added, removed, changed, total: int) -> str:
    lines = [
        f"{len(added)} added / {len(removed)} removed / "
        f"{len(changed)} changed of {total} cards"
    ]
    for name in added:
        lines.append(f"+ {name} (new to the pool)")
    for name in removed:
        lines.append(f"- {name} (gone from the pool)")
    for name, moves in changed.items():
        lines.append(f"~ {name}")
        for component, before, after in moves:
            lines.append(f"  {component}:")
            diff = difflib.unified_diff(
                _segments(before), _segments(after), lineterm="", n=1
            )
            for row in list(diff)[3:]:  # skip ---/+++/@@ header noise
                lines.append(f"    {row}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Whole-pool compiled-program differential: snapshot every card's "
            "full compiled program, then compare after a change to read every "
            "card that moved. No --set on purpose — the question is what a "
            "change touched beyond the card it was for."
        ),
        epilog=BLIND_SPOT,
    )
    parser.add_argument(
        "mode",
        choices=("snapshot", "compare"),
        help="snapshot: record the pool; compare: diff the pool against it",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=DEFAULT_SNAPSHOT,
        help=f"snapshot file (default {DEFAULT_SNAPSHOT.relative_to(REPO_ROOT)})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "snapshot":
        snapshot = snapshot_pool()
        write_snapshot(snapshot, args.snapshot)
        print(f"snapshot: {len(snapshot)} cards -> {args.snapshot}")
        return 0

    if not args.snapshot.exists():
        print(
            f"no snapshot at {args.snapshot} — run "
            "`python scripts/oracle_diff.py snapshot` before the change",
            file=sys.stderr,
        )
        return 2
    old = read_snapshot(args.snapshot)
    added, removed, changed = compare_snapshots(old, snapshot_pool())
    print(render_compare(added, removed, changed, total=len(old)))
    print(BLIND_SPOT)
    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
