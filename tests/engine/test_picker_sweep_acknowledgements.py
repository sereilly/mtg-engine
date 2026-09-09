"""Guard: ``picker_sweep.py`` cannot acknowledge a finding on its own.

The sweep is advisory — it always exits 0 and prints to stdout — which makes
its ``ACKNOWLEDGED`` dicts the softest place in the repo to make a finding go
away. Nothing fails if an entry is wrong, so nothing would ever say so. The
reviewed lists are the two in ``tests/engine/`` that a *ratchet* stands behind:

* ``test_targeting._NO_PICKER`` — a card whose **cast** picker is absent for a
  reason (Darkpact: the ante zone has no enumerator);
* ``test_activation_targeting._UNANNOUNCEABLE_TARGETS`` — an **activated
  ability** whose printed target this engine cannot announce at CR 601.2c
  (Carrion Beetles: a graveyard target, chosen at resolution instead).

So the script's dicts are held equal to those, **both ways**. An entry only the
script carries is a finding silenced without review; an entry only the tests
carry leaves the script reporting a decline that has already been made, and a
standing known-false finding is how a reader learns to skim the report — which
is what happened to Carrion Beetles, reported at every Urza's Saga sweep from
the day it was ingested while the reviewed list beside it said "reviewed,
declined, here are the four missing pieces".

This file also carries the staleness ratchet ``_UNANNOUNCEABLE_TARGETS`` never
had. ``_NO_PICKER`` has one (``test_the_no_picker_acknowledgements_are_not_
stale``): an acknowledgement whose card starts deriving a prompt fails, so a
fix cannot leave a dead excuse behind. The activation list was only ever
checked in the direction that lets an *unfixed* ability pass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from engine.card_loader import load_catalog
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

from .test_activation_targeting import _UNANNOUNCEABLE_TARGETS, _abilities
from .test_targeting import _NO_PICKER

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def supported_cards():
    """The shipped pool, compiled — the same fixture the two ratchet files
    beside this one use, spelled the same way."""
    return [card for card in load_catalog() if compile_card_oracle(card).supported]


def _picker_sweep():
    """Import ``scripts/picker_sweep.py`` by path.

    It is a script rather than a package module, and importing it by path is
    what makes this guard read the *same* dict the sweep prints from rather
    than a copy of its contents pasted here — which would be the third list
    the docstring above is about.
    """
    if "picker_sweep" in sys.modules:
        return sys.modules["picker_sweep"]
    scripts = _REPO / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location(
        "picker_sweep", scripts / "picker_sweep.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["picker_sweep"] = module
    spec.loader.exec_module(module)
    return module


def test_the_scripts_cast_acknowledgements_are_the_reviewed_ones():
    assert set(_picker_sweep().ACKNOWLEDGED) == set(_NO_PICKER), (
        "picker_sweep.ACKNOWLEDGED and test_targeting._NO_PICKER have drifted; "
        "the reviewed list is the test's"
    )


def test_the_scripts_activation_acknowledgements_are_the_reviewed_ones():
    assert set(_picker_sweep().ACKNOWLEDGED_ABILITIES) == set(_UNANNOUNCEABLE_TARGETS), (
        "picker_sweep.ACKNOWLEDGED_ABILITIES and "
        "test_activation_targeting._UNANNOUNCEABLE_TARGETS have drifted; "
        "the reviewed list is the test's"
    )


def test_the_unannounceable_acknowledgements_are_not_stale(supported_cards):
    """The direction the activation list was never checked in.

    An ability that starts deriving a spec has been fixed, and the entry
    excusing it is then a standing free pass for whatever the next parser
    change does to that card — the same reasoning
    ``test_the_no_picker_acknowledgements_are_not_stale`` gives one file over.
    """
    by_name = {card.name: card for card in supported_cards}

    for (name, index), reason in sorted(_UNANNOUNCEABLE_TARGETS.items()):
        card = by_name.get(name)
        assert card is not None, f"{name} is acknowledged but not in the pool"
        abilities = _abilities(card)
        assert index < len(abilities), (
            f"{name} no longer has an ability {index} — delete the entry"
        )
        assert derive_activation_spec(abilities[index]) is None, (
            f"{name} [{index}] derives a prompt now ({reason!r}) — delete its "
            "acknowledgement, here and in scripts/picker_sweep.py"
        )
        assert compile_card_oracle(card).supported, (
            f"{name} is acknowledged but is no longer supported"
        )


def test_the_shipped_pool_sweeps_clean(supported_cards):
    """And the whole point of the two dicts: with the reviewed declines
    accounted for, the shipped pool has **no** unexplained picker finding.

    The number is the assertion. A card ingested with a missing picker raises
    it, and so does a parser change that takes an existing card's evidence
    away — which is the Roots class arriving by regression rather than by
    ingest.
    """
    findings = _picker_sweep().sweep(supported_cards)
    unexplained = {
        key: rows for key, rows in findings.items()
        if key != "acknowledged" and rows
    }
    assert unexplained == {}, f"unexplained picker findings: {unexplained}"
