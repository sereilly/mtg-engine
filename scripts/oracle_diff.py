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

**A dataclass that gains a defaulted field moves every card that has one.**
The programs are stored as their ``repr``, so adding
``pay_life_per_counter=None`` to ``ActivatedAbilityCost`` reported **710 of
1,869** changed where ten had really moved, and Darksteel's
``unattach_granter_id=None`` read 2,407 for nine. That is not a false positive
to suppress — the repr is what makes the narrowing class visible in the first
place — so ``compare`` separates the two itself (:func:`split_defaulted`): a
field spelled ``, name=<literal>`` that **every** new repr of a class carries
and **no** old one does is a new defaulted field, and a card that moves by
nothing but that spelling (at the field's commonest value) is counted on one
line per field rather than listed. Every other card is a real move, its diff
printed without the new fields' spelling, and the exit code is about real
moves alone. A card carrying the field at any *other* value is a real move:
only the one spelling is struck, never the field.

Two stored snapshots compare without the engine: ``compare --against
<other.json>`` reads the second file as the "after".

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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Card text is UTF-8 and a Windows console is not. `reconfigure` is called
# rather than assumed available on a re-encoded stream, because the crash this
# prevents is the *merge gate's* — a compare that dies on a U+2212 in one
# moved card's payload takes the whole differential with it, and the gate then
# reads as "the instrument is broken" rather than "read these cards". Errors
# are replaced rather than raised for the same reason: a name this console
# cannot spell is still a name the reader needs to see.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-tty streams
        pass

from engine.card_loader import load_cards, manifest_set_paths  # noqa: E402
from engine.faces import face_cards  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402
from engine import program_store  # noqa: E402

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
    """Every card's program, **and every face's** under ``"Card [Face]"``.

    A split card's own program has no instructions by construction (CR 709.3a:
    only the chosen half is evaluated, so the halves are what compile —
    ``engine/faces.py``). Snapshotting the card alone would store an empty
    program for it, and a change that moved what Assault does would compare
    equal: the differential would be blind to exactly the cards whose text
    lives one level down. So each half is its own entry beside the card's.
    """
    snapshot: dict[str, dict[str, str]] = {}
    for card in load_pool():
        snapshot[card.name] = snapshot_card(card)
        for face in face_cards(card):
            snapshot[f"{card.name} [{face.name}]"] = snapshot_card(face)
    return snapshot


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


# ---------------------------------------------------------------------------
# New defaulted fields
# ---------------------------------------------------------------------------

# One token of a repr: a string (skipped whole, so a paren or "x=" inside one
# is text), a call head ``Name(``, a keyword ``name=`` (never ``==``), a
# bracket, or a comma. Everything else — numbers, ``None``, an enum's
# ``<Kind.X: 'x'>`` — lies between tokens and is only ever part of a value.
_TOKEN = re.compile(
    r"""(?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
    r"|(?P<call>[A-Za-z_][\w.]*\()"
    r"|(?P<keyword>[A-Za-z_]\w*=(?!=))"
    r"|(?P<open>[(\[{])"
    r"|(?P<close>[)\]}])"
    r"|(?P<comma>,)"
)
#: The spellings a field's default can have in a repr: the brief's
#: ``, name=<literal>``. A value outside these (a nested object, a computed
#: tuple) is never read as a default.
_LITERAL = re.compile(
    r"""None|True|False|-?\d+(?:\.\d+)?|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|"""
    r"""\(\)|\[\]|\{\}|frozenset\(\)|set\(\)"""
)


@dataclass(frozen=True)
class _Field:
    name: str
    #: Where the text to strike begins: the ", " before the field, or the
    #: field's own first character when it is the first in its call.
    start: int
    value_start: int
    value_end: int
    first: bool


@dataclass
class _Instance:
    cls: str
    fields: list[_Field] = field(default_factory=list)


def repr_instances(text: str) -> list[_Instance]:
    """Every ``Name(field=value, ...)`` call in *text*, with its keyword fields
    at their spans. Positional arguments (a ``frozenset({...})``) carry no
    field. Nested calls are instances of their own."""
    instances: list[_Instance] = []
    # Each frame: [instance or None, open field name, its start, value start, first]
    stack: list[list] = []

    def close_field(frame, end):
        if frame[0] is not None and frame[1] is not None:
            frame[0].fields.append(_Field(frame[1], frame[2], frame[3], end, frame[4]))
            frame[1] = None

    for match in _TOKEN.finditer(text):
        kind = match.lastgroup
        if kind == "string":
            continue
        if kind == "call":
            stack.append([_Instance(match.group()[:-1].rsplit(".", 1)[-1]), None, 0, 0, False])
        elif kind == "open":
            stack.append([None, None, 0, 0, False])
        elif kind == "close":
            if not stack:
                continue
            frame = stack.pop()
            close_field(frame, match.start())
            if frame[0] is not None:
                instances.append(frame[0])
        elif kind == "comma":
            if stack:
                close_field(stack[-1], match.start())
        elif kind == "keyword" and stack and stack[-1][0] is not None and stack[-1][1] is None:
            start = match.start()
            first = text[start - 2:start] != ", "
            stack[-1][1:] = [match.group()[:-1], start if first else start - 2, match.end(), first]
    return instances


@dataclass(frozen=True)
class DefaultedField:
    """A field every new repr of *cls* carries and no old one did, and the
    spelling a card may differ by and still count as unmoved."""

    cls: str
    name: str
    value: str
    #: How many new instances carry each other value — those cards are real moves.
    others: tuple[tuple[str, int], ...] = ()

    @property
    def label(self) -> str:
        return f"{self.cls}.{self.name}={self.value}"


def _strike(text: str, struck: set[tuple[str, str, str]]) -> tuple[str, set[tuple[str, str, str]]]:
    """*text* without each ``(cls, name, value)`` spelling, and which were struck."""
    spans: list[tuple[int, int]] = []
    hit: set[tuple[str, str, str]] = set()
    for instance in repr_instances(text):
        for index, item in enumerate(instance.fields):
            key = (instance.cls, item.name, text[item.value_start:item.value_end])
            if key not in struck:
                continue
            hit.add(key)
            if not item.first:
                spans.append((item.start, item.value_end))
            elif index + 1 < len(instance.fields):
                following = instance.fields[index + 1]
                spans.append((item.start, following.start + (0 if following.first else 2)))
            else:
                spans.append((item.start, item.value_end))
    if not spans:
        return text, hit
    out, cursor = [], 0
    for start, end in sorted(spans):
        out.append(text[cursor:start])
        cursor = max(cursor, end)
    out.append(text[cursor:])
    return "".join(out), hit


def defaulted_fields(old: dict, new: dict, changed: dict) -> list[DefaultedField]:
    """The new defaulted fields *changed* shows.

    Read off the moved components alone: a class that also appears in a
    component that did **not** move cannot have gained a field (that repr
    would have moved too, or would lack the field), so any such appearance
    rules the class out."""
    old_fields: dict[str, set[str]] = defaultdict(set)
    new_count: Counter = Counter()
    new_fields: dict[str, Counter] = defaultdict(Counter)
    values: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for name, moves in changed.items():
        for _component, before, after in moves:
            for instance in repr_instances(before):
                old_fields[instance.cls].update(item.name for item in instance.fields)
            for instance in repr_instances(after):
                new_count[instance.cls] += 1
                for item in instance.fields:
                    new_fields[instance.cls][item.name] += 1
                    values[instance.cls, item.name][after[item.value_start:item.value_end]] += 1
    candidates = {
        (cls, name)
        for cls, counts in new_fields.items() if cls in old_fields
        for name, count in counts.items()
        if count == new_count[cls] and name not in old_fields[cls]
    }
    if not candidates:
        return []
    classes = {cls for cls, _ in candidates}
    head = re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, sorted(classes))) + r")\(")
    seen_unmoved: set[str] = set()
    for name in old.keys() & new.keys():
        for component in COMPONENTS:
            text = old[name].get(component)
            if text != new[name].get(component) or not isinstance(text, str):
                continue
            # The regex is the cheap pass; the scan, which skips strings, decides.
            if head.search(text):
                seen_unmoved |= {i.cls for i in repr_instances(text)} & classes
    found = []
    for cls, name in sorted(candidates):
        if cls in seen_unmoved:
            continue
        spelled = values[cls, name].most_common()
        value = spelled[0][0]
        if not _LITERAL.fullmatch(value):
            continue
        found.append(DefaultedField(cls, name, value, tuple(spelled[1:])))
    return found


def split_defaulted(old: dict, new: dict, changed: dict):
    """``(real, by_field, fields)``: the cards that moved for real (their moves
    with the new fields' spelling struck, so a diff shows only what moved), the
    cards that moved by nothing else under each field's label, and the fields."""
    fields = defaulted_fields(old, new, changed)
    if not fields:
        return changed, {}, []
    struck = {(item.cls, item.name, item.value) for item in fields}
    label = {(item.cls, item.name, item.value): item.label for item in fields}
    real: dict[str, list[tuple[str, str, str]]] = {}
    by_field: dict[str, list[str]] = {item.label: [] for item in fields}
    for name, moves in changed.items():
        remaining, hits = [], set()
        for component, before, after in moves:
            stripped, hit = _strike(after, struck)
            hits |= hit
            if stripped != before:
                remaining.append((component, before, stripped))
        if remaining:
            real[name] = remaining
        else:
            for key in sorted(hits):
                by_field[label[key]].append(name)
    return real, by_field, fields


# A program repr is one long line; diffing it whole hides *where* it moved.
# Splitting after each `), ` puts one instruction/ability per segment, which is
# the granularity a reader compares at.
_SEGMENT = re.compile(r"(?<=\)), ")


def _segments(text: str) -> list[str]:
    return _SEGMENT.split(text)


def render_compare(added, removed, changed, total: int,
                   by_field: dict | None = None, fields=()) -> str:
    lines = [
        f"{len(added)} added / {len(removed)} removed / "
        f"{len(changed)} changed of {total} cards"
    ]
    if fields:
        only = {name for names in (by_field or {}).values() for name in names}
        lines.append(
            f"{len(only)} more moved only by a new defaulted field (every new repr "
            "of its class carries it, no old one did) — not counted above; the "
            "diffs below leave its spelling out:"
        )
        for item in fields:
            note = ""
            if item.others:
                spelled = ", ".join(f"{value} ×{count}" for value, count in item.others[:4])
                more = f", {len(item.others) - 4} more" if len(item.others) > 4 else ""
                note = f" (other values, read as moves: {spelled}{more})"
            lines.append(f"  {len(by_field.get(item.label, ())):>5}  {item.label}{note}")
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
    parser.add_argument(
        "--against",
        type=Path,
        metavar="OTHER",
        help="compare: read this second snapshot file as the 'after' instead "
             "of compiling the pool (two stored snapshots, no engine)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.against is not None and args.mode != "compare":
        parser.error("--against is a compare option")
    if args.against is None:
        program_store.warm()
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
    if args.against is not None:
        if not args.against.exists():
            print(f"no snapshot at {args.against}", file=sys.stderr)
            return 2
        new = read_snapshot(args.against)
    else:
        new = snapshot_pool()
    added, removed, changed = compare_snapshots(old, new)
    real, by_field, fields = split_defaulted(old, new, changed)
    print(render_compare(added, removed, real, total=len(old),
                         by_field=by_field, fields=fields))
    print(BLIND_SPOT)
    # Real moves only: a card that moved by a new field's default spelling and
    # nothing else is on its field's line, not in the exit code.
    return 1 if (added or removed or real) else 0


if __name__ == "__main__":
    raise SystemExit(main())
