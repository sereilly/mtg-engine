"""Guard: ``engine/effect_labels.py`` still describes the pool.

The tables in that module are the ``effect_kind`` vocabulary
``engine/parsing/`` used to produce, carried across the deletion so 57 cards
were not silently re-bucketed. A frozen list of strings copied out of deleted
code is exactly the kind of table that rots into a description of a pool that
has moved on — and the rot is invisible, because a stale entry simply stops
being reached and a missing one falls back to a plausible-looking default.

So the tables are held to the pool in both directions:

* **every entry is still reached.** An entry no card uses is dead and goes.
* **no ability falls back.** An ability the grammar reads whose kind is not in
  the table would take the category default, which is how the labels would drift
  back apart one card at a time.

Hooked abilities are excluded from the second check by construction: a
``card_hooks.CardLine`` carries its own label and never consults these tables.
"""

from __future__ import annotations

import pytest

import engine.oracle as oracle
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.effect_labels import (
    ACTIVATED_LABELS,
    TRIGGERED_LABELS,
    TRIGGERED_LABELS_BY_CONDITION,
)
from engine.oracle_types import OracleInstruction


@pytest.fixture(scope="module")
def grammar_abilities():
    """Every (position, key, label) the *shipped* pool's grammar-read abilities
    produce — what "no ability falls back" is asked about."""
    return _abilities_of(load_catalog())


@pytest.fixture(scope="module")
def measured_grammar_abilities():
    """The same, over shipped **and** measured sets.

    The two directions of this guard want two pools, and the asymmetry is the
    same one ``scripts/parse_coverage.py`` documents: "no ability falls back"
    gates on the shipped half, because a set ingested under ``measured`` is by
    definition not implemented yet and failing on it would make every ingest red
    on arrival. "Every entry is still reached" is the opposite question — an
    entry a measured set's card reaches is not dead — and asking it of the
    shipped pool alone would demand that a label be added only *after* its card
    ships, which is exactly when nothing is left to add it for.
    """
    return _abilities_of(load_cards(manifest_set_paths(include_measured=True)))


def _abilities_of(cards):
    activated: list[tuple[str, str, str]] = []
    triggered: list[tuple[str, str, str, str]] = []
    for card in cards:
        program = oracle.compile_card_oracle(card)
        for ability in program.activated_abilities:
            if ability.instruction is None:
                continue
            if oracle._grammar_instruction(ability.source_line, card.name, activated=True):
                activated.append((card.name, ability.instruction.kind, ability.effect_kind))
        for trig in program.triggered_abilities:
            if trig.instruction is None:
                continue
            if oracle._grammar_instruction(
                trig.source_line, card.name, condition_kind=trig.condition.kind
            ):
                triggered.append(
                    (card.name, trig.condition.kind, trig.instruction.kind, trig.effect_kind)
                )
    return activated, triggered


def test_no_grammar_read_ability_falls_back_to_the_category_default(grammar_abilities):
    activated, triggered = grammar_abilities

    missing_activated = sorted(
        {(name, kind) for name, kind, _label in activated if kind not in ACTIVATED_LABELS}
    )
    assert not missing_activated, (
        "activated abilities whose label comes from the grammar category rather "
        f"than the table — add them to ACTIVATED_LABELS: {missing_activated}"
    )

    missing_triggered = sorted(
        {
            (name, condition, kind)
            for name, condition, kind, _label in triggered
            if kind not in TRIGGERED_LABELS
            and (condition, kind) not in TRIGGERED_LABELS_BY_CONDITION
        }
    )
    assert not missing_triggered, (
        "triggered abilities whose label falls back to the `spell_pattern` "
        f"marker — add them to TRIGGERED_LABELS: {missing_triggered}"
    )


def test_every_table_entry_is_still_reached(measured_grammar_abilities):
    activated, triggered = measured_grammar_abilities

    reached_activated = {kind for _name, kind, _label in activated}
    dead = sorted(set(ACTIVATED_LABELS) - reached_activated)
    assert not dead, f"ACTIVATED_LABELS entries no card reaches, delete them: {dead}"

    reached_triggered = {kind for _n, _c, kind, _l in triggered}
    reached_pairs = {(c, kind) for _n, c, kind, _l in triggered}
    dead = sorted(set(TRIGGERED_LABELS) - reached_triggered)
    assert not dead, f"TRIGGERED_LABELS entries no card reaches, delete them: {dead}"
    dead = sorted(set(TRIGGERED_LABELS_BY_CONDITION) - reached_pairs)
    assert not dead, (
        f"TRIGGERED_LABELS_BY_CONDITION entries no card reaches, delete them: {dead}"
    )


def test_the_by_condition_table_only_holds_genuine_ambiguities(grammar_abilities):
    """An entry there that the kind alone would answer is a special case pretending
    to be one — and the next reader would copy the pattern."""
    _activated, triggered = grammar_abilities
    labels_by_kind: dict[str, set[str]] = {}
    for _name, _condition, kind, label in triggered:
        labels_by_kind.setdefault(kind, set()).add(label)

    needless = sorted(
        key for key in TRIGGERED_LABELS_BY_CONDITION
        if len(labels_by_kind.get(key[1], set())) < 2
    )
    assert not needless, (
        "TRIGGERED_LABELS_BY_CONDITION entries whose instruction kind has only "
        f"one label in the pool — move them to TRIGGERED_LABELS: {needless}"
    )


def test_a_trigger_the_grammar_reads_keeps_its_triggered_prefix():
    """The one label consumer that is behaviour, not reporting.

    `web/serialization.py` serializes a stack item's `is_triggered` from the
    label's `triggered_` prefix. These four are grammar-read triggers whose
    prefix therefore has to survive, and each was one of the 57 cards whose
    label the deletion would otherwise have changed.
    """
    catalog = {card.name: card for card in load_catalog()}
    expected = {
        "Cockatrice": "triggered_delayed_destroy",
        "Hypnotic Specter": "triggered_discard",
        "Sea Serpent": "triggered_sacrifice",
        "Hasran Ogress": "triggered_damage",
    }
    for name, label in expected.items():
        program = oracle.compile_card_oracle(catalog[name])
        labels = [t.effect_kind for t in program.triggered_abilities]
        assert label in labels, (name, labels)


def _composes_instructions(payload) -> bool:
    """Whether *payload* carries other instructions — i.e. its kind is a wrapper.

    Structural rather than a list of kind names, because a list of wrappers is
    the same thing this module exists to avoid: a frozen description of a pool
    that moves. `engine/handlers/control_flow.py` registers nine handlers and
    only some of them compose (a coin flip and a chosen number do not), so the
    question is asked of the compiled payload instead of the registry.
    """
    if isinstance(payload, OracleInstruction):
        return True
    if isinstance(payload, dict):
        return any(_composes_instructions(value) for value in payload.values())
    if isinstance(payload, (list, tuple, set)):
        return any(_composes_instructions(value) for value in payload)
    return False


def test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket(grammar_abilities):
    """A composed effect is labelled by its shape, never by one of its steps.

    `sequence` read `activated_damage` and `if_then` read `activated_mana` for
    four sets, each true of the card that prompted the entry (Orcish Artillery,
    the Urza's cycle) and false of most of the cards that later lowered to the
    same wrapper — 54 abilities in the damage bucket, of which six were Mana
    Batteries and five were planeswalkers. The failure is silent by
    construction: a wrapper generalises, so the better the grammar gets at
    composing effects the more cards the wrong label collects.

    The check needs no list of wrappers and no list of buckets. A wrapper is a
    kind whose payload carries other instructions; borrowing is that kind's
    label also being produced by a kind that composes nothing. A shape label
    (`activated_sequence`, `activated_conditional`, `activated_optional`) is
    unshared by construction, so it passes without being named here.
    """
    activated, _triggered = grammar_abilities
    wrappers: set[str] = set()
    leaves: set[str] = set()
    for card in load_catalog():
        program = oracle.compile_card_oracle(card)
        for ability in program.activated_abilities:
            if ability.instruction is None or ability.instruction.kind not in ACTIVATED_LABELS:
                continue
            side = wrappers if _composes_instructions(ability.instruction.payload) else leaves
            side.add(ability.instruction.kind)

    borrowed = sorted(
        (kind, ACTIVATED_LABELS[kind], sorted(
            leaf for leaf in leaves if ACTIVATED_LABELS[leaf] == ACTIVATED_LABELS[kind]
        ))
        for kind in wrappers
        if any(ACTIVATED_LABELS[leaf] == ACTIVATED_LABELS[kind] for leaf in leaves)
    )
    assert not borrowed, (
        "activated wrapper kinds whose label is also a leaf effect's bucket — "
        "the wrapper cannot say what the ability is for, so give it a label "
        f"naming its shape: {borrowed}"
    )
