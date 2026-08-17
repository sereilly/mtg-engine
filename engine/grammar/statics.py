"""Lowering a permanent's **static** abilities — the continuous half.

Split out of `lower.py` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut: everything here answers "what does this permanent
do while it sits on the battlefield?", which is a different question from
"what does this sentence do when it resolves" — no CR 608 resolution, no
targets, no order of steps. It is also the half whose correctness is a
*round trip*: a lord buff is lowered by handing the filter to
`engine/lord_buffs.py` and then rebuilding it, and the two are compared for
equality so nothing the derivation table cannot carry is silently dropped.

Sits between `lowering/` and `lower` in the layer order.
"""

from __future__ import annotations

from ..lord_buffs import (LORD_BUFF_KIND, LordBuff, LordBuffFilter,
                          QUALIFIER_FIELDS, grantable_keywords, lord_buff_payload)
from ..oracle_types import OracleInstruction
from . import ast
from .errors import LoweringError
from .lowering import _filter_payload, _is_source, _lower_pump, _signed


def _lord_filter(filt: ast.ObjectFilter) -> LordBuffFilter:
    """The derivation table's view of *filt*, dropping nothing silently.

    Only the fields ``engine/lord_buffs.py`` carries are read here; whether that
    lost anything is decided by :func:`_object_filter_of` rebuilding the filter
    and the caller comparing the two for **equality**. Probing field by field
    ("refuse if attacking, refuse if tapped, …") is how a filter field added to
    the AST later slips past a check written before it existed — which is the
    exact failure this family already had once, when the consumer read the
    colour and the controller and ignored the rest of the sentence.
    """
    qualifier = next(
        (
            name
            for name, (field_name, value) in QUALIFIER_FIELDS.items()
            if getattr(filt, field_name) is value
        ),
        None,
    )
    return LordBuffFilter(
        colors=filt.colors,
        subtypes=filt.subtypes,
        controller=filt.controller,
        other_than_source=filt.other_than_source,
        qualifier=qualifier,
        with_plus1_counter=filt.with_plus1_counter,
    )


def _object_filter_of(lord: LordBuffFilter) -> ast.ObjectFilter:
    """*lord* back as an ``ObjectFilter`` — the round trip the equality uses."""
    fields: dict[str, object] = {
        "card_types": ("creature",),
        "colors": lord.colors,
        "subtypes": lord.subtypes,
        "controller": lord.controller,
        "other_than_source": lord.other_than_source,
        "with_plus1_counter": lord.with_plus1_counter,
    }
    if lord.qualifier is not None:
        field_name, value = QUALIFIER_FIELDS[lord.qualifier]
        fields[field_name] = value
    return ast.ObjectFilter(**fields)


def _lower_lord_effects(
    node: ast.StaticAbilityNode, effects: tuple[ast.Statement, ...]
) -> LordBuff:
    """The buff *effects* describe. They must all share one subject: "Other
    Goblins get +1/+1 and have mountainwalk" is one ability over one set."""
    subjects = {getattr(effect, "subject", None) for effect in effects}
    if len(subjects) != 1:
        raise LoweringError("a static ability over two different subjects", node=node)
    subject = subjects.pop()
    # "All creatures…" and "Each creature you control…" (Pridemalkin) name the
    # same set — a static ability applies to every object matching its
    # description (CR 611.3a), so the distributive article is a spelling, not a
    # different effect. The derivation table consumes both words the same way.
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier not in ("all", "each"):
        raise LoweringError("static abilities need the CR 613 layers engine", node=node)

    power = toughness = 0
    keywords: list[str] = []
    for effect in effects:
        if isinstance(effect, ast.Pump):
            power = _signed(effect.power, effect.power_negative)
            toughness = _signed(effect.toughness, effect.toughness_negative)
            if not isinstance(power, int) or not isinstance(toughness, int):
                raise LoweringError("a variable continuous buff has no channel", node=node)
        elif isinstance(effect, ast.GainKeyword):
            for keyword in effect.keywords:
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"engine/lord_buffs.py grants no {keyword!r} at layer 6", node=node
                    )
                keywords.append(keyword)
        else:
            raise LoweringError("static abilities need the CR 613 layers engine", node=node)

    lord_filter = _lord_filter(subject.filter)
    if _object_filter_of(lord_filter) != subject.filter:
        raise LoweringError(
            "engine/lord_buffs.py carries no such restriction on the buffed "
            "creatures, so _recalculate_lord_buffs would drop it",
            node=node,
        )
    # A *union* is a separate question from a missing field, and the round trip
    # above cannot answer it: the table's own text parser reads one colour and
    # one subtype, so a grammar-only union would be a payload no printed card
    # produces and no test covers. Whether "white or blue creatures" means an
    # OR is decided when a card needs it.
    if len(lord_filter.colors) > 1 or len(lord_filter.subtypes) > 1:
        raise LoweringError(
            "engine/lord_buffs.py derives one colour and one subtype; a union "
            "has no matching rule behind it",
            node=node,
        )
    return LordBuff(lord_filter, power, toughness, tuple(keywords))


def _lower_static_ability(node: ast.StaticAbilityNode) -> tuple[OracleInstruction, ...]:
    """A continuous buff to a set of creatures, derived by ``engine/lord_buffs.py``.

    "Black creatures get +1/+1" (Bad Moon, Crusade, Gauntlet of Might), "Other
    Goblins get +1/+1 and have mountainwalk" (Goblin King, Lord of Atlantis),
    "Attacking creatures you control get +1/+0" (Orcish Oriflamme) and "Untapped
    creatures you control get +0/+2" (Castle) are one template with parameters,
    and ``_recalculate_lord_buffs`` now honours every one of them.

    **This is not the spell reading of the same sentence, and must not become
    it.** "Attacking creatures get +2/+0 *until end of turn*" is Army of Allah:
    a one-shot effect that locks its set in at resolution (CR 611.2c) and keeps
    ``buff_creatures_global``. Duration is what separates them, and a line
    carrying one never reaches this function — it lowers through ``_lower_pump``.

    What still refuses, and why the reason names code:

    - **A condition** ("as long as you control a Forest") belongs to
      ``engine/static_bonuses.py``, which derives the bonus from the text.
    - **A restriction the table does not carry.** The filter is rebuilt from
      what ``LordBuffFilter`` holds and compared for **equality** against the
      one the parser produced, so anything lost in that round trip refuses. A
      field added to ``ObjectFilter`` later is refused by default rather than
      ignored by a check that predates it.
    """
    if node.condition is not None:
        raise LoweringError(
            "a conditional static bonus is derived by engine/static_bonuses.py",
            node=node,
        )
    effect = node.effect
    effects = effect.effects if isinstance(effect, ast.Conjunction) else (effect,)
    # A static ability on the *source itself* whose size is computed (Carrion
    # Grub's "gets +X/+0, where X is the greatest power among creature cards in
    # your graveyard"). Not a lord buff — it buffs nobody else — and not a
    # one-shot pump, because it has no duration; it is the CR 613 layer 7c
    # contribution the P/T refresh rebuilds on every recompute. The pump
    # lowering knows how to say that, so this routes rather than repeats.
    if len(effects) == 1 and isinstance(effects[0], ast.Pump):
        pump = effects[0]
        if pump.x_definition is not None and _is_source(pump.subject):
            return _lower_pump(pump)
    buff = _lower_lord_effects(node, effects)
    return (OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(buff)),)
