"""A damage event's consequences have to be inside the damage event.

A damage event can stop part-way to ask the affected player which of several
effects applies first (CR 616.1e). While it waits, *nothing has happened* — no
shield spent, no life lost, no trigger fired — and 0 comes back. Answering
re-runs the call.

So anything the caller does with the number has to travel with the event, as
``then``. Code that reads the return value and acts on it afterwards would
report a suspended event as a 0-damage one — logging "dealt 0 damage", gaining
0 life for a Drain Life, tallying 0 lifelink — and would never come back to
correct itself, because the re-run does not re-run the caller.

That is invisible in a suite where nothing suspends, which is exactly why it is
a source guard rather than a behavioural test.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "engine"

#: ``x = game._deal_damage_to_player(...)`` and friends. A bare call is fine —
#: it means the caller wants nothing from the number — and so is ``return``,
#: which hands the question to *its* caller rather than acting on the answer.
BINDS_DEALT = re.compile(
    r"^\s*\w+\s*=\s*(?:game|self)\._(?:deal_damage_to_player|mark_damage_on_permanent)\("
)
BINDS_CREATURE_DEALT = re.compile(r"^\s*\w+\s*=\s*apply_damage_to_creature\(")


def _offenders(sources: dict[str, str]) -> list[str]:
    """Every place that binds the dealt amount instead of passing ``then``.
    One function so the guard and the test that proves it fires agree."""
    found = []
    for name, text in sources.items():
        for number, line in enumerate(text.splitlines(), 1):
            if BINDS_DEALT.match(line) or BINDS_CREATURE_DEALT.match(line):
                found.append(f"{name}:{number}: {line.strip()}")
    return found


def _engine_sources() -> dict[str, str]:
    return {
        str(path.relative_to(REPO)): path.read_text(encoding="utf-8")
        for path in ENGINE.rglob("*.py")
    }


def test_no_engine_code_acts_on_the_dealt_amount_after_the_fact():
    offenders = _offenders(_engine_sources())
    assert not offenders, (
        "these read the damage dealt and act on it after the event instead of "
        "passing `then=`, so a suspended event (CR 616.1e) would be reported as "
        "0 damage and never corrected:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_fires():
    """Verified by injection. A guard nobody has watched fail is a guard nobody
    has tested — and this one passes trivially on a suite where no damage event
    ever suspends."""
    offenders = _offenders(
        {
            "_probe.py": (
                "    dealt = game._deal_damage_to_player(target, 3, source=card)\n"
                "    game.log.append(f'dealt {dealt}')\n"
            ),
            "_probe_creature.py": "    dealt = apply_damage_to_creature(game, perm, 3, card)\n",
            "_fine.py": (
                "    game._deal_damage_to_player(target, 3, then=report)\n"
                "    return game._mark_damage_on_permanent(perm, 3, then=report)\n"
            ),
        }
    )
    assert len(offenders) == 2, offenders
    assert all("_probe" in offender for offender in offenders)
