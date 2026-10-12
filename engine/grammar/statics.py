"""Lowering a permanent's **static** abilities — the continuous half.

Split out of `lower.py` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut: everything here answers "what does this permanent
do while it sits on the battlefield?", which is a different question from
"what does this sentence do when it resolves" — no CR 608 resolution, no
targets, no order of steps. It is also the half whose correctness is a
*round trip*: a lord buff is lowered by handing the filter to
`engine/lord_buffs.py` and then rebuilding it, and the two are compared for
equality so nothing the derivation table cannot carry is silently dropped.

**The condition half left for `static_conditions.py`** at the 1,000-line
guard, the round Odyssey's threshold arrived: which "as long as" clauses may
gate a continuous effect, and the `conditional_static` instruction one
permanent carries while its clause holds. What is here is the anthem — the
round trip above — and the dispatch that decides which of the two a line is.

Sits between `static_conditions` and `lower` in the layer order.
"""

from __future__ import annotations

import dataclasses

from ..lord_buffs import (LORD_BUFF_KIND, LordBuff, LordBuffFilter,
                          QUALIFIER_FIELDS, grantable_keywords,
                          grantable_protection_quality, lord_buff_payload)
from ..oracle_types import OracleInstruction
from ..static_bonuses import RECIPIENT_SUBJECT
from . import ast
from .errors import LoweringError
from .lowering import (_filter_payload, _is_enchanted, _is_source,
                       _lower_pump, _signed)
from .static_conditions import (_lower_anthem_condition,
                                _lower_self_conditional_static,
                                _recipient_seat_condition)


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
    # Every state the filter names, not the first one found: a filter carrying
    # two would otherwise round-trip as one and the equality below would refuse
    # a sentence the table can express perfectly well. ``is`` rather than ``==``
    # because the unset value is None and ``None == False`` is already False —
    # but ``is`` says the three-valued field is being read as three-valued.
    qualifiers = tuple(
        name
        for name, (field_name, value) in QUALIFIER_FIELDS.items()
        if getattr(filt, field_name) is value
    )
    return LordBuffFilter(
        colors=filt.colors,
        subtypes=filt.subtypes,
        # "**Non-Wall** creatures…" and the second half of a union (Verdeloth
        # the Ancient). Carried for the reason every field below is: the round
        # trip decides whether the table can express the sentence.
        excluded_subtypes=filt.excluded_subtypes,
        controller=filt.controller,
        other_than_source=filt.other_than_source,
        qualifiers=qualifiers,
        with_plus1_counter=filt.with_plus1_counter,
        named=filt.named,
        # "Creatures **with flying** get +1/+1." (Serra Aviary.) Carried
        # through like every other field, so the equality below is what
        # decides whether the table can express it — the same round trip and
        # not a probe, for the reason this function's docstring gives.
        with_keywords=filt.with_keywords,
        # "Creatures **without** flying have reach." (Chaosphere.) The negated
        # twin, carried for the reason above it: what decides whether the table
        # can express a restriction is the round trip, never a probe.
        without_keywords=filt.without_keywords,
        # "**Noncreature artifacts** have shroud." (Spectral Guardian.) The
        # printed card type, carried rather than assumed: `_object_filter_of`
        # wrote "creature" back unconditionally, so an anthem about any other
        # permanent type failed the equality below and refused — the right
        # direction while the consumer asked `is_creature`, and the wrong one
        # now that it asks the filter.
        card_types=filt.card_types,
        excluded_types=filt.excluded_types,
        # "Each land **of the chosen type** has phasing." (Shimmer.) Carried
        # through like every other field, so the round trip below is what
        # decides whether the table can express it.
        chosen_land_type=filt.chosen_land_type,
        # "All creatures **of the chosen type** get -1/-1." (Engineered
        # Plague.) The line above's twin, carried for its reason exactly: the
        # round trip below is what decides whether the table can express it,
        # and probing field by field is how a field added later slips past a
        # check written before it existed.
        chosen_creature_type=filt.chosen_creature_type,
        # "**Nonblack** creatures get -1/-1." (Ascendant Evincar.) Carried for
        # the reason every field above is: the round trip decides.
        excluded_colors=filt.excluded_colors,
        # "**Basic** lands each player controls have shroud…" (Sheltering
        # Prayers.) ``LordBuffFilter`` has carried a supertype since Legends'
        # banding lands — through the text table — and this round trip did not,
        # so the grammar's reading of any supertyped anthem refused.
        supertypes=filt.supertypes,
    )


def _object_filter_of(lord: LordBuffFilter) -> ast.ObjectFilter:
    """*lord* back as an ``ObjectFilter`` — the round trip the equality uses."""
    fields: dict[str, object] = {
        "card_types": lord.card_types,
        "excluded_types": lord.excluded_types,
        "colors": lord.colors,
        "subtypes": lord.subtypes,
        "excluded_subtypes": lord.excluded_subtypes,
        "controller": lord.controller,
        "other_than_source": lord.other_than_source,
        "with_plus1_counter": lord.with_plus1_counter,
        "named": lord.named,
        "with_keywords": lord.with_keywords,
        "without_keywords": lord.without_keywords,
        "chosen_land_type": lord.chosen_land_type,
        "chosen_creature_type": lord.chosen_creature_type,
        "excluded_colors": lord.excluded_colors,
        "supertypes": lord.supertypes,
    }
    for qualifier in lord.qualifiers:
        field_name, value = QUALIFIER_FIELDS[qualifier]
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
    protection_from: list[str] = []
    lost_keywords: list[str] = []
    for effect in effects:
        if isinstance(effect, ast.Pump):
            if effect.per_each is not None:
                # "…gets +2/+2 for each Aura attached to it." The delta is a
                # count, and LordBuff carries a pair of integers — attached
                # unread it would be a flat +2/+2 on the whole set.
                raise LoweringError(
                    "engine/lord_buffs.py carries no repeated bonus", node=node
                )
            power = _signed(effect.power, effect.power_negative)
            toughness = _signed(effect.toughness, effect.toughness_negative)
            if not isinstance(power, int) or not isinstance(toughness, int):
                raise LoweringError("a variable continuous buff has no channel", node=node)
        elif isinstance(effect, ast.GainKeyword):
            for keyword in effect.keywords:
                # "White creatures you control have **protection from black**."
                # (Righteous War.) Protection is not a keyword this channel can
                # carry — ``grantable_keywords`` excludes the word on purpose,
                # because the quality is read from ``LordBuff.protection_from``
                # and answered by ``_protection_qualities`` — so it is lifted
                # into that field here rather than refused. The refusal it
                # replaces was real behaviour lost: ``lord_buff_for`` has read
                # this sentence since Feline Sovereign, and a *lowering* error
                # does not fall through to the derivation table, so the
                # enchantment printings of the anthem (whose path consults the
                # grammar alone) reported unsupported while the creature
                # printings worked.
                if keyword.startswith("protection from "):
                    quality = keyword[len("protection from "):].strip()
                    if not grantable_protection_quality(quality):
                        raise LoweringError(
                            f"no shield answers to protection from {quality!r}",
                            node=node,
                        )
                    protection_from.append(quality)
                    continue
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"engine/lord_buffs.py grants no {keyword!r} at layer 6", node=node
                    )
                keywords.append(keyword)
        elif isinstance(effect, ast.LoseKeyword):
            # "All creatures lose flying." (Gravity Sphere.) The mirror of the
            # grant above and the same layer, so the same vocabulary gates it:
            # a word the engine does not implement would be a removal of
            # nothing, reported as a working board-wide static.
            #
            # "All creatures lose **all abilities**" is not that sentence and
            # must not fall through it: this branch reads a *list of words*, so
            # a blanket removal arrives carrying none and the assembly below
            # produces a +0/+0 anthem — a card compiling clean and doing
            # nothing. CR 613.1f's blanket is `engine/global_statics.py`'s
            # (Humility, Titania's Song), re-derived from the board on every
            # recompute, and a refusal here is what leaves it there.
            if effect.all_abilities:
                raise LoweringError(
                    "a board-wide blanket ability removal is "
                    "engine/global_statics.py's, not a lord buff",
                    node=node,
                )
            for keyword in effect.keywords:
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"engine/lord_buffs.py removes no {keyword!r} at layer 6",
                        node=node,
                    )
                lost_keywords.append(keyword)
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
    # "Creatures **with <word>** get +1/+1." The round trip above only proves the
    # table can *carry* the word; whether the consumer can answer it is a
    # separate question, and it is the dangerous one. ``_lord_buff_matches``
    # asks ``Permanent.has_keyword``, which answers "no" for a category word
    # like "protection" on every creature there is — so an ungated word would
    # be an anthem that compiles, reports supported, and buffs nobody. The same
    # gate ``lord_buffs._filter_keywords`` puts on the text-table path, asked
    # here because the two front ends must admit the same sentences.
    for keyword in lord_filter.with_keywords:
        if keyword not in grantable_keywords():
            raise LoweringError(
                f"_lord_buff_matches cannot ask whether a creature has "
                f"{keyword!r}",
                node=node,
            )
    return LordBuff(
        lord_filter,
        power,
        toughness,
        tuple(keywords),
        protection_from=tuple(protection_from),
        lost_keywords=tuple(lost_keywords),
    )


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

    - **A condition on a self bonus** ("This creature gets +1/+2 as long as
      you control a Forest") belongs to ``engine/static_bonuses.py``, which
      derives the bonus from the text. A condition on the *anthem* shape lowers
      here — see the conditional branch below — and refuses whenever
      ``conditional_static_holds`` could not evaluate it.
    - **A restriction the table does not carry.** The filter is rebuilt from
      what ``LordBuffFilter`` holds and compared for **equality** against the
      one the parser produced, so anything lost in that round trip refuses. A
      field added to ``ObjectFilter`` later is refused by default rather than
      ignored by a check that predates it.
    """
    effect = node.effect
    effects = effect.effects if isinstance(effect, ast.Conjunction) else (effect,)
    # "**You** have shroud." (Ivory Mask.) A keyword granted to a *seat* rather
    # than to a set of permanents, which CR 702.18a says in as many words
    # ("This permanent **or player** can't be the target of spells or
    # abilities"). Read first, because every branch below asks the subject for
    # a noun phrase and a `PlayerRef` has none — the anthem reader refuses it
    # with "static abilities need the CR 613 layers engine", which named the
    # wrong missing piece for as long as the card was unsupported.
    #
    # The word is gated on `player_statics.GRANTABLE_PLAYER_KEYWORDS` rather
    # than on the permanent vocabulary: flying is implemented and a player
    # cannot have it, so admitting a word because a *creature* can carry it
    # would compile a static nothing reads.
    if (
        node.condition is None
        and len(effects) == 1
        and isinstance(effects[0], ast.GainKeyword)
        and isinstance(getattr(effects[0], "subject", None), ast.PlayerRef)
    ):
        from ..player_statics import (GRANTABLE_PLAYER_KEYWORDS,
                                      PLAYER_KEYWORD_STATIC_KIND)

        grant = effects[0]
        if grant.subject.kind != "you":
            raise LoweringError(
                "a player keyword static is read off its own controller's "
                "seat, and no other seat word has a reader",
                node=node,
            )
        if grant.duration.kind is not None or grant.choose_one or grant.chosen_ability:
            raise LoweringError(
                "a player keyword static carries no duration or choice", node=node
            )
        for keyword in grant.keywords:
            if keyword not in GRANTABLE_PLAYER_KEYWORDS:
                raise LoweringError(
                    f"the engine answers no {keyword!r} about a player",
                    node=node,
                )
        return (
            OracleInstruction(
                PLAYER_KEYWORD_STATIC_KIND, "",
                {"keywords": list(grant.keywords)},
            ),
        )
    if node.condition is not None:
        # A condition on the *anthem* shape — "Creatures named Ivory Guardians
        # get +1/+1 as long as an opponent controls a nontoken red permanent"
        # (Ivory Guardians) — is a lord buff that holds exactly while the
        # condition does: the recompute asks ``conditional_static_holds`` before
        # applying it, the same evaluator every ``conditional_static`` payload
        # gets, so the words cannot mean one thing on a self bonus and another
        # on an anthem. A condition that evaluator does not answer refuses in
        # :func:`_lower_anthem_condition` — attached unread it would be a buff
        # that never (or always) applies, which is the dropped-rider bug wearing
        # a condition.
        #
        # A conditional bonus on any *other* subject — "This creature gets +0/+3
        # as long as it's untapped" — still belongs to engine/static_bonuses.py,
        # whose derivation the compiler consults after this refusal.
        subject = getattr(effects[0], "subject", None) if effects else None
        if node.unless and not (_is_source(subject) or _is_enchanted(subject)):
            # An anthem behind "unless" has no reader — the lord-buff recompute
            # has no complement arm — and "as long as" is the card's opposite.
            raise LoweringError(
                "no anthem applies while its condition is false", node=node
            )
        if _is_source(subject) or _is_enchanted(subject):
            # "This creature gets +1/+1 as long as **an opponent** controls a
            # nontoken white permanent." (Beasts of Bogardan.) The same
            # conditional static the derivation table produces, on the same
            # instruction kind and answered by the same evaluator — but the
            # condition is a printed *noun phrase* about a board this engine
            # has no text-side reader for, and writing one would be a second
            # reader of the phrase, free to disagree with `subject_matches`
            # about what "a nontoken white permanent" is.
            return _lower_self_conditional_static(node, effects)
        if not (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier in ("all", "each")
        ):
            raise LoweringError(
                "a conditional static bonus is derived by engine/static_bonuses.py",
                node=node,
            )
        buff = _lower_lord_effects(node, effects)
        condition = _recipient_seat_condition(node.condition, subject, node)
        if condition is None:
            condition = _lower_anthem_condition(node.condition, node)
        if condition.get("kind") == "all_share_a_color":
            # "**They**" is the very set this anthem buffs, so the filter is
            # copied from the buff rather than parsed a second time — and it is
            # copied from `lord_buff_payload`'s own rendering, so the evaluator
            # reads exactly the set `_lord_buff_matches` will buff. Written here
            # because this is the one place that holds both halves.
            condition = {
                **condition,
                "filter": _filter_payload(subject.filter),
            }
        # "**Its** controller" needs one permanent to be the "it" of, and an
        # anthem describes a *set* — so the seat word the conditional-static
        # path above admits has no referent here. Refused rather than allowed
        # to fall through to the pivot's default, which is the lord itself:
        # that would silently read the clause as "you control", the seat the
        # word exists to distinguish itself from.
        if (
            condition.get("who") == "controller"
            and condition.get("subject") != RECIPIENT_SUBJECT
        ):
            raise LoweringError(
                "an anthem names a set of permanents, so 'its controller' has "
                "no referent",
                node=node,
            )
        return (
            OracleInstruction(
                LORD_BUFF_KIND,
                "",
                lord_buff_payload(dataclasses.replace(buff, condition=condition)),
            ),
        )
    # A static ability on the *source itself* whose size is computed (Carrion
    # Grub's "gets +X/+0, where X is the greatest power among creature cards in
    # your graveyard"). Not a lord buff — it buffs nobody else — and not a
    # one-shot pump, because it has no duration; it is the CR 613 layer 7c
    # contribution the P/T refresh rebuilds on every recompute. The pump
    # lowering knows how to say that, so this routes rather than repeats.
    if len(effects) == 1 and isinstance(effects[0], ast.Pump):
        pump = effects[0]
        computed = pump.x_definition is not None or pump.per_each is not None
        # …and the same sentence printed by an Aura about its **host**:
        # "Enchanted creature gets +1/+1 for each other creature you control"
        # (Vampirism). Layer 7c either way, sized by the same shared count spec
        # and rebuilt by the same P/T refresh — only the permanent the delta
        # lands on differs, which is the split `conditional_static` already
        # makes with its `subject` key one branch up. Routed rather than
        # repeated, so the two subjects cannot drift about what "for each other
        # creature you control" counts.
        if computed and (_is_source(pump.subject) or _is_enchanted(pump.subject)):
            return _lower_pump(pump)
    union = _lower_lord_union(node, effects)
    if union is not None:
        return union
    buff = _lower_lord_effects(node, effects)
    return (OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(buff)),)


def _lower_lord_union(
    node: ast.StaticAbilityNode, effects: tuple[ast.Statement, ...]
) -> "tuple[OracleInstruction, ...] | None":
    """"**Saproling creatures and other Treefolk creatures** get +1/+1."
    (Verdeloth the Ancient.) One static ability over the *union* of two
    described sets -- or None when the effects name a single subject, which is
    every anthem but this shape.

    ``LordBuff`` describes one set, so the union rides as one buff per subject.
    What makes that the printed sentence rather than two anthems is that the
    sets are made **disjoint** first: each later subject is narrowed by
    excluding every earlier one, so a creature in both (a Saproling Treefolk)
    is reached once and gets +1/+1, not +2/+2 -- CR 611.3a applies one ability
    to each object matching its description, once.

    Excluding a set needs that set to be *one creature type and nothing else*:
    "not a Saproling" is a filter field, "not (an attacking Goblin you
    control)" is not. Any earlier subject carrying another narrowing therefore
    refuses the line rather than being excluded approximately. The last subject
    may carry whatever a single anthem may ("other", a seat, a colour), since
    nothing has to exclude it.
    """
    groups: list[tuple[object, list[ast.Statement]]] = []
    for effect in effects:
        subject = getattr(effect, "subject", None)
        for known, members in groups:
            if known == subject:
                members.append(effect)
                break
        else:
            groups.append((subject, [effect]))
    if len(groups) < 2:
        return None
    instructions: list[OracleInstruction] = []
    excluded: tuple[str, ...] = ()
    for position, (subject, members) in enumerate(groups):
        if not isinstance(subject, ast.TargetSpec):
            raise LoweringError(
                "a static ability over two different subjects", node=node
            )
        narrowed = dataclasses.replace(
            subject,
            filter=dataclasses.replace(
                subject.filter,
                excluded_subtypes=subject.filter.excluded_subtypes + excluded,
            ),
        )
        buff = _lower_lord_effects(
            node,
            tuple(dataclasses.replace(member, subject=narrowed) for member in members),
        )
        if position < len(groups) - 1:
            if buff.filter != LordBuffFilter(subtypes=buff.filter.subtypes) or (
                len(buff.filter.subtypes) != 1
            ):
                raise LoweringError(
                    "a static ability over two subjects needs each earlier one "
                    "to be a single creature type, so the later ones can "
                    "exclude it",
                    node=node,
                )
            excluded += buff.filter.subtypes
        instructions.append(
            OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(buff))
        )
    return tuple(instructions)
