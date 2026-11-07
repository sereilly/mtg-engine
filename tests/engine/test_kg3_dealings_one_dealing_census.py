"""Every simultaneous damage event is one dealing — the static half.

``engine/simultaneous_damage.py`` reads a damage event from the end its
trigger names (CR 603.2c): a "whenever <source> deals damage" trigger once per
source, for the total, and a "whenever <recipient> is dealt damage" once per
recipient. That reading needs the event to *be* one: every chunk of it dealt
inside one open dealing, which the finish announces. kg3 `events` opened one
for the combat damage step and the sweeps; this holds every other place one
spell or ability deals damage to several recipients at once (CR 608.2f: "Some
spells and abilities include actions taken on multiple players and/or objects.
In most cases, each such action is processed simultaneously") to the same
shape, two ways:

* **the loops** — every damage loop in ``engine/`` (the census
  ``test_kg3_damage_asks_outside_handlers._damage_loops`` already keeps: a
  ``run_resumable`` whose step deals damage, or a call to
  ``simultaneous_damage.deal_at_once``) is a ``deal_at_once`` call, or sits in
  a function that opens a dealing itself, or is excused below with its rule;
* **the split sentences** — a printed damage sentence the lowering split into
  an instruction per clause or recipient ("…2 damage to any target **and** 3
  damage to you", Orcish Artillery) compiles to a ``sequence`` marked
  ``oracle_types.ONE_DEALING``. A ``sequence`` holding two damage steps and no
  marker must come from a line printing them as two sentences (Tracker's bite
  and bite back — two events, its ruling of 2009-10-01).

Validated backwards on 7d311d9f (the census's own reading, the helper and
the marker not existing there): fifteen of the nineteen damage loops opened no
dealing and were not excused, and no compiled sequence carried a marker.

The boards are driven in ``tests/rules/test_kg3_dealings_one_dealing.py`` and
``tests/regressions/test_kg3_dealings_boards.py``.
"""

from __future__ import annotations

import ast
import re

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from engine.oracle_types import ONE_DEALING, OracleInstruction
from tests.engine.test_kg3_damage_asks_outside_handlers import (
    _ENGINE, _damage_loops, _name,
)

#: Damage loops that are **not** one dealing, each with its rule. A loop
#: missing from here that opens no dealing fails; an entry naming no loop
#: fails too.
_NOT_ONE_DEALING = {
    ("phases/combat_damage_step.py", "resolve_all_combat_damage"):
        "first-strike and regular passes are two combat damage steps (CR "
        "510.4); each pass opens its own dealing (_deal_combat_damage_pass)",
    ("handlers/damage.py", "coin_flip_damage_loop"):
        "Mana Clash's ruling (2004-10-04): \"Each point of damage is dealt "
        "separately, so if you are damaged twice by this spell, each time is "
        "considered a separate time this source deals damage\"",
}

#: The names a function opens a dealing by: ``begin``, and the split
#: sentence's ``begin_sentence`` (kg4 `dealings`), which ``handlers/damage.py``
#: imports by name.
_OPENERS = {"begin", "begin_dealing", "begin_sentence"}


def _opens_a_dealing(function) -> bool:
    return any(
        isinstance(node, ast.Call) and _name(node) in _OPENERS
        and (
            not isinstance(node.func, ast.Attribute)
            or getattr(node.func.value, "id", "") == "simultaneous_damage"
        )
        for node in ast.walk(function)
    )


def _functions_by_name(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, node)
    return found


def test_every_damage_loop_runs_inside_one_dealing():
    loops = _damage_loops()
    # A floor on what was examined: 19 damage loops at kg3 `dealings`.
    assert len(loops) >= 15, loops
    at_once, opened, outside = [], [], []
    for where, line, function, _in_apnap_order in loops:
        source = (_ENGINE / where).read_text(encoding="utf-8")
        call = source.splitlines()[line - 1]
        if "deal_at_once(" in call:
            at_once.append((where, function))
            continue
        definition = _functions_by_name(_ENGINE / where).get(function)
        if definition is not None and _opens_a_dealing(definition):
            opened.append((where, function))
            continue
        if (where, function) not in _NOT_ONE_DEALING:
            outside.append(f"{where}:{line} ({function})")
    assert len(at_once) >= 12, at_once
    assert not outside, (
        "a loop dealing damage to several recipients at once opens no "
        "simultaneous dealing, so a trigger naming one end of the event fires "
        "once per chunk (CR 603.2c); use simultaneous_damage.deal_at_once: "
        f"{outside}"
    )
    excused = {(where, function) for where, _, function, _ in loops}
    stale = [key for key in _NOT_ONE_DEALING if key not in excused]
    assert not stale, f"exemptions naming no damage loop: {stale}"


# ---------------------------------------------------------------------------
# The split sentences
# ---------------------------------------------------------------------------

#: The instruction kinds that deal damage, for spotting a sequence of two.
_DAMAGE_KINDS = frozenset({
    "deal_damage", "deal_damage_and_self_damage", "coin_flip_damage_loop",
    "deal_damage_to_those_damaged_this_game",
    "deal_damage_to_recorded_permanents", "bound_bites_source",
    "bound_bites_player", "each_matching_bites_itself",
    "deal_damage_and_opponent_choice", "source_bites_target",
    "target_bites_target", "target_bites_itself", "deal_damage_to_player",
    "deal_damage_each_creature_and_player", "earthquake_damage",
    "hurricane_damage", "deal_damage_each_matching",
    "deal_damage_each_attacking_creature", "deal_damage_to_random_creatures",
})

#: kg3 `dealings`: 26 cards print a damage sentence the lowering splits.
_MARKED_FLOOR = 24


def _walk(value):
    if isinstance(value, OracleInstruction):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _sentences(line: str) -> int:
    return len([
        part for part in re.split(r"(?<=[.])\s+", (line or "").strip())
        if part.strip()
    ])


def test_a_split_damage_sentence_is_one_dealing():
    pool = load_cards(manifest_set_paths(include_measured=True))
    marked, wrong = set(), []
    for card in compilation_units(pool):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        roots = [
            (ability.source_line, ability.instruction)
            for ability in program.activated_abilities
        ] + [
            (trig.source_line, trig.instruction)
            for trig in program.triggered_abilities
        ]
        if "Instant" in card.type_line or "Sorcery" in card.type_line:
            roots.append((card.oracle_text, tuple(program.instructions)))
        for line, root in roots:
            for instruction in _walk(root):
                if instruction.kind != "sequence":
                    continue
                steps = [
                    step for step in instruction.payload.get("steps") or ()
                    if isinstance(step, OracleInstruction)
                ]
                if sum(step.kind in _DAMAGE_KINDS for step in steps) < 2:
                    continue
                if instruction.payload.get(ONE_DEALING):
                    marked.add(card.name)
                elif _sentences(line) < 2:
                    wrong.append((card.name, line))
    assert len(marked) >= _MARKED_FLOOR, sorted(marked)
    assert {"Orcish Artillery", "Heart of Bogardan", "Hail Storm"} <= marked
    assert not wrong, (
        "one printed damage sentence compiled to two damage steps with no "
        f"ONE_DEALING marker, so it is dealt as two events: {wrong}"
    )
