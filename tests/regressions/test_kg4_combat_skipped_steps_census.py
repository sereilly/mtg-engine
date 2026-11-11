"""Census: in seeded games, a combat nobody attacked in has no declare
blockers step and no combat damage step (CR 508.8).

"If no creatures are declared as attackers or put onto the battlefield
attacking, skip the declare blockers and combat damage steps." Since kg3 the
log said the declare blockers step was skipped and the engine entered it
anyway, with its priority window, and then the combat damage step with its
own — in every seeded game, on every turn the active seat attacked with
nobody.

This plays seeded AI games and watches, from outside the engine's own record
(``Game.combat_creatures_attacked`` is what is under test, so it is not
read): a spy on ``declare_attackers`` notes whether a declaration named any
attacker, and spies on the step walk, on ``offer_priority`` and on the log
say whether a combat with no attack entered either step, gave priority in
it, or wrote a line in it. A combat with an attack must still enter both.

Measured backwards: with ``_leave_combat_step``'s skip switched off every
no-attack combat in these runs enters both steps and is offered priority in
both.
"""
from __future__ import annotations

from collections import Counter

import pytest

from engine import ai_rehearsal
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import manifest_set_path
from engine.game import Game

SKIPPED = ("declare_blockers", "combat_damage")

#: (set, seed, games). ICE seed 9 since kg5: the round's AI branches, merged
#: together, left seed 7's one game three combats with no attack, under the
#: floor of five (the merged tree before ``ids`` already reads 3, the round's
#: base passes); 9 is the first seed after 7 that holds every assertion below
#: (seed 8's game has no attack at all; scratch/kg5/tools/reseed_skipped_steps.py).
_RUNS = (("LEA", 7, 2), ("ICE", 9, 1))


@pytest.fixture
def combat_spy(monkeypatch):
    record = {
        "games": [],
        "combat": {},
        "no_attack": 0,
        "with_attack": 0,
        "with_attack_entered": Counter(),
        "entered": [],
        "offers": [],
        "lines": [],
    }
    set_step, declare, offer = (
        Game._set_phase_and_step, Game.declare_attackers, Game.offer_priority,
    )

    def watched(game) -> dict | None:
        if ai_rehearsal.rehearsing():
            return None
        key = id(game)
        if key not in record["combat"]:
            # Held, so an id is never reused by a later game while counted.
            record["games"].append(game)
            record["combat"][key] = {"attacked": False, "log_at": len(game.log)}
        return record["combat"][key]

    def spied_set(self, phase, step):
        combat = watched(self)
        changing = (phase, step) != (self.current_turn_phase, self.current_step)
        if combat is not None and changing:
            if (
                self.current_turn_phase == "combat"
                and self.current_step in SKIPPED
                and not combat["attacked"]
            ):
                written = self.log[combat["log_at"]:]
                if written:
                    record["lines"].append((self.turn, self.current_step, written[:3]))
            if phase == "combat":
                if step == "declare_attackers":
                    combat["attacked"] = False
                elif step in SKIPPED:
                    if combat["attacked"] or self.combat_attackers:
                        record["with_attack_entered"][step] += 1
                    else:
                        record["entered"].append((self.turn, step, self.log[-3:]))
                elif step == "end_of_combat":
                    record["with_attack" if combat["attacked"] else "no_attack"] += 1
        result = set_step(self, phase, step)
        if combat is not None and changing:
            combat["log_at"] = len(self.log)
        return result

    def spied_declare(self, controller_index, attacker_indices, *args, **kwargs):
        ok, why = declare(self, controller_index, attacker_indices, *args, **kwargs)
        combat = watched(self)
        if combat is not None and ok and attacker_indices:
            combat["attacked"] = True
        return ok, why

    def spied_offer(self, *args, **kwargs):
        combat = watched(self)
        if (
            combat is not None
            and self.current_turn_phase == "combat"
            and self.current_step in SKIPPED
            and not combat["attacked"]
            and not self.combat_attackers
        ):
            record["offers"].append((self.turn, self.current_step))
        return offer(self, *args, **kwargs)

    monkeypatch.setattr(Game, "_set_phase_and_step", spied_set)
    monkeypatch.setattr(Game, "declare_attackers", spied_declare)
    monkeypatch.setattr(Game, "offer_priority", spied_offer)
    return record


@pytest.mark.full
@pytest.mark.parametrize("code, seed, games", _RUNS, ids=[run[0] for run in _RUNS])
def test_a_combat_with_no_attack_never_enters_the_two_steps(combat_spy, code, seed, games):
    report = run_ai_simulation(manifest_set_path(code), games=games, seed=seed)
    assert report.games_completed == games, code

    # Floors: the census measured something on both sides of the rule.
    assert combat_spy["no_attack"] >= 5, combat_spy["no_attack"]
    assert combat_spy["with_attack"] >= 1, combat_spy["with_attack"]
    assert combat_spy["with_attack_entered"]["declare_blockers"] >= 1, combat_spy
    assert combat_spy["with_attack_entered"]["combat_damage"] >= 1, combat_spy

    assert not combat_spy["entered"], combat_spy["entered"][:4]
    assert not combat_spy["offers"], combat_spy["offers"][:6]
    assert not combat_spy["lines"], combat_spy["lines"][:4]
