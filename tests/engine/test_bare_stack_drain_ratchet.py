"""A bare stack-drain loop in a test is a latent hang, and this ratchets them down.

``while game.stack: game.resolve_top_of_stack()`` spins forever once a
resolution stops to ask an interactive seat something: CR 608.2 keeps the object
on the stack until its last instruction is done and CR 117.3b holds priority
until then, so ``resolve_top_of_stack`` reports False and the loop never
terminates. It is invisible until a card in that test's pool starts asking
something, and then it wedges the whole run rather than failing one test —
which is exactly what happened the day a trigger began announcing a target.

``tests.helpers.resolve_stack`` is the drain to use instead. 207 of the 252
loops were swapped mechanically; the 45 counted here were left because the swap
would not have been behaviour-preserving, and each is a judgement call rather
than a rewrite:

* **40 read the prompt queue within a few lines afterwards.** The helper answers
  a decision that blocks the stack, so a test that resolves and then inspects
  what the resolution asked could be reading a prompt the helper had already
  taken the default for. Converting one means deciding what that test is really
  asserting.
* **5 have a second statement inside the loop body**, so the swap is not a
  two-line substitution at all.

**This is a ceiling, not a floor.** A file may go down and may not go up, and a
file absent from the baseline may have none at all — so the fix for a new test
is to use the helper, never to re-snapshot. Converting one of the 45 means
editing its count down here, which keeps the number honest in the one direction
that matters.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
BASELINE_PATH = pathlib.Path(__file__).with_name("bare_stack_drain_baseline.json")

#: ``while <something>.stack:`` at the head of a loop. Deliberately loose about
#: what the loop *body* is: a bare drain and a drain with an extra statement in
#: it are the same hazard, and matching only the two-line form would let the
#: second shape grow unmeasured.
BARE_DRAIN = re.compile(r"^[ \t]*while\s+[A-Za-z_][A-Za-z0-9_.]*\.stack\s*:\s*$", re.M)


def _counts() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(TESTS.rglob("*.py")):
        hits = len(BARE_DRAIN.findall(path.read_text(encoding="utf-8")))
        if hits:
            found[path.relative_to(ROOT).as_posix()] = hits
    return found


@pytest.fixture(scope="module")
def baseline() -> dict[str, int]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_no_test_file_grows_a_new_bare_stack_drain(baseline):
    """The ratchet itself, per file so the message names where to look."""
    found = _counts()
    grown = {
        path: (baseline.get(path, 0), count)
        for path, count in found.items()
        if count > baseline.get(path, 0)
    }
    assert not grown, (
        "these files gained a bare `while <game>.stack:` drain "
        f"(was -> now): {grown}. That loop hangs the run the moment the card "
        "under test starts asking a seat something (CR 608.2, CR 117.3b) — use "
        "`tests.helpers.resolve_stack`, which answers only what blocks the "
        "stack. Re-snapshotting the baseline is not the fix; it is a ceiling."
    )


def test_the_baseline_names_no_file_that_is_already_clean(baseline):
    """A ceiling that outlives its entries stops being a measurement.

    A file whose loops were all converted must leave the list, or the ratchet
    quietly permits them to come back — which is the failure mode the ``REVIEWED``
    list in ``test_cr_citation_subjects`` has its own guard for. Same shape,
    same reason.
    """
    found = _counts()
    stale = {
        path: was
        for path, was in baseline.items()
        if found.get(path, 0) < was
    }
    assert not stale, (
        f"the baseline is above what these files now contain: {stale}. "
        "Lower each entry to the real count (or drop it) — a ceiling nobody "
        "tightens is one that permits the loops back in."
    )
