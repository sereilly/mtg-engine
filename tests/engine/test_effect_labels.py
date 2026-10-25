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

from engine.faces import compilation_units
import engine.front_ends as front_ends
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
    # `compilation_units`: an ability is on the card whose text prints it,
    # which for a split card is a half. The whole card's program has none.
    for card in compilation_units(cards):
        program = oracle.compile_card_oracle(card)
        for ability in program.activated_abilities:
            if ability.instruction is None:
                continue
            if front_ends._grammar_instruction(ability.source_line, card.name, activated=True):
                activated.append((card.name, ability.instruction.kind, ability.effect_kind))
        for trig in program.triggered_abilities:
            if trig.instruction is None:
                continue
            if front_ends._grammar_instruction(
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


def test_the_by_condition_table_only_holds_genuine_ambiguities(
    measured_grammar_abilities,
):
    """An entry there that the kind alone would answer is a special case pretending
    to be one — and the next reader would copy the pattern.

    Asked of shipped **and** measured sets, for the reason
    ``test_every_table_entry_is_still_reached`` beside it is: what makes a kind
    ambiguous is a second card reaching it under another condition, and that
    card lands with its label while its set is still under ``measured``. Asked
    of the shipped pool alone this demanded the opposite of what that test
    demands — the entry a measured card needs was "needless" until promotion,
    and the kind's one shipped label was the wrong one for it in the meantime
    (Ice Cave's cast trigger read ``upkeep_effect``).
    """
    _activated, triggered = measured_grammar_abilities
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
    """Four grammar-read triggers whose label the parser's deletion would
    otherwise have changed — each one of the 57 cards it carried.

    This was "the one label consumer that is behaviour": `web/serialization.py`
    serialized a stack item's `is_triggered` from the `triggered_` prefix. It
    reads ``StackItem.ability_kind`` since the kg round
    (``tests/regressions/test_kg_kinds_ability_kind_is_structural.py``), so
    the labels here are the report vocabulary and nothing more.
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
    only some of them compose (a coin flip and a count do not), so the
    question is asked of the compiled payload instead of the registry.
    """
    if isinstance(payload, OracleInstruction):
        return True
    if isinstance(payload, dict):
        return any(_composes_instructions(value) for value in payload.values())
    if isinstance(payload, (list, tuple, set)):
        return any(_composes_instructions(value) for value in payload)
    return False


def activated_shapes(cards) -> list[tuple[str, str, str, bool]]:
    """``(name, kind, label, wrapper)`` for every activated ability the grammar
    reads: the label the table gives it **now** — its row, or the
    ``activated_<category>`` default when the kind has none — and whether the
    kind composes other instructions.

    The label is asked of ``front_ends._grammar_instruction`` rather than read
    off the compiled ability, because programs are cached for the process and
    the question is what the *table* says: a backwards validation that edits the
    table (``tests/engine/test_kg_kinds_wrapper_labels.py``) must see its edit.
    """
    shapes: list[tuple[str, str, str, bool]] = []
    for card in compilation_units(cards):
        program = oracle.compile_card_oracle(card)
        for ability in program.activated_abilities:
            if ability.instruction is None:
                continue
            read = front_ends._grammar_instruction(ability.source_line, card.name, activated=True)
            if not read:
                continue
            _instruction, label = read
            shapes.append((
                card.name, ability.instruction.kind, label,
                _composes_instructions(ability.instruction.payload),
            ))
    return shapes


def triggered_shapes(cards) -> list[tuple[str, str, str, str, bool, bool]]:
    """``(name, condition, kind, label, wrapper, by_condition)`` for every
    trigger the grammar reads, with the label the tables give it now and
    whether it came from ``TRIGGERED_LABELS_BY_CONDITION``."""
    shapes: list[tuple[str, str, str, str, bool, bool]] = []
    for card in compilation_units(cards):
        program = oracle.compile_card_oracle(card)
        for trig in program.triggered_abilities:
            if trig.instruction is None:
                continue
            condition = trig.condition.kind
            read = front_ends._grammar_instruction(
                trig.source_line, card.name, condition_kind=condition
            )
            if not read:
                continue
            _instruction, label = read
            kind = trig.instruction.kind
            shapes.append((
                card.name, condition, kind, label,
                _composes_instructions(trig.instruction.payload),
                (condition, kind) in TRIGGERED_LABELS_BY_CONDITION,
            ))
    return shapes


def borrowed_buckets(pairs) -> list[tuple[str, str, list[str]]]:
    """``(wrapper kind, label, the leaf kinds producing it too)`` from
    ``(kind, label, wrapper)`` triples — every wrapper whose label is also a
    leaf effect's bucket. A kind is never compared with itself."""
    wrappers: dict[str, set[str]] = {}
    leaves: dict[str, set[str]] = {}
    for kind, label, wrapper in pairs:
        (wrappers if wrapper else leaves).setdefault(label, set()).add(kind)
    return sorted(
        (kind, label, sorted(leaves[label] - {kind}))
        for label, kinds in wrappers.items()
        for kind in kinds
        if leaves.get(label, set()) - {kind}
    )


def test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket():
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

    **Asked of the label each ability gets**, row or default. Until the kg
    round the population was the table's rows: a kind missing from
    ``ACTIVATED_LABELS`` was skipped, so a wrapper defaulting to
    ``activated_<category>`` on a leaf's bucket — or a leaf defaulting onto a
    wrapper's — stayed invisible until its row was added, and the row could
    then be added under whatever label made this pass. (`unless_player_pays`
    was the wrapper this let through on its own row: filed under
    `activated_control`, and passing only because no control leaf had been
    filed there yet.)
    """
    shapes = activated_shapes(load_catalog())
    wrapped = {kind for _name, kind, _label, wrapper in shapes if wrapper}
    # A floor on what was examined: the pool composes effects through more than
    # half a dozen wrapper kinds, and `sequence` alone is on dozens of abilities.
    assert len(wrapped) >= 6 and len(shapes) >= 1000, (len(wrapped), len(shapes))

    borrowed = borrowed_buckets((kind, label, wrapper) for _n, kind, label, wrapper in shapes)
    assert not borrowed, (
        "activated wrapper kinds whose label is also a leaf effect's bucket — "
        "the wrapper cannot say what the ability is for, so give it a label "
        f"naming its shape: {borrowed}"
    )


def test_a_triggered_wrapper_row_never_borrows_a_leaf_effects_bucket():
    """The same rule on the triggered side, for the rows that can break it.

    A trigger's wrapper is labelled one of two ways. ``TRIGGERED_LABELS_BY_CONDITION``
    lets the *condition* name the moment (``("upkeep_self", "may")`` is
    `upkeep_effect`, the word the upkeep leaves share) — that is the table's
    design, so those rows are out of this check. A row in ``TRIGGERED_LABELS``
    is **condition-blind**: it labels the wrapper under every condition that
    reaches it, so it can only honestly name the shape (`triggered_sequence`,
    `triggered_repeated`). Measured at the kg round, three did not:
    `create_delayed_trigger` read `triggered_token` on some forty triggers of
    which three make a token, `choose_one` read `triggered_pump` (and labelled
    every printed modal trigger a pump through ``ability_lines``), and
    `unless_player_pays` read `upkeep_effect` for any condition at all.
    """
    shapes = triggered_shapes(load_catalog())
    blind = [
        (kind, label, wrapper)
        for _name, _condition, kind, label, wrapper, by_condition in shapes
        if not (wrapper and by_condition)
    ]
    assert sum(1 for *_rest, wrapper in blind if wrapper) >= 50, "no wrapper examined"
    borrowed = borrowed_buckets(blind)
    assert not borrowed, (
        "condition-blind TRIGGERED_LABELS rows for a wrapper kind whose label is "
        f"also a leaf effect's bucket — name the shape instead: {borrowed}"
    )
