"""How storm compiles, where it is refused, and the spell-effect gate it exposed.

Storm (CR 702.40a) is a keyword line the compiler turns into the triggered
ability the rule defines (``engine/storm.py``, read through
``keyword_lines.keyword_line_triggers``). Until Scourge it was a keyword line
the engine had never heard of, on a card whose other line compiled — so all
twelve storm cards reported supported with the line silently dropped, and only
``parse_coverage`` saw it.

Implementing it opened a second hole, which the last two tests close: a storm
spell's trigger made Mind's Desire *supported* while its own effect line still
refused, because an instant or sorcery with any ability beside its effect was
exempt from the hollow-spell gate. The census below is validated backwards:
on the base it names Decree of Pain, Decree of Annihilation and Gilded Light,
the three Scourge spells that arrived supported off a cycling line with no
spell effect compiled.
"""

from __future__ import annotations

import pytest

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS
from engine.keyword_lines import _is_supported_keyword_line
from engine.models import CardDefinition
from engine.oracle import _carries_no_behaviour, compile_card_oracle
from engine.storm import SPELLS_CAST_BEFORE_IT, storm_instances

_STORM_LINE = (
    "Storm (When you cast this spell, copy it for each spell cast before it "
    "this turn. You may choose new targets for the copies.)"
)


def _card(name, type_line, text, power=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw.update(power=str(power), toughness=str(power))
    return CardDefinition(
        name=name, mana_cost="{1}{R}", cmc=2.0, type_line=type_line,
        oracle_text=text, colors=("R",), color_identity=("R",),
        keywords=(), produced_mana=(), raw=raw,
    )


def _pool():
    found: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in compilation_units(load_cards(path)):
            found.setdefault(card.name, card)
    return found


def test_the_storm_line_is_admitted_by_its_reader_not_the_registry():
    """Admitted by ``storm.is_storm`` (its reader), and absent from
    ``IMPLEMENTED_KEYWORDS``: storm on a permanent spell is not built."""
    assert _is_supported_keyword_line(_STORM_LINE)
    assert _is_supported_keyword_line("Storm")
    assert "storm" not in IMPLEMENTED_KEYWORDS
    assert storm_instances("storm, storm") == 2


@pytest.mark.parametrize("type_line", ["Instant", "Sorcery"])
def test_a_storm_spell_compiles_one_cast_trigger_per_instance(type_line):
    card = _card("Probe Squall", type_line,
                 f"Probe Squall deals 1 damage to any target.\n{_STORM_LINE}")
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (storm,) = program.triggered_abilities
    assert storm.condition.kind == "self_cast"
    assert storm.instruction.kind == "copy_triggering_spell"
    assert storm.instruction.payload == {"for_each": SPELLS_CAST_BEFORE_IT}
    # The effect line still resolves as the spell's own instruction.
    assert [i.kind for i in program.instructions] == ["deal_damage"]


@pytest.mark.parametrize("type_line,power", [
    ("Creature — Ooze", 2), ("Artifact", None), ("Enchantment", None),
])
def test_storm_on_a_permanent_spell_is_refused_naming_it(type_line, power):
    """A copy of a permanent spell becomes a token (CR 707.10f, 608.3f), which
    the stack does not build: admitted, each copy would resolve as a card."""
    card = _card("Probe Ooze", type_line, f"Flying\n{_STORM_LINE}", power=power)
    program = compile_card_oracle(card)
    assert not program.supported
    assert "storm on a permanent spell" in program.reason
    assert "CR 707.10f" in program.reason


@pytest.mark.parametrize("ability", [_STORM_LINE, "Cycling {2}"])
def test_a_spell_whose_own_effect_is_unread_is_unsupported_beside_an_ability(ability):
    """An ability beside a spell's effect is not the spell: with the effect
    line unread, the cast would do nothing however the ability works."""
    card = _card("Probe Whimsy", "Sorcery",
                 f"Probe Whimsy frobnicates the moon twice.\n{ability}")
    program = compile_card_oracle(card)
    assert not program.supported
    assert program.reason == (
        "this spell's own effect is not implemented: "
        "Probe Whimsy frobnicates the moon twice."
    )


def test_every_supported_storm_card_carries_one_storm_trigger_per_instance():
    pool = _pool()
    storm_cards = [
        card for card in pool.values()
        if any(storm_instances(line.lower().split(" (")[0])
               for line in (card.oracle_text or "").splitlines())
    ]
    # The floor: Scourge's twelve. A census that found none passes anywhere.
    assert len(storm_cards) >= 12, [card.name for card in storm_cards]
    for card in storm_cards:
        program = compile_card_oracle(card)
        assert program.supported, (card.name, program.reason)
        triggers = [
            t for t in program.triggered_abilities
            if t.instruction is not None
            and t.instruction.payload.get("for_each") == SPELLS_CAST_BEFORE_IT
        ]
        assert len(triggers) == 1, card.name


def test_no_supported_instant_or_sorcery_lacks_an_effect_of_its_own():
    """Every supported instant and sorcery, both manifest roles, resolves an
    instruction that carries behaviour, or is modal. On the base this named
    Decree of Pain, Decree of Annihilation and Gilded Light."""
    examined = 0
    hollow = []
    for card in _pool().values():
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        examined += 1
        if program.modes:
            continue
        if not any(not _carries_no_behaviour(i) for i in program.instructions):
            hollow.append(card.name)
    assert examined > 1000, examined
    assert hollow == []
