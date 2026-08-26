"""Guard: ``card_hooks.CARD_LINE_INSTRUCTIONS`` stays honest.

The registry is where a printed line goes when it is one card's sentence rather
than a template — the reading `engine/parsing/` had, moved to the one file whose
subject is a card's name. That move is only safe while two things hold, and
neither holds by inspection:

* **the key still names a real line.** A key is normalized oracle text typed by
  hand. A typo, or an oracle update, turns the entry into a lookup that can
  never hit — the card silently loses its effect and nothing else notices,
  because a missing hook looks exactly like a card nobody hooked.
* **the entry is still load-bearing.** The grammar is consulted first, so a line
  that grows a production leaves its entry claiming nothing. A dead entry is
  worse than none: it reads as the card's implementation while the real one is
  somewhere else. Asked two ways, because the first way was not enough: the
  *kind* check below let five entries sit dead for weeks, since the production
  that overtook each of them emitted the very kind the hook named (Jandor's
  Saddlebags: ``untap_target_permanent`` on both sides). So the sharper
  question is asked of the key itself — the grammar must *refuse* it.
* **the card has lines.** ``hook_reliance.py`` counts hooked *cards* off the
  outer keys, so an entry left as ``{}`` when its last line moved to the grammar
  kept counting against the ceiling while implementing nothing (Armageddon
  Clock, for one round).

A third check stood here — *the reading is the same one the legacy rule gave* —
and it retired with `engine/parsing/`, as this docstring always said it would.
There is nothing left to compare a hook against; what holds the registry up now
is the two checks above plus `tests/engine/test_front_end_safety.py`, which
compiles the pool with the grammar stubbed and fails if a production has taken a
line over and produces *less* than the hook it superseded.
"""

from __future__ import annotations

import pytest

import engine.oracle as oracle
from engine.card_hooks import CARD_LINE_INSTRUCTIONS
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import compile_line
from engine.self_reference import expand_short_self_references


@pytest.fixture(scope="module")
def catalog_by_name():
    # Both manifest roles: a hook lands during a measured set's backlog rounds
    # (Rohgahh of Kher Keep's upkeep line arrived while Legends was measured),
    # and against the shipped pool alone this guard would report the card
    # unknown instead of verifying its key and its instruction. Implementation
    # instruments read the wide pool; ``load_catalog`` — what a player can
    # deck — deliberately stays narrower.
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _entries():
    for card_name, lines in CARD_LINE_INSTRUCTIONS.items():
        for key, entry in lines.items():
            yield card_name, key, entry


def _printed_lines(card) -> list[str]:
    """The card's lines as the compiler sees them: modal bullets expanded, and a
    legendary card's shortened self-reference written out in full.

    The second rewrite is here because a hook key is compared against the line
    the compiler *looks up*, and that line has already been through it — a key
    written the way the card prints it would match nothing, which is the shape
    this guard exists to catch and would then report against itself."""
    text = expand_short_self_references(
        card.oracle_text or "", card.name, legendary=card.is_legendary
    )
    text = oracle.expand_modal_activated_lines(text)
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

    An entry the grammar has since overtaken contributes nothing to the card's
    program, and has to go.
    """
    compiled = {
        name: oracle.compile_card_oracle(card)
        for name, card in catalog_by_name.items()
    }
    inert = []
    for card_name, key, entry in _entries():
        kinds = _flat_kinds(compiled[card_name])
        if entry.instruction.kind not in kinds:
            inert.append((card_name, key, entry.instruction.kind))

    assert not inert, (
        "CARD_LINE_INSTRUCTIONS entries whose instruction the card no longer "
        f"compiles with — the grammar has taken the line over, so delete them: {inert}"
    )


def test_every_card_in_the_registry_has_at_least_one_line():
    """An empty entry implements nothing and is still counted as a hooked card."""
    empty = [name for name, lines in CARD_LINE_INSTRUCTIONS.items() if not lines]
    assert not empty, (
        "CARD_LINE_INSTRUCTIONS entries with no lines — the grammar took the "
        f"last one, so delete the card: {empty}"
    )


def test_every_key_is_a_line_the_grammar_refuses():
    """The compiler asks the grammar first and the registry second, so an entry
    whose key the grammar compiles is never reached — whatever kind it names.

    ``compile_line`` is the grammar's front door (the same call the compiler
    makes); a key it parses *and* lowers is a production's line now.
    """
    overtaken = []
    for card_name, key, entry in _entries():
        compiled = compile_line(key, card_name=card_name)
        if compiled.instructions and not compiled.parse_error and not compiled.lowering_error:
            overtaken.append((card_name, key, [i.kind for i in compiled.instructions]))

    assert not overtaken, (
        "CARD_LINE_INSTRUCTIONS keys the grammar compiles — the production is "
        f"the implementation, so delete the entry: {overtaken}"
    )


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


