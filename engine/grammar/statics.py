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

import dataclasses

from ..lord_buffs import (LORD_BUFF_KIND, LordBuff, LordBuffFilter,
                          QUALIFIER_FIELDS, grantable_keywords,
                          grantable_protection_quality, lord_buff_payload)
from ..oracle_types import OracleInstruction
from ..search_filters import SEARCH_COMPARISONS
from ..static_bonuses import RECIPIENT_SUBJECT
from ..subject_filters import OBJECT_ONLY_FILTER_KEYS
from . import ast
from .errors import LoweringError
from .lowering import (_filter_payload, _is_enchanted, _is_source,
                       _lower_condition, _lower_pump, _signed)


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


def _lower_anthem_condition_payload(payload: dict, node: ast.StaticAbilityNode) -> dict:
    """:func:`_lower_anthem_condition`'s gate, asked of an already-lowered
    payload — which is what a conjunct is.

    Split out so a conjunction is checked by the *same* rules as the clause it
    would have been printed as on its own, rather than by a second, laxer copy
    of them.
    """
    # "During your turn" (Vibrating Sphere) and "it's blocking" (Snow Devil)
    # carry no filter and no seat word, so none of the ``controls`` gates below
    # apply to them — asking those of a payload that has no such parts would
    # refuse a clause the evaluator implements in full.
    if payload.get("kind") in ("your_turn", "is_state"):
        return payload
    # "As long as there is exactly one tide counter on this **enchantment**, all
    # blue creatures get -2/-0." (Tidal Influence.) A count of the *source's*
    # own counters, which carries no filter and no seat word either — and which
    # `conditional_static_holds` answers off the permanent it is handed. Named
    # here beside the two above rather than falling into the `controls` gates,
    # which would refuse it for parts the sentence does not have.
    if payload.get("kind") == "source_counter_count":
        return payload
    # "…as long as **they all share a color**" (Common Cause). Named here beside
    # the three above rather than falling into the `controls` gates below, which
    # would refuse it for parts the sentence does not have: it carries no seat
    # word and no board noun phrase of its own — the set is the anthem's, copied
    # on at the call site.
    if payload.get("kind") == "all_share_a_color":
        return payload
    # "…as long as **white is the most common color among all permanents** or
    # is tied for most common" (the Invasion Djinns). A census of the whole
    # battlefield: no seat word and no noun phrase for the `controls` gates
    # below to hold to anything, and `conditional_static_holds` answers it
    # through `engine/color_census.py`.
    if payload.get("kind") == "color_is_most_common":
        return payload
    # "…as long as **it's blocking and you control a snow land**" (Snow Devil).
    # CR 613 puts no limit on how many clauses a static's criteria have, so each
    # conjunct is checked by *this same gate* rather than by a second, laxer
    # copy — and the whole conjunction refuses if any part is one the evaluator
    # cannot answer, because a conjunct silently dropped is a static holding on
    # a board the card does not name.
    if payload.get("kind") == "all_of":
        return {
            **payload,
            "conditions": [
                _lower_anthem_condition_payload(part, node)
                for part in payload.get("conditions") or ()
            ],
        }
    if payload.get("kind") != "controls":
        raise LoweringError(
            "conditional_static_holds evaluates no such condition on a "
            "continuous buff",
            node=node,
        )
    who = payload.get("who")
    # "…as long as **its controller** controls another creature" (Favorable
    # Destiny). A fourth seat word, and the one that is a *pronoun*: it names
    # the controller of the permanent the sentence is about rather than a seat
    # fixed relative to the ability's own controller. CR 109.5 is why that is a
    # real distinction and not a synonym for "you" — an Aura's controller and
    # its host's controller part company the moment either is stolen, and this
    # clause follows the host.
    #
    # "…as long as **no opponent** controls a white or blue creature" (Kavu
    # Runner, Skittish Kavu) is the fifth, ``each_opponent``: every opponent's
    # board at once. Admitted only with the printed zero — the condition
    # lowering has already refused that seat with any other count, because a
    # pooled tally and an every-opponent test part company above zero — and
    # checked again here, since this gate is also handed payloads that did not
    # come through it.
    if who == "each_opponent" and (
        payload.get("op"), payload.get("count")
    ) != ("eq", 0):
        raise LoweringError(
            "conditional_static_holds answers 'no opponent controls' and no "
            "other count over every opponent",
            node=node,
        )
    if who not in ("you", "opponent", "target_opponent", "controller", "each_opponent"):
        raise LoweringError(
            f"conditional_static_holds answers 'controls' for you or an "
            f"opponent, not {who!r}",
            node=node,
        )
    if payload.get("shared_name"):
        raise LoweringError(
            "conditional_static_holds counts matches, not same-name relations",
            node=node,
        )
    if "count" in payload and payload.get("op") not in SEARCH_COMPARISONS:
        raise LoweringError(
            f"conditional_static_holds applies no {payload.get('op')!r} "
            "comparison to a buff condition",
            node=node,
        )
    described = payload.get("filter") or {}
    # ``exclude_self`` on top of the object-only set, because *this* caller has
    # a source to compare against: ``_controls_count_holds`` is handed the
    # permanent the static is about and passes it straight to the matcher. The
    # key is out of ``OBJECT_ONLY_FILTER_KEYS`` for the callers that have none
    # (a forced-sacrifice prompt, a cost charger), and refusing it here as well
    # cost Favorable Destiny's "another creature" a condition the evaluator
    # answers in full.
    extra = set(described) - (OBJECT_ONLY_FILTER_KEYS | {"exclude_self"})
    if extra:
        raise LoweringError(
            "subject_matches cannot test a buff condition's "
            + ", ".join(sorted(extra)),
            node=node,
        )
    if who == "target_opponent":
        payload = {**payload, "who": "opponent"}
    return payload


def _lower_anthem_condition(condition: ast.Condition, node: ast.StaticAbilityNode) -> dict:
    """The payload form of an "as long as" clause on a lord buff, or a refusal.

    Lowered by the one condition lowering (so "an opponent controls a nontoken
    red permanent" is the same payload here as on an intervening-if) and then
    held to what ``conditional_static_holds`` actually evaluates for a
    continuous buff. Everything outside that refuses — a threshold or a
    relative key the consumer cannot test would make the buff apply on a
    different board than the card prints, silently.
    """
    return _lower_anthem_condition_payload(_lower_condition(condition), node)


def _recipient_seat_condition(
    condition: ast.Condition, subject: ast.TargetSpec, node: ast.StaticAbilityNode
) -> dict | None:
    """"Basic lands **each player controls** have shroud as long as **that
    player** controls three or fewer lands." (Sheltering Prayers.)

    An anthem whose condition is asked **once per buffed permanent**: "that
    player" points back at the seat-quantifier inside the subject, so it is each
    land's own controller, and two lands on two sides of the table can answer
    differently. That is "**its** controller" with the set's member as the "it"
    — the seat word Favorable Destiny's Aura already carries — so the clause is
    lowered as exactly that, plus ``subject: "recipient"``, which is what tells
    the recompute to ask it of each permanent the buff reaches rather than once
    of the source (``static_bonuses.RECIPIENT_SUBJECT``).

    None for every other sentence, which leaves it to
    :func:`_lower_anthem_condition` and its refusals — including "that player"
    with no seat-quantifier in the subject to bind it, which still has no
    referent at all.
    """
    if not (
        isinstance(condition, ast.Controls)
        and condition.who.kind == "that_player"
        and subject.filter.controller == "any_player"
    ):
        return None
    bound = dataclasses.replace(
        condition, who=dataclasses.replace(condition.who, kind="controller")
    )
    return {
        **_lower_anthem_condition(bound, node),
        "subject": RECIPIENT_SUBJECT,
    }


def _conditional_static_effect(
    effects: tuple[ast.Statement, ...], node: ast.StaticAbilityNode
) -> tuple[int, int, list[str]]:
    """The ``(power, toughness, keywords)`` a conditional static's arm carries.

    Extracted so the "Otherwise, …" arm is read by **this** function rather
    than by a second copy of it: the two arms of Phyrexian Boon are the same
    kind of thing (CR 613.1 criteria that happen to be complementary), and an
    arm admitted by laxer rules than its sibling is an arm that lowers a delta
    the refresh cannot apply.
    """
    power = toughness = 0
    keywords: list[str] = []
    for effect in effects:
        if isinstance(effect, ast.Pump):
            if effect.per_each is not None:
                raise LoweringError(
                    "the conditional static channel carries a fixed delta",
                    node=node,
                )
            power = _signed(effect.power, effect.power_negative)
            toughness = _signed(effect.toughness, effect.toughness_negative)
            if not isinstance(power, int) or not isinstance(toughness, int):
                raise LoweringError(
                    "a variable conditional bonus has no channel", node=node
                )
        elif isinstance(effect, ast.GainKeyword):
            for keyword in effect.keywords:
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"the derived-grant channel gives no {keyword!r} at "
                        "layer 6",
                        node=node,
                    )
                keywords.append(keyword)
        else:
            raise LoweringError(
                "a conditional static bonus is derived by engine/static_bonuses.py",
                node=node,
            )
    return power, toughness, keywords


def _lower_self_conditional_static(
    node: ast.StaticAbilityNode, effects: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...]:
    """"This creature <effect> as long as <condition>", with the condition read
    by the grammar's noun parser (Beasts of Bogardan) — and the same sentence
    printed about an Aura's host, "Enchanted creature gets +2/+2 as long as an
    opponent controls a black permanent" (Ice Age's five Scarabs).

    Those two differ in **which permanent the bonus lands on** and in nothing
    else: same effect, same condition, same evaluator, same seat (CR 109.5 — the
    ability is the Aura's, so its controller is who "an opponent" is measured
    against). So the subject rides the payload as ``subject: "attached"`` and
    the P/T refresh reads it, rather than the sentence getting a second
    lowering, a second condition reader and a chance to disagree about what "a
    black permanent" is.

    ``engine/static_bonuses.py`` owns the same instruction kind and the same
    evaluator, and every condition it reads is about **you** or about the
    creature itself: a land you control, a planeswalker you control, your
    graveyard, your draws, this creature being untapped. The split is that
    line — a condition about *another player's* board lowers here, everything
    else falls through to the table.

    Drawing it anywhere wider would move the cards the table already runs onto
    this path, and ``test_as_long_as_lines_stay_unlowered_and_unusable`` says
    what that costs: two mechanisms for one sentence, with nothing to say which
    of them a given printing goes through.

    The effect side is held to what the refresh consumes, and by the same
    argument the anthem lowering uses one function up — a delta or a keyword
    lowered into a payload no pass reads is a static that never applies while
    the card reports supported.
    """
    power, toughness, keywords = _conditional_static_effect(effects, node)
    attached = _is_enchanted(
        getattr(effects[0], "subject", None) if effects else None
    )
    # "…**as long as it's black**" (Phyrexian Boon). The pronoun is the
    # sentence's own subject — the enchanted creature — which is a referent the
    # general condition lowering has no way to see: it resolves "it" to a
    # *chosen target*, and an "as long as" clause chooses nothing (CR 613.1), so
    # it refuses there with "'it' has no target to be a colour of here". Asked
    # here, where the subject is in hand, and answered as the
    # ``attached_matches`` payload ``conditional_static_holds`` already
    # evaluates — so the colour is read by ``subject_matches`` through the
    # layers, and an Aura on a creature something has recoloured switches arms
    # by itself.
    colour = _attached_colour_condition(node.condition) if attached else None
    # "…unless **it shares a color with the most common color among all
    # permanents** or a color tied for most common" (Heroic Defiance). The
    # second pronoun-about-the-subject clause, and unreadable by the general
    # lowering for the first one's reason: there "it" is a chosen target, and a
    # static chooses nothing. Asked here with the subject in hand.
    if colour is None and isinstance(node.condition, ast.SharesMostCommonColor):
        colour = {"kind": "shares_most_common_color"}
    condition = colour if colour is not None else _lower_anthem_condition(
        node.condition, node
    )
    # **Where the split with ``engine/static_bonuses.py`` runs.** That table
    # reads the sentence printed about "this creature" and every condition it
    # knows is about *your* board or the creature itself, so a same-subject
    # clause lowered here would be one sentence with two mechanisms and nothing
    # to say which a printing goes through — which is what
    # ``test_as_long_as_lines_stay_unlowered_and_unusable`` measures.
    #
    # An Aura's sentence is not in that table's territory at all: it matches on
    # the literal subject ``"this creature "``, so "enchanted creature has first
    # strike as long as …" (Snow Devil) is a line it cannot read and there is no
    # second mechanism to collide with. So the refusal is asked of the
    # same-subject case only.
    # "As long as there is exactly one tide counter on this creature, it gets
    # -1/-1." (Homarid.) Not in that table's territory either, and for a
    # sharper reason than the Aura's: the table has no row for a counter count
    # at all, so refusing here would leave the sentence read by nobody — the
    # "refusal can expire" failure arriving before the refusal was even
    # written. It is the *same* sentence Tidal Influence prints about a set of
    # creatures instead of about itself, and both lower to one condition
    # payload answered by one evaluator.
    #
    # The colour census (the Invasion Djinns) is a third: about the whole
    # battlefield rather than about your board or the creature, a condition
    # that table has no row for and could not write one for without a second
    # reader of the clause the two census *spells* go through the grammar for.
    counted = condition.get("kind") in (
        "source_counter_count", "color_is_most_common",
        # …and the census asked *of the subject* (Heroic Defiance): the same
        # whole-battlefield count, with the subject's own colours as the thing
        # compared against it.
        "shares_most_common_color",
    )
    if not attached and not counted and condition.get("who") not in (
        "opponent", "each_opponent",
    ):
        raise LoweringError(
            # The table has no "unless" row at all, so naming it for that
            # spelling would point the next reader at a file that cannot help.
            "no reader applies a self bonus while a condition about your own "
            "board is false"
            if node.unless else
            "a conditional static bonus about your own board is derived by "
            "engine/static_bonuses.py",
            node=node,
        )
    payload: dict[str, object] = {"condition": condition}
    if node.unless:
        # "…gets +3/+3 **unless** <condition>" (Heroic Defiance). The delta
        # goes on the *complement* arm — the one "Otherwise, it gets -1/-2"
        # (Phyrexian Boon) already fills — so the criteria are asked once and
        # the answer selects the arm, rather than a negated copy of the
        # condition somebody has to keep exact. The refresh reads an arm that
        # is 0/0 beside a complement that is not as a live effect, which is
        # exactly this.
        #
        # A keyword behind the word, or a printed "Otherwise" beside it,
        # refuses: the keyword pass reads no complement arm, and two sentences
        # both claiming the false side is a card nobody prints.
        if keywords or node.otherwise is not None or not (power or toughness):
            raise LoweringError(
                "an 'unless' static carries one P/T delta on its complement "
                "arm and nothing else",
                node=node,
            )
        payload["otherwise_power"] = power
        payload["otherwise_toughness"] = toughness
    elif power or toughness:
        payload["power"] = power
        payload["toughness"] = toughness
    if keywords:
        payload["keywords"] = keywords
    if attached:
        # The bonus goes to the permanent this one is attached to, and so does
        # every "it" in the condition: "enchanted creature has first strike as
        # long as **it's** blocking" is about the creature, not about the Aura,
        # which never blocks. Both halves are read by ``permanent_state`` — the
        # P/T by ``_refresh_dynamic_creatures`` and the keywords by
        # ``_recalculate_lord_buffs``'s conditional-self-grant step — and both
        # read this one key.
        payload["subject"] = "attached"
        payload["condition"] = _condition_about_the_host(condition)
    if node.otherwise is not None:
        _add_otherwise_arm(payload, node, attached)
    return (OracleInstruction("conditional_static", "", payload),)


def _add_otherwise_arm(
    payload: dict, node: ast.StaticAbilityNode, attached: bool
) -> None:
    """Fold "Otherwise, it gets -1/-2." into *payload* (Phyrexian Boon).

    **One instruction, not two.** The obvious shape is a second
    ``conditional_static`` carrying the negated condition, and it is wrong twice
    over. The compiler wraps a line that lowers to several instructions in a
    ``sequence`` (``_line_instruction``), and every pass that applies a
    conditional static scans ``prog.instructions`` for that *kind* — so the
    wrapper hides both arms and the card does nothing at all while reporting
    supported. And two payloads is two conditions, asked separately, free to
    both answer True on a board where the negation and the assertion disagree.

    Asked once and answered once: the refresh evaluates the criteria and applies
    whichever arm the answer selects, so the two arms partition the board by
    construction rather than by a negation somebody has to keep exact.

    A keyword arm refuses. The delta arm is read by ``_refresh_dynamic_creatures``
    and the keyword arm would have to be read by ``_recalculate_lord_buffs``
    as well; no card in the pool prints one, and a keyword lowered into a
    payload that pass does not read is a grant that never happens — the
    unread-rider failure this whole family is arranged against.
    """
    other_effect = node.otherwise
    other_effects = (
        other_effect.effects
        if isinstance(other_effect, ast.Conjunction) else (other_effect,)
    )
    if _is_enchanted(getattr(other_effects[0], "subject", None)) != attached:
        raise LoweringError(
            "an 'otherwise' arm applies to the same permanent as the arm it "
            "complements",
            node=node,
        )
    other_power, other_toughness, other_keywords = _conditional_static_effect(
        other_effects, node
    )
    if other_keywords:
        raise LoweringError(
            "_recalculate_lord_buffs reads no 'otherwise' keyword arm",
            node=node,
        )
    if not (other_power or other_toughness):
        raise LoweringError(
            "an 'otherwise' arm with no delta is a sentence nothing applies",
            node=node,
        )
    payload["otherwise_power"] = other_power
    payload["otherwise_toughness"] = other_toughness


def _attached_colour_condition(condition) -> dict | None:
    """``as long as it's <colour>`` about an Aura's host, as a payload.

    None for anything else, so the ordinary condition lowering runs unchanged —
    this is a branch the general reader genuinely cannot take, not a shortcut
    around it.

    The colour becomes a **filter**, asked through ``subject_matches`` like
    every other printed noun-phrase narrowing in the engine, rather than a
    bespoke "is it black" test that would be a second reader free to disagree
    with the layers about what black is.
    """
    from ..subject_filters import untestable_filter_keys

    if not isinstance(condition, ast.ItIsColor):
        return None
    if condition.negated:
        # "as long as it's **not** black" has no printing in the pool and
        # ``attached_matches`` has no negation, so the word would be consumed
        # and dropped — a criteria clause reading as its own opposite. None
        # here sends the line to the general lowering, which refuses it by name.
        return None
    described = {"color_filter": condition.color}
    if untestable_filter_keys(described):
        return None
    return {"kind": "attached_matches", "filter": described}




def _condition_about_the_host(condition: dict) -> dict:
    """*condition* with every "it" pointed at the attached permanent.

    Only ``is_state`` carries such a pronoun; a ``controls`` clause names a
    *seat*, and CR 109.5 makes that the ability's controller — the Aura's —
    whichever permanent the effect lands on. So this rewrites one kind and
    walks the conjunction, rather than stamping a subject over the whole tree
    and quietly moving "you control a snow land" onto the host's controller.
    """
    if condition.get("kind") == "all_of":
        return {
            **condition,
            "conditions": [
                _condition_about_the_host(part)
                for part in condition.get("conditions") or ()
            ],
        }
    if condition.get("kind") in ("is_state", "shares_most_common_color"):
        # "…unless **it** shares a color with the most common color" (Heroic
        # Defiance) is the same pronoun: the colours compared against the
        # census are the enchanted creature's, never the Aura's.
        return {**condition, "subject": "attached"}
    # Two parts of a ``controls`` clause are pronouns like ``is_state``'s, and
    # only these two: "**its** controller" (``who: "controller"``) and
    # "**another** creature" (``exclude_self``, CR 109.5's "other than this
    # object"). Both are about the permanent the sentence is about — the
    # enchanted creature — so the clause is stamped for them and for nothing
    # else. Stamping every ``controls`` clause would quietly move "you control a
    # snow land" onto the host's controller, which is the seat CR 109.5 says it
    # is *not*.
    if condition.get("kind") == "controls" and (
        condition.get("who") == "controller"
        or (condition.get("filter") or {}).get("exclude_self")
    ):
        return {**condition, "subject": "attached"}
    return condition


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
            # An anthem behind "unless" has no reader: the lord-buff recompute
            # asks its condition and applies the buff while it holds, with no
            # complement arm to put the delta on. Refused rather than lowered
            # as "as long as", which is the card's opposite.
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
