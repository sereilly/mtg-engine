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
                          QUALIFIER_FIELDS, grantable_keywords, lord_buff_payload)
from ..oracle_types import OracleInstruction
from ..search_filters import SEARCH_COMPARISONS
from ..subject_filters import OBJECT_ONLY_FILTER_KEYS
from . import ast
from .errors import LoweringError
from .lowering import (_is_enchanted, _is_source, _lower_condition, _lower_pump,
                       _signed)


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
    )


def _object_filter_of(lord: LordBuffFilter) -> ast.ObjectFilter:
    """*lord* back as an ``ObjectFilter`` — the round trip the equality uses."""
    fields: dict[str, object] = {
        "card_types": lord.card_types,
        "excluded_types": lord.excluded_types,
        "colors": lord.colors,
        "subtypes": lord.subtypes,
        "controller": lord.controller,
        "other_than_source": lord.other_than_source,
        "with_plus1_counter": lord.with_plus1_counter,
        "named": lord.named,
        "with_keywords": lord.with_keywords,
        "without_keywords": lord.without_keywords,
        "chosen_land_type": lord.chosen_land_type,
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
    if who not in ("you", "opponent", "target_opponent", "controller"):
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
    counted = condition.get("kind") == "source_counter_count"
    if not attached and not counted and condition.get("who") != "opponent":
        raise LoweringError(
            "a conditional static bonus about your own board is derived by "
            "engine/static_bonuses.py",
            node=node,
        )
    payload: dict[str, object] = {"condition": condition}
    if power or toughness:
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
    if condition.get("kind") == "is_state":
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
        condition = _lower_anthem_condition(node.condition, node)
        # "**Its** controller" needs one permanent to be the "it" of, and an
        # anthem describes a *set* — so the seat word the conditional-static
        # path above admits has no referent here. Refused rather than allowed
        # to fall through to the pivot's default, which is the lord itself:
        # that would silently read the clause as "you control", the seat the
        # word exists to distinguish itself from.
        if condition.get("who") == "controller":
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
        if computed and _is_source(pump.subject):
            return _lower_pump(pump)
    buff = _lower_lord_effects(node, effects)
    return (OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(buff)),)
