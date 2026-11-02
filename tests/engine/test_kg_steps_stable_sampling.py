"""A census samples by what a row *is*, never by where it sits.

A census too slow to run over the whole pool on every build takes a share of
it. The censuses that took "every Nth card" (``cards[::STRIDE]``,
``if position % STRIDE: continue``) took a share **of a position**: the pool is
sorted and filtered, so a card supported by a merge, or a set promoted or
ingested, shifted every row behind it one place and the sample moved. Over a
pool that holds the measured set that is every merge — at Judgment Shaman's
Trance's finding in the zone-cast twin census flickered in and out across four
of them, and the promotion rehearsal moved the loses-all-abilities census off
every door granter it had pinned its floor to.

``tests.helpers.stable_sample`` takes the share by a digest of the row's own
label (``zlib.crc32``; the built-in ``hash()`` is salted per process), so a
row's membership is a fact about the row and a growing pool only adds rows.

This guard holds that, over the files that act — every module under
``tests/`` — in two parts:

* a module that reads the measured set (``include_measured=True``) samples by
  position nowhere;
* every positional sampler left anywhere else is counted, per module
  (``POSITIONAL_SAMPLERS``), so a new one is noticed and a converted one
  tightens the table. The table is empty since kg3, which converted the last
  ten — each over the **shipped** pool, so each had re-sampled at every
  promotion — so a positional sampler anywhere is now a red.

A partition (``names[part::N]`` with ``part`` over every part) is not a sample
— every row is still examined, only the test id that reports it moves — and is
not counted.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests.helpers import full_census, stable_digest, stable_sample

TESTS = Path(__file__).resolve().parents[1]

#: The name a position counter is compared against, by convention.
_SHARE_WORDS = ("STRIDE", "SAMPLE", "EVERY")

#: Positional samplers left, per module. Empty since kg3, which switched the
#: last ten (each over the shipped pool, so each had re-sampled at every
#: promotion) to ``stable_sample`` and re-measured their floors; a new one is
#: a red here, not a row.
POSITIONAL_SAMPLERS: dict[str, int] = {}

#: The modules kg3 converted, each of which now samples by the digest.
CONVERTED_AT_KG3 = frozenset({
    "ai/test_ai_activation_effective_card_census.py",
    "ai/test_ai_combat_trick_census.py",
    "ai/test_ai_hidden_information_census.py",
    "ai/test_ai_idle_cast_census.py",
    "engine/test_permanent_spell_target_readers_census.py",
    "engine/test_trigger_order_census.py",
    "rules/test_gained_land_type_mana.py",
    "rules/test_land_tap_asks_for_a_symbol.py",
    "rules/test_static_of_a_source_that_lost_its_abilities.py",
    "ui/test_auto_tap_plan_census.py",
})


def _is_share_name(node: ast.AST) -> bool:
    name = node.id if isinstance(node, ast.Name) else (
        node.attr if isinstance(node, ast.Attribute) else ""
    )
    return any(word in name.upper() for word in _SHARE_WORDS)


def samplers_in(source: str) -> int:
    """How many positional samplers *source* holds.

    * a slice with a step and no start, or a literal one (``rows[::N]``,
      ``rows[3::N]``) — a start that is a *name* is a partition's part;
    * a counter taken modulo a share (``position % SAMPLE_EVERY``,
      ``ordinal % stride``) — a digest taken modulo one is a call, not a
      counter, and is not counted;
    * a seeded ``.sample(population, k)``, whose draw depends on what the
      population holds and in what order.
    """
    found = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            piece = node.slice
            if piece.step is not None and piece.upper is None and (
                piece.lower is None or isinstance(piece.lower, ast.Constant)
            ):
                found += 1
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            if isinstance(node.left, (ast.Name, ast.Attribute)) and _is_share_name(node.right):
                found += 1
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sample"
            and len(node.args) == 2
        ):
            found += 1
    return found


#: This module, whose examples are samplers on purpose.
_SELF = Path(__file__).resolve().relative_to(TESTS).as_posix()


def _modules() -> dict[str, str]:
    return {
        path.relative_to(TESTS).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(TESTS.rglob("*.py"))
        if path.relative_to(TESTS).as_posix() != _SELF
    }


def test_the_detector_tells_a_sample_from_a_partition_and_a_digest():
    assert samplers_in("names = cards[::STRIDE]") == 1
    assert samplers_in("names = cards[0::4]") == 1
    assert samplers_in(
        "for position, card in enumerate(pool):\n"
        "    if sample and position % SAMPLE_EVERY:\n"
        "        continue\n"
    ) == 1
    assert samplers_in("if ordinal % stride:\n    pass\n") == 1
    assert samplers_in("a, b = rng.sample(pool, 2)") == 1
    # Not samples: a partition, a digest, a parity.
    assert samplers_in("names = cards[part::_SLICES]") == 0
    assert samplers_in("keep = zlib.crc32(label.encode()) % _SAMPLE == 0") == 0
    assert samplers_in("keep = stable_sample(card.name, STRIDE)") == 0
    assert samplers_in("odd = index % 2") == 0


def test_no_census_over_the_measured_set_samples_by_position():
    modules = _modules()
    measured = {
        name: source for name, source in modules.items()
        if "include_measured=True" in source
    }
    # The floor: the scan reads the tree it guards.
    assert len(modules) >= 600, len(modules)
    assert len(measured) >= 40, len(measured)
    assert "regressions/test_ody_w2g2_zone_cast_census.py" in measured
    offenders = {
        name: count for name, source in measured.items()
        if (count := samplers_in(source))
    }
    assert offenders == {}, (
        "a census over a pool holding the measured set samples by position; "
        f"sample by tests.helpers.stable_sample instead: {offenders}"
    )


def test_every_positional_sampler_left_is_counted():
    found = {
        name: count for name, source in _modules().items()
        if (count := samplers_in(source))
    }
    assert found == POSITIONAL_SAMPLERS, (
        "positional samplers moved; a new one belongs on stable_sample, and a "
        "converted one comes off the table"
    )
    # …and the digest is in use where the round put it: sampling, or — the
    # zone-cast census in the full pass — partitioning by it.
    users = [
        name for name, source in _modules().items()
        if ("stable_sample(" in source or "stable_part(" in source)
        and name != "helpers.py"
    ]
    assert {
        "regressions/test_ody_w2g2_zone_cast_census.py",
        "rules/test_loses_all_abilities_timestamp_order.py",
    } | CONVERTED_AT_KG3 <= set(users), sorted(CONVERTED_AT_KG3 - set(users))


def test_a_digest_sample_is_a_fact_about_the_row(monkeypatch):
    """Growing a population never moves an old row in or out — the property
    the positional samplers lacked — and the digest is ``crc32``, the same in
    every process."""
    import zlib

    monkeypatch.delenv("MTG_FULL_CENSUS", raising=False)
    names = [f"Card {index}" for index in range(400)]
    before = {name for name in names if stable_sample(name, 6)}
    grown = sorted(names + [f"Inserted {index}" for index in range(150)])
    after = {name for name in grown if stable_sample(name, 6)}
    assert before == after & set(names)
    assert 40 <= len(before) <= 100, len(before)
    assert stable_digest("Lightning Bolt") == zlib.crc32(b"Lightning Bolt")
    # A positional sample of the same two populations does move.
    assert set(names[::6]) != set(grown[::6]) & set(names)


def test_the_full_census_switch_takes_every_row(monkeypatch):
    monkeypatch.setenv("MTG_FULL_CENSUS", "1")
    assert full_census()
    assert all(stable_sample(f"Card {index}", 10) for index in range(50))
    monkeypatch.setenv("MTG_FULL_CENSUS", "0")
    assert not full_census()
    assert not all(stable_sample(f"Card {index}", 10) for index in range(50))
