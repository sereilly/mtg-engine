"""Guard: a colour effect is recorded in one place, with its timestamp.

CR 613.7 orders the effects in a layer by timestamp, and a resolved effect's is
"the time it's created" (CR 613.7b). Eight sites wrote a permanent's colour by
poking a metadata key — five handlers in ``handlers/board_misc.py``,
``mixins/effects.py``, ``mixins/stack/choices.py`` and the land-animation
refresh in ``mixins/permanent_state.py`` — and none of them recorded when. The
layer bridge had nothing to order by and ordered the *channels* by a constant
instead, so under Darkest Hour a later "becomes white until end of turn" did
nothing (``tests/rules/test_color_effects_timestamp_order.py`` is the census).

``engine/color_changes.py`` is the write API now, with the stamp inside
``change_color``. This file is what keeps it the only one: a ninth direct write
would be a ninth effect with no timestamp, and it would not fail anything else
— an unstamped slot reads as older than everything, which is wrong only in a
game where something else is recolouring the same permanent.

**Read as string constants off the AST, not as text.**
``tests.source_index.code_only_lines`` blanks every string literal along with
the comments, so a pattern that *is* a string literal — a metadata key in
quotes — can never match a line it returns. The storage-key guard in
``test_layer_reads.py`` was written that way and was blind: it passed over a
raw ``metadata["land_type_effects"]`` poke exactly as it passed over none. Both
read ``tests.source_index.string_key_uses`` now, and the first test here is the
proof that it sees one.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine import color_changes
from tests.source_index import (REPO_ROOT, python_files, source_tree,
                                string_key_uses)

OWNER = "engine/color_changes.py"

#: The keys nothing but the write API may spell, anywhere.
_PRIVATE_KEYS = (
    color_changes.COLOR_OVERRIDE_UNTIL_EOT,
    color_changes.COLOR_OVERRIDE_TIMESTAMP,
    color_changes.COLOR_OVERRIDE_UNTIL_EOT_TIMESTAMP,
    color_changes.DERIVED_COLOR_CHANGES,
)

#: ``"color_override"`` is also — and separately — the key a **spell on the
#: stack** carries its recolour under (``StackItem.choices``, the Lace cycle's
#: "target spell") and the name of the wire field the canvas badges from. Those
#: are a different object's record and a payload name; neither is a
#: permanent's slot. Each module that spells the word is listed with how many
#: times and why, held in both directions: one more is a new use to justify,
#: one fewer is a stale allowance.
_SHARED_WORD_USES = {
    "engine/game_types.py": (
        1, "the StackItem.choices keys a copy of a spell does not inherit",
    ),
    "engine/handlers/board_misc.py": (
        1, "recolor_target_from_text writes the stack item's own key",
    ),
    "engine/mixins/helpers.py": (
        1, "_stack_item_colors reads the stack item's own key",
    ),
    "web/serialization.py": (
        5,
        "the wire field's name (permanent, stack card, stack item), the stack "
        "item's own key, and one read of a permanent's indefinite slot for the "
        "canvas's colour badge — a display hint, never an answer about colour "
        "(the payload's `colors` is `Game._effective_colors`)",
    ),
}


def _modules() -> list[tuple[str, Path]]:
    return [
        (str(path.relative_to(REPO_ROOT)).replace("\\", "/"), path)
        for path in python_files("engine", "web")
    ]


def test_the_key_reader_sees_a_string_constant():
    """The scanner is sighted — asked of the one module that must spell every
    key, it finds each of them. (The reader this replaces, asked the same
    question, found nothing in any file.)"""
    owner = REPO_ROOT / OWNER
    spelled = {key for _line, key in string_key_uses(
        owner, (*_PRIVATE_KEYS, color_changes.COLOR_OVERRIDE),
    )}
    assert spelled == {*_PRIVATE_KEYS, color_changes.COLOR_OVERRIDE}
    # …and an f-string piece counts, which is how one read used to spell two
    # slots at once.
    probe = ast.parse('value = meta.get(f"color_override{suffix}")\n')
    pieces = [
        node.value for node in ast.walk(probe)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert pieces == ["color_override"]


def test_no_module_but_the_write_api_spells_a_colour_slot():
    """A ninth direct write would be an effect with no timestamp. The four keys
    only ``engine/color_changes.py`` has any business naming appear nowhere
    else in ``engine/`` or ``web/`` — not as a write, not as a read, not as a
    key computed from a duration."""
    offenders = []
    examined = 0
    for name, path in _modules():
        examined += 1
        if name == OWNER:
            continue
        offenders.extend(
            f"  {name}:{line}: {key!r}" for line, key in string_key_uses(path, _PRIVATE_KEYS)
        )
    assert not offenders, (
        "a colour slot named outside engine/color_changes.py — record the "
        "effect with change_color(perm, colours, until_eot=…) so it is "
        "stamped (CR 613.7b), and read it through color_changes():\n"
        + "\n".join(offenders)
    )
    # "No offenders" over a sweep that opened nothing is a true statement
    # about nothing.
    assert examined >= 400, examined


def test_the_indefinite_slots_word_is_used_only_where_it_names_something_else():
    """``"color_override"`` outside the write API is a stack item's key or the
    wire field's name, module by module and count by count — so a permanent's
    slot written under that word from anywhere new fails here."""
    counted = {}
    for name, path in _modules():
        if name == OWNER:
            continue
        uses = string_key_uses(path, (color_changes.COLOR_OVERRIDE,))
        if uses:
            counted[name] = len(uses)
    allowed = {name: count for name, (count, _why) in _SHARED_WORD_USES.items()}
    assert counted == allowed, (
        '"color_override" spelled outside engine/color_changes.py where it is '
        "not accounted for (a permanent's colour is written by change_color; a "
        "count that fell is a stale allowance to remove):\n"
        + "\n".join(
            f"  {name}: allowed {allowed.get(name, 0)}, found {counted.get(name, 0)}"
            for name in sorted(set(counted) | set(allowed))
            if counted.get(name, 0) != allowed.get(name, 0)
        )
    )


def test_the_collector_is_the_only_reader_of_the_recorded_changes():
    """One consumer: ``layer_bridge.collect_color_effects`` applies the layer.
    A second caller of ``color_changes()`` is a second opinion about what the
    effects add up to — ``Game._effective_colors`` is the answer."""
    callers = []
    for name, path in _modules():
        for node in ast.walk(source_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, (ast.Name, ast.Attribute))
                and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
                == "color_changes"
            ):
                callers.append(name)
    assert sorted(set(callers)) == ["engine/layer_bridge.py"], callers


def _colour_writing_instructions():
    """Every colour-writing instruction over both manifest roles, with the
    card it is on and how long its effect lasts."""
    import dataclasses

    from engine.card_loader import load_cards, manifest_set_paths
    from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES
    from engine.oracle import compiled_units
    from engine.oracle_types import OracleInstruction

    def walk(value, seen):
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, OracleInstruction):
            yield value
            yield from walk(value.payload, seen)
        elif isinstance(value, dict):
            for item in value.values():
                yield from walk(item, seen)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                yield from walk(item, seen)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            for field in dataclasses.fields(value):
                yield from walk(getattr(value, field.name), seen)

    pool = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    found = []
    for card, program in compiled_units(pool.values()):
        for instruction in walk(program, set()):
            kind = instruction.kind
            recolours = INSTRUCTION_CATEGORIES.get(kind) == "recolor"
            animates = kind.startswith("animate_") and instruction.payload.get("colors")
            if not (recolours or animates):
                continue
            found.append((card.name, instruction))
    return len(pool), found


#: How long a colour-writing instruction's effect lasts, read off what the
#: handler reads: the kind's own suffix, or the payload's ``until_eot``.
def _duration(instruction) -> str | None:
    kind = instruction.kind
    if kind.endswith("_until_eot") or instruction.payload.get("until_eot"):
        return "until end of turn"
    if kind.endswith("_indefinitely") or kind in (
        "recolor_target_from_text", "recolor_target_chosen_color",
        "recolor_enchanted_chosen_color", "recolor_self_chosen_color",
    ):
        return "indefinitely"
    return None


def test_every_colour_effect_in_the_pool_lasts_one_of_two_durations():
    """Why two slots lose nothing: a slot holds its *latest* effect, and that is
    all CR 613.7 can ever read from it only because every effect in a slot ends
    at the same moment — never, or at cleanup (CR 514.2). A card whose recolour
    lasts "until your next turn" or "until end of combat" would need a third
    slot with its own sweep; written into either of these it would end at the
    wrong time, or overwrite an effect that outlives it. This is the test that
    says so the day such a card is ingested."""
    pool_size, found = _colour_writing_instructions()
    odd = sorted({
        f"{name}: {instruction.kind}" for name, instruction in found
        if _duration(instruction) is None
    })
    assert not odd, (
        "a colour effect with a duration engine/color_changes.py has no slot "
        f"for: {odd}"
    )
    assert {_duration(instruction) for _name, instruction in found} == {
        "until end of turn", "indefinitely",
    }
    # The floor: both manifest roles, and enough instructions that the sweep
    # cannot have walked past the programs.
    assert pool_size >= 4700, pool_size
    assert len({name for name, _instruction in found}) >= 35, len(found)


@pytest.mark.parametrize("until_eot", [False, True])
def test_change_color_stamps_the_slot_it_writes(until_eot):
    """The write API's own contract, stated on a permanent: the value is stored
    as given, the stamp beside it is the clock's, a second write takes a later
    one, and the reader reports exactly that."""
    from engine.continuous import next_timestamp
    from engine.models import CardDefinition, Permanent

    perm = Permanent(card=CardDefinition(
        name="Test Bear", mana_cost="{1}{G}", cmc=2.0, type_line="Creature — Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(), raw={"power": "2", "toughness": "2"},
    ))
    assert color_changes.color_changes(perm) == ()

    watermark = next_timestamp()
    first = color_changes.change_color(perm, "U", until_eot=until_eot)
    assert first > watermark
    (recorded,) = color_changes.color_changes(perm)
    assert (recorded["colors"], recorded["timestamp"]) == (("U",), first)

    second = color_changes.change_color(perm, (), until_eot=until_eot)
    assert second > first
    (recorded,) = color_changes.color_changes(perm)
    assert (recorded["colors"], recorded["timestamp"]) == ((), second)

    with pytest.raises(ValueError):
        color_changes.change_color(perm, None, until_eot=until_eot)
