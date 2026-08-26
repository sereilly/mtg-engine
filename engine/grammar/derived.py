"""Whole lines whose ``OracleInstruction`` a derivation table already computes.

The sibling of :mod:`engine.grammar.registries`, and the same idea one step
further. Both delegate the *claim* to the implementing code rather than copying
its phrases into the grammar; they differ only in what that code produces:

* a **registry line** is executed off the card's raw oracle text by a sidecar
  registry, so it lowers to nothing;
* a **derived line** is executed by an ordinary handler, and the table computes
  the instruction *and* its payload — the grammar's whole job is to hand that
  over unchanged.

Four tables qualify today, each of them already the single source of truth for
its family:

============================  =======================================
``engine/land_animation.py``  "All Swamps are 1/1 black creatures that
                              are still lands." (Kormus Bell, Living Lands)
``engine/land_types.py``      "All Mountains are Plains." (Conversion)
``engine/lord_buffs.py``      a continuous anthem carrying a condition
                              the grammar's own condition vocabulary does
                              not model (Jihad)
``engine/enter_tapped_statics.py``
                              "Artifacts, creatures, and lands your
                              opponents control enter tapped." (Kismet)
============================  =======================================

**Consulted only where the grammar has already refused the line in full.**
:func:`parser.parse_line` tries every production first and falls back here on
``GrammarError``. That ordering is what stops a table shadowing a production:
the lord-buff table would claim "Other Goblins get +1/+1" quite happily, but
that line parses, so it never arrives. A table is therefore additive by
construction — it can only reach text nothing else could read.

Adding an entry means naming the table that computes the payload. If that table
is deleted or generalised into a production, the entry goes with it, and
``tests/engine/test_grammar_derived_lines.py`` fails when one stops being
reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..land_animation import (
    LAND_ANIMATION_KIND,
    land_animation_for,
    land_animation_payload,
)
from ..enter_tapped_statics import (
    ENTER_TAPPED_STATIC_KIND,
    enter_tapped_static_for,
    enter_tapped_static_payload,
)
from ..land_types import (
    STATIC_LAND_TYPE_KIND,
    static_land_type_change_for,
    static_land_type_change_payload,
)
from ..lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from ..oracle_types import OracleInstruction


@dataclass(frozen=True)
class DerivationTable:
    """One derivation table: its matcher, its instruction kind, its payload.

    ``match`` must claim the **whole** normalized line or return None — every
    matcher below is anchored at both ends for that reason. A table that
    recognized a prefix would let the grammar report a sentence as understood
    while the rider after it went nowhere, which is the dropped-rider bug the
    full-consumption invariant exists to remove.
    """

    name: str
    match: Callable[[str], Any | None]
    kind: str
    payload: Callable[[Any], dict]


TABLES: tuple[DerivationTable, ...] = (
    DerivationTable(
        "land_animation", land_animation_for, LAND_ANIMATION_KIND, land_animation_payload
    ),
    DerivationTable(
        "land_types",
        static_land_type_change_for,
        STATIC_LAND_TYPE_KIND,
        static_land_type_change_payload,
    ),
    DerivationTable("lord_buffs", lord_buff_for, LORD_BUFF_KIND, lord_buff_payload),
    DerivationTable(
        "enter_tapped_statics",
        enter_tapped_static_for,
        ENTER_TAPPED_STATIC_KIND,
        enter_tapped_static_payload,
    ),
)


def _normalized(line: str) -> str:
    """The line as the derivation tables see it.

    Every matcher below takes what ``oracle.normalize_creature_line`` produces,
    so this reduction has to be the same one: lowercased, whitespace collapsed,
    trailing stop dropped. Reminder text is already gone by the time the parser
    is reached, because the lexer strips it.
    """
    return " ".join(line.split()).strip().lower().rstrip(".")


def derived_instruction_for_line(line: str) -> tuple[str, OracleInstruction] | None:
    """``(table name, instruction)`` for *line*, or ``None``.

    The table name labels the AST node; nothing dispatches on it. The
    instruction is the table's own output, so a grammar-lowered line and a
    legacy-parsed one cannot describe different effects — they are the same
    function call.
    """
    normalized = _normalized(line)
    for table in TABLES:
        derived = table.match(normalized)
        if derived is not None:
            return table.name, OracleInstruction(table.kind, "", table.payload(derived))
    return None


__all__ = ["TABLES", "DerivationTable", "derived_instruction_for_line"]
