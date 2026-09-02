"""Picker sweep — does each supported card's UI picker match its printed line?

The instrument that found Roots on the day of the Homelands ingest: a supported
Aura, no hollow line, every sentence claimed, and a cast spec of None — which is
the exact value the client tests to decide whether to ask for a target, so the
app sent a bare cast and the engine refused it. A supported card no player
could put on the battlefield, and this sweep is the only instrument in the repo
that sees one.

The shipped pool is already held by the ratchets in
``tests/engine/test_targeting.py`` / ``test_activation_targeting.py``; this
script exists so the same sweep can run over a **measured** set during Phase 3
(``--set <CODE>``), when those fixtures cannot see the set under work and the
findings pay most (SET_PLAYBOOK.md Phase 1 step 4). Advisory: exit 0 always,
stdout only — a measured set never gates.

Scope (the playbook's own disclaimer): this answers for the *cast* and
*activation* pickers. A choice made as a permanent enters, or at resolution
inside a triggered ability, is out of scope and reads as a false positive —
and the chooser census is deliberately loose (any choosing word hands the card
to the sweep), so read a finding as a work-list entry, not a diagnosis.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.card_loader import load_cards  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402
from engine.targeting import (  # noqa: E402
    card_names_a_chooser,
    cast_picker_expected,
    derive_activation_spec,
    derive_cast_spec,
)
from set_argument import add_set_argument, resolve_set  # noqa: E402

_REMINDER = re.compile(r"\([^)]*\)")
#: Quoted ability text ("You get an emblem with '…target creature…'"): the
#: target belongs to the granted ability when *it* goes on the stack
#: (CR 603.3d), never to the activation that granted it — Liliana, Waker of
#: the Dead's −7 is the shipped example.
_QUOTED = re.compile(r'"[^"]*"')

#: Cards the sweep would flag whose picker really is absent for a reason —
#: mirrors ``_NO_PICKER`` in tests/engine/test_targeting.py, which is the
#: reviewed list; a new entry belongs there first.
ACKNOWLEDGED = {
    "Darkpact": "the ante zone has no picker (tests/engine/test_targeting.py)",
}


def sweep(cards):
    """Classify every supported card's cast/activation picker evidence.

    Returns a dict of finding lists:

    - ``no_picker``: the Roots class — ``cast_picker_expected`` (the precise
      forward probe: cast-relevant lines plus the enchant/copy/cost evidence)
      says casting should raise a picker, and ``derive_cast_spec`` returns
      None/"none", so the client sends a bare cast the engine may refuse.
    - ``phantom_picker``: the Cleanse class — a spec is derived but the text
      chooses nothing (``card_names_a_chooser``, the deliberately *loose*
      census: any choosing word hands the card back), so the picker aborts
      the cast on an empty candidate list (a mass effect misread as targeted,
      usually).
    - ``activation_no_picker``: an activated ability whose printed line says
      "target" while ``derive_activation_spec`` returns None — the ability
      the web picker cannot ask about.
    - ``acknowledged``: matched ``no_picker`` but stands acknowledged above.
    """
    findings = {
        "no_picker": [],
        "phantom_picker": [],
        "activation_no_picker": [],
        "acknowledged": [],
    }
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        spec = derive_cast_spec(card, program)
        derives = spec is not None and spec.get("kind") != "none"
        if cast_picker_expected(card, program) and not derives:
            if card.name in ACKNOWLEDGED:
                findings["acknowledged"].append((card.name, ACKNOWLEDGED[card.name]))
            else:
                findings["no_picker"].append(
                    (card.name, (card.oracle_text or "").splitlines()[0])
                )
        if derives and not card_names_a_chooser(card, program):
            findings["phantom_picker"].append((card.name, str(spec)))
        for ability in program.activated_abilities:
            line = _QUOTED.sub("", _REMINDER.sub("", ability.source_line or "")).lower()
            if "of an opponent's choice" in line:
                # The opponent picks, not the activator (Preacher) — the
                # activation ratchet derives the same exclusion from the
                # program (tests/engine/test_activation_targeting.py).
                continue
            if "target" in line and derive_activation_spec(ability) is None:
                findings["activation_no_picker"].append(
                    (card.name, ability.source_line)
                )
    return findings


_HEADLINES = {
    "no_picker": (
        "Text names a choice, derivation offers no picker (the Roots class — "
        "the client sends a bare cast):"
    ),
    "phantom_picker": (
        "Derivation offers a picker, text chooses nothing (the Cleanse class — "
        "the picker aborts the cast on an empty board):"
    ),
    "activation_no_picker": (
        "Activated ability says 'target', derivation offers no picker:"
    ),
    "acknowledged": "Acknowledged (reviewed, really has no picker):",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep every supported card's cast/activation picker against its "
            "printed line. The shipped pool is ratcheted in tests; run this "
            "with --set <CODE> over a measured set during Phase 3, which is "
            "when the fixtures cannot see it. Advisory — always exits 0."
        )
    )
    add_set_argument(parser, default=None)
    return parser


def main() -> int:
    # Card text carries U+2212 loyalty minuses a cp1252 console cannot encode.
    sys.stdout.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args()
    selection = resolve_set(parser, args)
    findings = sweep(load_cards(selection.paths))

    print(f"Pool: {selection.label}")
    total = sum(len(rows) for key, rows in findings.items() if key != "acknowledged")
    print(f"Picker findings: {total}")
    for key, headline in _HEADLINES.items():
        rows = findings[key]
        if not rows:
            continue
        print()
        print(headline)
        for name, detail in rows:
            print(f"  {name}: {detail}")
    if total:
        print()
        print("Scope: cast and activation pickers only — a choice made as a")
        print("permanent enters, or at resolution inside a triggered ability,")
        print("is out of scope here and reads as a false positive. A finding")
        print("is a work-list entry, not a diagnosis; and read it as *half*")
        print("the card (Roots' one line had a second, independent failure).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
