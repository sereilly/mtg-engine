"""No Python module in `engine/`, `web/` or `scripts/` passes 2,000 lines.

The cap began as the grammar's (1,000 lines, `engine/grammar/` only) and was
the signal that a family had stopped absorbing new work. It was raised to
2,000 and widened to every package whose modules a set's work lands in, on
2026-10-21, for two reasons that are both about the next set rather than
about style:

* **A 1,000-line cap cost a pre-split round before every set.** Splits were
  made to just under the cap, so the same modules came back to the band the
  set after; Torment's Phase 0 was ten pre-splits in three rounds before a
  card was touched.
* **A module outside the cap grew without limit.** `mixins/stack/choices.py`
  reached 13,000 lines and `handlers/zones.py` 11,700. Every parallel group
  of a wave edits them, so they are where the merge conflicts were, and an
  agent pays for every line it has to read to find its place.

Not covered, each deliberately: `tests/` (a test file is grouped by the rule
or set it verifies, and `tests/sets/` has its own split convention, by
printed type), and `web/static/` (the client is loaded as global scripts, so
splitting it is a change to how it loads, not a move).

**Split along the subject the new work belongs to, never by raising this
number.** A split should leave every module it touches well clear of the cap
(SET_PLAYBOOK.md's Phase 0 says how far), or it has bought one set.
"""

from __future__ import annotations

import pytest

from tests.source_index import REPO_ROOT, python_files, source_text

CAP = 2000

#: The packages the cap covers. A new top-level package that holds engine or
#: web code belongs here.
AREAS = ("engine", "web", "scripts")

#: Modules over the cap on the day it was widened, each held at that size so
#: none can grow while the split round that clears them is under way. An entry
#: leaves when its module is split, and this dict is empty when the round is.
#: Grouped by the agent splitting them; the comment line between groups keeps
#: two groups' deletions from touching in a merge.
OVERSIZED: dict[str, int] = {
    # --- S1 ---
    # --- S2 ---
    "engine/handlers/zones.py": 11769,
    "engine/handlers/_common.py": 3838,
    # --- S3 ---
    "engine/ai_policy.py": 9198,
    "engine/ai_valuation.py": 4935,
    # --- S4 ---
    "engine/oracle.py": 8417,
    "engine/targeting.py": 5535,
    # --- S5 ---
    # --- S6 ---
    "engine/mixins/stack/casting.py": 6192,
    "engine/mixins/stack/activation.py": 4300,
    "engine/mixins/stack/resolution.py": 2906,
    # --- S7 ---
    "engine/handlers/control_flow.py": 5470,
    "engine/handlers/board_misc.py": 4089,
    "engine/handlers/damage.py": 3397,
    "engine/handlers/pump.py": 2894,
    # --- S8 ---
    "engine/replacements.py": 5549,
    "engine/prevention.py": 2974,
    "engine/handlers/stack.py": 2223,
    "engine/handlers/combat.py": 2145,
    # --- S9 ---
    "engine/mixins/permanent_state.py": 4737,
    "engine/mixins/helpers.py": 4386,
    "engine/mixins/effects.py": 2209,
    # --- S10 ---
    "engine/auras.py": 3773,
    "engine/cast_costs.py": 2410,
    "engine/enter_effects.py": 2267,
    "engine/combat_restrictions.py": 2187,
    "engine/cost_modifiers.py": 2178,
    # --- S11 ---
    "web/prompts.py": 2892,
    "engine/phases/declare_blockers_step.py": 2830,
    "engine/phases/declare_attackers_step.py": 2042,
    # --- integrator ---
}


def _sizes() -> dict[str, int]:
    return {
        path.relative_to(REPO_ROOT).as_posix(): len(source_text(path).splitlines())
        for path in python_files(*AREAS)
    }


def test_no_module_passes_the_cap():
    oversized = {
        name: size
        for name, size in _sizes().items()
        if size > CAP and size > OVERSIZED.get(name, 0)
    }
    assert not oversized, (
        f"modules over the {CAP:,}-line cap (or past the size they were held "
        f"at): {oversized}. Split along the subject the new work belongs to "
        "rather than raising either number."
    )


@pytest.mark.parametrize("name", sorted(OVERSIZED))
def test_every_held_module_is_still_over_the_cap(name):
    """An entry for a module that has been split is a hole nobody can see:
    the module could grow back to its old size and this dict would allow it."""
    size = _sizes().get(name)
    assert size is not None, f"{name} no longer exists; delete its entry"
    assert size > CAP, (
        f"{name} is {size:,} lines, under the cap; delete its OVERSIZED entry"
    )
