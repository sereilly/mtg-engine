"""Every damage sentence's printed dealer reaches the program, or the line refuses.

CR 120.7: the source of damage is the object that dealt it. A damage sentence
names that object as its grammatical subject — "**this creature** deals …",
"**enchanted creature** deals …", "**that artifact** deals …" — and
``lowering/damage._lower_damage_shape`` builds a plain ``deal_damage`` from the
recipients and the amount without reading it. For the ability's own source that
is right by default. For any other subject it is the wrong source, with the
card reporting supported: Goblin Tinkerer's destroyed artifact was the one
shipped instance, and four deletion-probe findings (a card named "<type word>
<noun>" with the noun deleted) were the same hole read as harmless.

So the lowering has a post-condition per kind of foreign subject
(``_with_attached_dealer``, ``_with_foreign_dealer``): the dealer rides the
payload as ``biter`` or the line raises. This is the census of that rule over
both manifest roles. Validated backwards on the tree before the fix, where it
names Goblin Tinkerer and both invented sentences compile.
"""

from __future__ import annotations

import dataclasses

from engine import faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar import ast, compile_line
from engine.oracle import expand_ability_lines
from engine.oracle_types import strip_ability_word

#: Printed lines mentioning damage in both roles (900), the ``DealDamage``
#: nodes read out of them (517) and the ones whose subject is not the ability's
#: own source (14) when this was written. Floors, because a census that
#: examined nothing passes for the same reason as one that found nothing.
_LINE_FLOOR = 800
_NODE_FLOOR = 450
_FOREIGN_FLOOR = 10


def _w2g5_nodes(value, seen=None):
    """Every dataclass node under *value* (the AST is nested dataclasses)."""
    seen = seen if seen is not None else set()
    if id(value) in seen:
        return
    seen.add(id(value))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        yield value
        for field in dataclasses.fields(value):
            yield from _w2g5_nodes(getattr(value, field.name), seen)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _w2g5_nodes(item, seen)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _w2g5_nodes(item, seen)


def _w2g5_instructions(instructions):
    for instruction in instructions or ():
        yield instruction
        for value in instruction.payload.values():
            if isinstance(value, tuple) and value and hasattr(value[0], "kind"):
                yield from _w2g5_instructions(value)


def _w2g5_is_own_source(source) -> bool:
    """Whether a damage node's subject is the ability's own source.

    A bare "it" counts: wherever the pool prints it in a plain damage sentence
    it is the source ("sacrifice this creature and it deals 3 damage …", Mogg
    Bombers), and the dealers that are *not* — the enchanted creature, the
    event's subject — lower to kinds that carry ``biter`` themselves.
    """
    if source is None or not isinstance(source, ast.TargetSpec):
        return True
    return source.filter.is_source or source.quantifier in ("this", "it") and not (
        source.filter.is_enchanted or source.filter.enchanted_only
    )


def _w2g5_dropped_dealers(line: str, card_name: str) -> list[str]:
    """The foreign dealers *line* prints that its program does not carry."""
    compiled = compile_line(line, card_name=card_name)
    if compiled.node is None or not compiled.instructions:
        return []
    plain = [
        instruction for instruction in _w2g5_instructions(compiled.instructions)
        if instruction.kind == "deal_damage"
    ]
    dropped = []
    for node in _w2g5_nodes(compiled.node):
        if not isinstance(node, ast.DealDamage) or _w2g5_is_own_source(node.source):
            continue
        if plain and not any("biter" in instruction.payload for instruction in plain):
            dropped.append(node.source.quantifier)
    return dropped


def _w2g5_census():
    cards: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
        for face in faces.face_cards(card):
            cards.setdefault(face.name, face)
    lines = damage_nodes = foreign = 0
    found: list[tuple[str, str]] = []
    for name, card in sorted(cards.items()):
        text = expand_ability_lines(
            card.oracle_text or "", card_name=card.name, legendary=card.is_legendary
        )
        for raw in text.split("\n"):
            line = strip_ability_word(raw).strip()
            if " deal" not in line.lower():
                continue
            lines += 1
            compiled = compile_line(line, card_name=card.name)
            if compiled.node is None:
                continue
            for node in _w2g5_nodes(compiled.node):
                if isinstance(node, ast.DealDamage):
                    damage_nodes += 1
                    foreign += not _w2g5_is_own_source(node.source)
            if _w2g5_dropped_dealers(line, card.name):
                found.append((name, line))
    return lines, damage_nodes, foreign, found


def test_w2g5_no_damage_sentence_drops_its_printed_dealer():
    lines, damage_nodes, foreign, found = _w2g5_census()

    assert lines >= _LINE_FLOOR, lines
    assert damage_nodes >= _NODE_FLOOR, damage_nodes
    assert foreign >= _FOREIGN_FLOOR, foreign
    assert not found, (
        "these lines print a dealer that is not the ability's own source and "
        f"compile to a deal_damage that carries none (CR 120.7): {found}"
    )


def test_w2g5_a_back_referenced_dealer_is_read_from_the_record():
    """"That artifact" after a destroy is the object the destroy recorded. The
    sentence on an invented card, so it is the shape that is held and not one
    name; and the same back-reference with nothing behind it refuses rather
    than quietly becoming the ability's own source."""
    read = compile_line(
        "{T}: Destroy target artifact. That artifact deals 2 damage to you.",
        card_name="Probe Smith",
    )
    damage = [
        instruction for instruction in _w2g5_instructions(read.instructions)
        if instruction.kind == "deal_damage"
    ]
    assert [instruction.payload.get("biter") for instruction in damage] == [
        "destroyed_target"
    ]

    orphan = compile_line(
        "{T}: That artifact deals 2 damage to you.", card_name="Probe Smith"
    )
    assert not orphan.instructions


def test_w2g5_a_class_or_a_target_as_the_dealer_refuses():
    """"Target creature deals 3 damage to any target" has no handler that makes
    the creature the source, so it refuses instead of compiling as the spell
    dealing 3.

    No card prints the shape. It is how the deletion probe read four shipped
    cards whose names open with a type word — Goblin Grenade, Blood Oath,
    Cinder Cloud, Eternal Flame — and Invasion's Tribal Flames: delete the
    second word of the name and what is left is a class subject, which used to
    lower to the very instruction the whole name lowers to, so the probe
    reported the deleted word as one no rule had read.
    """
    for sentence in (
        "Target creature deals 3 damage to any target.",
        "Each creature deals 1 damage to its controller.",
        "Creatures deal 3 damage to any target.",
    ):
        assert not compile_line(sentence, card_name="Probe Card").instructions, sentence

    for name, kept in (("Goblin Grenade", "Goblin"), ("Tribal Flames", "Tribal")):
        whole = compile_line(f"{name} deals 5 damage to any target.", card_name=name)
        assert [i.kind for i in whole.instructions] == ["deal_damage"]
        clipped = compile_line(f"{kept} deals 5 damage to any target.", card_name=name)
        assert not clipped.instructions, kept
