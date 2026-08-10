"""Guard: ``card_hooks.CARD_LINE_INSTRUCTIONS`` stays honest.

The registry is where a printed line goes when it is one card's sentence rather
than a template — the reading `engine/parsing/` had, moved to the one file whose
subject is a card's name. That move is only safe while three things hold, and
none of them holds by inspection:

* **the key still names a real line.** A key is normalized oracle text typed by
  hand. A typo, or an oracle update, turns the entry into a lookup that can
  never hit — the card silently loses its effect and nothing else notices,
  because a missing hook looks exactly like a card nobody hooked.
* **the entry is still load-bearing.** The grammar is consulted first, so a line
  that grows a production leaves its entry claiming nothing. A dead entry is
  worse than none: it reads as the card's implementation while the real one is
  somewhere else.
* **the reading is the same one the card had.** Every entry here replaces a
  legacy rule, and the point of the exercise is that behaviour does not change.

The third check compares against `engine/parsing/`, so it retires with those
rules. The first two do not.
"""

from __future__ import annotations

import pytest

import engine.oracle as oracle
from engine.card_hooks import CARD_LINE_INSTRUCTIONS
from engine.card_loader import load_catalog
from engine.parsing import parse_primary_instruction


@pytest.fixture(scope="module")
def catalog_by_name():
    return {card.name: card for card in load_catalog()}


def _entries():
    for card_name, lines in CARD_LINE_INSTRUCTIONS.items():
        for key, entry in lines.items():
            yield card_name, key, entry


def _printed_lines(card) -> list[str]:
    """The card's lines as the compiler sees them, modal bullets expanded."""
    text = oracle.expand_modal_activated_lines(card.oracle_text or "")
    return [line.strip() for line in text.splitlines() if line.strip()]


def test_every_key_is_a_printed_line_of_that_card(catalog_by_name):
    """A key that matches nothing is a hook that can never fire."""
    unmatched = []
    for card_name, key, _entry in _entries():
        card = catalog_by_name.get(card_name)
        if card is None:
            unmatched.append((card_name, "card not in the pool"))
            continue
        normalized = {oracle.normalize_creature_line(line) for line in _printed_lines(card)}
        if key not in normalized:
            unmatched.append((card_name, key))

    assert not unmatched, (
        "CARD_LINE_INSTRUCTIONS keys that match no printed line: "
        f"{unmatched}"
    )


def test_every_entry_supplies_an_instruction_the_card_compiles_with(catalog_by_name):
    """A dead entry claims to be a card's implementation while something else is.

    Measured the way the registry is meant to be read — with the legacy rules
    stubbed out, which is the state the deletion is heading for. An entry the
    grammar has since overtaken contributes nothing there, and has to go.
    """
    stubbed = _compile_without_legacy_rules(catalog_by_name)
    inert = []
    for card_name, key, entry in _entries():
        kinds = _flat_kinds(stubbed[card_name])
        if entry.instruction.kind not in kinds:
            inert.append((card_name, key, entry.instruction.kind))

    assert not inert, (
        "CARD_LINE_INSTRUCTIONS entries whose instruction the card no longer "
        f"compiles with — the grammar has taken the line over, so delete them: {inert}"
    )


def test_every_entry_reads_its_line_the_way_the_legacy_rule_did(catalog_by_name):
    """The migration's whole claim: the reading moved, it did not change.

    Retires with ``engine/parsing/`` — there will be nothing to compare against
    once the rules are gone, and by then this file's other two tests are what
    hold the registry up.
    """
    divergent = []
    for card_name, key, entry in _entries():
        legacy, legacy_kind = _legacy_reading(key)
        if legacy is None:
            divergent.append((card_name, key, "no legacy rule claims this line"))
            continue
        if (legacy.kind, legacy.value, legacy.payload) != (
            entry.instruction.kind, entry.instruction.value, entry.instruction.payload
        ):
            divergent.append((card_name, key, f"legacy {legacy!r} vs hook {entry.instruction!r}"))
            continue
        if legacy_kind != entry.effect_kind:
            divergent.append(
                (card_name, key, f"effect_kind legacy {legacy_kind!r} vs hook {entry.effect_kind!r}")
            )

    assert not divergent, f"card-line hooks that diverge from the rule they replace: {divergent}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NESTED_STEP_KEYS = ("steps", "then", "else", "action", "otherwise", "effect")


def _flat_kinds(program) -> set[str]:
    def walk(instructions):
        for instruction in instructions:
            yield instruction.kind
            for key in _NESTED_STEP_KEYS:
                yield from walk(instruction.payload.get(key) or ())

    kinds = set(walk(program.instructions))
    kinds |= {a.instruction.kind for a in program.activated_abilities if a.instruction}
    kinds |= {t.instruction.kind for t in program.triggered_abilities if t.instruction}
    return kinds


def _compile_without_legacy_rules(catalog_by_name) -> dict:
    """Every card's program with the ``@parse_rule`` registry stubbed out.

    The same stub the deletion applies: the grammar and the card hooks are the
    only front ends left, so an entry that contributes nothing here contributes
    nothing that survives the deletion either.
    """
    saved = (
        oracle.parse_primary_instruction,
        oracle.parse_modal_options,
        oracle.parse_static_coeffects,
    )
    oracle.parse_primary_instruction = lambda text, activated=False: (None, "")
    oracle.parse_modal_options = lambda text: None
    oracle.parse_static_coeffects = lambda *args, **kwargs: ()
    oracle._compile_card_oracle.cache_clear()
    try:
        return {
            name: oracle.compile_card_oracle(card)
            for name, card in catalog_by_name.items()
        }
    finally:
        (
            oracle.parse_primary_instruction,
            oracle.parse_modal_options,
            oracle.parse_static_coeffects,
        ) = saved
        oracle._compile_card_oracle.cache_clear()


def _legacy_reading(normalized_line: str):
    """What the ``@parse_rule`` registry makes of *normalized_line*.

    Reproduces the compiler's own split: an activated ability's rules see the
    clause right of the colon, a trigger's see the clause after the condition,
    and everything else sees the whole line.
    """
    if ":" in normalized_line:
        return parse_primary_instruction(
            normalized_line.split(":", 1)[1].strip(), activated=True
        )
    condition, remainder = oracle._parse_trigger_condition(normalized_line)
    if condition is not None:
        _if_kind, effect = oracle._extract_if_condition(remainder.lstrip(": "))
        return parse_primary_instruction(effect, activated=False)
    return parse_primary_instruction(normalized_line, activated=False)
